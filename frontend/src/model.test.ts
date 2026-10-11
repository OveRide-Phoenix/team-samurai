import { describe, expect, it } from 'vitest';
import { toggleSavedSelection, applyBackendEvent, recordBackendRun, initialCompanyPrompt, companyBriefSchema, chooseWorkflow, orderedPanels, movePanel, latestPanels, emptyWorkspace, eventSchema, panelSchema, portfolioSchema, restorePortfolio, workspaceSchema } from './model';
import { onboardingPreview, demoTransport, initialWorkspace, offer, pricing, prospects, evidence, launchPlan } from './demo';

describe('backend-facing UI contract', () => {
  it('starts empty and migrates the old preview without losing company data', () => {
    expect(restorePortfolio(null, null).companies).toEqual([]);
    const migrated = restorePortfolio(null, JSON.stringify(initialWorkspace));
    expect(migrated.activeId).toBeNull();
    expect(migrated.companies[0].workspace).toEqual(initialWorkspace);
    expect(emptyWorkspace().messages).toEqual([]);
    expect(emptyWorkspace().pinned).toEqual([]);
  });
  it('rejects dangling company selection and keeps independent company state', () => {
    const portfolio = { version: 2, mode: 'dark', activeId: 'a', companies: [
      { id: 'a', name: 'One', workspace: initialWorkspace },
      { id: 'b', name: 'Two', workspace: emptyWorkspace() },
    ] };
    expect(portfolioSchema.safeParse(portfolio).success).toBe(true);
    expect(portfolioSchema.safeParse({ ...portfolio, activeId: 'missing' }).success).toBe(false);
    const restored = restorePortfolio(JSON.stringify(portfolio), null);
    expect(restored.companies[1].workspace.shortlist).toEqual([]);
    expect(restored.mode).toBe('dark');
  });
  it('accepts our fixtures and persisted workspace', () => {
    [offer, pricing, prospects, evidence, launchPlan].forEach(panel => expect(panelSchema.safeParse(panel).success).toBe(true));
    expect(workspaceSchema.safeParse(initialWorkspace).success).toBe(true);
  });
  it('rejects executable or malformed panel types and invalid activity states', () => {
    expect(panelSchema.safeParse({ kind: 'script', code: 'alert(1)' }).success).toBe(false);
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
    expect(workspaceSchema.parse(legacy).completedTasks).toEqual([]);
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
    expect(workspaceSchema.parse(legacy).panelOrder).toEqual([]);
    expect(orderedPanels([offer, pricing, prospects], [pricing.id, 'missing', pricing.id]).map(p => p.id)).toEqual([pricing.id, offer.id, prospects.id]);
  });
  it('moves in both directions, ignores unknown drag payloads and persists per company', () => {
    const panels = [offer, pricing, prospects];
    const order = movePanel(panels, offer.id, prospects.id);
    expect(order).toEqual([pricing.id, prospects.id, offer.id]);
    expect(movePanel(panels, prospects.id, offer.id)).toEqual([prospects.id, offer.id, pricing.id]);
    expect(movePanel(panels, 'unknown', pricing.id)).toEqual(panels.map(p => p.id));
    const saved = JSON.stringify({version: 2, mode: 'light', activeId: 'a', companies: [{id: 'a', name: 'A', workspace: {...initialWorkspace, panelOrder: order}}, {id: 'b', name: 'B', workspace: emptyWorkspace()}]});
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
    const saved = { version: 2, mode: 'light', activeId: 'brief', companies: [{ id: 'brief', name: 'Cycle Co', workspace: { ...emptyWorkspace(), brief } }] };
    expect(restorePortfolio(JSON.stringify(saved), null).companies[0].workspace.brief).toEqual(brief);
    expect(workspaceSchema.parse(initialWorkspace).brief).toBeUndefined();
  });
  it('uses the supplied brief without inventing dental fixtures and yields valid events', async () => {
    const events = [];
    for await (const raw of onboardingPreview(brief, new AbortController().signal)) events.push(eventSchema.parse(raw));
    expect(events.filter(e => e.type === 'activity' && e.state === 'working')).toHaveLength(4);
    const result = events.find(e => e.type === 'message');
    expect(JSON.stringify(result)).toContain('Local cyclists');
    expect(JSON.stringify(result)).toContain('Pune');
    expect(JSON.stringify(result)).not.toContain('Dental');
    expect(result?.type === 'message' && result.panel?.kind).toBe('launch-plan');
  });
  it('cancels the initial preview before producing a plan', async () => {
    const controller = new AbortController();
    const stream = onboardingPreview(brief, controller.signal)[Symbol.asyncIterator]();
    expect((await stream.next()).value?.type).toBe('activity');
    const waiting = stream.next();
    controller.abort();
    await expect(waiting).rejects.toBeDefined();
  });
});


