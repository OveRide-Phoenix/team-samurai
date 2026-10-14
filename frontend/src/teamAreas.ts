import type { Agent, Message, Panel, TeamArea, WorkflowArea, Workspace } from './model';

export const teamAreas: { id: TeamArea; name: string; agent?: Agent; goal: string; prompt: string }[] = [
  { id: 'overview', name: 'Overview', goal: 'Your brief and the next founder decision.', prompt: 'Help me choose the next step for our company.' },
  { id: 'research', name: 'Researcher', agent: 'Researcher', goal: 'Understand customers, competitors and demand.', prompt: 'Research our market using stage=research. Stop before strategy.' },
  { id: 'strategy', name: 'Strategist', agent: 'Strategist', goal: 'Shape the offer, pricing and delivery.', prompt: 'Shape our offer using stage=strategy. Stop before the delivery plan.' },
  { id: 'verification', name: 'Verifier', agent: 'Verifier', goal: 'Check support, gaps and conflicting claims.', prompt: 'Read our existing company evidence and verification findings. Do not rerun research or strategy.' },
  { id: 'sales', name: 'Sales', agent: 'Sales', goal: 'Qualify prospects and prepare conversations.', prompt: 'Read our company context and help qualify first customers. Keep outreach as drafts.' },
];
export const workflowAreas = teamAreas.filter((item): item is typeof item & { id: WorkflowArea } => item.id !== 'overview');
export function selectedWorkflowAreas(workspace: Workspace): WorkflowArea[] {
  return workspace.selectedAreas ?? (workspace.selectedArea === 'overview' ? [] : [workspace.selectedArea]);
}
export function toggleWorkflowArea(areas: readonly WorkflowArea[], area: WorkflowArea): WorkflowArea[] {
  return areas.includes(area) ? areas.filter(id => id !== area) : [...areas, area];
}
export function conversationArea(areas: readonly WorkflowArea[]): TeamArea {
  return areas.length === 1 ? areas[0] : 'overview';
}
export function areaForPanel(panel: Panel, workspace?: Workspace): TeamArea {
  const kind = panel.provenance?.artifact_type;
  if (kind === 'intake' || panel.title === 'Company brief' || panel.title === 'Company context') return 'overview';
  if (kind === 'verification' || /verification/i.test(panel.title)) return 'verification';
  if (kind === 'sales_draft' || panel.kind === 'prospects') return 'sales';
  if (['strategy', 'product_plan'].includes(String(kind)) || ['offer', 'pricing', 'launch-plan'].includes(panel.kind)) return 'strategy';
  if (['builder_draft', 'marketing_draft', 'analysis'].includes(String(kind))) return 'overview';
  if (kind === 'research' || panel.kind === 'evidence') return 'research';
  return workspace?.messages.slice().reverse().find(message => message.panel?.id === panel.id)?.area || 'overview';
}
export function areaForMessage(message: Message, workspace?: Workspace): TeamArea {
  return message.area || (message.panel ? areaForPanel(message.panel, workspace) : 'overview');
}
export function messagesForArea(workspace: Workspace, area: TeamArea): Message[] {
  return area === 'overview' ? workspace.messages : workspace.messages.filter(message => areaForMessage(message, workspace) === area);
}
export function panelsForArea(panels: Panel[], workspace: Workspace, area: TeamArea): Panel[] {
  return panelsForAreas(panels, workspace, [area]);
}
export function panelsForAreas(panels: Panel[], workspace: Workspace, areas: readonly TeamArea[]): Panel[] {
  const selected = panels.filter(panel => !areas.length || areas.includes(areaForPanel(panel, workspace)));
  const latest = new Map<string, Panel>();
  const key = (panel: Panel) => panel.provenance?.artifact_type ? String(panel.provenance.artifact_type) + ':' + panel.kind : panel.id;
  for (const panel of selected) {
    const previous = latest.get(key(panel));
    if (!previous || Number(panel.provenance?.revision || 0) >= Number(previous.provenance?.revision || 0)) latest.set(key(panel), panel);
  }
  const current = selected.filter(panel => latest.get(key(panel)) === panel);
  return areas.length ? areas.flatMap(area => current.filter(panel => areaForPanel(panel, workspace) === area)) : current;
}
