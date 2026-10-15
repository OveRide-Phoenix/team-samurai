import { describe, expect, it } from 'vitest';
import { beginBackendRun, continueCompanyView, finishActivities, hasActiveBackendRun, isCancellableBackendRun, nextJourneyApproval, toggleSavedSelection, applyBackendEvent, recordBackendRun, initialCompanyPrompt, companyBriefSchema, chooseWorkflow, orderedPanels, movePanel, latestPanels, emptyCompanyView, eventSchema, panelSchema, portfolioSchema, restorePortfolio, companyViewSchema } from './model';
import { onboardingPreview, demoTransport, initialWorkspace, offer, pricing, prospects, evidence, launchPlan } from './demo';

describe('backend-facing UI contract', () => {
  it('starts empty and migrates the old preview without losing company data', () => {
    expect(restorePortfolio(null, null).companies).toEqual([]);
    const migrated = restorePortfolio(null, JSON.stringify(initialWorkspace));
    expect(migrated.activeId).toBeNull();
    expect(migrated.companies[0].workspace).toEqual(initialWorkspace);
    expect(emptyCompanyView().messages).toEqual([]);
    expect(emptyCompanyView().pinned).toEqual([]);
  });
  it('rejects dangling company selection and keeps independent company state', () => {
    const portfolio = { version: 2, mode: 'dark', activeId: 'a', companies: [
      { id: 'a', name: 'One', workspace: initialWorkspace },
      { id: 'b', name: 'Two', workspace: emptyCompanyView() },
    ] };
    expect(portfolioSchema.safeParse(portfolio).success).toBe(true);
    expect(portfolioSchema.safeParse({ ...portfolio, activeId: 'missing' }).success).toBe(false);
    const restored = restorePortfolio(JSON.stringify(portfolio), null);
    expect(restored.companies[1].workspace.shortlist).toEqual([]);
    expect(restored.mode).toBe('dark');
  });
  it('accepts our fixtures and persisted workspace', () => {
    [offer, pricing, prospects, evidence, launchPlan].forEach(panel => expect(panelSchema.safeParse(panel).success).toBe(true));
    expect(companyViewSchema.safeParse(initialWorkspace).success).toBe(true);
  });
  it('rejects executable or malformed panel types and invalid activity states', () => {
    expect(panelSchema.safeParse({ kind: 'script', code: 'alert(1)' }).success).toBe(false);
    expect(panelSchema.safeParse({ ...offer, component: 'FounderTruth' }).success).toBe(false);
    expect(panelSchema.safeParse({ ...offer, founder_context: { next_decision: null, evidence_gaps: [], framework: { id: 'founder_truth', version: '1.0.0', attribution: 'Adapted', source_repository: 'example/repo', source_revision: '0'.repeat(40), source_url: 'javascript:alert(1)' } } }).success).toBe(false);
    expect(panelSchema.safeParse({ ...prospects, rows: [{ name: 'Missing fields' }] }).success).toBe(false);
    expect(eventSchema.safeParse({ type: 'activity', agent: 'Researcher', state: 'unknown', detail: '' }).success).toBe(false);
  });
  it('routes business requests and gives an honest fallback', () => {
    expect(chooseWorkflow('Who should we sell to first?')).toBe('prospects');
    expect(chooseWorkflow('Is this pricing viable?')).toBe('pricing');
    expect(chooseWorkflow('Review our offer')).toBe('offer');
    expect(chooseWorkflow('Validate assumptions')).toBe('evidence');
    expect(chooseWorkflow('Create a launch plan')).toBe('launch-plan');
    expect(chooseWorkflow('What is the weather?')).toBe('help');
  });
  it('requires sources for supported claims and rejects unsafe links', () => {
    const claim = { id: 'c', claim: 'Example', status: 'supported', detail: 'Example', sources: [] };
    expect(panelSchema.safeParse({ ...evidence, claims: [claim] }).success).toBe(false);
    expect(panelSchema.safeParse({ ...evidence, claims: [{ ...claim, sources: [{ title: 'Source', url: 'javascript:alert(1)' }] }] }).success).toBe(false);
    expect(panelSchema.safeParse({ ...evidence, claims: [{ ...claim, sources: [{ title: 'Source', url: 'https://example.org/evidence' }] }] }).success).toBe(true);
  });
  it('restores old workspaces and rejects ambiguous launch task IDs', () => {
    const { completedTasks, ...legacy } = initialWorkspace;
    expect(companyViewSchema.parse(legacy).completedTasks).toEqual([]);
    const task = { id: 'same', title: 'Interview', owner: 'Founder', timing: 'Today', detail: 'Learn' };
    expect(panelSchema.safeParse({ ...launchPlan, tasks: [task, task] }).success).toBe(false);
  });
  it('uses the newest result for an existing pinned panel without duplicating it', () => {
    const updated = { ...offer, price: 'Updated hypothesis' };
    const workspace = { ...initialWorkspace, messages: [...initialWorkspace.messages, { id: 'updated', role: 'assistant' as const, text: 'Updated', panel: updated }] };
    expect(latestPanels(workspace)).toEqual([updated]);
    expect(initialWorkspace.pinned).toEqual([offer]);
  });
  it('stops a demo run without emitting a completed panel', async () => {
    const controller = new AbortController();
    const stream = demoTransport('Find customers', controller.signal)[Symbol.asyncIterator]();
    expect((await stream.next()).value?.type).toBe('activity');
    controller.abort();
    await expect(stream.next()).rejects.toMatchObject({ name: 'AbortError' });
  });
});

