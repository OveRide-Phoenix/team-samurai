import { afterEach, describe, expect, it, vi } from 'vitest';
import { cancelAgentosRun, createAgentosTransport, readAgentosRun, presentMessages, type AgentosRun } from './agentos';
import type { Message, WorkEvent } from './model';

const company = '00000000-0000-4000-8000-000000000001';
const artifactId = '00000000-0000-4000-8000-000000000002';
const sourceId = '00000000-0000-4000-8000-000000000003';
const claimId = '00000000-0000-4000-8000-000000000004';
const result = {
  company_id: company, revision: 1, outcome: 'needs_rework', questions: [], artifacts: [{
    artifact_id: artifactId, company_id: company, artifact_type: 'research', revision: 1, input_revision: 0,
    producer: 'researcher', status: 'needs_rework', acceptance_status: 'accepted',
    payload: { artifact_type: 'research', summary: 'Pricing varies — more evidence needed.', conflicts: ['Conflicting source'] },
    founder_statements: [], assumptions: [], measurements: [],
    sources: [{ source_id: sourceId, url: 'https://example.org/research', title: 'Independent reference', retrieved_at: '2026-10-11T00:00:00Z', search_query: 'pricing', excerpt: 'A limited sample' }],
    claims: [{ claim_id: claimId, text: 'There may be demand', source_ids: [sourceId], support_status: 'mapped', support_segments: ['A limited sample'], verification_status: 'unverified' }],
    verification_findings: [{ code: 'missing_evidence', message: 'Validate demand', severity: 'warning' }],
  }],
};
const wire = (event: string, fields: Record<string, unknown> = {}) => ({ event, run_id: 'run-1', session_id: 'session-1', agent_id: 'samurai', ...fields });
const frame = (value: unknown) => `data: ${JSON.stringify(value)}\r\n\r\n`;
function response(data: string, split = false): Response {
  const bytes = new TextEncoder().encode(data);
  return new Response(new ReadableStream<Uint8Array>({ start(controller) {
    if (split) for (let index = 0; index < bytes.length; index += 1) controller.enqueue(bytes.slice(index, index + 1));
    else controller.enqueue(bytes);
    controller.close();
  } }), { headers: { 'Content-Type': 'text/event-stream' } });
}
async function collect(events: AsyncIterable<WorkEvent>): Promise<WorkEvent[]> {
  const output: WorkEvent[] = [];
  for await (const event of events) output.push(event);
  return output;
}
function serve(data: string, split = false) {
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => options?.method === 'POST' && options.body ? response(data, split) : new Response('{}'));
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}
afterEach(() => vi.unstubAllGlobals());

