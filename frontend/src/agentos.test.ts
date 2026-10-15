import { afterEach, describe, expect, it, vi } from 'vitest';
import { cancelAgentosRun, companyResultSchema, companySnapshotEvents, createAgentosTransport, readAgentosRun, resumeAgentosRun, presentMessages, type AgentosRun } from './agentos';
import { loadPortfolio, persistPortfolio, portfolioStorageKey } from './browserStorage';
import { emptyCompanyView, type Message, type WorkEvent } from './model';

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
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => options?.method === 'POST' && options.body ? response(data, split) : new Response(JSON.stringify(options?.method === 'GET' ? wire('RunCancelled', { status: 'CANCELLED' }) : {})));
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}
afterEach(() => vi.unstubAllGlobals());

describe('AgentOS transport wire boundary', () => {
  it('rejects hostile HTML before mapping panels and leaves the last saved workspace intact', async () => {
    const hostile = { ...result, artifacts: [{ ...result.artifacts[0], payload: { ...result.artifacts[0].payload, summary: '<img src=x onerror="alert(1)">' } }] };
    const script = { ...result, artifacts: [{ ...result.artifacts[0], payload: { ...result.artifacts[0].payload, summary: '<script>alert(1)</script>' } }] };
    const ordinaryBusinessText = { ...result, artifacts: [{ ...result.artifacts[0], payload: { ...result.artifacts[0].payload, summary: 'Pilot price ₹4,999 < ₹5,499 budget' } }] };
    expect(companyResultSchema.safeParse(hostile).success).toBe(false);
    expect(companyResultSchema.safeParse(script).success).toBe(false);
    expect(companyResultSchema.safeParse(ordinaryBusinessText).success).toBe(true);

    const scope = { kind: 'development' } as const;
    const saved = new Map<string, string>();
    const lastValid = { version: 2 as const, mode: 'light' as const, activeId: 'saved-company', companies: [{ id: 'saved-company', name: 'Saved clinic pilot', workspace: emptyCompanyView() }] };
    const key = portfolioStorageKey(scope);
    expect(persistPortfolio({ setItem: (storageKey, value) => { saved.set(storageKey, value); } }, key, lastValid)).toBe(true);

    serve(frame(wire('RunStarted')) + frame(wire('RunCompleted', { content: hostile })));
    await expect(collect(createAgentosTransport('session-1')('Check pricing', new AbortController().signal))).rejects.toThrow('invalid workflow result');
    expect(loadPortfolio({ getItem: storageKey => saved.get(storageKey) ?? null }, scope)).toEqual(lastValid);
  });

  it('parses adjudicated Research with the existing evidence panel and rejects malformed provenance', async () => {
    const raw = result.artifacts[0];
    const source = raw.sources[0], claim = raw.claims[0];
    const decision = {
      research_artifact_id: raw.artifact_id, research_revision: raw.revision, claim_id: claim.claim_id, claim_text: claim.text, source_id: source.source_id, source_url: source.url,
      attempted_at: '2026-10-12T00:00:00Z', fetched_at: '2026-10-12T00:00:01Z', final_url: source.url, content_sha256: 'a'.repeat(64), media_type: 'text/html', evidence_quote: 'A limited sample', verdict: 'supported', rationale: 'The retained excerpt supports the claim.',
    };
    const adjudicated = {
      ...result, revision: 2, artifacts: [{
        ...raw, artifact_id: '00000000-0000-4000-8000-000000000005', revision: 2, input_revision: 1,
        claims: [{ ...claim, verification_status: 'supported' },],
        payload: { ...raw.payload, adjudicated_from_artifact_id: raw.artifact_id, adjudicated_from_revision: raw.revision, adjudications: [decision] },
      }],
    };

    const parsed = companyResultSchema.safeParse(adjudicated);
    expect(parsed.success).toBe(true);
    serve(frame(wire('RunStarted')) + frame(wire('RunCompleted', { content: adjudicated })));
    const events = await collect(createAgentosTransport('session-1')('Research', new AbortController().signal));
    expect(events[0]).toMatchObject({ type: 'message', panel: { kind: 'evidence', title: 'Research evidence' } });

    const malformed = {
      ...adjudicated,
      artifacts: [{ ...adjudicated.artifacts[0], payload: { ...adjudicated.artifacts[0]?.payload, adjudications: [{ ...decision, content_sha256: 'not-a-sha' }] } }],
    };
    expect(companyResultSchema.safeParse(malformed).success).toBe(false);
    const forgedStatus = { ...adjudicated, artifacts: [{ ...adjudicated.artifacts[0], claims: [claim] }] };
    expect(companyResultSchema.safeParse(forgedStatus).success).toBe(false);
  });

  it('preserves strict knowledge references and rejects malformed source identity', () => {
    const reference = {
      chunk_id: '00000000-0000-4000-8000-000000000010', file_id: '00000000-0000-4000-8000-000000000011', artifact_id: null,
      indexed_revision: 7, ordinal: 2, content_sha256: 'b'.repeat(64), trust_class: 'uploaded_file', evidence_status: 'untrusted_context',
    };
    const grounded = { ...result, artifacts: [{ ...result.artifacts[0], knowledge_references: [reference] }] };
    const parsed = companyResultSchema.safeParse(grounded);

    expect(parsed.success).toBe(true);
    if (!parsed.success) throw new Error('Expected a grounded artifact');
    expect(parsed.data.artifacts[0]?.knowledge_references).toEqual([reference]);
    expect(companyResultSchema.safeParse({ ...grounded, artifacts: [{ ...grounded.artifacts[0], knowledge_references: [{ ...reference, artifact_id: artifactId }] }] }).success).toBe(false);
    expect(companyResultSchema.safeParse({ ...grounded, artifacts: [{ ...grounded.artifacts[0], knowledge_references: [{ ...reference, content_sha256: 'bad' }] }] }).success).toBe(false);
  });

  it('parses additive founder truth and exact framework provenance in Intake snapshots', () => {
    const framework = { id: 'founder_truth', version: '1.0.0', source_repository: 'gvkhosla/founder-skills', source_revision: '07ea968338cff2ba67ff245671765ea957ce0a0c', source_url: 'https://github.com/gvkhosla/founder-skills/tree/07ea968338cff2ba67ff245671765ea957ce0a0c', license: 'MIT', attribution: 'Adapted from Founder Skills by Geet Khosla.', allowed_roles: ['intake', 'strategist', 'verifier'], sha256: 'ba206825fb8ebd15cf911397e55628ff8b5aacf28cbb02b65d20c978bc31e0bb', review_date: '2026-10-15' };
    const truth = { known: [{ text: 'Python', basis: 'founder_context', context_key: 'founder_skills', evidence_ids: [] }], believed: ['Clinics may lose bookings'], hoped: ['A clinic will pay'], evidence_gaps: ['No interviews'], bottleneck: 'Validate the pain', next_decision: 'Choose a clinic segment' };
    const intake = { ...result.artifacts[0], artifact_type: 'intake', producer: 'intake', sources: [], claims: [], payload: { artifact_type: 'intake', brief: { idea: 'AI receptionist', target_customer: 'Clinics', geography: 'India', budget: 'INR 50000', founder_skills: 'Python', goal: 'Validate demand', supplied_context: [], assumptions: [], open_questions: [], next_actions: [] }, founder_truth: truth, frameworks: [framework] } };
    const snapshot = { summary: { company_id: company, revision: 1, artifact_count: 1, status: 'active', brief: intake.payload.brief, founder_truth: truth, sources: [], evidence_conflicts: [], verification_findings: [], next_decision: truth.next_decision, artifacts: [intake], frameworks: [framework] }, artifacts: [intake] };

    const events = companySnapshotEvents(snapshot, company);

    expect(events.some(event => event.type === 'message' && event.panel?.provenance && 'founder_truth' in event.panel.provenance)).toBe(true);
    const briefPanel = events.find(event => event.type === 'message' && event.panel?.title === 'Company brief');
    if (briefPanel?.type !== 'message' || briefPanel.panel?.kind !== 'evidence') throw new Error('Expected founder brief panel');
    expect(briefPanel.panel.id).toBe(`artifact-${artifactId}`);
    expect(briefPanel.panel.founder_context).toMatchObject({ next_decision: truth.next_decision, evidence_gaps: truth.evidence_gaps, framework: { id: 'founder_truth', version: '1.0.0' } });
    expect(briefPanel.panel.claims.map(claim => claim.claim)).toContain('Believed: Clinics may lose bookings');
  });
  it('maps an evidence-gated offer diagnostic to stable offer and pricing panels', () => {
    const framework = { id: 'offer_diagnostic', version: '1.0.0', source_repository: 'mindantic/hormozi', source_revision: '45ab29ffa1aab417f76b90e49dd97e1007af81f7', source_url: 'https://github.com/mindantic/hormozi/tree/45ab29ffa1aab417f76b90e49dd97e1007af81f7', license: 'MIT', attribution: 'Adapted from reviewed offer diagnostics.', allowed_roles: ['strategist'], sha256: 'c'.repeat(64), review_date: '2026-10-15' };
    const diagnostic = { market: 'Independent clinics', painful_problem: 'Missed calls', purchasing_power_assumption: { assumption_id: '00000000-0000-4000-8000-000000000008', text: 'Clinics can test a monthly fee' }, draft_offer: 'Receptionist trial', evidence_needed: ['Interview five owners'], framework };
    const strategy = { ...result.artifacts[0], artifact_id: '00000000-0000-4000-8000-000000000009', artifact_type: 'strategy', producer: 'strategist', claims: [], sources: [], payload: { artifact_type: 'strategy', ideal_customer_profile: 'Independent clinics', positioning: 'Reduce missed calls', offer: 'Receptionist trial', pricing_assumptions: ['₹4999 monthly'], offer_diagnostic: diagnostic } };
    const events = companySnapshotEvents({ summary: { company_id: company, revision: 1, artifact_count: 1, status: 'active', brief: null, sources: [], evidence_conflicts: [], verification_findings: [], next_decision: null, artifacts: [], frameworks: [] }, artifacts: [strategy] }, company);
    const panels = events.flatMap(event => event.type === 'message' && event.panel ? [event.panel] : []);
    expect(panels.map(panel => panel.id)).toEqual([`company-summary-${company}`, `artifact-${strategy.artifact_id}`, `artifact-${strategy.artifact_id}-pricing`]);
    const offer = panels.find(panel => panel.kind === 'offer');
    const pricing = panels.find(panel => panel.kind === 'pricing');
    expect(offer?.founder_context).toMatchObject({ evidence_gaps: ['Interview five owners', 'Purchasing power assumption: Clinics can test a monthly fee'], framework: { id: 'offer_diagnostic' } });
    expect(pricing?.founder_context).toMatchObject({ evidence_gaps: ['Interview five owners', 'Purchasing power assumption: Clinics can test a monthly fee'] });
    expect(pricing?.founder_context?.framework).toBeUndefined();
  });
  it('hydrates matching canonical summary and strategy/product artifacts without a run', () => {
    const strategy = { ...result.artifacts[0], artifact_id: '00000000-0000-4000-8000-000000000005', artifact_type: 'strategy', producer: 'strategist', claims: [], sources: [], payload: { artifact_type: 'strategy', ideal_customer_profile: 'Independent clinics', positioning: 'Reduce missed calls', offer: 'Receptionist trial', pricing_assumptions: [] } };
    const plan = { ...result.artifacts[0], artifact_id: '00000000-0000-4000-8000-000000000006', artifact_type: 'product_plan', producer: 'product_manager', claims: [], sources: [], payload: { artifact_type: 'product_plan', minimum_viable_offering: ['Call routing'], delivery_requirements: ['Founder approves trial'], user_stories: [], roadmap: ['Collect feedback'] } };
    const framework = { id: 'founder_truth', version: '1.0.0', source_repository: 'gvkhosla/founder-skills', source_revision: '07ea968338cff2ba67ff245671765ea957ce0a0c', source_url: 'https://github.com/gvkhosla/founder-skills/tree/07ea968338cff2ba67ff245671765ea957ce0a0c', license: 'MIT', attribution: 'Adapted from Founder Skills by Geet Khosla.', allowed_roles: ['intake', 'strategist', 'verifier'], sha256: 'ba206825fb8ebd15cf911397e55628ff8b5aacf28cbb02b65d20c978bc31e0bb', review_date: '2026-10-15' };
    const snapshot = { summary: { company_id: company, revision: 1, artifact_count: 2, status: 'active', brief: null, sources: [], evidence_conflicts: [], verification_findings: [], next_decision: null, artifacts: [strategy], frameworks: [framework] }, artifacts: [strategy, plan] };
    const events = companySnapshotEvents(snapshot, company);
    const panels = events.flatMap(event => event.type === 'message' && event.panel ? [event.panel] : []);
    expect(panels.map(panel => panel.kind)).toEqual(['evidence', 'offer', 'launch-plan']);
    expect(panels[0]?.provenance).toMatchObject({ frameworks: [framework] });
    expect(() => companySnapshotEvents({ ...snapshot, summary: { ...snapshot.summary, company_id: '00000000-0000-4000-8000-000000000009' } }, company)).toThrow('does not match');
    expect(() => companySnapshotEvents({ ...snapshot, summary: { ...snapshot.summary, frameworks: [{ ...framework, resource: '../private.md' }] } }, company)).toThrow('does not match');
    expect(() => companySnapshotEvents({ ...snapshot, summary: { ...snapshot.summary, frameworks: [framework, framework] } }, company)).toThrow('does not match');
  });
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
    expect(runs.at(-1)).toMatchObject({ runId: 'run-1', status: 'completed', companyId: company, revision: 1 });
    const options = fetcher.mock.calls[0]?.[1];
    expect(options?.headers).toMatchObject({ 'X-Samurai-Client': '1', 'X-Samurai-Submission-Id': expect.any(String) });
    expect(options?.credentials).toBe('same-origin');
    expect(options?.body).toBeInstanceOf(FormData);
    if (!(options?.body instanceof FormData)) throw new Error('Expected form');
    expect(Object.fromEntries(options.body)).toEqual({ message: 'Research an idea', session_id: 'session-1', stream: 'true', background: 'true' });
  });

  it('persists the logical submission before sending the only run POST', async () => {
    const fetcher = serve(frame(wire('RunStarted')) + frame(wire('RunCompleted', { content: 'Done' })));
    const runs: AgentosRun[] = [];
    const transport = createAgentosTransport('session-1', run => {
      runs.push(run);
      return run.status !== 'submitting' || runs.length === 1;
    }, () => [], () => '00000000-0000-4000-8000-000000000099');
    await collect(transport('Build it', new AbortController().signal));
    expect(runs[0]).toEqual({ submissionId: '00000000-0000-4000-8000-000000000099', status: 'submitting' });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0]?.[1]?.headers).toMatchObject({ 'X-Samurai-Submission-Id': '00000000-0000-4000-8000-000000000099' });
  });

  it('sends explicit founder approval only as validated stage headers', async () => {
    const fetcher = serve(frame(wire('RunStarted')) + frame(wire('RunCompleted', { content: result })));
    const transport = createAgentosTransport('session-1', () => true, () => [], () => '00000000-0000-4000-8000-000000000099');
    await collect(transport('Research our market and stop before strategy.', new AbortController().signal, { operation: 'journey', stage: 'research', expectedRevision: 3, companyId: company }));
    expect(fetcher.mock.calls[0]?.[1]?.headers).toMatchObject({
      'X-Samurai-Submission-Id': '00000000-0000-4000-8000-000000000099',
      'X-Samurai-Operation': 'journey',
      'X-Samurai-Stage': 'research',
      'X-Samurai-Expected-Revision': '3',
      'X-Samurai-Company-Id': company,
    });
    expect(Object.fromEntries(fetcher.mock.calls[0]?.[1]?.body as FormData)).toEqual({ message: 'Research our market and stop before strategy.', session_id: 'session-1', stream: 'true', background: 'true' });
  });

  it('does not submit when the logical submission cannot be persisted', async () => {
    const fetcher = vi.fn<typeof fetch>();
    vi.stubGlobal('fetch', fetcher);
    const transport = createAgentosTransport('session-1', () => false, () => [], () => '00000000-0000-4000-8000-000000000099');
    await expect(collect(transport('Build it', new AbortController().signal))).rejects.toThrow('saved');
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('resumes the same durable run after an SSE disconnect without replaying the submit POST', async () => {
    const calls: Array<[string, RequestInit | undefined]> = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
      calls.push([url, options]);
      if (calls.length === 1) return response(frame(wire('RunStarted', { event_index: 0 })) + frame(wire('CustomEvent', { event_index: 1, kind: 'workflow_progress', content: 'Research started' })));
      return response(frame(wire('RunCompleted', { event_index: 2, content: result })));
    }));
    const events = await collect(createAgentosTransport('session-1', () => true, () => [], () => '00000000-0000-4000-8000-000000000099')('Research', new AbortController().signal));
    expect(events).toHaveLength(2);
    expect(calls.map(call => call[0])).toEqual([
      '/api/agentos/agents/samurai/runs',
      '/api/agentos/agents/samurai/runs/run-1/resume',
    ]);
    expect(calls.filter(call => call[0] === '/api/agentos/agents/samurai/runs')).toHaveLength(1);
    const resumeBody = calls[1]?.[1]?.body;
    expect(resumeBody).toBeInstanceOf(FormData);
    if (!(resumeBody instanceof FormData)) throw new Error('Expected resume form');
    expect(Object.fromEntries(resumeBody)).toEqual({ session_id: 'session-1', last_event_index: '1' });
  });

  it('uses the owner receipt when the initial stream is lost before RunStarted', async () => {
    const calls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      calls.push(url);
      if (url.includes('/work-receipts/')) return Response.json({ run_id: 'run-1', session_id: 'session-1', status: 'PENDING', attempt: 0, max_attempts: 2, recovering: false, failure_reason: null, company_id: null, revision: null, updated_at: null });
      if (url.endsWith('/resume')) return response(frame(wire('RunStarted', { event_index: 0 })) + frame(wire('RunCompleted', { event_index: 1, content: 'Recovered' })));
      return response('');
    }));
    const output = await collect(createAgentosTransport('session-1', () => true, () => [], () => '00000000-0000-4000-8000-000000000099')('Build it', new AbortController().signal));
    expect(output).toEqual([{ type: 'message', text: 'Recovered' }]);
    expect(calls).toEqual([
      '/api/agentos/agents/samurai/runs',
      '/api/agentos/work-receipts/00000000-0000-4000-8000-000000000099?session_id=session-1',
      '/api/agentos/agents/samurai/runs/run-1/resume',
    ]);
  });

  it('reloads from the saved receipt and resumes without submitting again', async () => {
    const calls: string[] = [];
    const states: AgentosRun[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      calls.push(url);
      if (url.includes('/work-receipts/')) return Response.json({ run_id: 'run-1', session_id: 'session-1', status: 'RUNNING', attempt: 0, max_attempts: 2, recovering: false, failure_reason: null, company_id: null, revision: null, updated_at: null });
      return response(frame(wire('RunCompleted', { event_index: 5, content: 'Done after reload' })));
    }));
    const events = await collect(resumeAgentosRun('session-1', { submissionId: '00000000-0000-4000-8000-000000000099', status: 'submitting' }, new AbortController().signal, run => states.push(run)));
    expect(events).toEqual([{ type: 'message', text: 'Done after reload' }]);
    expect(states.at(-1)).toMatchObject({ submissionId: '00000000-0000-4000-8000-000000000099', runId: 'run-1', status: 'completed', attempt: 0, maxAttempts: 2, lastEventIndex: 5 });
    expect(calls).toEqual([
      '/api/agentos/work-receipts/00000000-0000-4000-8000-000000000099?session_id=session-1',
      '/api/agentos/agents/samurai/runs/run-1/resume',
    ]);
    expect(calls).not.toContain('/api/agentos/agents/samurai/runs');
  });

  it.each([
    ['CANCELLED', 'cancelled'],
    ['ERROR', 'failed'],
  ] as const)('reconciles a saved running run with a terminal %s receipt without replaying submit or resume', async (receiptStatus, expectedStatus) => {
    const calls: Array<[string, string | undefined]> = [];
    const states: AgentosRun[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
      calls.push([url, options?.method]);
      if (url.includes('/work-receipts/')) return Response.json({ run_id: 'run-1', session_id: 'session-1', status: receiptStatus, attempt: receiptStatus === 'ERROR' ? 2 : 1, max_attempts: 2, recovering: false, failure_reason: receiptStatus === 'ERROR' ? 'work stopped after the allowed attempts' : 'work was cancelled', company_id: null, revision: null, updated_at: 1 });
      return Response.json({ run_id: 'run-1', session_id: 'session-1', agent_id: 'samurai', status: receiptStatus });
    }));
    const events = await collect(resumeAgentosRun('session-1', { submissionId: '00000000-0000-4000-8000-000000000099', runId: 'run-1', status: 'running' }, new AbortController().signal, run => states.push(run)));
    expect(events).toEqual([]);
    expect(states.at(-1)).toMatchObject({ submissionId: '00000000-0000-4000-8000-000000000099', runId: 'run-1', status: expectedStatus, attempt: receiptStatus === 'ERROR' ? 2 : 1, maxAttempts: 2 });
    expect(calls).toEqual([
      ['/api/agentos/work-receipts/00000000-0000-4000-8000-000000000099?session_id=session-1', 'GET'],
      ['/api/agentos/agents/samurai/runs/run-1?session_id=session-1', 'GET'],
    ]);
    expect(calls.some(([url]) => url === '/api/agentos/agents/samurai/runs' || url.endsWith('/resume'))).toBe(false);
  });

  it('cancels once when abort precedes the receipt run id without replaying submit', async () => {
    const abort = new AbortController();
    const calls: Array<[string, string | undefined]> = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
      calls.push([url, options?.method]);
      if (url.includes('/work-receipts/')) return Response.json({ run_id: 'run-1', session_id: 'session-1', status: 'PENDING', attempt: 0, max_attempts: 2, recovering: false, failure_reason: null, company_id: null, revision: null, updated_at: null });
      if (url.includes('/cancel?')) return Response.json({});
      if (options?.method === 'GET') return Response.json({ run_id: 'run-1', session_id: 'session-1', agent_id: 'samurai', status: 'CANCELLED' });
      return response('');
    }));
    const events = await collect(createAgentosTransport('session-1', run => { if (run.status === 'submitting') abort.abort(); return true; }, () => [], () => '00000000-0000-4000-8000-000000000099')('Build it', abort.signal));
    expect(events).toEqual([]);
    expect(calls.filter(([url]) => url === '/api/agentos/agents/samurai/runs')).toHaveLength(1);
    expect(calls.filter(([url]) => url.includes('/cancel?session_id=session-1'))).toHaveLength(1);
    expect(calls.some(([url]) => url.endsWith('/resume'))).toBe(false);
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

  it('keeps cancellation active after acknowledgement until the scoped run is terminal', async () => {
    const abort = new AbortController();
    let acknowledge: ((value: Response) => void) | undefined;
    const ack = new Promise<Response>(resolve => { acknowledge = resolve; });
    let confirm: ((value: Response) => void) | undefined;
    const stored = new Promise<Response>(resolve => { confirm = resolve; });
    const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
      if (url.includes('/cancel?')) return ack;
      if (options?.method === 'GET') return stored;
      return new Response(new ReadableStream<Uint8Array>({ start(controller) {
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
    acknowledge?.(new Response('{}'));
    await vi.waitFor(() => expect(fetcher.mock.calls.some(call => call[1]?.method === 'GET')).toBe(true));
    expect(settled).toBe(false);
    expect(statuses.at(-1)?.status).toBe('running');
    confirm?.(new Response(JSON.stringify(wire('RunCancelled', { status: 'CANCELLED' }))));
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
    expect(statuses.at(-1)).toMatchObject({ runId: 'run-1', status: 'running' });
    vi.stubGlobal('fetch', vi.fn(async (_url: string, options?: RequestInit) => new Response(JSON.stringify(options?.method === 'GET' ? wire('RunCancelled', { status: 'CANCELLED' }) : {}))));
    await expect(cancelAgentosRun('session-1', 'run-1')).resolves.toMatchObject({ run: { runId: 'run-1', status: 'cancelled' }, events: [] });
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

  it('does not replay run creation while checking a receipt after HTTP failure', async () => {
    const fetcher = vi.fn(async (_url: string, _options?: RequestInit) => new Response('{}', { status: 503 }));
    vi.stubGlobal('fetch', fetcher);
    await expect(collect(createAgentosTransport('session-1')('Check market', new AbortController().signal))).rejects.toThrow('503');
    expect(fetcher.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1);
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes('/work-receipts/'))).toHaveLength(1);
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


describe('authoritative cancellation confirmation', () => {
  it('polls pending, running and paused states before confirming cancellation', async () => {
    let reads = 0;
    const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
      if (options?.method !== 'GET') return new Response('{}');
      reads += 1;
      return new Response(JSON.stringify(wire('RunStarted', { status: reads === 1 ? 'PENDING' : reads === 2 ? 'RUNNING' : reads === 3 ? 'PAUSED' : 'CANCELLED' })));
    });
    vi.stubGlobal('fetch', fetcher);
    expect((await cancelAgentosRun('session-1', 'run-1')).run.status).toBe('cancelled');
    expect(reads).toBe(4);
    for (const [url, options] of fetcher.mock.calls) if (options?.method === 'GET') expect(url).toContain('/run-1?session_id=session-1');
  });

  it('reports completed and recovers artifacts when completion wins the Stop race', async () => {
    const abort = new AbortController();
    vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
      if (url.includes('/cancel?')) return new Response('{}');
      if (options?.method === 'GET') return new Response(JSON.stringify(wire('RunCompleted', { status: 'COMPLETED', content: result })));
      abort.abort();
      return response(frame(wire('RunStarted')));
    }));
    const statuses: AgentosRun[] = [];
    const events = await collect(createAgentosTransport('session-1', run => statuses.push(run))('Research', abort.signal));
    expect(statuses.at(-1)).toMatchObject({ runId: 'run-1', status: 'completed', companyId: company, revision: 1 });
    expect(statuses.some(run => run.status === 'cancelled')).toBe(false);
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ type: 'message', panel: { id: `artifact-${artifactId}` } });
  });

  it('does not reinterpret a stored error as cancellation', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_url: string, options?: RequestInit) => new Response(JSON.stringify(options?.method === 'GET' ? wire('RunError', { status: 'ERROR' }) : {}))));
    expect((await cancelAgentosRun('session-1', 'run-1')).run.status).toBe('failed');
  });

  it('keeps the run possibly active when confirmation reads fail', async () => {
    const abort = new AbortController();
    vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
      if (url.includes('/cancel?')) return new Response('{}');
      if (options?.method === 'GET') return new Response('{}', { status: 503 });
      abort.abort();
      return response(frame(wire('RunStarted')));
    }));
    const statuses: AgentosRun[] = [];
    await expect(collect(createAgentosTransport('session-1', run => statuses.push(run))('Research', abort.signal))).rejects.toThrow('503');
    expect(statuses.at(-1)).toMatchObject({runId:'run-1', status:'running'});
  });

  it('rejects confirmation from another session instead of unlocking the run', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_url: string, options?: RequestInit) => new Response(JSON.stringify(options?.method === 'GET' ? wire('RunCancelled', { status: 'CANCELLED', session_id: 'foreign' }) : {}))));
    await expect(cancelAgentosRun('session-1', 'run-1')).rejects.toThrow('another session or run');
  });
});

