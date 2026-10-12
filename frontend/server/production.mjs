import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { readFile, realpath, stat } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import { dirname, extname, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { createIapVerifier, productionConfig, RequestError, signAgentosToken } from './iapAuth.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../dist/client');
const safeId = /^[A-Za-z0-9_-]{1,200}$/;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const runPath = '/api/agentos/agents/samurai/runs';
const operations = new Set(['journey', 'launch_drafts', 'metrics_analysis']);
const stages = new Set(['brief', 'research', 'strategy', 'plan']);
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.woff2': 'font/woff2', '.json': 'application/json' };
const bodyLimit = 64 * 1024;
function json(res, status, value) {
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(value));
}
function route(url, method) {
  if (!url.search && method === 'GET' && url.pathname === '/api/agentos/connection') return { kind: 'connection' };
  if (!url.search && method === 'GET' && url.pathname === '/api/agentos/intake') return { kind: 'intake', path: '/api/company/intake' };
  if (method === 'POST' && url.pathname === runPath && !url.search) return { kind: 'run', path: '/agentos/agents/samurai/runs' };
  const receipt = /^\/api\/agentos\/work-receipts\/([0-9a-f-]{36})$/.exec(url.pathname);
  if (receipt) {
    if (method !== 'GET' || !uuid.test(receipt[1])) throw new RequestError(404, 'Route not available.');
    const ids = url.searchParams.getAll('session_id');
    if ([...url.searchParams.keys()].some(key => key !== 'session_id') || ids.length !== 1 || !safeId.test(ids[0])) throw new RequestError(400, 'Query not allowed.');
    return { kind: 'receipt', path: `/agentos/work-receipts/${receipt[1]}${url.search}` };
  }
  const resume = /^\/api\/agentos\/agents\/samurai\/runs\/([A-Za-z0-9_-]{1,200})\/resume$/.exec(url.pathname);
  if (resume) {
    if (method !== 'POST' || url.search) throw new RequestError(404, 'Route not available.');
    return { kind: 'resume', path: `/agentos/agents/samurai/runs/${resume[1]}/resume` };
  }
  const match = /^\/api\/agentos\/agents\/samurai\/runs\/([A-Za-z0-9_-]{1,200})(\/cancel)?$/.exec(url.pathname);
  if (!match || method !== (match[2] ? 'POST' : 'GET')) throw new RequestError(404, 'Route not available.');
  const ids = url.searchParams.getAll('session_id');
  if ([...url.searchParams.keys()].some(key => key !== 'session_id') || ids.length !== 1 || !safeId.test(ids[0])) throw new RequestError(400, 'Query not allowed.');
  return { kind: match[2] ? 'cancel' : 'read', path: `/agentos${url.pathname.slice('/api/agentos'.length)}${url.search}` };
}
async function formBody(req) {
  const chunks = [];
  let length = 0;
  for await (const chunk of req.iterator({ destroyOnReturn: false })) {
    length += chunk.length;
    if (length > bodyLimit) throw new RequestError(413, 'Request too large.');
    chunks.push(chunk);
  }
  const type = req.headers['content-type'] ?? '';
  if (!type.startsWith('multipart/form-data;') && type !== 'application/x-www-form-urlencoded') throw new RequestError(415, 'Form data required.');
  let form;
  try { form = await new Response(Buffer.concat(chunks), { headers: { 'content-type': type } }).formData(); }
  catch { throw new RequestError(400, 'Invalid form data.'); }
  return form;
}
async function runBody(req) {
  const form = await formBody(req);
  const allowed = ['message', 'session_id', 'stream', 'background'];
  if ([...form.keys()].some(key => !allowed.includes(key)) || allowed.some(key => form.getAll(key).length !== 1) || typeof form.get('message') !== 'string' || !form.get('message').trim() || form.get('message').length > 20000 || !safeId.test(form.get('session_id')) || form.get('stream') !== 'true' || form.get('background') !== 'true') throw new RequestError(400, 'Invalid run fields.');
  return form;
}
async function resumeBody(req) {
  const form = await formBody(req);
  const allowed = ['session_id', 'last_event_index'];
  const sessionId = form.get('session_id');
  const cursors = form.getAll('last_event_index');
  if ([...form.keys()].some(key => !allowed.includes(key)) || form.getAll('session_id').length !== 1 || typeof sessionId !== 'string' || !safeId.test(sessionId) || cursors.length > 1 || (cursors.length === 1 && (typeof cursors[0] !== 'string' || !/^(0|[1-9][0-9]*)$/.test(cursors[0])))) throw new RequestError(400, 'Invalid resume fields.');
  return form;
}
async function staticFile(req, res, directory) {
  if (!['GET', 'HEAD'].includes(req.method)) throw new RequestError(405, 'Method not allowed.');
  let raw;
  try { raw = decodeURIComponent(req.url.split('?')[0]); }
  catch { throw new RequestError(400, 'Invalid path.'); }
  if (raw.includes('\\') || raw.includes('\0') || raw.split('/').some(part => part === '..' || part.startsWith('.'))) throw new RequestError(400, 'Invalid path.');
  const base = await realpath(directory);
  let path = resolve(base, `.${raw}`);
  if (!path.startsWith(`${base}${sep}`) && path !== base) throw new RequestError(400, 'Invalid path.');
  try { if (!(await stat(path)).isFile()) path = resolve(base, 'index.html'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; if (extname(path)) throw new RequestError(404, 'File not found.'); path = resolve(base, 'index.html'); }
  path = await realpath(path);
  if (!path.startsWith(`${base}${sep}`)) throw new RequestError(404, 'File not found.');
  res.writeHead(200, { 'Content-Type': mime[extname(path)] ?? 'application/octet-stream', 'Cache-Control': extname(path) === '.html' ? 'no-cache' : 'public, max-age=3600' });
  if (req.method === 'HEAD') return res.end();
  await pipeline(createReadStream(path), res);
}

export function createProductionServer(config, { verifyIdentity = createIapVerifier(config.audience), fetchImpl = fetch, staticDirectory = root } = {}) {
  const server = createServer(async (req, res) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'same-origin');
    const controller = new AbortController();
    res.once('close', () => { if (!res.writableFinished) controller.abort(); });
    try {
      const url = new URL(req.url, config.origin);
      if (url.pathname === '/healthz' && req.method === 'GET' && !url.search) return json(res, 200, { status: 'ok' });
      if (req.headers.authorization || req.headers['x-user-id'] || req.headers['x-samurai-user-id']) throw new RequestError(403, 'Client identity override denied.');
      const subject = await verifyIdentity(req.headers['x-goog-iap-jwt-assertion']);
      if (url.pathname === '/api' || url.pathname.startsWith('/api/')) {
        if (req.headers['x-samurai-client'] !== '1' || (req.headers.origin && req.headers.origin !== config.origin) || (req.method !== 'GET' && req.headers.origin !== config.origin)) throw new RequestError(403, 'Invalid client origin.');
        const selected = route(url, req.method);
        if (selected.kind === 'connection') return json(res, 200, { backend: config.backend, configured: true, auth: 'jwt', storageNamespace: createHash('sha256').update(subject).digest('hex') });
        if (Number(req.headers['content-length'] ?? 0) > bodyLimit) throw new RequestError(413, 'Request too large.');
        const body = selected.kind === 'run' ? await runBody(req) : selected.kind === 'resume' ? await resumeBody(req) : undefined;
        if (!['run', 'resume'].includes(selected.kind) && (req.headers['transfer-encoding'] || Number(req.headers['content-length'] ?? 0) > 0)) throw new RequestError(400, 'Body not allowed.');
        const upstreamHeaders = { authorization: `Bearer ${signAgentosToken(subject, config.key)}`, 'x-samurai-client': '1' };
        if (selected.kind === 'run') {
          const submissionId = req.headers['x-samurai-submission-id'];
          if (typeof submissionId !== 'string' || !uuid.test(submissionId)) throw new RequestError(400, 'Valid submission id required.');
          upstreamHeaders['idempotency-key'] = submissionId;
          const approval = [req.headers['x-samurai-operation'], req.headers['x-samurai-stage'], req.headers['x-samurai-expected-revision'], req.headers['x-samurai-company-id']];
          if (approval.some(value => value !== undefined)) {
            const [operation, stage, revision, companyId] = approval;
            if (typeof operation !== 'string' || typeof stage !== 'string' || typeof revision !== 'string' || typeof companyId !== 'string' || !operations.has(operation) || !stages.has(stage) || !uuid.test(companyId) || !/^(0|[1-9][0-9]*)$/.test(revision) || (operation !== 'journey' && stage !== 'plan')) throw new RequestError(400, 'Invalid approval headers.');
            upstreamHeaders['x-samurai-operation'] = operation;
            upstreamHeaders['x-samurai-stage'] = stage;
            upstreamHeaders['x-samurai-expected-revision'] = revision;
            upstreamHeaders['x-samurai-company-id'] = companyId;
          }
        }
        const upstream = await fetchImpl(`${config.backend}${selected.path}`, { method: req.method, redirect: 'error', headers: upstreamHeaders, body, signal: AbortSignal.any([controller.signal, AbortSignal.timeout(3_600_000)]) });
        if (!upstream.ok) {
          await upstream.body?.cancel();
          return json(res, upstream.status >= 500 ? 503 : upstream.status, { detail: upstream.status >= 500 ? 'Samurai AgentOS is unavailable.' : 'AgentOS request denied.' });
        }
        res.writeHead(upstream.status, { 'Content-Type': upstream.headers.get('content-type') ?? 'application/json', 'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no' });
        res.flushHeaders();
        if (!upstream.body) return res.end();
        return await pipeline(Readable.fromWeb(upstream.body), res);
      }
      await staticFile(req, res, staticDirectory);
    } catch (error) { // HTTP boundary: keep upstream bodies, credentials and crypto errors out of responses/logs.
      if (res.destroyed) return;
      if (res.headersSent) return res.destroy();
      json(res, error instanceof RequestError ? error.status : 502, { detail: error instanceof RequestError ? error.message : 'Samurai is unavailable.' });
    }
  });
  server.requestTimeout = 30_000;
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const config = productionConfig();
  await readFile(resolve(root, 'index.html'));
  const server = createProductionServer(config);
  server.listen(Number(process.env.PORT ?? 8080), '0.0.0.0');
  process.once('SIGTERM', () => { server.close(); setTimeout(() => process.exit(0), 9000).unref(); });
}
