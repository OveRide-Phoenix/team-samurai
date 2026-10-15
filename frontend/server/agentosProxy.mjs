import fs from 'node:fs';
import { sandboxPolicy, serveCopilot } from './copilotkit.mjs';
import { parseEnv } from 'node:util';
import { URL } from 'node:url';
import { Readable } from 'node:stream';
import { Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { FounderOperationsRequestError, founderOperationsBody, founderOperationsHeaders, founderOperationsRoute } from './founderOperationsProxy.mjs';

const BACKEND = 'http://127.0.0.1:8000';
const RUN = /^\/api\/agentos\/agents\/samurai\/runs$/;
const SAFE_ID = '[A-Za-z0-9_-]{1,200}';
const RUN_ID = new RegExp(`^/api/agentos/agents/samurai/runs/(${SAFE_ID})$`);
const CANCEL = new RegExp(`^/api/agentos/agents/samurai/runs/(${SAFE_ID})/cancel$`);
const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}';
const IDEMPOTENCY_KEY = new RegExp(`^${UUID}$`, 'i');
const WORKSPACES = /^\/api\/agentos\/samurai\/workspaces$/;
const MEMBERS = new RegExp(`^/api/agentos/samurai/workspaces/(${UUID})/members/([A-Za-z0-9._:@-]{1,200})$`);
const COMPANIES = new RegExp(`^/api/agentos/samurai/workspaces/(${UUID})/companies$`);
const OPEN_COMPANY = new RegExp(`^/api/agentos/samurai/workspaces/(${UUID})/companies/(${UUID})/open$`);
const FILES = new RegExp(`^/api/agentos/samurai/workspaces/(${UUID})/files(?:/(${UUID})(/download)?)?$`);
const FILE_CLEANUP = new RegExp(`^/api/agentos/samurai/workspaces/(${UUID})/files/cleanup$`);
const FILE_BODY_LIMIT = 10 * 1024 * 1024 + 24 * 1024;
const FILE_SIZE_LIMIT = 10 * 1024 * 1024;
const MULTIPART_HEADER_LIMIT = 16 * 1024;