describe('dashboard panel order', () => {
  it('migrates saved workspaces and appends newly generated panels', () => {
    const { panelOrder: _, ...legacy } = initialWorkspace;
    expect(companyViewSchema.parse(legacy).panelOrder).toEqual([]);
    expect(orderedPanels([offer, pricing, prospects], [pricing.id, 'missing', pricing.id]).map(p => p.id)).toEqual([pricing.id, offer.id, prospects.id]);
  });
  it('moves in both directions, ignores unknown drag payloads and persists per company', () => {
    const panels = [offer, pricing, prospects];
    const order = movePanel(panels, offer.id, prospects.id);
    expect(order).toEqual([pricing.id, prospects.id, offer.id]);
    expect(movePanel(panels, prospects.id, offer.id)).toEqual([prospects.id, offer.id, pricing.id]);
    expect(movePanel(panels, 'unknown', pricing.id)).toEqual(panels.map(p => p.id));
    const saved = JSON.stringify({version: 2, mode: 'light', activeId: 'a', companies: [{id: 'a', name: 'A', workspace: {...initialWorkspace, panelOrder: order}}, {id: 'b', name: 'B', workspace: emptyCompanyView()}]});
    const restored = restorePortfolio(saved, null);
    expect(restored.companies[0].workspace.panelOrder).toEqual(order);
    expect(restored.companies[1].workspace.panelOrder).toEqual([]);
  });
});

describe('company prerequisites', () => {
  const brief = { idea: 'A repair service for bicycles', customer: 'Local cyclists', location: 'Pune', budget: '0', goal: 'One paying pilot' };
  it('requires a complete brief and retains it through portfolio reload', () => {
    expect(companyBriefSchema.safeParse(brief).success).toBe(true);
    expect(companyBriefSchema.safeParse({ ...brief, customer: '   ' }).success).toBe(false);
    expect(companyBriefSchema.safeParse({ ...brief, idea: 'a'.repeat(1501) }).success).toBe(false);
    const saved = { version: 2, mode: 'light', activeId: 'brief', companies: [{ id: 'brief', name: 'Cycle Co', workspace: { ...emptyCompanyView(), brief } }] };
    expect(restorePortfolio(JSON.stringify(saved), null).companies[0].workspace.brief).toEqual(brief);
    expect(companyViewSchema.parse(initialWorkspace).brief).toBeUndefined();
  });
  it('uses the supplied brief without inventing dental fixtures and yields valid events', async () => {
    const events = [];
    for await (const raw of onboardingPreview(brief, new AbortController().signal)) events.push(eventSchema.parse(raw));
    expect(events).toHaveLength(1);
    expect(events.filter(e => e.type === 'activity')).toHaveLength(0);
    const result = events.find(e => e.type === 'message');
    expect(JSON.stringify(result)).toContain('Local cyclists');
    expect(JSON.stringify(result)).toContain('Pune');
    expect(JSON.stringify(result)).not.toContain('Dental');
    expect(result?.type === 'message' && result.panel?.title).toBe('Company brief');
  });
  it('does not produce a brief when the initial preview was cancelled', async () => {
    const controller = new AbortController();
    const stream = onboardingPreview(brief, controller.signal)[Symbol.asyncIterator]();
    controller.abort();
    expect((await stream.next()).done).toBe(true);
  });
});


