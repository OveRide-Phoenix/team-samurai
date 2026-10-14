import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createHash, generateKeyPairSync, sign, verify } from 'node:crypto';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { once } from 'node:events';

const rsa = generateKeyPairSync('rsa', { modulusLength: 2048 });
const ec = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
const audience = '/projects/590733583260/locations/asia-south1/services/samurai-frontend';
const now = Math.floor(Date.now() / 1000);
function assertion(patch = {}, key = ec.privateKey, header = {}) {
  const encode = data => Buffer.from(JSON.stringify(data)).toString('base64url');
  const data = `${encode({ alg: 'ES256', kid: 'test', ...header })}.${encode({ iss: 'https://cloud.google.com/iap', aud: audience, sub: 'user-a', iat: now, exp: now + 600, ...patch })}`;
  return `${data}.${sign('sha256', Buffer.from(data), { key, dsaEncoding: 'ieee-p1363' }).toString('base64url')}`;
}
const publicKeys = async () => ({ pubkeys: { test: ec.publicKey.export({ type: 'spki', format: 'pem' }) }, res: { headers: new Headers({ 'cache-control': 'max-age=3600' }) } });
const privateKey = rsa.privateKey.export({ type: 'pkcs8', format: 'pem' });

test('returns the existing connection contract for a verified user', async t => {
  const app = await fixture(t, () => assert.fail('upstream reached'));
  const response = await app.request('/api/agentos/connection');
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { backend: 'https://backend.example', configured: true, auth: 'jwt', storageNamespace: createHash('sha256').update('iap:user-a').digest('hex') });
});

export { assertion, publicKeys, privateKey, audience, rsa, now };

async function fixture(t, fetchImpl) {
  const { OAuth2Client } = await import('google-auth-library');
  const { createIapVerifier, productionConfig } = await import('../server/iapAuth.mjs');
  const { createProductionServer } = await import('../server/production.mjs');
  const client = new OAuth2Client();
  client.getIapPublicKeys = publicKeys;
  const directory = await mkdtemp(join(tmpdir(), 'samurai-bff-'));
  await writeFile(join(directory, 'index.html'), '<html>Samurai fixture</html>');
  await writeFile(join(directory, 'app.js'), 'console.log("public asset")');
  const config = productionConfig({ PUBLIC_ORIGIN: 'https://samurai.example', AGENTOS_BACKEND_URL: 'https://backend.example', IAP_AUDIENCE: audience, AGENTOS_SIGNING_KEY: privateKey });
  const server = createProductionServer(config, { verifyIdentity: createIapVerifier(audience, client), fetchImpl, staticDirectory: directory });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await rm(directory, { recursive: true }); });
  const url = `http://127.0.0.1:${server.address().port}`;
  return { url, request: (path, options = {}) => fetch(url + path, { ...options, headers: { 'x-goog-iap-jwt-assertion': assertion(), 'x-samurai-client': '1', ...options.headers } }) };
}

for (const [name, token] of Object.entries({ missing: '', malformed: 'bad', expired: assertion({ exp: now - 60, iat: now - 600 }), audience: assertion({ aud: 'other' }), issuer: assertion({ iss: 'evil' }), future: assertion({ iat: now + 90 }), lifetime: assertion({ exp: now + 1000 }), algorithm: assertion({}, ec.privateKey, { alg: 'HS256' }), signature: assertion({}, generateKeyPairSync('ec', { namedCurve: 'prime256v1' }).privateKey) })) {
  test(`rejects ${name} IAP assertion before upstream access`, async t => {
    const app = await fixture(t, () => assert.fail('upstream reached'));
    const response = await app.request('/api/agentos/connection', { headers: { 'x-goog-iap-jwt-assertion': token, 'x-goog-authenticated-user-email': 'spoof@example.com' } });
    assert.equal(response.status, 401);
  });
}

test('mints distinct scoped RS256 subjects for two verified users', async t => {
  const tokens = [];
  const app = await fixture(t, async (_url, options) => { tokens.push(options.headers.authorization.slice(7)); return new Response('{}'); });
  for (const sub of ['user-a', 'user-b']) await app.request('/api/agentos/intake', { headers: { 'x-goog-iap-jwt-assertion': assertion({ sub }) } });
  const subjects = tokens.map(token => {
    const [head, payload, signature] = token.split('.');
    assert.ok(verify('RSA-SHA256', Buffer.from(`${head}.${payload}`), rsa.publicKey, Buffer.from(signature, 'base64url')));
    const claims = JSON.parse(Buffer.from(payload, 'base64url'));
    assert.deepEqual(claims.scopes, ['agents:samurai:read', 'agents:samurai:run']);
    assert.equal(claims.exp - claims.iat, 300);
    return claims.sub;
  });
  assert.deepEqual(subjects, ['iap:user-a', 'iap:user-b']);
});