export class MultipartFileError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
function multipartBoundary(contentType) {
  const match = /^multipart\/form-data; boundary=([A-Za-z0-9'()+_,.\/:=?-]{1,70})$/.exec(contentType ?? '');
  if (!match) throw new MultipartFileError(415, 'Multipart form data required.');
  return Buffer.from(match[1], 'ascii');
}
export function multipartFileBody(req) {
  const boundary = multipartBoundary(req.headers['content-type']);
  if (Number(req.headers['content-length'] ?? 0) > FILE_BODY_LIMIT) throw new MultipartFileError(413, 'File upload too large.');
  const opening = Buffer.concat([Buffer.from('--'), boundary, Buffer.from('\r\n')]);
  const separator = Buffer.concat([Buffer.from('\r\n--'), boundary]);
  let buffered = Buffer.alloc(0), state = 'opening', current, received = 0, fileBytes = 0, finished = false;
  const seen = new Set();
  const fail = (status, message) => { throw new MultipartFileError(status, message); };
  const validateHeaders = value => {
    const lines = value.toString('latin1').split('\r\n');
    const disposition = lines.filter(line => /^content-disposition:/i.test(line));
    if (disposition.length !== 1 || lines.some(line => !/^content-disposition:|^content-type:/i.test(line))) fail(400, 'Invalid file upload fields.');
    const match = /^content-disposition:\s*form-data;\s*name="(file|company_id)"(?:;\s*filename="[^"\r\n]*")?$/i.exec(disposition[0]);
    if (!match || seen.has(match[1])) fail(400, 'Invalid file upload fields.');
    const field = match[1];
    if ((field === 'file') !== /;\s*filename="[^"\r\n]*"$/i.test(disposition[0]) || (field === 'file' && lines.filter(line => /^content-type:/i.test(line)).length !== 1)) fail(400, 'Invalid file upload fields.');
    seen.add(field);
    current = field;
  };
  return req.pipe(new Transform({
    transform(chunk, _encoding, callback) {
      try {
        received += chunk.length;
        if (received > FILE_BODY_LIMIT) fail(413, 'File upload too large.');
        buffered = Buffer.concat([buffered, chunk]);
        while (true) {
          if (state === 'opening') {
            if (buffered.length < opening.length) break;
            if (!buffered.subarray(0, opening.length).equals(opening)) fail(400, 'Invalid multipart form data.');
            this.push(buffered.subarray(0, opening.length)); buffered = buffered.subarray(opening.length); state = 'headers'; continue;
          }
          if (state === 'headers') {
            const end = buffered.indexOf('\r\n\r\n');
            if (end < 0) { if (buffered.length > MULTIPART_HEADER_LIMIT) fail(400, 'Invalid multipart form data.'); break; }
            validateHeaders(buffered.subarray(0, end));
            this.push(buffered.subarray(0, end + 4)); buffered = buffered.subarray(end + 4); state = 'body'; continue;
          }
          if (state === 'body') {
            const end = buffered.indexOf(separator);
            if (end < 0) {
              const keep = separator.length - 1;
              if (current === 'company_id' && buffered.length > 36 + keep) fail(400, 'Invalid company binding.');
              if (current === 'file' && buffered.length > keep) {
                const value = buffered.subarray(0, buffered.length - keep);
                fileBytes += value.length;
                if (fileBytes > FILE_SIZE_LIMIT) fail(413, 'File upload too large.');
                this.push(value); buffered = buffered.subarray(buffered.length - keep);
              }
              break;
            }
            const value = buffered.subarray(0, end);
            if (current === 'file') {
              fileBytes += value.length;
              if (fileBytes > FILE_SIZE_LIMIT) fail(413, 'File upload too large.');
            }
            if (current === 'company_id' && (!UUID || !new RegExp(`^${UUID}$`, 'i').test(value.toString('ascii')))) fail(400, 'Invalid company binding.');
            this.push(value); buffered = buffered.subarray(end); state = 'separator'; continue;
          }
          if (state === 'separator') {
            if (buffered.length < separator.length + 2) break;
            if (!buffered.subarray(0, separator.length).equals(separator)) fail(400, 'Invalid multipart form data.');
            const suffix = buffered.subarray(separator.length, separator.length + 2).toString('ascii');
            if (suffix === '--') {
              if (buffered.length < separator.length + 4 || buffered.subarray(separator.length + 2, separator.length + 4).toString('ascii') !== '\r\n') break;
              this.push(buffered.subarray(0, separator.length + 4)); buffered = buffered.subarray(separator.length + 4); state = 'done'; finished = true; continue;
            }
            if (suffix !== '\r\n') fail(400, 'Invalid multipart form data.');
            this.push(buffered.subarray(0, separator.length + 2)); buffered = buffered.subarray(separator.length + 2); state = 'headers'; continue;
          }
          if (state === 'done') { if (buffered.length) fail(400, 'Invalid multipart form data.'); break; }
        }
        callback();
      } catch (error) { callback(error); }
    },
    flush(callback) {
      try {
        if (!finished || buffered.length || !seen.has('file')) fail(400, 'Invalid file upload fields.');
        callback();
      } catch (error) { callback(error); }
    },
  }));
}

function envFile(path) {
  try { return parseEnv(fs.readFileSync(path, 'utf8')); } catch { return {}; }
}
function envValue(text, key) {
  return text[key]?.trim() ?? '';
}
function config(root) {
  const frontend = envFile(`${root}/.env.local`);
  const backend = envFile(`${root}/../backend/.env`);
  const token = envValue(frontend, 'AGENTOS_USER_TOKEN');
  const verificationKey = envValue(backend, 'JWT_VERIFICATION_KEY');
  const model = envValue(backend, 'GEMINI_MODEL');
  return { token, configured: Boolean(token && verificationKey && model === 'gemini-3.5-flash-lite') };
}

function reject(response, status, message) {
  response.statusCode = status;
  response.setHeader('Content-Type', 'application/json');
  response.end(JSON.stringify({ detail: message }));
}
class DirectoryRequestError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
async function directoryBody(req, kind) {
  const chunks = [];
  let length = 0;
  for await (const chunk of req) {
    length += chunk.length;
    if (length > 64 * 1024) throw new DirectoryRequestError(413, 'Request too large.');
    chunks.push(chunk);
  }
  if (req.headers['content-type'] !== 'application/json') throw new DirectoryRequestError(415, 'JSON required.');
  let value;
  try { value = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { throw new DirectoryRequestError(400, 'Invalid JSON.'); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new DirectoryRequestError(400, 'Invalid workspace request fields.');
  const keys = Object.keys(value);
  if (kind === 'workspace_create' && keys.length === 1 && keys[0] === 'display_name' && typeof value.display_name === 'string' && value.display_name.trim() && value.display_name.trim().length <= 200) return JSON.stringify({ display_name: value.display_name });
  if (kind === 'member_update' && keys.length === 1 && keys[0] === 'role' && ['owner', 'editor', 'viewer'].includes(value.role)) return JSON.stringify({ role: value.role });
  if (['company_create', 'company_open'].includes(kind) && keys.length === 0) return '{}';
  throw new DirectoryRequestError(400, 'Invalid workspace request fields.');
}

export function agentosProxy(root, fetchImpl = fetch) {
  return async (req, res, next) => {
    res.setHeader('Content-Security-Policy', sandboxPolicy);
    const copilot = req.url === '/api/copilotkit' && req.method === 'POST';
    if (!copilot && !req.url?.startsWith('/api/agentos/')) return next();
    if (req.headers['x-samurai-client'] !== '1' || req.headers.authorization) return reject(res, 403, 'invalid local client');
    const requestHost = String(req.headers.host ?? '');
    const host = requestHost.split(':')[0];
    const origin = req.headers.origin;
    if (!['127.0.0.1', 'localhost'].includes(host) || (origin && ![`http://${requestHost}`, `https://${requestHost}`].includes(origin))) return reject(res, 403, 'invalid local origin');
    const url = new URL(req.url, 'http://127.0.0.1:4173');
    let operation;
    try { operation = founderOperationsRoute(url, req.method); }
    catch (error) { return error instanceof FounderOperationsRequestError ? reject(res, error.status, error.message) : reject(res, 502, 'Samurai AgentOS is unavailable.'); }
    const { token, configured } = config(root);
    if (url.pathname === '/api/agentos/connection' && req.method === 'GET' && !url.search) {
      res.statusCode = configured ? 200 : 503;
      res.setHeader('Content-Type', 'application/json');
      return res.end(JSON.stringify({ backend: BACKEND, configured, auth: 'jwt' }));
    }
    if (!configured) return reject(res, 503, 'Samurai AgentOS is not configured.');
    if (copilot) {
      const controller = new AbortController();
      res.once('close', () => { if (!res.writableFinished) controller.abort(); });
      try { return await serveCopilot(req, res, { backend: BACKEND, token, origin: `http://${req.headers.host}`, signal: controller.signal, fetchImpl }); }
      catch { if (!res.headersSent) return reject(res, 502, 'Samurai AgentOS is unavailable.'); return res.destroy(); }
    }
    const isIntake = url.pathname === '/api/agentos/intake' && req.method === 'GET' && !url.search;
    const fileRoute = !url.search ? FILES.exec(url.pathname) : null;
    const cleanupRoute = !url.search ? FILE_CLEANUP.exec(url.pathname) : null;
    const fileKind = fileRoute ? (!fileRoute[2] && req.method === 'GET' ? 'file_list' : !fileRoute[2] && req.method === 'POST' ? 'file_upload' : fileRoute[2] && !fileRoute[3] && req.method === 'GET' ? 'file_metadata' : fileRoute[2] && fileRoute[3] && req.method === 'GET' ? 'file_download' : fileRoute[2] && !fileRoute[3] && req.method === 'DELETE' ? 'file_delete' : undefined) : cleanupRoute && req.method === 'POST' ? 'file_cleanup' : undefined;
    const directoryKind = !url.search && WORKSPACES.test(url.pathname) ? (req.method === 'GET' ? 'workspace_list' : req.method === 'POST' ? 'workspace_create' : undefined)
      : !url.search && MEMBERS.test(url.pathname) ? (req.method === 'PUT' ? 'member_update' : req.method === 'DELETE' ? 'member_delete' : undefined)
        : !url.search && COMPANIES.test(url.pathname) ? (req.method === 'GET' ? 'company_list' : req.method === 'POST' ? 'company_create' : undefined)
          : !url.search && OPEN_COMPANY.test(url.pathname) && req.method === 'POST' ? 'company_open' : undefined;
    const match = url.pathname.match(RUN) ?? url.pathname.match(RUN_ID) ?? url.pathname.match(CANCEL);
    const isRun = RUN.test(url.pathname) && req.method === 'POST';
    const isRead = RUN_ID.test(url.pathname) && req.method === 'GET';
    const isCancel = CANCEL.test(url.pathname) && req.method === 'POST';
    if (!operation && !isIntake && !directoryKind && !fileKind && (!match || (!isRun && !isRead && !isCancel))) return reject(res, 404, 'route not available');
    const sessions = url.searchParams.getAll('session_id');
    if (!operation && ([...url.searchParams.keys()].some(key => key !== 'session_id') || (isRun && url.search) || (!directoryKind && !fileKind && !isRun && !isIntake && (sessions.length !== 1 || !/^[A-Za-z0-9_-]{1,200}$/.test(sessions[0]))))) return reject(res, 400, 'query not allowed');
    const target = operation ? `${BACKEND}${operation.path}` : isIntake ? `${BACKEND}/api/company/intake` : `${BACKEND}/agentos${url.pathname.slice('/api/agentos'.length)}${url.search}`;
    const headers = { authorization: `Bearer ${token}`, 'x-samurai-client': '1' };
    if (req.headers['content-type']) headers['content-type'] = req.headers['content-type'];
    if (operation) Object.assign(headers, founderOperationsHeaders(req, operation));
    if (directoryKind === 'company_create') {
      const submissionId = req.headers['x-samurai-submission-id'];
      if (typeof submissionId !== 'string' || !IDEMPOTENCY_KEY.test(submissionId)) return reject(res, 400, 'Valid submission id required.');
      headers['idempotency-key'] = submissionId;
    }
    const controller = new AbortController();
    res.once('close', () => { if (!res.writableFinished) controller.abort(); });
    try {
      const body = operation?.body ? await founderOperationsBody(req, operation.body) : directoryKind && !['workspace_list', 'company_list', 'member_delete'].includes(directoryKind) ? await directoryBody(req, directoryKind) : fileKind === 'file_upload' ? multipartFileBody(req) : isRun ? req : undefined;
      if (directoryKind && body) headers['content-type'] = 'application/json';
      if (fileKind === 'file_upload') headers['content-type'] = req.headers['content-type'];
      if ((operation && !operation.body || fileKind && fileKind !== 'file_upload') && (req.headers['transfer-encoding'] || Number(req.headers['content-length'] ?? 0) > 0)) return reject(res, 400, 'Body not allowed.');
      const upstream = await fetchImpl(target, { signal: controller.signal, method: req.method, headers, body, ...((isRun || fileKind === 'file_upload') ? { duplex: 'half' } : {}) });
      if (operation?.optional && upstream.status === 404) {
        await upstream.body?.cancel();
        res.statusCode = 204;
        return res.end();
      }
      res.statusCode = upstream.status;
      if (upstream.headers.get('content-type')) res.setHeader('Content-Type', upstream.headers.get('content-type'));
      if (!upstream.ok && (upstream.status === 401 || upstream.status >= 500)) {
        res.statusCode = upstream.status >= 500 ? 503 : 401;
        res.setHeader('Content-Type', 'application/json');
        return res.end(JSON.stringify({ detail: upstream.status === 401 ? 'AgentOS authentication failed.' : 'Samurai AgentOS is unavailable.' }));
      }
      if (fileKind === 'file_download' && upstream.ok) {
        const allowed = {
          'content-type': /^(?:text\/(?:plain|markdown|csv)|application\/(?:json|pdf))(?:; charset=utf-8)?$/i,
          'content-disposition': /^attachment; filename="download"; filename\*=UTF-8''(?:[A-Za-z0-9!#$&+.^_`|~-]|%[0-9a-f]{2})+$/i,
          'content-length': /^[0-9]+$/,
          'x-content-sha256': /^[a-f0-9]{64}$/i,
          'cache-control': /^(?:private, )?no-store$/,
          'x-content-type-options': /^nosniff$/i,
        };
        for (const [name, pattern] of Object.entries(allowed)) {
          const value = upstream.headers.get(name);
          if (!value || !pattern.test(value)) { await upstream.body?.cancel(); return reject(res, 502, 'Invalid file download response.'); }
          res.setHeader(name, value);
        }
      }
      if (!upstream.body) return res.end();
      await pipeline(Readable.fromWeb(upstream.body), res);
    } catch (error) {
      if (res.destroyed) return;
      if (res.headersSent) return res.destroy();
      const multipartError = error instanceof MultipartFileError ? error : error instanceof TypeError && error.cause instanceof MultipartFileError ? error.cause : undefined;
      if (error instanceof DirectoryRequestError || error instanceof FounderOperationsRequestError || multipartError) return reject(res, error instanceof DirectoryRequestError || error instanceof FounderOperationsRequestError ? error.status : multipartError.status, error instanceof DirectoryRequestError || error instanceof FounderOperationsRequestError ? error.message : multipartError.message);
      return reject(res, 502, 'Samurai AgentOS is unavailable.');
    }
  };
}

export const __private__ = { config, envValue };