describe('AgentOS transport wire boundary', () => {
  it('decodes fragmented UTF8/CRLF and multiline SSE, retaining unverified provenance once', async () => {
    const completed = JSON.stringify(wire('RunCompleted', { content: result }));
    const fetcher = serve(': heartbeat\r\n\r\n' + frame(wire('RunStarted')) + frame(wire('ToolCallCompleted', { tool: { result: '\nSAMURAI_WORKFLOW_RESULT=' + JSON.stringify(result) } })) + `data: ${completed.slice(0, completed.indexOf('"content"'))}\r\ndata: ${completed.slice(completed.indexOf('"content"'))}\r\n\r\n`, true);
    const runs: AgentosRun[] = [];
    const events = await collect(createAgentosTransport('session-1', run => runs.push(run))('Research an idea', new AbortController().signal));
    expect(events).toHaveLength(1);
    const event = events[0];
    expect(event?.type).toBe('message');
    if (event?.type !== 'message' || event.panel?.kind !== 'evidence') throw new Error('Expected evidence');
    expect(event.panel.id).toBe(`artifact-${artifactId}`);
    expect(event.panel.claims.find(claim => claim.id === claimId)).toMatchObject({ id: claimId, status: 'needs-check', sources: [{ url: 'https://example.org/research', title: 'Independent reference' }] });
    expect(event.panel.claims.some(claim => claim.claim === 'Conflicting source')).toBe(true);
    expect(event.panel.provenance).toMatchObject({ status: 'needs_rework', sources: [{ source_id: sourceId, search_query: 'pricing', excerpt: 'A limited sample' }] });
    expect(runs.at(-1)).toEqual({ runId: 'run-1', status: 'completed', companyId: company, revision: 1 });
    const options = fetcher.mock.calls[0]?.[1];
    expect(options?.headers).toEqual({ 'X-Samurai-Client': '1' });
    expect(options?.credentials).toBe('same-origin');
    expect(options?.body).toBeInstanceOf(FormData);
    if (!(options?.body instanceof FormData)) throw new Error('Expected form');
    expect(Object.fromEntries(options.body)).toEqual({ message: 'Research an idea', session_id: 'session-1', stream: 'true', background: 'false' });
  });

  it('shows only real named progress and ordinary final text once', async () => {
    serve(frame(wire('RunStarted')) + frame(wire('CustomEvent', { kind: 'workflow_progress', content: 'Workflow step started' })) + frame(wire('CustomEvent', { kind: 'workflow_progress', content: 'Researcher checking prices' })) + frame(wire('CustomEvent', { kind: 'workflow_progress', content: 'Strategy started' })) + frame(wire('CustomEvent', { kind: 'workflow_progress', content: 'Verify evidence started' })) + frame(wire('RunContent', { content: 'Hello' })) + frame(wire('RunCompleted', { content: 'Hello founder' })));
    expect(await collect(createAgentosTransport('session-1')('Check prices', new AbortController().signal))).toEqual([
      { type: 'activity', agent: 'Researcher', state: 'working', detail: 'Researcher checking prices' },
      { type: 'activity', agent: 'Strategist', state: 'working', detail: 'Strategy started' },
      { type: 'activity', agent: 'Verifier', state: 'working', detail: 'Verify evidence started' },
      { type: 'message', text: 'Hello founder' },
    ]);
  });

  it.each([
    ['malformed JSON', 'data: {oops}\n\n'],
    ['partial event', frame(wire('RunStarted')) + 'data: {'],
    ['missing terminal', frame(wire('RunStarted'))],
    ['foreign session', frame(wire('RunStarted', { session_id: 'session-other' }))],
    ['foreign run', frame(wire('RunStarted')) + frame(wire('RunCompleted', { run_id: 'other', content: 'wrong' }))],
    ['foreign company', frame(wire('RunStarted')) + frame(wire('RunCompleted', { content: { ...result, company_id: '00000000-0000-4000-8000-000000000009' } }))],
    ['unknown claim source', frame(wire('RunStarted')) + frame(wire('RunCompleted', { content: { ...result, artifacts: [{ ...result.artifacts[0], sources: [] }] } }))],
    ['invalid workflow field', frame(wire('RunStarted')) + frame(wire('RunCompleted', { content: { ...result, extra: true } }))],
  ])('rejects %s instead of reporting success', async (_name, data) => {
    serve(data);
    await expect(collect(createAgentosTransport('session-1')('Run research', new AbortController().signal))).rejects.toThrow();
  });

  it('rejects a different company across subsequent runs of the same session transport', async () => {
    const transport = createAgentosTransport('session-1');
    serve(frame(wire('RunStarted')) + frame(wire('RunCompleted', { content: result })));
    await collect(transport('First research', new AbortController().signal));
    const foreign = '00000000-0000-4000-8000-000000000009';
    serve(frame(wire('RunStarted')) + frame(wire('RunCompleted', { content: { ...result, company_id: foreign, artifacts: [{ ...result.artifacts[0], company_id: foreign }] } })));
    await expect(collect(transport('Second research', new AbortController().signal))).rejects.toThrow('another company');
  });

  it('waits for cancel acknowledgement after an abort before RunStarted, without yielding late data', async () => {
    const abort = new AbortController();
    let started: ReadableStreamDefaultController<Uint8Array> | undefined;
    let acknowledge: ((value: Response) => void) | undefined;
    const ack = new Promise<Response>(resolve => { acknowledge = resolve; });
    const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
      if (url.includes('/cancel?')) return ack;
      return new Response(new ReadableStream<Uint8Array>({ start(controller) {
        started = controller;
        options?.signal?.addEventListener('abort', () => controller.error(new DOMException('Cancelled', 'AbortError')));
        abort.abort();
        controller.enqueue(new TextEncoder().encode(frame(wire('RunStarted'))));
      } }), { headers: { 'Content-Type': 'text/event-stream' } });
    });
    vi.stubGlobal('fetch', fetcher);
    const statuses: AgentosRun[] = [];
    let settled = false;
    const output = collect(createAgentosTransport('session-1', run => statuses.push(run))('Check market', abort.signal)).then(events => { settled = true; return events; });
    await vi.waitFor(() => expect(fetcher.mock.calls.some(call => call[0].includes('/cancel?session_id=session-1'))).toBe(true));
    expect(settled).toBe(false);
    started?.enqueue(new TextEncoder().encode(frame(wire('RunCompleted', { content: result }))));
    acknowledge?.(new Response('{}'));
    expect(await output).toEqual([]);
    expect(statuses.at(-1)?.status).toBe('cancelled');
  });

  it('retains a possibly running backend identity when cancellation fails and permits retry', async () => {
    const abort = new AbortController();
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('/cancel?')) return new Response('{}', { status: 403 });
      abort.abort();
      return response(frame(wire('RunStarted')));
    }));
    const statuses: AgentosRun[] = [];
    await expect(collect(createAgentosTransport('session-1', run => statuses.push(run))('Check market', abort.signal))).rejects.toThrow('403');
    expect(statuses.at(-1)).toEqual({ runId: 'run-1', status: 'running' });
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}')));
    await expect(cancelAgentosRun('session-1', 'run-1')).resolves.toBeUndefined();
  });

  it('adapts actual strategy and delivery fields without fabricating pricing', async () => {
    const strategy = { ...result.artifacts[0], artifact_type: 'strategy', producer: 'strategist', payload: { artifact_type: 'strategy', ideal_customer_profile: 'Independent clinics', positioning: 'Reduce missed calls', offer: 'Receptionist trial', pricing_assumptions: [] }, claims: [], sources: [] };
    const plan = { ...result.artifacts[0], artifact_id: '00000000-0000-4000-8000-000000000005', artifact_type: 'product_plan', producer: 'product_manager', payload: { artifact_type: 'product_plan', minimum_viable_offering: ['Call routing'], delivery_requirements: ['Founder approves trial'], user_stories: [], roadmap: ['Collect feedback'] }, claims: [], sources: [] };
    serve(frame(wire('RunStarted')) + frame(wire('RunCompleted', { content: { ...result, artifacts: [strategy, plan] } })));
    const output = await collect(createAgentosTransport('session-1')('Plan my company', new AbortController().signal));
    const panels = output.flatMap(event => event.type === 'message' && event.panel ? [event.panel] : []);
    expect(panels.map(panel => panel.kind)).toEqual(['offer', 'launch-plan']);
    expect(panels[0]).toMatchObject({ customer: 'Independent clinics', promise: 'Receptionist trial', price: 'No pricing assumption supplied' });
    expect(panels[1]).toMatchObject({ tasks: [{ title: 'Call routing' }, { title: 'Founder approves trial' }, { title: 'Collect feedback' }] });
  });

  it('treats RunError as a terminal failure without issuing another cancellation', async () => {
    const fetcher = serve(frame(wire('RunStarted')) + frame(wire('RunError', { content: 'Provider internal detail' })));
    const statuses: AgentosRun[] = [];
    await expect(collect(createAgentosTransport('session-1', run => statuses.push(run))('Run research', new AbortController().signal))).rejects.toThrow('could not complete');
    expect(statuses.at(-1)?.status).toBe('failed');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['2026-10-11T10:00:00+05:30', '2026-10-11T06:00:00Z', true],
    ['2026-10-11T06:00:00Z', '2026-10-11T10:00:00+05:30', false],
  ])('compares offset metric windows by actual time (%s → %s)', async (start, end, valid) => {
    const metricId = '00000000-0000-4000-8000-000000000006';
    const measured = { ...result, outcome: 'based_on_founder_supplied_metrics', artifacts: [{
      ...result.artifacts[0], artifact_type: 'analysis', producer: 'analyst', status: 'based_on_founder_supplied_metrics', claims: [], sources: [],
      payload: { artifact_type: 'analysis', metric_ids: [metricId], findings: ['Founder supplied a conversion count'], recommendations: ['Confirm measurement'], basis: 'based_on_founder_supplied_metrics' },
      measurements: [{ metric_id: metricId, name: 'Trials', value: 3, unit: 'count', window_start: start, window_end: end, source_label: 'Founder CRM export', collected_at: '2026-10-11T07:00:00Z', provenance: 'founder_supplied', trusted_connector_receipt: null }],
    }] };
    serve(frame(wire('RunStarted')) + frame(wire('RunCompleted', { content: measured })));
    const output = collect(createAgentosTransport('session-1')('Assess the founder metrics', new AbortController().signal));
    if (valid) expect(await output).toHaveLength(1);
    else await expect(output).rejects.toThrow('invalid workflow');
  });

  it('projects founder intake into a concise review panel while retaining full provenance', async () => {
    const brief = { idea: 'Cycle repairs for commuters', target_customer: 'Local cyclists', geography: 'Pune', budget: '1000 INR', founder_skills: null, goal: 'First paid pilot', supplied_context: [], assumptions: ['Demand is untested'], open_questions: ['Which neighborhood?'], next_actions: ['Interview cyclists'] };
    const intake = { ...result.artifacts[0], artifact_type: 'intake', producer: 'intake', claims: [], sources: [], payload: { artifact_type: 'intake', brief } };
    serve(frame(wire('RunStarted')) + frame(wire('RunCompleted', { content: { ...result, artifacts: [intake] } })));
    const events = await collect(createAgentosTransport('session-1')('Build my company', new AbortController().signal));
    const event = events[0];
    if (event?.type !== 'message' || event.panel?.kind !== 'evidence') throw new Error('Expected company brief');
    expect(event.panel.title).toBe('Company brief');
    expect(event.panel.claims.find(claim => claim.claim.startsWith('First customers:'))).toMatchObject({ claim: 'First customers: Local cyclists', status: 'needs-check', detail: 'Founder supplied context, not market evidence', sources: [] });
    expect(event.panel.provenance).toEqual(intake);
    expect(event.text).not.toContain('artifact_id');
  });

  it('keeps generated drafts readable and preserves undisplayed content', async () => {
    const marketing = { ...result.artifacts[0], artifact_type: 'marketing_draft', producer: 'marketer', claims: [], sources: [], payload: { artifact_type: 'marketing_draft', landing_page: 'Draft landing page', ads: ['Draft ad'], social_posts: [], emails: ['Draft email'] } };
    serve(frame(wire('RunStarted')) + frame(wire('RunCompleted', { content: { ...result, artifacts: [marketing] } })));
    const events = await collect(createAgentosTransport('session-1')('Prepare drafts', new AbortController().signal));
    const event = events[0];
    if (event?.type !== 'message' || event.panel?.kind !== 'evidence') throw new Error('Expected draft panel');
    expect(event.panel.claims.map(claim => claim.claim)).toEqual(['landing page: Draft landing page', 'ads: Draft ad', 'emails: Draft email']);
    expect(event.panel.provenance).toEqual(marketing);
    expect(event.text).not.toContain('artifact_id');
  });

  it('does not retry run creation on HTTP failure', async () => {
    const fetcher = vi.fn(async () => new Response('{}', { status: 503 }));
    vi.stubGlobal('fetch', fetcher);
    await expect(collect(createAgentosTransport('session-1')('Check market', new AbortController().signal))).rejects.toThrow('503');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('recovers completed artifacts from a scoped saved run without starting another run', async () => {
    const fetcher = vi.fn(async (_url: string, _options?: RequestInit) => Response.json({ run_id: 'run-1', session_id: 'session-1', agent_id: 'samurai', status: 'COMPLETED', content: result, metrics: {} }));
    vi.stubGlobal('fetch', fetcher);
    const saved = await readAgentosRun('session-1', 'run-1');
    expect(saved.run).toEqual({ runId: 'run-1', status: 'completed', companyId: company, revision: 1 });
    expect(saved.events).toHaveLength(1);
    expect(fetcher.mock.calls[0]?.[0]).toBe('/api/agentos/agents/samurai/runs/run-1?session_id=session-1');
    expect(fetcher.mock.calls[0]?.[1]?.method).toBe('GET');
  });

  it('rejects foreign identity during saved run recovery', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ run_id: 'run-1', session_id: 'another-session', agent_id: 'samurai', status: 'COMPLETED', content: result })));
    await expect(readAgentosRun('session-1', 'run-1')).rejects.toThrow('another session');
  });
});


