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
  it('forwards only strict workspace directory requests', async () => {
    const { request, upstream } = await fixture();
    const workspaceId = '00000000-0000-4000-8000-000000000001';
    const companyId = '00000000-0000-4000-8000-000000000002';
    expect((await request('/api/agentos/samurai/workspaces')).status).toBe(200);
    expect((await request(`/api/agentos/samurai/workspaces/${workspaceId}/companies/${companyId}/open`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' })).status).toBe(200);
    expect(upstream.mock.calls.map(call => call[0])).toEqual([
      'http://127.0.0.1:8000/agentos/samurai/workspaces',
      `http://127.0.0.1:8000/agentos/samurai/workspaces/${workspaceId}/companies/${companyId}/open`,
    ]);
  });
  it('forwards only bounded, fixed workspace file requests', async () => {
    const upstream = vi.fn<typeof fetch>(async (url, init) => {
      if (init?.method === 'POST') {
        expect(init.body).toBeDefined();
        for await (const _chunk of init.body as AsyncIterable<Uint8Array>) {}
        return Response.json({ file_id: '00000000-0000-4000-8000-000000000003' });
      }
      if (String(url).endsWith('/download')) return new Response('bounded file', { headers: {
        'content-type': 'text/csv; charset=utf-8', 'content-disposition': "attachment; filename=\"download\"; filename*=UTF-8''table.csv",
        'content-length': '12', 'x-content-sha256': 'a'.repeat(64), 'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff',
      } });
      return Response.json([]);
    });
    const { request } = await fixture(true, upstream);
    const workspaceId = '00000000-0000-4000-8000-000000000001';
    const form = new FormData();
    form.set('file', new File(['bounded file'], 'brief.md', { type: 'text/markdown' }));
    form.set('company_id', '00000000-0000-4000-8000-000000000002');

    expect((await request(`/api/agentos/samurai/workspaces/${workspaceId}/files`)).status).toBe(200);
    expect((await request(`/api/agentos/samurai/workspaces/${workspaceId}/files`, { method: 'POST', body: form })).status).toBe(200);
    const download = await request(`/api/agentos/samurai/workspaces/${workspaceId}/files/00000000-0000-4000-8000-000000000003/download`);
    expect(download.status).toBe(200);
    expect(download.headers.get('content-disposition')).toBe("attachment; filename=\"download\"; filename*=UTF-8''table.csv");
    expect(upstream.mock.calls.map(call => call[0])).toEqual([
      `http://127.0.0.1:8000/agentos/samurai/workspaces/${workspaceId}/files`,
      `http://127.0.0.1:8000/agentos/samurai/workspaces/${workspaceId}/files`,
      `http://127.0.0.1:8000/agentos/samurai/workspaces/${workspaceId}/files/00000000-0000-4000-8000-000000000003/download`,
    ]);
  });
  it('rejects an unknown multipart field without forwarding file bytes', async () => {
    const upstream = vi.fn<typeof fetch>(async (_url, init) => {
      if (init?.body) for await (const _chunk of init.body as AsyncIterable<Uint8Array>) {}
      return Response.json({});
    });
    const { request } = await fixture(true, upstream);
    const form = new FormData();
    form.set('file', new File(['bounded file'], 'brief.md', { type: 'text/markdown' }));
    form.set('user_id', 'forged');
    const response = await request('/api/agentos/samurai/workspaces/00000000-0000-4000-8000-000000000001/files', { method: 'POST', body: form });
    expect(response.status).toBe(400);
  });
  it('requires a submission ID for company reservations and maps it to the upstream idempotency key', async () => {
    const { request, upstream } = await fixture();
    const workspaceId = '00000000-0000-4000-8000-000000000001';
    const submissionId = '00000000-0000-4000-8000-000000000003';
    const response = await request(`/api/agentos/samurai/workspaces/${workspaceId}/companies`, { method: 'POST', headers: { 'content-type': 'application/json', 'x-samurai-submission-id': submissionId, 'idempotency-key': 'browser-forged' }, body: '{}' });
    expect(response.status).toBe(200);
    expect(upstream.mock.calls[0]?.[1]?.headers).toMatchObject({ 'idempotency-key': submissionId });
    expect((await request(`/api/agentos/samurai/workspaces/${workspaceId}/companies`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' })).status).toBe(400);
  });
  it('forwards only a typed scenario run through the local proxy', async () => {
    const { request, upstream } = await fixture();
    const workspaceId = '00000000-0000-4000-8000-000000000001';
    const companyId = '00000000-0000-4000-8000-000000000002';
    const scenarioId = '00000000-0000-4000-8000-000000000003';
    const response = await request(`/api/agentos/samurai/workspaces/${workspaceId}/companies/${companyId}/scenarios/${scenarioId}/runs`, { method: 'POST', headers: { 'content-type': 'application/json', 'x-samurai-submission-id': scenarioId }, body: '{}' });
    expect(response.status).toBe(200);
    expect(upstream.mock.calls[0]?.[0]).toBe(`http://127.0.0.1:8000/agentos/samurai/workspaces/${workspaceId}/companies/${companyId}/scenarios/${scenarioId}/runs`);
    expect(upstream.mock.calls[0]?.[1]?.headers).toMatchObject({ 'idempotency-key': scenarioId, authorization: 'Bearer test-private-token' });
  });
  it('rejects malformed directory bodies, unsafe identity fields, invalid UUIDs and methods', async () => {
    const { request, upstream } = await fixture();
    const workspaceId = '00000000-0000-4000-8000-000000000001';
    for (const body of ['{', JSON.stringify({ display_name: 'Founders', user_id: 'forged' })]) {
      expect((await request('/api/agentos/samurai/workspaces', { method: 'POST', headers: { 'content-type': 'application/json' }, body })).status).toBe(400);
    }
    for (const body of ['null', '[]', 'false', '42']) {
      expect((await request(`/api/agentos/samurai/workspaces/${workspaceId}/companies`, { method: 'POST', headers: { 'content-type': 'application/json' }, body })).status).toBe(400);
    }
    expect((await request('/api/agentos/samurai/workspaces/not-a-uuid/companies', { method: 'GET' })).status).toBe(404);
    expect((await request(`/api/agentos/samurai/workspaces/${workspaceId}/companies`, { method: 'PUT' })).status).toBe(404);
    expect(upstream).not.toHaveBeenCalled();
  });
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


it('forwards prerequisite definitions only to their fixed backend route', async () => {
  const { request, upstream } = await fixture();
  expect((await request('/api/agentos/intake')).status).toBe(200);
  expect(upstream.mock.calls[0][0]).toBe('http://127.0.0.1:8000/api/company/intake');
  expect((await request('/api/agentos/intake?session_id=a')).status).toBe(404);
});
