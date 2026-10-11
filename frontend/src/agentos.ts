import { z } from 'zod';
import { agents, panelSchema, type Panel, type Transport, type WorkEvent } from './model';

const base = '/api/agentos/agents/samurai/runs';
const headers = { 'X-Samurai-Client': '1' } as const;
const limit = 2_000_000;
const text = z.string().min(1).max(20_000);
const strings = z.array(text).max(100);
const uuid = z.string().uuid();
const date = z.string().datetime({ offset: true });
const outcome = z.enum(['verified', 'needs_input', 'needs_rework', 'insufficient_evidence', 'draft_only', 'requires_metrics', 'based_on_founder_supplied_metrics']);
const roles = z.enum(['intake', 'researcher', 'strategist', 'product_manager', 'builder', 'marketer', 'sales', 'analyst', 'verifier']);
const brief = z.strictObject({ idea: text, target_customer: text.nullable(), geography: text.nullable(), budget: text.nullable(), founder_skills: text.nullable(), goal: text.nullable(), supplied_context: strings, assumptions: strings, open_questions: strings, next_actions: strings });
const payload = z.discriminatedUnion('artifact_type', [
  z.strictObject({ artifact_type: z.literal('intake'), brief }),
  z.strictObject({ artifact_type: z.literal('research'), summary: text, conflicts: strings }),
  z.strictObject({ artifact_type: z.literal('strategy'), ideal_customer_profile: text, positioning: text, offer: text, pricing_assumptions: strings }),
  z.strictObject({ artifact_type: z.literal('product_plan'), minimum_viable_offering: strings, delivery_requirements: strings, user_stories: strings, roadmap: strings }),
  z.strictObject({ artifact_type: z.literal('builder_draft'), architecture: strings, database_schema: strings, apis: strings, user_interface: strings, deployment_configuration: strings }),
  z.strictObject({ artifact_type: z.literal('marketing_draft'), landing_page: text, ads: strings, social_posts: strings, emails: strings }),
  z.strictObject({ artifact_type: z.literal('sales_draft'), prospect_criteria: strings, outreach: strings, scripts: strings, objection_handling: strings }),
  z.strictObject({ artifact_type: z.literal('analysis'), metric_ids: z.array(uuid).min(1).max(100), findings: strings, recommendations: strings, basis: z.enum(['connected_measurements', 'based_on_founder_supplied_metrics']) }),
  z.strictObject({ artifact_type: z.literal('verification'), checked_artifact_ids: z.array(uuid).min(1).max(100), outcome: z.enum(['verified', 'needs_input', 'needs_rework']) }),
]);
const source = z.strictObject({ source_id: uuid, url: z.string().url().refine(value => /^https?:\/\//.test(value)), title: text, retrieved_at: date, search_query: text, excerpt: z.string().min(1).max(2000) });
const metric = z.strictObject({ metric_id: uuid, name: text, value: z.number().finite(), unit: text, window_start: date, window_end: date, source_label: text, collected_at: date, provenance: z.enum(['connected_measurement', 'founder_supplied', 'demo_fixture']), trusted_connector_receipt: text.nullable().default(null) }).refine(value => Date.parse(value.window_end) > Date.parse(value.window_start) && ((value.provenance === 'connected_measurement') === Boolean(value.trusted_connector_receipt)));
const artifact = z.strictObject({
  artifact_id: uuid, company_id: uuid, artifact_type: text, revision: z.number().int().min(1), input_revision: z.number().int().min(0), producer: roles,
  status: z.enum(['complete', 'insufficient_evidence', 'needs_input', 'needs_rework', 'draft_only', 'requires_metrics', 'based_on_founder_supplied_metrics']), acceptance_status: z.enum(['pending', 'accepted']).default('pending'), payload,
  founder_statements: z.array(z.strictObject({ statement_id: uuid, text })).max(100).default([]), sources: z.array(source).max(100).default([]),
  claims: z.array(z.strictObject({ claim_id: uuid, text, source_ids: z.array(uuid).min(1).max(100), support_status: z.enum(['mapped', 'unmapped']), support_segments: strings, verification_status: z.enum(['unverified', 'supported', 'contradicted']) }).refine(value => value.support_status !== 'mapped' || value.support_segments.length > 0)).max(100).default([]),
  measurements: z.array(metric).max(100).default([]), assumptions: z.array(z.strictObject({ assumption_id: uuid, text })).max(100),
  verification_findings: z.array(z.strictObject({ code: text, message: text, severity: z.enum(['info', 'warning', 'error']) })).min(1).max(100),
}).refine(value => value.artifact_type === value.payload.artifact_type && value.claims.every(claim => claim.source_ids.every(id => value.sources.some(item => item.source_id === id))) && value.measurements.every(item => item.provenance !== 'connected_measurement')).refine(value => {
  if (value.payload.artifact_type !== 'analysis') return true;
  const ids = value.payload.metric_ids;
  return value.payload.basis === 'based_on_founder_supplied_metrics' && value.status === 'based_on_founder_supplied_metrics' && ids.length === new Set(ids).size && value.measurements.length === ids.length && new Set(value.measurements.map(item => item.metric_id)).size === ids.length && value.measurements.every(item => ids.includes(item.metric_id) && item.provenance === 'founder_supplied');
});
const resultSchema = z.strictObject({ company_id: uuid, revision: z.number().int().min(0), outcome, artifacts: z.array(artifact).max(100).default([]), questions: z.array(z.string().min(1).max(200)).max(100).default([]) }).refine(value => (value.outcome === 'needs_input') === (value.questions.length > 0) && value.artifacts.every(item => item.company_id === value.company_id && item.revision <= value.revision));
type WorkflowResult = z.infer<typeof resultSchema>;

export type AgentosRun = { readonly runId: string; readonly status: 'running' | 'completed' | 'cancelled' | 'failed'; readonly companyId?: string; readonly revision?: number };
export class AgentosError extends Error {
  readonly name = 'AgentosError';
  constructor(readonly code: 'http' | 'protocol' | 'scope' | 'stream' | 'cancel', message: string) { super(message); }
}

function json(value: string): unknown {
  if (value.length > limit) throw new AgentosError('protocol', 'AgentOS payload exceeds the size limit.');
  try { return JSON.parse(value); } catch (error) {
    if (error instanceof SyntaxError) throw new AgentosError('protocol', 'AgentOS returned malformed JSON.');
    throw error;
  }
}
function workflow(value: unknown): WorkflowResult | undefined {
  if (typeof value === 'string') {
    const marker = '\nSAMURAI_WORKFLOW_RESULT=';
    const index = value.lastIndexOf(marker);
    if (index >= 0) value = json(value.slice(index + marker.length));
    else if (value.trim().startsWith('{')) {
      value = json(value);
      const candidate = recordSchema.safeParse(value);
      if (candidate.success && !('outcome' in candidate.data)) return undefined;
    }
    else return undefined;
  }
  if (value === undefined || value === null) return undefined;
  const parsed = resultSchema.safeParse(value);
  if (!parsed.success) throw new AgentosError('protocol', 'AgentOS returned an invalid workflow result.');
  return parsed.data;
}

function resultEvents(result: WorkflowResult, seen: Set<string>): WorkEvent[] {
  const events: WorkEvent[] = [];
  for (const item of result.artifacts) {
    const key = `${item.artifact_id}:${item.revision}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const id = `artifact-${item.artifact_id}`;
    // Preserve the complete validated lineage even where the existing panel catalog has no dedicated field.
    const note = `${item.status}; ${item.acceptance_status}; revision ${item.revision}. Generated artifact; review source support and assumptions.`;
    const data = item.payload;
    const panels: Panel[] = [];
    if (data.artifact_type === 'intake') {
      const brief = data.brief;
      const fields = [['Idea', brief.idea], ['First customers', brief.target_customer], ['Market', brief.geography], ['Budget', brief.budget], ['Founder skills', brief.founder_skills], ['First milestone', brief.goal], ['Supplied context', brief.supplied_context.join('; ')], ['Assumptions', brief.assumptions.join('; ')], ['Open questions', brief.open_questions.join('; ')], ['Proposed next actions', brief.next_actions.join('; ')]] as const;
      panels.push({ id, kind: 'evidence', title: 'Company brief', note: `${item.status}; founder inputs retained for this company.`, claims: fields.flatMap(([label, value], index) => value ? [{ id: `${id}-brief-${index}`, claim: `${label}: ${value}`, status: 'needs-check' as const, detail: 'Founder supplied context, not market evidence', sources: [] }] : []) });
    } else if (data.artifact_type === 'strategy') {
      panels.push({ id, kind: 'offer', title: 'Business offer', note, customer: data.ideal_customer_profile, promise: data.offer, price: data.pricing_assumptions.join('\n') || 'No pricing assumption supplied', includes: [data.positioning] });
      if (data.pricing_assumptions.length) panels.push({ id: `${id}-pricing`, kind: 'pricing', title: 'Pricing assumptions', note, options: data.pricing_assumptions.slice(0, 10).map((price, index) => ({ name: `Assumption ${index + 1}`, price, description: 'Founder review required' })) });
    } else if (data.artifact_type === 'product_plan') {
      panels.push({ id, kind: 'launch-plan', title: 'Minimum offering and delivery plan', note, tasks: [...data.minimum_viable_offering, ...data.delivery_requirements, ...data.user_stories, ...data.roadmap].slice(0, 30).map((title, index) => ({ id: `${id}-${index}`, title, owner: item.producer, timing: 'Not scheduled', detail: item.status })) });
    } else if (data.artifact_type === 'research' || data.artifact_type === 'verification') {
      const claims: Extract<Panel, { kind: 'evidence' }>['claims'] = item.claims.map(claim => ({ id: claim.claim_id, claim: claim.text, status: claim.verification_status === 'supported' && claim.support_status === 'mapped' ? 'supported' : 'needs-check', detail: `${claim.verification_status}; ${claim.support_status}. ${claim.support_segments.join('\n')}`, sources: item.sources.filter(entry => claim.source_ids.includes(entry.source_id)).map(entry => ({ title: entry.title, url: entry.url })).slice(0, 10) }));
      claims.push(...item.assumptions.map(entry => ({ id: entry.assumption_id, claim: entry.text, status: 'hypothesis' as const, detail: 'Assumption, not sourced fact', sources: [] })));
      claims.push(...item.verification_findings.map((finding, index) => ({ id: `${id}-finding-${index}`, claim: finding.message, status: 'needs-check' as const, detail: `${finding.severity}: ${finding.code}`, sources: [] })));
      const summary = data.artifact_type === 'research' ? [data.summary, ...data.conflicts].join('\n') : `${data.outcome}; checked artifacts: ${data.checked_artifact_ids.join(', ')}`;
      panels.push({ id, kind: 'evidence', title: data.artifact_type === 'research' ? 'Research evidence' : 'Verification review', note: `${summary}\n${note}`, claims: claims.slice(0, 30) });
    }
    if (!panels.length) {
      const entries: readonly [string, unknown][] = Object.entries(data);
      const drafts = entries.filter(([field]) => !['artifact_type', 'metric_ids', 'basis'].includes(field)).flatMap(([field, value]) => {
        const values = typeof value === 'string' ? [value] : Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === 'string') : [];
        return values.map(value => `${field.replaceAll('_', ' ')}: ${value}`);
      });
      panels.push({ id, kind: 'evidence', title: data.artifact_type.replaceAll('_', ' '), note, claims: drafts.slice(0, 10).map((claim, index) => ({ id: `${id}-draft-${index}`, claim: claim.length > 250 ? `${claim.slice(0, 247)}…` : claim, status: 'needs-check', detail: data.artifact_type === 'analysis' ? 'Based on founder supplied measurements; review before acting' : 'Generated draft; not sent, published or executed', sources: [] })) });
    }
    for (const panel of panels) events.push({ type: 'message', text: `${item.artifact_type.replaceAll('_', ' ')}: ${item.status}`, panel: panelSchema.parse({ ...panel, provenance: item }) });
  }
  const outcomeKey = `outcome:${result.company_id}:${result.revision}:${result.outcome}`;
  if (result.outcome === 'insufficient_evidence' && !seen.has(outcomeKey)) {
    seen.add(outcomeKey);
    events.push(
      { type: 'activity', agent: 'Researcher', state: 'waiting', detail: 'Research finished without sufficient source evidence.' },
      { type: 'activity', agent: 'Verifier', state: 'waiting', detail: 'Evidence review blocked: source support is missing.' },
      { type: 'activity', agent: 'Strategist', state: 'waiting', detail: 'Waiting for source evidence before strategy can start.' },
    );
  }
  const questionsKey = `questions:${JSON.stringify(result.questions)}`;
  if (result.questions.length && !seen.has(questionsKey)) {
    seen.add(questionsKey);
    events.push({ type: 'message', text: result.questions.join('\n') });
  }
  return events;
}

// Agno adds versioned metadata to envelopes; project only consumed fields, then validate strictly.
const envelopeSchema = z.strictObject({ event: text, run_id: text, session_id: text, agent_id: z.literal('samurai'), content: z.unknown().optional(), tool: z.unknown().optional(), kind: z.string().optional() });
const recordSchema = z.record(z.string(), z.unknown());
const relevant = new Set(['RunStarted', 'ToolCallCompleted', 'CustomEvent', 'RunCompleted', 'RunCancelled', 'RunError']);
function envelope(raw: string) {
  const value = recordSchema.parse(json(raw));
  if (typeof value.event !== 'string' || !relevant.has(value.event)) return undefined;
  const parsed = envelopeSchema.safeParse({ event: value.event, run_id: value.run_id, session_id: value.session_id, agent_id: value.agent_id, content: value.content, tool: value.tool, kind: value.kind });
  if (!parsed.success) throw new AgentosError('protocol', 'AgentOS returned an invalid event envelope.');
  return parsed.data;
}
function progressEvent(content: unknown): Extract<WorkEvent, { type: 'activity' }> | undefined {
  if (typeof content !== 'string') {
    const parsed = z.strictObject({ kind: z.literal('workflow_progress'), detail: z.string().max(2000) }).safeParse(content);
    if (!parsed.success) return undefined;
    content = parsed.data.detail;
  }
  if (typeof content !== 'string' || content.length > 2000) return undefined;
  const agent = agents.find(name => new RegExp(`^${name}\\b`, 'i').test(content))
    ?? (/^Research (started|completed)\b/i.test(content) ? 'Researcher'
      : /^Strategy (started|completed)\b/i.test(content) ? 'Strategist'
        : /^Verify (brief|evidence|journey) (started|completed)\b/i.test(content) ? 'Verifier' : undefined);
  return agent ? { type: 'activity', agent, state: /\b(completed|finished|done)\b/i.test(content) ? 'done' : 'working', detail: content } : undefined;
}
async function* frames(body: ReadableStream<Uint8Array>): AsyncIterable<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let buffer = '', bytes = 0;
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) { buffer += decoder.decode(); break; }
      bytes += part.value.byteLength;
      if (bytes > limit) throw new AgentosError('stream', 'AgentOS stream exceeds the size limit.');
      buffer += decoder.decode(part.value, { stream: true });
      let boundary = /\r?\n\r?\n/.exec(buffer);
      while (boundary) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const data = frame.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).replace(/^ /, '')).join('\n');
        if (data) yield data;
        boundary = /\r?\n\r?\n/.exec(buffer);
      }
    }
    if (buffer.trim()) throw new AgentosError('stream', 'AgentOS stream ended inside an event.');
  } finally { await reader.cancel(); reader.releaseLock(); }
}
async function request(url: string, options: RequestInit): Promise<Response> {
  const response = await fetch(url, { ...options, credentials: 'same-origin', headers });
  if (!response.ok) throw new AgentosError('http', `AgentOS request failed (${response.status}).`);
  return response;
}


export async function cancelAgentosRun(sessionId: string, runId: string): Promise<void> {
  text.parse(sessionId); text.parse(runId);
  const response = await request(`${base}/${encodeURIComponent(runId)}/cancel?session_id=${encodeURIComponent(sessionId)}`, { method: 'POST', signal: AbortSignal.timeout(15_000) });
  const receipt = await response.text();
  if (receipt.trim()) z.strictObject({}).parse(json(receipt));
}

export function createAgentosTransport(sessionId: string, onRun?: (run: AgentosRun) => void): Transport {
  text.parse(sessionId);
  let companyId: string | undefined;
  return async function* (input, signal) {
    if (signal.aborted) throw new DOMException('Run was cancelled before starting.', 'AbortError');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 600_000);
    let runId: string | undefined, revision: number | undefined;
    let terminal = false;
    let cancellation: Promise<void> | undefined;
    const notify = (status: AgentosRun['status']) => { if (runId) onRun?.({ runId, status, ...(companyId ? { companyId } : {}), ...(revision !== undefined ? { revision } : {}) }); };
    const cancel = () => {
      if (!runId || terminal || cancellation) return;
      cancellation = cancelAgentosRun(sessionId, runId).then(() => { if (signal.aborted) notify('cancelled'); }).catch(error => { notify('running'); throw error; }).finally(() => controller.abort());
      // The generator awaits and surfaces cancellation failures; attach a handler immediately to prevent an unhandled rejection.
      void cancellation.catch(() => undefined);
    };
    signal.addEventListener('abort', cancel);
    const seen = new Set<string>();
    try {
      const form = new FormData();
      form.set('message', text.parse(input)); form.set('session_id', sessionId); form.set('stream', 'true'); form.set('background', 'false');
      const response = await request(base, { method: 'POST', body: form, signal: controller.signal });
      if (!response.body || !response.headers.get('content-type')?.includes('text/event-stream')) throw new AgentosError('protocol', 'AgentOS did not return an event stream.');
      for await (const raw of frames(response.body)) {
        const event = envelope(raw);
        if (!event) continue;
        if (event.session_id !== sessionId || (runId && event.run_id !== runId)) throw new AgentosError('scope', 'AgentOS returned an event for another session or run.');
        if (!runId) {
          if (event.event !== 'RunStarted') throw new AgentosError('protocol', 'AgentOS omitted RunStarted.');
          runId = event.run_id; notify('running');
        }
        if (signal.aborted) { cancel(); if (cancellation) { await cancellation; return; } }
        if (event.event === 'CustomEvent' && (event.kind === 'workflow_progress' || event.kind === undefined)) {
          const activity = progressEvent(event.content);
          if (activity) yield activity;
        }
        if (event.event === 'ToolCallCompleted' || event.event === 'RunCompleted') {
          const tool = event.tool === undefined ? undefined : recordSchema.parse(event.tool);
          const result = workflow(event.event === 'ToolCallCompleted' ? tool?.result : event.content);
          if (result) {
            if (companyId && companyId !== result.company_id) throw new AgentosError('scope', 'AgentOS returned a result for another company.');
            companyId = result.company_id; revision = result.revision; notify('running');
            for (const output of resultEvents(result, seen)) {
              if (signal.aborted) { cancel(); if (cancellation) await cancellation; return; }
              yield output;
            }
          } else if (event.event === 'RunCompleted' && typeof event.content === 'string' && event.content.trim()) yield { type: 'message', text: event.content };
        }
        if (event.event === 'RunError') { terminal = true; throw new AgentosError('stream', 'Samurai could not complete this run.'); }
        if (event.event === 'RunCompleted' || event.event === 'RunCancelled') { terminal = true; notify(event.event === 'RunCancelled' ? 'cancelled' : 'completed'); return; }
      }
      throw new AgentosError('stream', 'AgentOS stream ended before a terminal event.');
    } catch (error) {
      if (cancellation) { await cancellation; return; }
      notify('failed');
      throw error;
    } finally {
      signal.removeEventListener('abort', cancel); clearTimeout(timeout);
      if (!terminal && runId && !cancellation) cancel();
      try { if (cancellation) await cancellation; } finally { controller.abort(); }
    }
  };
}

export async function readAgentosRun(sessionId: string, runId: string, signal?: AbortSignal): Promise<{ readonly run: AgentosRun; readonly events: readonly WorkEvent[] }> {
  text.parse(sessionId); text.parse(runId);
  const response = await request(`${base}/${encodeURIComponent(runId)}?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET', signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15_000)]) : AbortSignal.timeout(15_000) });
  const wire = recordSchema.parse(json(await response.text()));
  const run = z.strictObject({ run_id: text, session_id: text, agent_id: z.literal('samurai'), status: z.enum(['RUNNING', 'PENDING', 'COMPLETED', 'CANCELLED', 'ERROR']), content: z.unknown().optional() }).parse({ run_id: wire.run_id, session_id: wire.session_id, agent_id: wire.agent_id, status: wire.status, content: wire.content });
  if (run.run_id !== runId || run.session_id !== sessionId) throw new AgentosError('scope', 'AgentOS returned another session or run.');
  const status = run.status === 'COMPLETED' ? 'completed' : run.status === 'CANCELLED' ? 'cancelled' : run.status === 'ERROR' ? 'failed' : 'running';
  const result = status === 'completed' ? workflow(run.content) : undefined;
  return { run: { runId, status, ...(result ? { companyId: result.company_id, revision: result.revision } : {}) }, events: [...recoveredActivities(wire.events, sessionId, runId), ...(result ? resultEvents(result, new Set()) : status === 'completed' && typeof run.content === 'string' ? [{ type: 'message' as const, text: run.content }] : [])] };
}

function recoveredActivities(value: unknown, sessionId: string, runId: string): WorkEvent[] {
  if (value === undefined || value === null) return [];
  const saved = z.array(recordSchema).max(1000).parse(value);
  return saved.flatMap(event => {
    if (event.event !== 'CustomEvent' || (event.kind !== undefined && event.kind !== 'workflow_progress')) return [];
    if (event.session_id !== sessionId || event.run_id !== runId || event.agent_id !== 'samurai') throw new AgentosError('scope', 'Saved activity belongs to another session or run.');
    const activity = progressEvent(event.content);
    return activity ? [activity] : [];
  }).slice(-100);
}