it('retains real start and completion events from saved runs after reload', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ run_id: 'run-1', session_id: 'session-1', agent_id: 'samurai', status: 'COMPLETED', content: 'Research needs sources', events: [wire('CustomEvent', { kind: 'workflow_progress', content: 'Research started' }), wire('CustomEvent', { kind: 'workflow_progress', content: 'Research completed' })] }))));
  const recovered = await readAgentosRun('session-1', 'run-1');
  expect(recovered.events.slice(0, 2)).toEqual([
    { type: 'activity', agent: 'Researcher', state: 'working', detail: 'Research started' },
    { type: 'activity', agent: 'Researcher', state: 'done', detail: 'Research completed' },
  ]);
});


it('reads progress from native serialized content when Agno drops custom top-level fields', async () => {
  serve(frame(wire('RunStarted')) + frame(wire('CustomEvent', { content: { kind: 'workflow_progress', detail: 'Research started' } })) + frame(wire('CustomEvent', { content: { kind: 'workflow_progress', detail: 'Research completed' } })) + frame(wire('RunCompleted', { content: 'Insufficient evidence' })));
  expect((await collect(createAgentosTransport('session-1')('Synthetic test', new AbortController().signal))).slice(0, 2)).toEqual([
    { type: 'activity', agent: 'Researcher', state: 'working', detail: 'Research started' },
    { type: 'activity', agent: 'Researcher', state: 'done', detail: 'Research completed' },
  ]);
});