for (const [name, path, options, status] of [
  ['authorization', '/api/agentos/intake', { headers: { authorization: 'Bearer forged' } }, 403],
  ['identity header', '/api/agentos/intake', { headers: { 'x-user-id': 'other' } }, 403],
  ['origin', '/api/agentos/intake', { headers: { origin: 'https://evil.example' } }, 403],
  ['missing mutation origin', '/api/agentos/agents/samurai/runs', { method: 'POST' }, 403],
  ['unknown api', '/api/no-such-route', {}, 404],
  ['admin route', '/api/agentos/config', {}, 404],
  ['identity query', '/api/agentos/agents/samurai/runs/run1?session_id=s1&user_id=other', {}, 400],
  ['duplicate query', '/api/agentos/agents/samurai/runs/run1?session_id=s1&session_id=s2', {}, 400],
  ['missing session', '/api/agentos/agents/samurai/runs/run1', {}, 400],
  ['unknown static asset', '/missing.js', {}, 404],
  ['encoded traversal', '/%2e%2e%2fsecret', {}, 400],
  ['malformed escape', '/%ZZ', {}, 400],
]) test(`rejects ${name}`, async t => {
  const app = await fixture(t, () => assert.fail('upstream reached'));
  const response = await app.request(path, options);
  assert.equal(response.status, status);
});

function form(extra = {}) {
  const body = new FormData();
  for (const [name, value] of Object.entries({ message: 'Build a company', session_id: 'session1', stream: 'true', background: 'false', ...extra })) body.set(name, value);
  return body;
}
for (const field of ['user_id', 'session_state', 'dependencies']) test(`rejects ${field} body override`, async t => {
  const app = await fixture(t, () => assert.fail('upstream reached'));
  const response = await app.request('/api/agentos/agents/samurai/runs', { method: 'POST', headers: { origin: 'https://samurai.example' }, body: form({ [field]: 'other' }) });
  assert.equal(response.status, 400);
});

test('rejects oversized request before upstream access', async t => {
  const app = await fixture(t, () => assert.fail('upstream reached'));
  const response = await app.request('/api/agentos/agents/samurai/runs', { method: 'POST', headers: { origin: 'https://samurai.example' }, body: form({ message: 'x'.repeat(70000) }) });
  assert.equal(response.status, 413);
});

test('streams SSE first event before upstream ends and aborts on disconnect', async t => {
  let upstreamSignal;
  const app = await fixture(t, async (_url, options) => {
    upstreamSignal = options.signal;
    assert.equal(options.body.get('message'), 'Build a company');
    return new Response(new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode('data: first\n\n')); } }), { headers: { 'content-type': 'text/event-stream' } });
  });
  const response = await app.request('/api/agentos/agents/samurai/runs', { method: 'POST', headers: { origin: 'https://samurai.example' }, body: form() });
  assert.equal(response.headers.get('x-accel-buffering'), 'no');
  const reader = response.body.getReader();
  assert.equal(new TextDecoder().decode((await reader.read()).value), 'data: first\n\n');
  const aborted = once(upstreamSignal, 'abort');
  await reader.cancel();
  await aborted;
});

test('forwards cancellation once with the scoped session', async t => {
  const calls = [];
  const app = await fixture(t, async (url, options) => { calls.push([url, options.method]); return new Response('{}'); });
  const response = await app.request('/api/agentos/agents/samurai/runs/run1/cancel?session_id=session1', { method: 'POST', headers: { origin: 'https://samurai.example' } });
  assert.equal(response.status, 200);
  assert.deepEqual(calls, [['https://backend.example/agentos/agents/samurai/runs/run1/cancel?session_id=session1', 'POST']]);
});

test('sanitizes upstream failures', async t => {
  const app = await fixture(t, async () => new Response('private credential', { status: 500 }));
  const response = await app.request('/api/agentos/intake');
  assert.equal(response.status, 503);
  assert.equal((await response.json()).detail, 'Samurai AgentOS is unavailable.');
});

test('serves authenticated deep links and public liveness', async t => {
  const app = await fixture(t, () => assert.fail('upstream reached'));
  assert.match(await (await app.request('/company/example')).text(), /Samurai fixture/);
  assert.equal((await fetch(app.url + '/healthz')).status, 200);
  assert.equal((await fetch(app.url + '/')).status, 401);
});

test('fails closed when production auth settings are absent', async () => {
  const { productionConfig } = await import('../server/iapAuth.mjs');
  assert.throws(() => productionConfig({}), /Missing production/);
});