describe('canonical company recall', () => {
  const summary = {
    company_id: company, revision: 3, artifact_count: 2, status: 'active',
    brief: { idea: 'A clinic receptionist', target_customer: 'Independent clinics', geography: 'Pune', budget: 'INR 20000', founder_skills: 'Software delivery', goal: 'One pilot', supplied_context: [], assumptions: ['Customers may pay monthly'], open_questions: [], next_actions: ['Interview clinics'] },
    sources: [{ source_id: sourceId, url: 'https://example.org/research', title: 'Independent reference', retrieved_at: '2026-10-11T00:00:00Z', search_query: 'pricing', excerpt: 'A limited sample' }],
    evidence_conflicts: ['Prices differ between sources'],
    verification_findings: [{ code: 'missing_evidence', message: 'Validate demand', severity: 'warning' }],
    next_decision: 'Interview clinics',
  };
  function expectReadable(events: readonly WorkEvent[]) {
    const messages = events.flatMap(event => event.type === 'message' ? [{ id: 'recall', role: 'assistant' as const, text: event.text, ...(event.panel ? { panel: event.panel } : {}) }] : []);
    const displayed = presentMessages(messages);
    const content = JSON.stringify(displayed);
    for (const value of ['A clinic receptionist', 'Independent clinics', 'Interview clinics', 'Prices differ between sources', 'Validate demand', 'https://example.org/research']) expect(content).toContain(value);
    expect(displayed.some(message => message.panel)).toBe(true);
    expect(displayed.some(message => message.text.includes('could not be displayed'))).toBe(false);
  }
  it.each([true, false])('renders a canonical summary on streamed completion (string=%s)', async stringify => {
    // Given a native read_company_state result, When the stream completes, Then its context is readable.
    const content = stringify ? JSON.stringify(summary) : summary;
    serve(frame(wire('RunStarted')) + frame(wire('ToolCallCompleted', { tool: { result: content } })) + frame(wire('RunCompleted', { content })));
    const runs: AgentosRun[] = [];
    const events = await collect(createAgentosTransport('session-1', run => runs.push(run))('Recall my company', new AbortController().signal));
    expectReadable(events);
    expect(events.filter(event => event.type === 'message' && event.panel)).toHaveLength(1);
    expect(runs.at(-1)).toMatchObject({ companyId: company, revision: 3, status: 'completed' });
  });
  it('renders canonical summary when recovering a saved completed run', async () => {
    // Given saved native JSON, When recovering it, Then the same readable context is restored.
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(wire('RunCompleted', { status: 'COMPLETED', content: JSON.stringify(summary) })))));
    expectReadable((await readAgentosRun('session-1', 'run-1')).events);
  });
  it('rejects a malformed canonical summary instead of rendering it', async () => {
    // Given an invalid source URL, When consuming recall, Then boundary validation rejects it.
    serve(frame(wire('RunStarted')) + frame(wire('RunCompleted', { content: { ...summary, sources: [{ ...summary.sources[0], url: 'javascript:alert(1)' }] } })));
    await expect(collect(createAgentosTransport('session-1')('Recall', new AbortController().signal))).rejects.toThrow('invalid workflow result');
  });
  it('renders an unstarted company without inventing a company identity', async () => {
    // Given a valid empty summary, When recalling it, Then no artificial company binding is created.
    serve(frame(wire('RunStarted')) + frame(wire('RunCompleted', { content: { company_id: null, revision: 0, artifact_count: 0, status: 'not_started' } })));
    const runs: AgentosRun[] = [];
    const events = await collect(createAgentosTransport('session-1', run => runs.push(run))('Recall', new AbortController().signal));
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ type: 'message' });
    expect(runs.at(-1)?.companyId).toBeUndefined();
  });
  it('presents previously saved summary JSON through the same readable view', () => {
    // Given a stored raw summary, When presenting history, Then its content is available as a panel.
    const displayed = presentMessages([{ id: 'saved-summary', role: 'assistant', text: JSON.stringify(summary) }]);
    expectReadable(displayed.map(message => ({ type: 'message', text: message.text, ...(message.panel ? { panel: message.panel } : {}) })));
  });
});