describe('live workspace state', () => {
  it('persists a logical submission before the backend assigns a run id', () => {
    const submissionId = '00000000-0000-4000-8000-000000000099';
    const pending = beginBackendRun(emptyCompanyView(), submissionId);
    expect(pending.backendRun).toEqual({ submissionId, status: 'submitting' });
    expect(companyViewSchema.parse(pending).backendRun).toEqual(pending.backendRun);
    expect(hasActiveBackendRun(pending.backendRun)).toBe(true);

    const accepted = recordBackendRun(pending, { submissionId, runId: 'run-1', status: 'queued' });
    expect(accepted.backendRun).toEqual({ submissionId, runId: 'run-1', status: 'queued' });
    expect(hasActiveBackendRun(accepted.backendRun)).toBe(true);
    expect(hasActiveBackendRun({ ...accepted.backendRun, status: 'completed' })).toBe(false);
  });
  it('rejects a backend receipt for a different logical submission', () => {
    const pending = beginBackendRun(emptyCompanyView(), '00000000-0000-4000-8000-000000000099');
    expect(() => recordBackendRun(pending, {
      submissionId: '00000000-0000-4000-8000-000000000098', runId: 'run-2', status: 'queued',
    })).toThrow('another submission');
  });

  it('allows cancellation for every active durable state only after a run id exists', () => {
    expect(isCancellableBackendRun({ submissionId: '00000000-0000-4000-8000-000000000099', status: 'submitting' })).toBe(false);
    for (const status of ['queued', 'running', 'recovering', 'paused'] as const) expect(isCancellableBackendRun({ runId: 'run-1', status })).toBe(true);
    for (const status of ['completed', 'cancelled', 'failed'] as const) expect(isCancellableBackendRun({ runId: 'run-1', status })).toBe(false);
  });
  it('keeps old saved companies explicitly preview and retains live backend mapping', () => {
    const { executionMode: _, ...legacy } = initialWorkspace;
    expect(companyViewSchema.parse(legacy).executionMode).toBe('preview');
    const live = { ...emptyCompanyView(), executionMode: 'live', backendRun: { runId: 'r1', status: 'completed', companyId: '00000000-0000-4000-8000-000000000001', revision: 2 } };
    const restored = restorePortfolio(JSON.stringify({ version: 2, mode: 'light', activeId: 'one', companies: [{ id: 'one', name: 'One', workspace: live }, { id: 'two', name: 'Demo', workspace: legacy }] }), null);
    expect(restored.companies[0].workspace.executionMode).toBe('live');
    expect(restored.companies[0].workspace.backendRun).toEqual(live.backendRun);
    expect(restored.companies[1].workspace.executionMode).toBe('preview');
  });
  it('continues a hydrated editor company at the returned revision', () => {
    const companyId = '00000000-0000-4000-8000-000000000001';
    const intake = { ...evidence, provenance: { artifact_type: 'intake', acceptance_status: 'accepted', status: 'complete' } };
    const hydrated = continueCompanyView({ ...emptyCompanyView(), messages: [{ id: 'strategy', role: 'assistant', text: 'Hydrated strategy', panel: intake }] }, companyId, 7);
    expect(hydrated.executionMode).toBe('live');
    expect(hydrated.companyId).toBe(companyId);
    expect(hydrated.currentRevision).toBe(7);
    expect(hydrated.backendRun).toBeUndefined();
    expect(hydrated.messages).toHaveLength(1);
    expect(nextJourneyApproval(hydrated)).toEqual({ stage: 'research', expectedRevision: 7, companyId });
  });
  it('rejects foreign recovery binding before applying output and preserves known identity across new runs', () => {
    const companyId = '00000000-0000-4000-8000-000000000001';
    const state = recordBackendRun(emptyCompanyView(), { runId: 'r1', status: 'completed', companyId, revision: 1 });
    expect(beginBackendRun(state, '00000000-0000-4000-8000-000000000099').backendRun).toEqual({ submissionId: '00000000-0000-4000-8000-000000000099', status: 'submitting', companyId, revision: 1 });
    const next = recordBackendRun(state, { runId: 'r2', status: 'running' });
    expect(next.backendRun).toEqual({ runId: 'r2', status: 'running', companyId, revision: 1 });
    expect(() => recordBackendRun(next, { runId: 'r2', status: 'completed', companyId: '00000000-0000-4000-8000-000000000009' })).toThrow('another company');
  });
  it('deduplicates recovered messages and updates an existing pinned artifact', () => {
    const state = { ...emptyCompanyView(), pinned: [offer] };
    const event = { type: 'message' as const, text: 'Result', panel: { ...offer, price: 'Revised assumption' } };
    const first = applyBackendEvent(state, 'r1', event);
    expect(applyBackendEvent(first, 'r1', event)).toBe(first);
    expect(first.messages).toHaveLength(1);
    expect(first.messages[0].backendRunId).toBe('r1');
    expect(first.pinned[0]).toMatchObject({ price: 'Revised assumption' });
    expect(applyBackendEvent(first, 'r2', event).messages).toHaveLength(2);
    if (event.panel.kind !== 'offer') throw new Error('Expected offer fixture');
    const revised = applyBackendEvent(first, 'r1', { ...event, panel: { ...event.panel, note: 'New revision' } });
    expect(revised.messages).toHaveLength(2);
    expect(revised.pinned[0].note).toBe('New revision');
  });
  it('sends all saved intake fields as founder input to the backend', () => {
    const prompt = initialCompanyPrompt({ idea: 'Cycle repair business', customer: 'Local cyclists', location: 'Pune', budget: '1000 INR', goal: 'First paid pilot' });
    const brief = JSON.parse(prompt.slice(prompt.indexOf('\n') + 1));
    expect(brief).toEqual({ idea: 'Cycle repair business', target_customer: 'Local cyclists', geography: 'Pune', budget: '1000 INR', goal: 'First paid pilot' });
  });
  it('offers only the next explicitly accepted journey stage at the current revision', () => {
    const companyId = '00000000-0000-4000-8000-000000000001';
    const panel = { ...evidence, provenance: { artifact_type: 'intake', acceptance_status: 'accepted', status: 'complete' } };
    const intake = { ...emptyCompanyView(), backendRun: { runId: 'r1', status: 'completed' as const, companyId, revision: 3 }, messages: [{ id: 'm1', role: 'assistant' as const, text: '', panel }] };
    expect(nextJourneyApproval(intake)).toEqual({ stage: 'research', expectedRevision: 3, companyId });
    const research = { ...intake, messages: [{ ...intake.messages[0], panel: { ...panel, provenance: { artifact_type: 'research', acceptance_status: 'accepted', status: 'needs_rework' } } }] };
    expect(nextJourneyApproval(research)).toEqual({ stage: 'research', expectedRevision: 3, companyId });
    const completedResearch = { ...research, messages: [{ ...research.messages[0], panel: { ...panel, provenance: { artifact_type: 'research', acceptance_status: 'accepted', status: 'complete' } } }] };
    expect(nextJourneyApproval(completedResearch)).toEqual({ stage: 'strategy', expectedRevision: 3, companyId });
    expect(nextJourneyApproval({ ...intake, backendRun: { ...intake.backendRun, status: 'running' } })).toBeUndefined();
  });
});