it('shows evidence gates as waiting instead of inventing strategy completion', async () => {
  serve(frame(wire('RunStarted')) + frame(wire('RunCompleted', { content: { ...result, outcome: 'insufficient_evidence' } })));
  const events = await collect(createAgentosTransport('session-1')('Synthetic test', new AbortController().signal));
  expect(events.filter(event => event.type === 'activity')).toEqual([
    { type: 'activity', agent: 'Researcher', state: 'waiting', detail: 'Research finished without sufficient source evidence.' },
    { type: 'activity', agent: 'Verifier', state: 'waiting', detail: 'Evidence review blocked: source support is missing.' },
    { type: 'activity', agent: 'Strategist', state: 'waiting', detail: 'Waiting for source evidence before strategy can start.' },
  ]);
});

describe('founder-facing saved response presentation', () => {
  it('hides status labels and maps saved wire JSON without changing the original', () => {
    const saved: Message[] = [
      { id: 'user', role: 'user', text: 'product plan: complete' },
      { id: 'status', role: 'assistant', text: 'product plan: complete' },
      { id: 'wire', role: 'assistant', text: JSON.stringify(result.artifacts[0]) },
    ];
    const before = JSON.stringify(saved);
    const presented = presentMessages(saved);
    expect(presented).toHaveLength(2);
    expect(presented[0]?.text).toBe('product plan: complete');
    expect(presented[1]?.text).toBe('');
    expect(presented[1]?.panel?.provenance).toEqual(result.artifacts[0]);
    expect(JSON.stringify(saved)).toBe(before);
    expect(presentMessages([...saved, presented[1]!])).toHaveLength(2);
  });

  it('does not expose malformed or incomplete wire JSON', () => {
    const saved: Message = { id: 'invalid', role: 'assistant', text: '{"artifact_type":"research"}' };
    expect(presentMessages([saved])[0]?.text).toBe('This response could not be displayed. Its data is incomplete.');
  });

  it('keeps genuine questions and human explanations', () => {
    const message: Message = { id: 'question', role: 'assistant', text: 'Ready to research your market?' };
    expect(presentMessages([message])).toEqual([message]);
  });

  it('does not repeat unchanged artifacts on the next founder-approved stage', async () => {
    serve(frame(wire('RunStarted')) + frame(wire('RunCompleted', { content: result })));
    const saved = presentMessages([{ id: 'wire', role: 'assistant', text: JSON.stringify(result) }]);
    expect(await collect(createAgentosTransport('session-1', undefined, () => saved)('Continue', new AbortController().signal))).toEqual([]);
  });
});


