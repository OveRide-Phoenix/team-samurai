import type { Message, Panel, TeamArea, WorkflowArea, Workspace } from './model';
import { workflowAreaSchema, type CheckpointStatus, type IdeaArea } from './aspectState';
import { aspectCatalog } from './ideaAspectCatalog';

export const workflowAreas = workflowAreaSchema.options.map(id => ({ id, ...aspectCatalog[id] }));
export const teamAreas = [{ id: 'overview' as const, name: 'Idea overview', shortName: 'Idea', goal: 'Explore any aspect of your software idea.', prompt: 'Help me choose the next useful step to validate this software idea.', checkpoints: [], related: [], agent: undefined }, ...workflowAreas];
export const panelChoiceAreas: Readonly<Record<string, IdeaArea>> = {
  'Customer pipeline': 'sales', 'Offer & positioning': 'strategy', 'Pricing exploration': 'resources',
  'Evidence review': 'verification', 'Launch plan': 'verification',
};
export function scopeForAspect(area: IdeaArea): TeamArea {
  return area === 'overview' ? 'overview' : aspectCatalog[area].scope;
}
export function aspectReadiness(area: WorkflowArea, workspace: Workspace): CheckpointStatus {
  const checks = aspectCatalog[area].checkpoints.map(check => workspace.aspectChecks[check.id]?.status);
  if (checks.includes('blocked')) return 'blocked';
  return checks.every(status => status === 'ready') ? 'ready' : 'in-progress';
}
export function selectedWorkflowAreas(workspace: Workspace): WorkflowArea[] {
  return workspace.selectedAreas ?? (workspace.selectedArea === 'overview' ? [] : [workspace.selectedArea]);
}
export function toggleWorkflowArea(areas: readonly WorkflowArea[], area: WorkflowArea): WorkflowArea[] {
  return areas.includes(area) ? areas.filter(id => id !== area) : [...areas, area];
}
export function conversationArea(areas: readonly WorkflowArea[]): TeamArea {
  return areas.length === 1 ? scopeForAspect(areas[0]) : 'overview';
}
export function areaForPanel(panel: Panel, workspace?: Workspace): IdeaArea {
  const kind = panel.provenance?.artifact_type;
  if (kind === 'intake' || panel.title === 'Company brief' || panel.title === 'Company context') return 'overview';
  if (kind === 'verification' || /verification/i.test(panel.title)) return 'verification';
  if (kind === 'sales_draft' || panel.kind === 'prospects') return 'sales';
  if (panel.kind === 'pricing' || panel.kind === 'scenario') return 'resources';
  if (kind === 'product_plan' || kind === 'builder_draft' || kind === 'analysis' || panel.kind === 'launch-plan') return 'verification';
  if (kind === 'marketing_draft') return 'sales';
  if (kind === 'strategy' || panel.kind === 'offer') return 'strategy';
  if (kind === 'research' || panel.kind === 'evidence') return 'research';
  const origin = workspace?.messages.slice().reverse().find(message => message.panel?.id === panel.id);
  return origin?.aspect ?? origin?.area ?? 'overview';
}
export function areaForMessage(message: Message, workspace?: Workspace): TeamArea {
  return message.area || (message.panel ? scopeForAspect(areaForPanel(message.panel, workspace)) : 'overview');
}
export function messagesForArea(workspace: Workspace, area: IdeaArea): Message[] {
  return area === 'overview' ? workspace.messages : workspace.messages.filter(message => (message.aspect ?? areaForMessage(message, workspace)) === area);
}
export function panelsForArea(panels: Panel[], workspace: Workspace, area: IdeaArea): Panel[] {
  return panelsForAreas(panels, workspace, [area]);
}
export function panelsForAreas(panels: Panel[], workspace: Workspace, areas: readonly IdeaArea[]): Panel[] {
  const belongs = (panel: Panel, area: IdeaArea) => areaForPanel(panel, workspace) === area || (area === 'market' && areaForPanel(panel, workspace) === 'research');
  const selected = panels.filter(panel => !areas.length || areas.some(area => belongs(panel, area)));
  const latest = new Map<string, Panel>();
  const key = (panel: Panel) => panel.provenance?.artifact_type ? String(panel.provenance.artifact_type) + ':' + panel.kind : panel.id;
  for (const panel of selected) {
    const previous = latest.get(key(panel));
    if (!previous || Number(panel.provenance?.revision || 0) >= Number(previous.provenance?.revision || 0)) latest.set(key(panel), panel);
  }
  const current = selected.filter(panel => latest.get(key(panel)) === panel);
  return areas.length ? [...new Set(areas.flatMap(area => current.filter(panel => belongs(panel, area))))] : current;
}