describe('live workspace state', () => {
  it('keeps old saved companies explicitly preview and retains live backend mapping', () => {
    const { executionMode: _, ...legacy } = initialWorkspace;
    expect(workspaceSchema.parse(legacy).executionMode).toBe('preview');
    const live = { ...emptyWorkspace(), executionMode: 'live', backendRun: { runId: 'r1', status: 'completed', companyId: '00000000-0000-4000-8000-000000000001', revision: 2 } };
    const restored = restorePortfolio(JSON.stringify({ version: 2, mode: 'light', activeId: 'one', companies: [{ id: 'one', name: 'One', workspace: live }, { id: 'two', name: 'Demo', workspace: legacy }] }), null);
    expect(restored.companies[0].workspace.executionMode).toBe('live');
    expect(restored.companies[0].workspace.backendRun).toEqual(live.backendRun);
    expect(restored.companies[1].workspace.executionMode).toBe('preview');
  });
  it('rejects foreign recovery binding before applying output and preserves known identity across new runs', () => {
    const companyId = '00000000-0000-4000-8000-000000000001';
    const state = recordBackendRun(emptyWorkspace(), { runId: 'r1', status: 'completed', companyId, revision: 1 });
    const next = recordBackendRun(state, { runId: 'r2', status: 'running' });
    expect(next.backendRun).toEqual({ runId: 'r2', status: 'running', companyId, revision: 1 });
    expect(() => recordBackendRun(next, { runId: 'r2', status: 'completed', companyId: '00000000-0000-4000-8000-000000000009' })).toThrow('another company');
  });
  it('deduplicates recovered messages and updates an existing pinned artifact', () => {
    const state = { ...emptyWorkspace(), pinned: [offer] };
    const event = { type: 'message' as const, text: 'Result', panel: { ...offer, price: 'Revised assumption' } };
    const first = applyBackendEvent(state, 'r1', event);
    expect(applyBackendEvent(first, 'r1', event)).toBe(first);
    expect(first.messages).toHaveLength(1);
    expect(first.messages[0].backendRunId).toBe('r1');
    expect(first.pinned[0]).toMatchObject({ price: 'Revised assumption' });
    expect(applyBackendEvent(first, 'r2', event).messages).toHaveLength(2);
    const revised = applyBackendEvent(first, 'r1', { ...event, panel: { ...event.panel, note: 'New revision' } });
    expect(revised.messages).toHaveLength(2);
    expect(revised.pinned[0].note).toBe('New revision');
  });
  it('sends all saved intake fields as founder input to the backend', () => {
    const prompt = initialCompanyPrompt({ idea: 'Cycle repair business', customer: 'Local cyclists', location: 'Pune', budget: '1000 INR', goal: 'First paid pilot' });
    const brief = JSON.parse(prompt.slice(prompt.indexOf('\n') + 1));
    expect(brief).toEqual({ idea: 'Cycle repair business', target_customer: 'Local cyclists', geography: 'Pune', budget: '1000 INR', goal: 'First paid pilot' });
  });
});


describe('saved selection limits', () => {
  it('keeps recent reviews and shortlists reloadable after reaching their schema limits', () => {
    let state = emptyWorkspace();
    for (let index = 0; index < 110; index += 1) state = { ...state, shortlist: toggleSavedSelection(state.shortlist, `customer-${index}`, 100), approvedOffers: toggleSavedSelection(state.approvedOffers, `offer-${index}`, 20) };
    const saved = JSON.stringify({ version: 2, mode: 'light', activeId: 'one', companies: [{ id: 'one', name: 'One', workspace: state }] });
    const restored = restorePortfolio(saved, null);
    expect(restored.companies).toHaveLength(1);
    expect(restored.companies[0].workspace.approvedOffers).toEqual(Array.from({ length: 20 }, (_, index) => `offer-${index + 90}`));
    expect(restored.companies[0].workspace.shortlist).toHaveLength(100);
    expect(toggleSavedSelection(['one', 'two'], 'one', 20)).toEqual(['two']);
  });
});
