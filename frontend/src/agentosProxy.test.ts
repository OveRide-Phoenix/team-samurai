/// <reference types="node" />
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createServer, type Server } from 'node:http';
import { agentosProxy } from '../server/agentosProxy.mjs';

const roots: string[] = [];
const servers: Server[] = [];
afterEach(async () => {
  await Promise.all(servers.splice(0).map(server => new Promise<void>(resolve => server.close(() => resolve()))));
  roots.splice(0).forEach(root => rmSync(root, { recursive: true, force: true }));
});
async function fixture(configured = true, upstream = vi.fn<typeof fetch>(async () => new Response('data: result\n\n', { headers: { 'content-type': 'text/event-stream' } }))) {
  const root = mkdtempSync(join(tmpdir(), 'samurai-proxy-')); roots.push(root);
  mkdirSync(join(root, 'frontend')); mkdirSync(join(root, 'backend'));
  if (configured) {
    writeFileSync(join(root, 'frontend/.env.local'), 'AGENTOS_USER_TOKEN=test-private-token\n');
    writeFileSync(join(root, 'backend/.env'), 'GEMINI_MODEL=gemini-3.5-flash-lite\nJWT_VERIFICATION_KEY="test-public-key"\n');
  }
  const handler = agentosProxy(join(root, 'frontend'), upstream);
  const server = createServer((req, res) => void handler(req, res, () => { res.statusCode = 404; res.end(); })); servers.push(server);
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address(); if (!address || typeof address === 'string') throw Error('Missing test port');
  const url = 'http://127.0.0.1:' + address.port;
  return { upstream, request: (path: string, options: RequestInit = {}) => fetch(url + path, { ...options, headers: { 'X-Samurai-Client': '1', ...options.headers } }) };
}
describe('actual local AgentOS proxy', () => {
  it('serves sanitized missing-config status without preventing UI startup', async () => {
    const { request, upstream } = await fixture(false);
    const response = await request('/api/agentos/connection');
    expect(response.status).toBe(503); expect(await response.json()).toEqual({ backend: 'http://127.0.0.1:8000', configured: false, auth: 'jwt' }); expect(upstream).not.toHaveBeenCalled();
  });
  it('injects server credentials and streams only the fixed backend route', async () => {
    const { request, upstream } = await fixture();
    const form = new FormData(); form.set('message', 'Build a company'); form.set('session_id', 'company-a');
    const response = await request('/api/agentos/agents/samurai/runs', { method: 'POST', body: form });
    expect(response.status).toBe(200); expect(await response.text()).toBe('data: result\n\n');
    expect(upstream.mock.calls[0][0]).toBe('http://127.0.0.1:8000/agentos/agents/samurai/runs');
    expect(upstream.mock.calls[0][1]?.headers).toMatchObject({ authorization: 'Bearer test-private-token' });
    expect(response.headers.get('authorization')).toBeNull();
  });
  it('rejects foreign origins and browser bearer tokens', async () => {
    const { request, upstream } = await fixture();
    for (const headers of [{ Origin: 'https://evil.example' }, { Authorization: 'Bearer foreign-token' }] as Record<string, string>[]) {
      expect((await request('/api/agentos/connection', { headers })).status).toBe(403);
    }
    expect(upstream).not.toHaveBeenCalled();
  });
  it('rejects arbitrary routes, methods, traversal and duplicate session scopes', async () => {
    const { request, upstream } = await fixture();
    for (const path of ['/api/agentos/config', '/api/agentos/agents/samurai/runs/..%2Fconfig?session_id=a', '/api/agentos/agents/samurai/runs/a?session_id=a&session_id=b', '/api/agentos/agents/samurai/runs/a?token=secret', '/api/agentos/agents/samurai/runs/a?session_id=']) {
      expect((await request(path)).status).toBeGreaterThanOrEqual(400);
    }
    expect((await request('/api/agentos/agents/samurai/runs', { method: 'DELETE' })).status).toBe(404);
    expect(upstream).not.toHaveBeenCalled();
  });
  it('forwards scoped read and cancellation, sanitizing upstream failures', async () => {
    const upstream = vi.fn<typeof fetch>(async () => new Response('private provider failure', { status: 500, headers: { 'set-cookie': 'private=secret', 'content-length': '999' } }));
    const { request } = await fixture(true, upstream);
    const response = await request('/api/agentos/agents/samurai/runs/run-a/cancel?session_id=company-a', { method: 'POST' });
    expect(response.status).toBe(503); expect(await response.text()).not.toContain('private'); expect(response.headers.get('set-cookie')).toBeNull(); expect(response.headers.get('content-length')).not.toBe('999');
    await request('/api/agentos/agents/samurai/runs/run-a?session_id=company-a');
    expect(upstream).toHaveBeenCalledTimes(2);
  });
});