it('retains later conflicts and review warnings when research has more than 30 findings', async () => {
  const large = structuredClone(result);
  large.artifacts[0]!.claims = Array.from({length: 31}, (_, index) => ({ ...result.artifacts[0]!.claims[0]!, claim_id: `00000000-0000-4000-8000-${String(index + 100).padStart(12, '0')}`, text: `Finding ${index + 1}` }));
  serve(frame(wire('RunStarted')) + frame(wire('RunCompleted', {content: large})));
  const events = await collect(createAgentosTransport('session-1')('Research', new AbortController().signal));
  const event = events[0];
  if (event?.type !== 'message' || event.panel?.kind !== 'evidence') throw new Error('Expected research');
  expect(event.panel.claims).toHaveLength(34);
  expect(event.panel.claims.some(claim => claim.claim === 'Conflicting source')).toBe(true);
  expect(event.panel.claims.some(claim => claim.claim === 'Validate demand')).toBe(true);
  expect(event.panel.claims.some(claim => claim.claim === 'Finding 31')).toBe(true);
});


it('keeps the offer concise while retaining all pricing options', () => {
  const prices = Array.from({length: 13}, (_, index) => `Test price ${index + 1}`);
  const saved: Message = { id: 'strategy', role: 'assistant', text: JSON.stringify({ ...result.artifacts[0], artifact_type: 'strategy', producer: 'strategist', payload: { artifact_type: 'strategy', ideal_customer_profile: 'Test customers', positioning: 'Simple positioning', offer: 'A focused pilot', pricing_assumptions: prices } }) };
  const messages = presentMessages([saved]);
  expect(messages.find(message => message.panel?.kind === 'offer')?.panel).toMatchObject({price: prices[0]});
  expect(messages.find(message => message.panel?.kind === 'pricing')?.panel).toMatchObject({options: prices.map((price, index) => ({name: `Assumption ${index + 1}`, price, description: ''}))});
});