describe('saved selection limits', () => {
  it('keeps recent reviews and shortlists reloadable after reaching their schema limits', () => {
    let state = emptyCompanyView();
    for (let index = 0; index < 110; index += 1) state = { ...state, shortlist: toggleSavedSelection(state.shortlist, `customer-${index}`, 100), approvedOffers: toggleSavedSelection(state.approvedOffers, `offer-${index}`, 20) };
    const saved = JSON.stringify({ version: 2, mode: 'light', activeId: 'one', companies: [{ id: 'one', name: 'One', workspace: state }] });
    const restored = restorePortfolio(saved, null);
    expect(restored.companies).toHaveLength(1);
    expect(restored.companies[0].workspace.approvedOffers).toEqual(Array.from({ length: 20 }, (_, index) => `offer-${index + 90}`));
    expect(restored.companies[0].workspace.shortlist).toHaveLength(100);
    expect(toggleSavedSelection(['one', 'two'], 'one', 20)).toEqual(['two']);
  });
});


it('preserves legacy briefs and includes explicitly supplied skills in the live prompt', () => {
  const brief = { idea: 'Cycle repair business', customer: 'Local cyclists', location: 'Pune', budget: '1000 INR', goal: 'First paid pilot' };
  expect(companyBriefSchema.parse(brief).founderSkills).toBeUndefined();
  const prompt = initialCompanyPrompt({ ...brief, founderSkills: 'No technical skills yet; delivery help needed' });
  expect(prompt).toContain('"founder_skills":"No technical skills yet; delivery help needed"');
  expect(companyViewSchema.parse({ ...emptyCompanyView(), activityLog: undefined }).activityLog).toEqual([]);
});

describe('terminal team activity', () => {
  it('settles only unfinished roles after backend cancellation and preserves completed history', () => {
    const history = eventSchema.array().parse([
      { type: 'activity', agent: 'Researcher', state: 'working', detail: 'Research started' },
      { type: 'activity', agent: 'Researcher', state: 'done', detail: 'Research completed' },
      { type: 'activity', agent: 'Verifier', state: 'working', detail: 'Verify evidence started' },
    ]).filter(event => event.type === 'activity');
    const cancelled = finishActivities(history, 'cancelled');
    expect(cancelled.slice(0, 3)).toEqual(history);
    expect(cancelled.slice(3)).toMatchObject([{ agent: 'Verifier', state: 'stopped' }]);
    expect(finishActivities(cancelled, 'cancelled')).toEqual(cancelled);
    expect(finishActivities(history, 'running')).toEqual(history);
    expect(finishActivities(history, 'completed').at(-1)).toMatchObject({ agent: 'Verifier', state: 'waiting' });
  });
});
