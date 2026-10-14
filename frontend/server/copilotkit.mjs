import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { HttpAgent } from '@ag-ui/client';

process.env.COPILOTKIT_TELEMETRY_DISABLED = 'true';
const { AgentRunner, CopilotRuntime, createCopilotRuntimeHandler } = await import('@copilotkit/runtime/v2');
const safeId = /^[A-Za-z0-9_-]{1,200}$/;
export const sandboxPolicy = "frame-src 'none'; object-src 'none'";

// Agno owns history and cancellation. Avoid CopilotKit's global in-memory thread store.
class AgnoRunner extends AgentRunner {
  run({ agent, input }) { return agent.run(input); }
  connect() { throw new Error('Use the owner-scoped AgentOS run read.'); }
  async isRunning() { return false; }
  async stop() { throw new Error('Use the owner-scoped AgentOS cancellation route.'); }
}

export function validateCopilotBody(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key => !['method', 'params', 'body'].includes(key))) throw new Error('Invalid CopilotKit request.');
  if (value.method === 'info') {
    if (Object.keys(value.params ?? {}).length || Object.keys(value.body ?? {}).length) throw new Error('Invalid discovery request.');
    return value;
  }
  const props = value.body?.forwardedProps;
  if (props != null && (typeof props !== 'object' || Array.isArray(props) || Object.keys(props).some(key => key !== 'team_area') || (Object.keys(props).length && !['overview', 'research', 'strategy', 'verification', 'sales'].includes(props.team_area)))) throw new Error('Invalid team area.');
  const body = value.body;
  if (value.method !== 'agent/run' || value.params?.agentId !== 'samurai' || Object.keys(value.params).some(key => key !== 'agentId') || !body || typeof body !== 'object' || Array.isArray(body)) throw new Error('CopilotKit method not allowed.');
  const allowed = ['threadId', 'runId', 'protocolVersion', 'parentRunId', 'state', 'messages', 'tools', 'context', 'forwardedProps', 'resume'];
  if (Object.keys(body).some(key => !allowed.includes(key)) || typeof body.threadId !== 'string' || !safeId.test(body.threadId) || typeof body.runId !== 'string' || !safeId.test(body.runId) || Object.keys(body.state ?? {}).length || (body.tools?.length ?? 0) || (body.context?.length ?? 0) || (body.resume?.length ?? 0) || body.parentRunId) throw new Error('Client context overrides are forbidden.');
  const message = body.messages?.[0];
  if (!Array.isArray(body.messages) || body.messages.length !== 1 || !message || message.role !== 'user' || typeof message.content !== 'string' || !message.content.trim() || message.content.length > 20000 || Object.keys(message).some(key => !['id', 'role', 'content'].includes(key))) throw new Error('Exactly one text turn is required.');
  return value;
}

export async function readCopilotBody(req) {
  if (!req.headers['content-type']?.startsWith('application/json')) throw new Error('JSON required.');
  const chunks = [];
  let length = 0;
  for await (const chunk of req.iterator({ destroyOnReturn: false })) {
    length += chunk.length;
    if (length > 65536) throw new Error('Request too large.');
    chunks.push(chunk);
  }
  return validateCopilotBody(JSON.parse(Buffer.concat(chunks).toString('utf8')));
}

export async function serveCopilot(req, res, { backend, token, origin, signal, fetchImpl = fetch }) {
  let body;
  try { body = await readCopilotBody(req); }
  catch { res.writeHead(400, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); return res.end(JSON.stringify({ detail: 'Invalid CopilotKit request.' })); }
  const agent = new HttpAgent({
    agentId: 'samurai', url: `${backend}/agentos/agents/samurai/agui`,
    headers: { authorization: `Bearer ${token}`, 'x-samurai-client': '1' },
    fetch: (url, options) => fetchImpl(url, { ...options, redirect: 'error', signal: options.signal ? AbortSignal.any([signal, options.signal]) : signal }),
  });
  const runtime = new CopilotRuntime({ agents: { samurai: agent }, runner: new AgnoRunner() });
  const handler = createCopilotRuntimeHandler({ runtime, basePath: '/api/copilotkit', mode: 'single-route', activateChannels: false });
  const result = await handler(new Request(`${origin}/api/copilotkit`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body), signal }));
  res.writeHead(result.status, { 'Content-Type': result.headers.get('content-type') ?? 'application/json', 'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no' });
  res.flushHeaders();
  if (!result.body) return res.end();
  await pipeline(Readable.fromWeb(result.body), res);
}
