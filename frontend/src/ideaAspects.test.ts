import { describe, expect, it } from 'vitest';
import { applyBackendEvent, beginBackendRun, emptyWorkspace, recordBackendRun, workspaceSchema } from './model';
import { areaForPanel, aspectReadiness, conversationArea, messagesForArea, panelChoiceAreas, panelsForAreas, teamAreas, workflowAreas } from './teamAreas';
import { evidence, launchPlan, pricing, prospects, offer } from './demo';

describe('idea aspect readiness', () => {
  it('keeps all six aspects available when the idea has no results', () => {
    const workspace = emptyWorkspace();
    expect(workflowAreas).toHaveLength(6);
    expect(workflowAreas.map(aspect => aspectReadiness(aspect.id, workspace))).toEqual(Array(6).fill('in-progress'));
  });

  it('marks an aspect ready only when every checkpoint is explicitly ready', () => {
    const aspect = teamAreas.find(item => item.id === 'resources');
    if (!aspect) throw new Error('Budget aspect is missing');
    const workspace = workspaceSchema.parse({ ...emptyWorkspace(), aspectChecks: Object.fromEntries(aspect.checkpoints.map(check => [check.id, { status: 'ready', note: 'Reviewed assumption' }])) });
    expect(aspectReadiness('resources', workspace)).toBe('ready');
    expect(aspectReadiness('sales', workspace)).toBe('in-progress');
  });

  it('keeps a blocker within its own aspect', () => {
    const workspace = workspaceSchema.parse({ ...emptyWorkspace(), aspectChecks: { 'technical-feasibility': { status: 'blocked', note: 'Need access to the API' } } });
    expect(aspectReadiness('strategy', workspace)).toBe('blocked');
    expect(aspectReadiness('sales', workspace)).toBe('in-progress');
  });

  it('restores legacy workspaces and saves checkpoint notes without dropping history', () => {
    const workspace = workspaceSchema.parse({ ...emptyWorkspace(), aspectChecks: undefined, drafts: { strategy: 'Saved technical question' } });
    expect(workspace.aspectChecks).toEqual({});
    expect(workspace.drafts.strategy).toBe('Saved technical question');
    const saved = workspaceSchema.parse(JSON.parse(JSON.stringify({ ...workspace, aspectChecks: { 'build-budget': { status: 'in-progress', note: '₹50,000 ceiling' } }, selectedAreas: ['resources', 'market'] })));
    expect(saved.aspectChecks['build-budget']?.note).toBe('₹50,000 ceiling');
    expect(saved.selectedAreas).toEqual(['resources', 'market']);
  });

  it('uses the existing backend scopes for the two new UX aspects', () => {
    expect(conversationArea(['market'])).toBe('research');
    expect(conversationArea(['resources'])).toBe('strategy');
  });

  it('keeps shared research visible only once when related aspects are selected', () => {
    expect(panelsForAreas([evidence], emptyWorkspace(), ['research', 'market'])).toEqual([evidence]);
  });

  it('opens panel requests in the same aspect that owns their resulting panels', () => {
    for (const [title, panel] of [['Pricing exploration', pricing], ['Launch plan', launchPlan], ['Customer pipeline', prospects], ['Offer & positioning', offer], ['Evidence review', { ...evidence, title: 'Verification review' }]] as const) {
      expect(panelChoiceAreas[title]).toBe(areaForPanel(panel));
    }
  });

  it.each([['research', 'market'], ['strategy', 'resources']] as const)('keeps %s and %s history and drafts distinct across reload and recovery', (first, second) => {
    let workspace = emptyWorkspace();
    for (const aspect of [first, second]) {
      const scope = conversationArea([aspect]);
      workspace = { ...workspace, drafts: { ...workspace.drafts, [aspect]: `Draft for ${aspect}` }, messages: [...workspace.messages, { id: aspect, role: 'user', text: `Question for ${aspect}`, area: scope, aspect }] };
      workspace = beginBackendRun(workspace, crypto.randomUUID(), scope, aspect);
      workspace = recordBackendRun(workspace, { status: 'completed', runId: `run-${aspect}`, area: scope });
      workspace = workspaceSchema.parse(JSON.parse(JSON.stringify(workspace)));
      workspace = applyBackendEvent(workspace, `run-${aspect}`, { type: 'message', text: `Reply for ${aspect}` });
      expect(workspace.backendRun?.area).toBe(scope);
    }
    for (const aspect of [first, second]) {
      expect(workspace.drafts[aspect]).toBe(`Draft for ${aspect}`);
      expect(messagesForArea(workspace, aspect).map(message => message.text)).toEqual([`Question for ${aspect}`, `Reply for ${aspect}`]);
    }
    expect(messagesForArea(workspace, 'overview')).toHaveLength(4);
  });
});
