import fs from 'node:fs';
import { sandboxPolicy, serveCopilot } from './copilotkit.mjs';
import { parseEnv } from 'node:util';
import { URL } from 'node:url';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';

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
    const host = String(req.headers.host ?? '').split(':')[0];
    const origin = req.headers.origin;
    if (!['127.0.0.1', 'localhost'].includes(host) || (origin && !/^https?:\/\/(127\.0\.0\.1|localhost):4173$/.test(origin))) return reject(res, 403, 'invalid local origin');
    const url = new URL(req.url, 'http://127.0.0.1:4173');
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
    const directoryKind = !url.search && WORKSPACES.test(url.pathname) ? (req.method === 'GET' ? 'workspace_list' : req.method === 'POST' ? 'workspace_create' : undefined)
      : !url.search && MEMBERS.test(url.pathname) ? (req.method === 'PUT' ? 'member_update' : req.method === 'DELETE' ? 'member_delete' : undefined)
        : !url.search && COMPANIES.test(url.pathname) ? (req.method === 'GET' ? 'company_list' : req.method === 'POST' ? 'company_create' : undefined)
          : !url.search && OPEN_COMPANY.test(url.pathname) && req.method === 'POST' ? 'company_open' : undefined;
    const match = url.pathname.match(RUN) ?? url.pathname.match(RUN_ID) ?? url.pathname.match(CANCEL);
    const isRun = RUN.test(url.pathname) && req.method === 'POST';
    const isRead = RUN_ID.test(url.pathname) && req.method === 'GET';
    const isCancel = CANCEL.test(url.pathname) && req.method === 'POST';
    if (!isIntake && !directoryKind && (!match || (!isRun && !isRead && !isCancel))) return reject(res, 404, 'route not available');
    const sessions = url.searchParams.getAll('session_id');
    if ([...url.searchParams.keys()].some(key => key !== 'session_id') || (isRun && url.search) || (!directoryKind && !isRun && !isIntake && (sessions.length !== 1 || !/^[A-Za-z0-9_-]{1,200}$/.test(sessions[0])))) return reject(res, 400, 'query not allowed');
    const target = isIntake ? `${BACKEND}/api/company/intake` : `${BACKEND}/agentos${url.pathname.slice('/api/agentos'.length)}${url.search}`;
    const headers = { authorization: `Bearer ${token}`, 'x-samurai-client': '1' };
    if (req.headers['content-type']) headers['content-type'] = req.headers['content-type'];
    if (directoryKind === 'company_create') {
      const submissionId = req.headers['x-samurai-submission-id'];
      if (typeof submissionId !== 'string' || !IDEMPOTENCY_KEY.test(submissionId)) return reject(res, 400, 'Valid submission id required.');
      headers['idempotency-key'] = submissionId;
    }
    const controller = new AbortController();
    res.once('close', () => { if (!res.writableFinished) controller.abort(); });
    try {
      const body = directoryKind && !['workspace_list', 'company_list', 'member_delete'].includes(directoryKind) ? await directoryBody(req, directoryKind) : isRun ? req : undefined;
      if (directoryKind && body) headers['content-type'] = 'application/json';
      const upstream = await fetchImpl(target, { signal: controller.signal, method: req.method, headers, body, ...(isRun ? { duplex: 'half' } : {}) });
      res.statusCode = upstream.status;
      if (upstream.headers.get('content-type')) res.setHeader('Content-Type', upstream.headers.get('content-type'));
      if (!upstream.ok && (upstream.status === 401 || upstream.status >= 500)) {
        res.statusCode = upstream.status >= 500 ? 503 : 401;
        res.setHeader('Content-Type', 'application/json');
        return res.end(JSON.stringify({ detail: upstream.status === 401 ? 'AgentOS authentication failed.' : 'Samurai AgentOS is unavailable.' }));
      }
      if (!upstream.body) return res.end();
      await pipeline(Readable.fromWeb(upstream.body), res);
    } catch (error) {
      if (res.destroyed) return;
      if (res.headersSent) return res.destroy();
      if (error instanceof DirectoryRequestError) return reject(res, error.status, error.message);
      return reject(res, 502, 'Samurai AgentOS is unavailable.');
    }
  };
}

export const __private__ = { config, envValue };