test('reuses cached rotating IAP public keys', async () => {
  const { OAuth2Client } = await import('google-auth-library');
  const { createIapVerifier } = await import('../server/iapAuth.mjs');
  const client = new OAuth2Client();
  let requests = 0;
  client.getIapPublicKeys = async () => { requests++; return publicKeys(); };
  const identity = createIapVerifier(audience, client);
  await Promise.all([identity(assertion()), identity(assertion({ sub: 'user-b' }))]);
  assert.equal(requests, 1);
});


test('CopilotKit discovery keeps IAP identity and private AgentOS tokens server-side', async t => {
  const app = await fixture(t, () => assert.fail('discovery invoked the backend'));
  const response = await app.request('/api/copilotkit', { method: 'POST', headers: { origin: 'https://samurai.example', 'content-type': 'application/json' }, body: JSON.stringify({ method: 'info' }) });
  assert.equal(response.status, 200);
  const info = await response.json();
  assert.ok(info.agents.samurai);
  assert.ok(!JSON.stringify(info).includes('Bearer'));
  assert.equal(response.headers.get('content-security-policy'), "frame-src 'none'; object-src 'none'");
});

for (const [name, value] of Object.entries({
  connect: { method: 'agent/connect', params: { agentId: 'samurai' } },
  otherAgent: { method: 'agent/run', params: { agentId: 'other' }, body: {} },
  missingIds: { method: 'agent/run', params: { agentId: 'samurai' }, body: { messages: [{ id: 'u', role: 'user', content: 'Read state' }] } },
  state: { method: 'agent/run', params: { agentId: 'samurai' }, body: { threadId: 'company', runId: 'run', state: { company_id: 'foreign' }, messages: [{ id: 'u', role: 'user', content: 'Read state' }] } },
})) test(`CopilotKit refuses ${name} without upstream access`, async t => {
  const app = await fixture(t, () => assert.fail('upstream reached'));
  const response = await app.request('/api/copilotkit', { method: 'POST', headers: { origin: 'https://samurai.example', 'content-type': 'application/json' }, body: JSON.stringify(value) });
  assert.equal(response.status, 400);
});

test('CopilotKit streams Agno with the verified founder JWT and no global thread history', async t => {
  let calls = 0;
  const app = await fixture(t, async (url, options) => {
    calls += 1;
    assert.equal(url, 'https://backend.example/agentos/agents/samurai/agui');
    const claims = JSON.parse(Buffer.from(new Headers(options.headers).get('authorization').split('.')[1], 'base64url'));
    assert.equal(claims.sub, 'iap:user-a');
    assert.deepEqual(claims.scopes, ['agents:samurai:read', 'agents:samurai:run']);
    const input = JSON.parse(options.body);
    assert.equal(input.messages.length, 1);
    assert.deepEqual(input.state, {});
    assert.deepEqual(input.forwardedProps, { team_area: 'research' });
    const events = [
      { type: 'RUN_STARTED', threadId: input.threadId, runId: input.runId },
      { type: 'CUSTOM', name: 'samurai', value: { event: 'RunStarted', agent_id: 'samurai', session_id: input.threadId, run_id: input.runId } },
      { type: 'CUSTOM', name: 'samurai', value: { event: 'RunCompleted', agent_id: 'samurai', session_id: input.threadId, run_id: input.runId, content: 'Hello founder' } },
      { type: 'RUN_FINISHED', threadId: input.threadId, runId: input.runId },
    ];
    return new Response(events.map(event => `data: ${JSON.stringify(event)}\n\n`).join(''), { headers: { 'content-type': 'text/event-stream' } });
  });
  const body = { method: 'agent/run', params: { agentId: 'samurai' }, body: { threadId: 'company', runId: 'run', state: {}, tools: [], context: [], forwardedProps: { team_area: 'research' }, messages: [{ id: 'u', role: 'user', content: 'Read state' }] } };
  const response = await app.request('/api/copilotkit', { method: 'POST', headers: { origin: 'https://samurai.example', 'content-type': 'application/json' }, body: JSON.stringify(body) });
  assert.equal(response.status, 200);
  const stream = await response.text();
  assert.ok(stream.includes('Hello founder'), stream);
  assert.ok(stream.includes('RUN_FINISHED'), stream);
  assert.equal(calls, 1);
});


test('CopilotKit accepts only a typed team choice while rejecting identity overrides', async () => {
  const { validateCopilotBody } = await import('../server/copilotkit.mjs');
  const body = { method: 'agent/run', params: { agentId: 'samurai' }, body: { threadId: 'company', runId: 'run', state: {}, messages: [{ id: 'u', role: 'user', content: 'Research competitors' }], forwardedProps: { team_area: 'research' } } };
  assert.deepEqual(validateCopilotBody(body), body);
  for (const forwardedProps of [{ team_area: 'other' }, { team_area: 'research', user_id: 'other' }, { company_id: 'foreign' }, [], 'research']) {
    assert.throws(() => validateCopilotBody({ ...body, body: { ...body.body, forwardedProps } }));
  }
});
