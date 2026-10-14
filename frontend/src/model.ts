import { z } from 'zod';

const basePanel = { id: z.string(), title: z.string(), note: z.string(), provenance: z.record(z.string(), z.unknown()).optional() };
const shortText = z.string().min(1).max(4000);
export const panelBlockSchema = z.discriminatedUnion('kind', [
  z.strictObject({ kind: z.literal('text'), text: shortText }),
  z.strictObject({ kind: z.literal('metric'), label: shortText, value: shortText, detail: shortText }),
  z.strictObject({ kind: z.literal('list'), title: shortText, items: z.array(shortText).min(1).max(30) }),
  z.strictObject({ kind: z.literal('table'), columns: z.array(shortText).min(1).max(8), rows: z.array(z.array(shortText).max(8)).max(100) }).refine(block => block.rows.every(row => row.length === block.columns.length), 'Rows must match columns'),
]);
const draftNote = z.literal('Generated view · Working assumptions, not verified business results');
export const panelSchema = z.discriminatedUnion('kind', [
  z.object({ ...basePanel, kind: z.literal('prospects'), rows: z.array(z.object({
    id: z.string(), name: z.string(), area: z.string(), reason: z.string(), fit: z.enum(['High', 'Medium']),
  })).max(100) }),
  z.object({ ...basePanel, kind: z.literal('offer'), customer: z.string(), promise: z.string(),
    price: z.string(), includes: z.array(z.string()).max(20) }),
  z.object({ ...basePanel, kind: z.literal('evidence'), claims: z.array(z.object({
    id: z.string(), claim: z.string(), status: z.enum(['hypothesis', 'needs-check', 'supported']),
    detail: z.string(), sources: z.array(z.object({ title: z.string(), url: z.string().url().refine(url => /^https?:\/\//.test(url)) })).max(100),
  }).refine(claim => claim.status !== 'supported' || claim.sources.length > 0, 'Supported claims need sources')).max(500) }),
  z.object({ ...basePanel, kind: z.literal('launch-plan'), tasks: z.array(z.object({
    id: z.string(), title: z.string(), owner: z.string(), timing: z.string(), detail: z.string(),
  })).max(400).refine(tasks => new Set(tasks.map(task => task.id)).size === tasks.length, 'Task IDs must be unique') }),
  z.strictObject({ provenance: z.never().optional(), id: z.string().uuid(), kind: z.literal('declarative'), title: z.string().min(1).max(120), note: draftNote, blocks: z.array(panelBlockSchema).min(1).max(20) }).refine(panel => JSON.stringify(panel).length <= 100000, 'Panel exceeds size limit'),
  z.strictObject({ provenance: z.never().optional(), id: z.string().uuid(), kind: z.literal('custom'), title: z.string().min(1).max(120), note: draftNote, html: z.string().min(1).max(60000), css: z.string().max(20000), javascript: z.string().max(20000) }),
  z.object({ ...basePanel, kind: z.literal('pricing'), options: z.array(z.object({
    name: z.string(), price: z.string(), description: z.string(),
  })).max(100) }),
]);
export type Panel = z.infer<typeof panelSchema>;
export const teamAreaSchema = z.enum(["overview", "research", "strategy", "verification", "sales"]);
export type TeamArea = z.infer<typeof teamAreaSchema>;
export const workflowAreaSchema = teamAreaSchema.exclude(["overview"]);
export type WorkflowArea = z.infer<typeof workflowAreaSchema>;
export const messageSchema = z.object({
  id: z.string(), role: z.enum(['user', 'assistant']), text: z.string(), panel: panelSchema.optional(), backendRunId: z.string().optional(), area: teamAreaSchema.optional(), handoff: teamAreaSchema.optional(), handoffPrerequisite: z.boolean().optional(),
});
export type Message = z.infer<typeof messageSchema>;
export const agents = ['Researcher', 'Strategist', 'Verifier', 'Sales'] as const;
export type Agent = typeof agents[number];
export const activitySchema = z.object({ type: z.literal('activity'), agent: z.enum(agents), state: z.enum(['working', 'done', 'waiting', 'stopped']), detail: z.string().max(2000) });
export const eventSchema = z.discriminatedUnion('type', [
  activitySchema,
  z.object({ type: z.literal('message'), text: z.string(), panel: panelSchema.optional(), handoff: teamAreaSchema.optional(), handoffPrerequisite: z.boolean().optional() }),
]);
export type WorkEvent = z.infer<typeof eventSchema>;
export type Transport = (input: string, signal: AbortSignal, area?: TeamArea) => AsyncIterable<WorkEvent>;
export const companyBriefSchema = z.object({
  idea: z.string().trim().min(8).max(1500),
  customer: z.string().trim().min(3).max(300),
  location: z.string().trim().min(2).max(120),
  budget: z.string().trim().min(1).max(120),
  goal: z.string().trim().min(3).max(500),
  founderSkills: z.string().trim().min(3).max(500).optional(),
});
export type CompanyBrief = z.infer<typeof companyBriefSchema>;
const backendRunStatusSchema = z.enum(['submitting', 'queued', 'running', 'recovering', 'paused', 'completed', 'cancelled', 'failed']);
export const backendRunSchema = z.object({
  submissionId: z.string().uuid().optional(), runId: z.string().min(1).optional(), status: backendRunStatusSchema,
  companyId: z.string().uuid().optional(), revision: z.number().int().min(0).optional(), lastEventIndex: z.number().int().min(0).optional(),
  attempt: z.number().int().min(0).optional(), maxAttempts: z.number().int().min(1).optional(), failureReason: z.string().min(1).max(2000).optional(), area: teamAreaSchema.optional(),
}).refine(run => Boolean(run.runId) || (['submitting', 'recovering'].includes(run.status) && Boolean(run.submissionId)), 'A backend run needs a run or submission ID');
export type BackendRun = z.infer<typeof backendRunSchema>;
export const workspaceSchema = z.object({
  executionMode: z.enum(['preview', 'live']).default('preview'), backendRun: backendRunSchema.optional(),
  companyId: z.string().uuid().optional(), currentRevision: z.number().int().min(0).optional(),
  brief: companyBriefSchema.optional(),
  selectedArea: teamAreaSchema.default("overview"),
  selectedAreas: z.array(workflowAreaSchema).max(4).refine(items => new Set(items).size === items.length).optional(),
  drafts: z.partialRecord(teamAreaSchema, z.string().max(4000)).default({}),
  activityLog: z.array(activitySchema).max(100).default([]),
  version: z.literal(1), messages: z.array(messageSchema).max(200), pinned: z.array(panelSchema).max(12),
  completedTasks: z.array(z.string()).max(400).default([]),
  panelOrder: z.array(z.string()).max(212).default([]),
  shortlist: z.array(z.string()).max(100), approvedOffers: z.array(z.string()).max(20), theme: z.enum(['sky', 'dusk']),
});
export type Workspace = z.infer<typeof workspaceSchema>;
export type CompanyView = Workspace;
export const companyViewSchema = workspaceSchema;
export const storageKey = 'samurai-ui-preview-v1';

export const portfolioKey = 'samurai-companies-v2';
export const companySchema = z.object({
  id: z.string(), name: z.string().min(1).max(80), workspace: workspaceSchema,
  workspaceId: z.string().uuid().optional(), companyId: z.string().uuid().optional(),
  currentRevision: z.number().int().min(0).optional(), createdAt: z.number().int().min(0).optional(),
  role: z.enum(['owner', 'editor', 'viewer']).optional(),
});
export const portfolioSchema = z.object({
  version: z.literal(2), companies: z.array(companySchema).max(50), activeId: z.string().nullable(), mode: z.enum(['light', 'dark']),
}).refine(value => new Set(value.companies.map(company => company.id)).size === value.companies.length &&
  (value.activeId === null || value.companies.some(company => company.id === value.activeId)));
export type Portfolio = z.infer<typeof portfolioSchema>;
export function emptyWorkspace(): Workspace {
  return { selectedArea: 'overview', selectedAreas: [], drafts: {}, executionMode: 'preview', activityLog: [], version: 1, messages: [], pinned: [], completedTasks: [], panelOrder: [], shortlist: [], approvedOffers: [], theme: 'sky' };
}
export const emptyCompanyView = emptyWorkspace;
export function continueCompanyView(workspace: CompanyView, companyId: string, revision: number): CompanyView {
  return { ...workspace, executionMode: 'live', companyId: z.string().uuid().parse(companyId), currentRevision: z.number().int().min(0).parse(revision) };
}
export function restorePortfolio(saved: string | null, legacy: string | null): Portfolio {
  if (saved) {
    try { return portfolioSchema.parse(JSON.parse(saved)); } catch { /* Recover a valid legacy preview if available. */ }
  }
  if (legacy) {
    try {
      const workspace = workspaceSchema.parse(JSON.parse(legacy));
      return { version: 2, activeId: null, mode: 'light', companies: [{ id: 'legacy-dental', name: 'Dental receptionist', workspace }] };
    } catch { /* Invalid browser data starts a fresh portfolio. */ }
  }
  return { version: 2, companies: [], activeId: null, mode: 'light' };
}

export function readWorkspace(initial: Workspace): Workspace {
  try {
    const saved = localStorage.getItem(storageKey);
    return saved ? workspaceSchema.parse(JSON.parse(saved)) : initial;
  } catch { return initial; }
}
export const readCompanyView = readWorkspace;

export function chooseWorkflow(input: string): 'prospects' | 'offer' | 'pricing' | 'evidence' | 'launch-plan' | 'help' {
  if (/evidence|validate|validation|assumption|source|risk/i.test(input)) return 'evidence';
  if (/launch|roadmap|next steps|plan|checklist/i.test(input)) return 'launch-plan';
  if (/price|pricing|cost|charge|viable/i.test(input)) return 'pricing';
  if (/offer|position|strategy|business model/i.test(input)) return 'offer';
  if (/customer|prospect|sell|sales|research|market|build|business/i.test(input)) return 'prospects';
  return 'help';
}

// Pinned panels keep their place while newer results replace their contents.
export function latestPanels(workspace: Workspace): Panel[] {
  return Array.from(new Map([...workspace.pinned, ...workspace.messages.flatMap(message => message.panel ? [message.panel] : [])].map(panel => [panel.id, panel])).values());
}

export function orderedPanels(panels: Panel[], order: string[]): Panel[] {
  const remaining = new Map(panels.map(panel => [panel.id, panel]));
  const result: Panel[] = [];
  for (const id of order) {
    const panel = remaining.get(id);
    if (panel) { result.push(panel); remaining.delete(id); }
  }
  return [...result, ...remaining.values()];
}
export function movePanel(panels: Panel[], id: string, target: string): string[] {
  const ids = panels.map(panel => panel.id);
  const from = ids.indexOf(id), to = ids.indexOf(target);
  if (from < 0 || to < 0 || from === to) return ids;
  ids.splice(from, 1);
  ids.splice(to, 0, id);
  return ids;
}

export function recordBackendRun(workspace: Workspace, run: BackendRun): Workspace {
  if (workspace.backendRun?.submissionId && run.submissionId && workspace.backendRun.submissionId !== run.submissionId) throw new Error('The backend result belongs to another submission.');
  if (workspace.backendRun?.companyId && run.companyId && workspace.backendRun.companyId !== run.companyId) throw new Error('The backend result belongs to another company.');
  return { ...workspace, backendRun: backendRunSchema.parse({ ...workspace.backendRun, ...run }) };
}
export function beginBackendRun(workspace: Workspace, submissionId: string): Workspace {
  if (hasActiveBackendRun(workspace.backendRun)) throw new Error('A backend run is already active.');
  return { ...workspace, backendRun: backendRunSchema.parse({
    submissionId, status: 'submitting',
    ...(workspace.backendRun?.companyId ? { companyId: workspace.backendRun.companyId } : {}),
    ...(workspace.backendRun?.revision !== undefined ? { revision: workspace.backendRun.revision } : {}),
  }) };
}
export function hasActiveBackendRun(run: BackendRun | undefined): boolean {
  return run !== undefined && ['submitting', 'queued', 'running', 'recovering', 'paused'].includes(run.status);
}
export function isCancellableBackendRun(run: BackendRun | undefined): run is BackendRun & { runId: string } {
  return Boolean(run?.runId) && hasActiveBackendRun(run);
}
export type JourneyApproval = { readonly stage: 'research' | 'strategy' | 'plan'; readonly expectedRevision: number; readonly companyId: string };
export function nextJourneyApproval(workspace: Workspace): JourneyApproval | undefined {
  const run = workspace.backendRun;
  if (run && run.status !== 'completed') return undefined;
  const companyId = run?.companyId ?? workspace.companyId;
  const revision = run?.revision ?? workspace.currentRevision;
  if (!companyId || revision === undefined) return undefined;
  const artifacts = workspace.messages.flatMap(message => {
    const value = message.panel?.provenance;
    if (!value || value.acceptance_status !== 'accepted' || typeof value.artifact_type !== 'string' || typeof value.status !== 'string') return [];
    return [{ artifactType: value.artifact_type, status: value.status }];
  });
  const accepted = (artifactType: string) => artifacts.filter(item => item.artifactType === artifactType);
  if (accepted('product_plan').some(item => item.status === 'complete')) return undefined;
  if (accepted('strategy').length) return { stage: accepted('strategy').some(item => item.status === 'complete') ? 'plan' : 'strategy', expectedRevision: revision, companyId };
  if (accepted('research').length) return { stage: accepted('research').some(item => item.status === 'complete') ? 'strategy' : 'research', expectedRevision: revision, companyId };
  if (accepted('intake').length) return { stage: 'research', expectedRevision: revision, companyId };
  return undefined;
}
export function applyBackendEvent(workspace: Workspace, runId: string, event: Extract<WorkEvent, { type: 'message' }>): Workspace {
  if (workspace.messages.some(message => message.backendRunId === runId && message.text === event.text && JSON.stringify(message.panel) === JSON.stringify(event.panel))) return workspace;
  const message: Message = { id: crypto.randomUUID(), backendRunId: runId, area: workspace.backendRun?.area || 'overview', ...(event.handoff ? { handoff: event.handoff, handoffPrerequisite: event.handoffPrerequisite } : {}), role: 'assistant', text: event.text, ...(event.panel ? { panel: event.panel } : {}) };
  return { ...workspace, messages: [...workspace.messages, message].slice(-200), pinned: event.panel ? workspace.pinned.map(panel => panel.id === event.panel?.id ? event.panel : panel) : workspace.pinned };
}
export function initialCompanyPrompt(brief: CompanyBrief): string {
  return `Prepare only my company brief using stage="brief", then wait for my decision before research or planning. These are inputs and hypotheses, not verified facts. Preserve missing evidence and request clarification when needed.\n${JSON.stringify({ idea: brief.idea, target_customer: brief.customer, geography: brief.location, budget: brief.budget, founder_skills: brief.founderSkills, goal: brief.goal })}`;
}

export function toggleSavedSelection(ids: readonly string[], id: string, limit: number): string[] {
  return ids.includes(id) ? ids.filter(item => item !== id) : [...ids, id].slice(-limit);
}

export function finishActivities(history: Workspace['activityLog'], status: BackendRun['status'], mode: 'live' | 'preview' = 'live'): Workspace['activityLog'] {
  if (['submitting', 'queued', 'running', 'recovering', 'paused'].includes(status)) return history;
  const latest = Object.values(Object.fromEntries(history.map(activity => [activity.agent, activity])));
  const pending = latest.filter(activity => activity.state === 'working');
  const state = status === 'cancelled' || status === 'failed' ? 'stopped' : 'waiting';
  const detail = mode === 'preview' ? status === 'cancelled' ? 'Preview stopped.' : status === 'failed' ? 'Preview failed.' : 'Preview finished.' : status === 'cancelled' ? 'The backend acknowledged cancellation.' : status === 'failed' ? 'The backend run failed.' : 'The run finished without a completion event for this step.';
  return [...history, ...pending.map(activity => ({ ...activity, state, detail } satisfies z.infer<typeof activitySchema>))].slice(-100);
}
