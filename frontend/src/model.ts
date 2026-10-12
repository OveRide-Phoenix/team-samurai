import { z } from 'zod';

const basePanel = { id: z.string(), title: z.string(), note: z.string(), provenance: z.record(z.string(), z.unknown()).optional() };
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
  z.object({ ...basePanel, kind: z.literal('pricing'), options: z.array(z.object({
    name: z.string(), price: z.string(), description: z.string(),
  })).max(100) }),
]);
export type Panel = z.infer<typeof panelSchema>;
export const messageSchema = z.object({
  id: z.string(), role: z.enum(['user', 'assistant']), text: z.string(), panel: panelSchema.optional(), backendRunId: z.string().optional(),
});
export type Message = z.infer<typeof messageSchema>;
export const agents = ['Researcher', 'Strategist', 'Verifier', 'Sales'] as const;
export type Agent = typeof agents[number];
export const activitySchema = z.object({ type: z.literal('activity'), agent: z.enum(agents), state: z.enum(['working', 'done', 'waiting', 'stopped']), detail: z.string().max(2000) });
export const eventSchema = z.discriminatedUnion('type', [
  activitySchema,
  z.object({ type: z.literal('message'), text: z.string(), panel: panelSchema.optional() }),
]);
export type WorkEvent = z.infer<typeof eventSchema>;
export type Transport = (input: string, signal: AbortSignal) => AsyncIterable<WorkEvent>;
export const companyBriefSchema = z.object({
  idea: z.string().trim().min(8).max(1500),
  customer: z.string().trim().min(3).max(300),
  location: z.string().trim().min(2).max(120),
  budget: z.string().trim().min(1).max(120),
  goal: z.string().trim().min(3).max(500),
  founderSkills: z.string().trim().min(3).max(500).optional(),
});
export type CompanyBrief = z.infer<typeof companyBriefSchema>;
export const backendRunSchema = z.object({ runId: z.string().min(1), status: z.enum(['running', 'completed', 'cancelled', 'failed']), companyId: z.string().uuid().optional(), revision: z.number().int().min(0).optional() });
export type BackendRun = z.infer<typeof backendRunSchema>;
export const workspaceSchema = z.object({
  executionMode: z.enum(['preview', 'live']).default('preview'), backendRun: backendRunSchema.optional(),
  brief: companyBriefSchema.optional(),
  activityLog: z.array(activitySchema).max(100).default([]),
  version: z.literal(1), messages: z.array(messageSchema).max(200), pinned: z.array(panelSchema).max(12),
  completedTasks: z.array(z.string()).max(400).default([]),
  panelOrder: z.array(z.string()).max(212).default([]),
  shortlist: z.array(z.string()).max(100), approvedOffers: z.array(z.string()).max(20), theme: z.enum(['sky', 'dusk']),
});
export type Workspace = z.infer<typeof workspaceSchema>;
export const storageKey = 'samurai-ui-preview-v1';

export const portfolioKey = 'samurai-companies-v2';
export const companySchema = z.object({ id: z.string(), name: z.string().min(1).max(80), workspace: workspaceSchema });
export const portfolioSchema = z.object({
  version: z.literal(2), companies: z.array(companySchema).max(50), activeId: z.string().nullable(), mode: z.enum(['light', 'dark']),
}).refine(value => new Set(value.companies.map(company => company.id)).size === value.companies.length &&
  (value.activeId === null || value.companies.some(company => company.id === value.activeId)));
export type Portfolio = z.infer<typeof portfolioSchema>;
export function emptyWorkspace(): Workspace {
  return { executionMode: 'preview', activityLog: [], version: 1, messages: [], pinned: [], completedTasks: [], panelOrder: [], shortlist: [], approvedOffers: [], theme: 'sky' };
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
  if (workspace.backendRun?.companyId && run.companyId && workspace.backendRun.companyId !== run.companyId) throw new Error('The backend result belongs to another company.');
  return { ...workspace, backendRun: { ...workspace.backendRun, ...run } };
}
export function applyBackendEvent(workspace: Workspace, runId: string, event: Extract<WorkEvent, { type: 'message' }>): Workspace {
  if (workspace.messages.some(message => message.backendRunId === runId && message.text === event.text && JSON.stringify(message.panel) === JSON.stringify(event.panel))) return workspace;
  const message: Message = { id: crypto.randomUUID(), backendRunId: runId, role: 'assistant', text: event.text, ...(event.panel ? { panel: event.panel } : {}) };
  return { ...workspace, messages: [...workspace.messages, message].slice(-200), pinned: event.panel ? workspace.pinned.map(panel => panel.id === event.panel?.id ? event.panel : panel) : workspace.pinned };
}
export function initialCompanyPrompt(brief: CompanyBrief): string {
  return `Prepare only my company brief using stage="brief", then wait for my decision before research or planning. These are inputs and hypotheses, not verified facts. Preserve missing evidence and request clarification when needed.\n${JSON.stringify({ idea: brief.idea, target_customer: brief.customer, geography: brief.location, budget: brief.budget, founder_skills: brief.founderSkills, goal: brief.goal })}`;
}

export function toggleSavedSelection(ids: readonly string[], id: string, limit: number): string[] {
  return ids.includes(id) ? ids.filter(item => item !== id) : [...ids, id].slice(-limit);
}

export function finishActivities(history: Workspace['activityLog'], status: BackendRun['status']): Workspace['activityLog'] {
  if (status === 'running') return history;
  const latest = Object.values(Object.fromEntries(history.map(activity => [activity.agent, activity])));
  const pending = latest.filter(activity => activity.state === 'working');
  const state = status === 'cancelled' || status === 'failed' ? 'stopped' : 'waiting';
  const detail = status === 'cancelled' ? 'The backend acknowledged cancellation.' : status === 'failed' ? 'The backend run failed.' : 'The run finished without a completion event for this step.';
  return [...history, ...pending.map(activity => ({ ...activity, state, detail } satisfies z.infer<typeof activitySchema>))].slice(-100);
}
