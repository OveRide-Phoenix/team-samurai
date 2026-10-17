import { describe, expect, it, vi } from 'vitest';
import { finishActivities, applyBackendEvent, emptyWorkspace, workspaceSchema, type Panel } from './model';
import { areaForPanel, conversationArea, messagesForArea, panelsForArea, panelsForAreas, selectedWorkflowAreas, toggleWorkflowArea } from './teamAreas';
import { demoTransport, evidence, offer, pricing, prospects, launchPlan, previewBrief } from './demo';
import { createAgentosTransport, readAgentosRun } from './agentos';

const brief = previewBrief({ idea: 'A clinic receptionist business', customer: 'Clinics', location: 'Pune', budget: '₹50000', goal: 'One pilot' });

describe('focused company areas', () => {
  it('restores old workspaces without dropping their saved actions or panels', () => {
    const old = { ...emptyWorkspace(), pinned: [offer], shortlist: ['maple'], completedTasks: ['saved'], drafts: undefined, selectedArea: undefined };
    const saved = workspaceSchema.parse(JSON.parse(JSON.stringify(old)));
    expect(saved.selectedArea).toBe('overview');
    expect(saved.drafts).toEqual({});
    expect(saved.pinned).toEqual([offer]);
    expect(saved.shortlist).toEqual(['maple']);
    expect(saved.completedTasks).toEqual(['saved']);
  });
  it('keeps the brief separate and uses artifact ownership for research and verification', () => {
    const review: Panel = { id: 'review', kind: 'evidence', claims: [], note: '', title: 'Verification review', provenance: { artifact_type: 'verification' } };
    const workspace = emptyWorkspace();
    const panels = [brief, evidence, review, offer, pricing, launchPlan, prospects];
    expect(panelsForArea(panels, workspace, 'overview')).toEqual([brief]);
    expect(panelsForArea(panels, workspace, 'research')).toEqual([evidence]);
    expect(panelsForArea(panels, workspace, 'market')).toEqual([evidence]);
    expect(panelsForArea(panels, workspace, 'verification')).toEqual([review, launchPlan]);
    expect(panelsForArea(panels, workspace, 'strategy')).toEqual([offer]);
    expect(panelsForArea(panels, workspace, 'resources')).toEqual([pricing]);
    expect(panelsForArea(panels, workspace, 'sales')).toEqual([prospects]);
  });
  it('shows the latest native result while retaining its older lineage in conversation', () => {
    const older: Panel = { id: 'old', kind: 'evidence', title: 'Verification review', note: '', claims: [], provenance: { artifact_type: 'verification', revision: 2 } };
    const newer: Panel = { ...older, id: 'new', provenance: { artifact_type: 'verification', revision: 3 } };
    const workspace = workspaceSchema.parse({ ...emptyWorkspace(), messages: [{ id: 'history', role: 'assistant', text: '', panel: older }] });
    expect(panelsForArea([newer, older], workspace, 'verification')).toEqual([newer]);
    expect(workspace.messages[0].panel).toEqual(older);
  });
  it('keeps authored views with the area that created them and separates conversations', () => {
    const panel: Panel = { id: '00000000-0000-4000-8000-000000000011', kind: 'declarative', title: 'Competition', note: 'Generated view · Working assumptions, not verified business results', blocks: [{ kind: 'text', text: 'Hypothesis' }] };
    const workspace = workspaceSchema.parse({ ...emptyWorkspace(), drafts: { research: 'Check sources', strategy: 'Compare prices' }, messages: [
      { id: 'r', role: 'user', text: 'Competitors', area: 'research' },
      { id: 's', role: 'user', text: 'Pricing', area: 'strategy' },
      { id: 'view', role: 'assistant', text: '', panel, area: 'research' },
    ] });
    expect(areaForPanel(panel, workspace)).toBe('research');
    expect(messagesForArea(workspace, 'research').map(item => item.id)).toEqual(['r', 'view']);
    expect(messagesForArea(workspace, 'strategy').map(item => item.id)).toEqual(['s']);
    expect(workspace.drafts).toEqual({ research: 'Check sources', strategy: 'Compare prices' });
    const result = applyBackendEvent({ ...workspace, backendRun: { runId: 'running', status: 'running', area: 'research' } }, 'running', { type: 'message', text: 'Result' });
    expect(result.messages.at(-1)?.area).toBe('research');
  });
  it('migrates the single workflow choice and preserves an explicitly cleared filter', () => {
    const old = workspaceSchema.parse({ ...emptyWorkspace(), selectedArea: 'research', selectedAreas: undefined });
    expect(selectedWorkflowAreas(old)).toEqual(['research']);
    expect(selectedWorkflowAreas({ ...old, selectedAreas: [] })).toEqual([]);
    expect(workspaceSchema.safeParse({ ...old, selectedAreas: ['overview'] }).success).toBe(false);
    expect(workspaceSchema.safeParse({ ...old, selectedAreas: ['research', 'research'] }).success).toBe(false);
  });
  it('toggles workflows independently and returns to the company conversation when cleared or combined', () => {
    const combined = toggleWorkflowArea(['research'], 'strategy');
    expect(combined).toEqual(['research', 'strategy']);
    expect(conversationArea(combined)).toBe('overview');
    const single = toggleWorkflowArea(combined, 'research');
    expect(single).toEqual(['strategy']);
    expect(conversationArea(single)).toBe('strategy');
    const cleared = toggleWorkflowArea(single, 'strategy');
    expect(cleared).toEqual([]);
    expect(conversationArea(cleared)).toBe('overview');
  });
  it('shows all results without a filter and the union of selected workflow results', () => {
    const panels = [brief, evidence, offer, pricing, launchPlan, prospects];
    const workspace = emptyWorkspace();
    expect(panelsForAreas(panels, workspace, [])).toEqual(panels);
    expect(panelsForAreas(panels, workspace, ['research', 'strategy'])).toEqual([evidence, offer]);
    expect(panelsForAreas(panels, workspace, ['sales'])).toEqual([prospects]);
  });
  it('appends newly selected workflows in click order and returns reselected groups to the end', () => {
    let areas = toggleWorkflowArea([], 'sales');
    areas = toggleWorkflowArea(areas, 'strategy');
    areas = toggleWorkflowArea(areas, 'research');
    expect(areas).toEqual(['sales', 'strategy', 'research']);
    const panels = [brief, evidence, offer, pricing, launchPlan, prospects];
    expect(panelsForAreas(panels, emptyWorkspace(), areas)).toEqual([prospects, offer, evidence]);
    areas = toggleWorkflowArea(areas, 'strategy');
    areas = toggleWorkflowArea(areas, 'strategy');
    expect(areas).toEqual(['sales', 'research', 'strategy']);
    expect(panelsForAreas(panels, emptyWorkspace(), areas)).toEqual([prospects, evidence, offer]);
    const restored = workspaceSchema.parse(JSON.parse(JSON.stringify({ ...emptyWorkspace(), selectedAreas: areas })));
    expect(selectedWorkflowAreas(restored)).toEqual(areas);
  });
  it('can explore sample pricing from a different aspect without a forced handoff', async () => {
    const events = [];
    for await (const event of demoTransport('Change our pricing', new AbortController().signal, 'research')) events.push(event);
    expect(events.some(event => event.type === 'message' && event.panel?.kind === 'pricing')).toBe(true);
    expect(events.some(event => event.type === 'message' && event.handoff)).toBe(false);
  });
  it('labels cancelled preview activity without claiming a backend acknowledgement', () => {
    const history = finishActivities([{ type: 'activity', agent: 'Sales', state: 'working', detail: 'Preparing a sample' }], 'cancelled', 'preview');
    expect(history.at(-1)).toMatchObject({ state: 'stopped', detail: 'Preview stopped.' });
    expect(history.at(-1)?.detail).not.toContain('backend');
  });
  it('validates, deduplicates and recovers a backend team handoff with its original area', async () => {
    const content = 'SAMURAI_HANDOFF=' + JSON.stringify({ area: 'strategy', text: 'Open Strategist to review pricing.', prerequisite: true });
    const event = (kind: string, fields = {}) => ({ event: kind, run_id: 'r', session_id: 's', agent_id: 'samurai', ...fields });
    const wire = [event('RunStarted'), event('ToolCallCompleted', { tool: { result: content } }), event('RunCompleted', { content })].map(item => 'data: ' + JSON.stringify(item) + '\n\n').join('');
    vi.stubGlobal('fetch', vi.fn(async (_url, options) => options?.method === 'GET' ? new Response(JSON.stringify(event('RunCompleted', { status: 'COMPLETED', content, metadata: { team_area: 'research' } }))) : new Response(wire, { headers: { 'content-type': 'text/event-stream' } })));
    try {
      const events = [];
      for await (const item of createAgentosTransport('s')('Pricing', new AbortController().signal, 'research')) events.push(item);
      expect(events).toEqual([{ type: 'message', text: 'Open Strategist to review pricing.', handoff: 'strategy', handoffPrerequisite: true }]);
      const recovered = await readAgentosRun('s', 'r');
      expect(recovered.run.area).toBe('research');
      expect(recovered.events).toEqual(events);
    } finally { vi.unstubAllGlobals(); }
  });
});
