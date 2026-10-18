import { z } from 'zod';
import { fillAspectStartingPoints, ideaAnalysisSchema } from './ideaAnalysis';
import { teamAreaSchema, workflowAreaSchema, ideaAreaSchema, aspectChecksSchema, aspectFormDraftsSchema, type IdeaArea } from './aspectState';
export { teamAreaSchema, workflowAreaSchema } from './aspectState';

const frameworkAttribution = z.strictObject({
  id: z.enum(['founder_truth', 'offer_diagnostic']), version: z.string().regex(/^\d+\.\d+\.\d+$/), attribution: z.string().min(1).max(20_000),
  source_repository: z.string().regex(/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/), source_revision: z.string().regex(/^[0-9a-f]{40}$/),
  source_url: z.string().url().refine(url => /^https:\/\/github\.com\//.test(url)),
}).refine(value => value.source_url.replace(/\/$/, '') === `https://github.com/${value.source_repository}/tree/${value.source_revision}`);
const founderPanelContext = z.strictObject({
  next_decision: z.string().min(1).max(20_000).nullable().default(null), evidence_gaps: z.array(z.string().min(1).max(20_000)).max(100).default([]),
  framework: frameworkAttribution.optional(),
});
const shortText = z.string().min(1).max(4000);
const externalEvidenceSource = z.strictObject({ kind: z.literal('external'), title: shortText, url: z.string().url().refine(url => /^https?:\/\//.test(url)) });
const legacyExternalEvidenceSource = z.strictObject({ title: shortText, url: z.string().url().refine(url => /^https?:\/\//.test(url)) }).transform(source => ({ ...source, kind: 'external' as const }));
const knowledgeProvenance = z.strictObject({ chunk_id: z.string().uuid(), indexed_revision: z.number().int().min(0), ordinal: z.number().int().min(0), content_sha256: z.string().regex(/^[a-f0-9]{64}$/), trust_class: z.enum(['accepted_artifact', 'uploaded_file']), evidence_status: z.literal('untrusted_context') });
const workspaceFileEvidenceSource = knowledgeProvenance.extend({ kind: z.literal('workspace_file'), file_id: z.string().uuid(), title: z.string().min(1).max(200).nullable().default(null), trust_class: z.literal('uploaded_file') });
const acceptedArtifactEvidenceSource = knowledgeProvenance.extend({ kind: z.literal('accepted_artifact'), artifact_id: z.string().uuid(), trust_class: z.literal('accepted_artifact') });
export const evidenceSourceSchema = z.union([externalEvidenceSource, legacyExternalEvidenceSource, workspaceFileEvidenceSource, acceptedArtifactEvidenceSource]);
export type EvidenceSource = z.infer<typeof evidenceSourceSchema>;
const panelKnowledgeSources = z.array(z.union([workspaceFileEvidenceSource, acceptedArtifactEvidenceSource])).min(1).max(5).refine(sources => new Set(sources.map(source => source.chunk_id)).size === sources.length);
const basePanel = { id: z.string(), title: z.string(), note: z.string(), provenance: z.record(z.string(), z.unknown()).optional(), founder_context: founderPanelContext.optional(), knowledge_sources: panelKnowledgeSources.optional(), idea_analysis: ideaAnalysisSchema.optional() };
export const panelBlockSchema = z.discriminatedUnion('kind', [
  z.strictObject({ kind: z.literal('text'), text: shortText }),
  z.strictObject({ kind: z.literal('metric'), label: shortText, value: shortText, detail: shortText }),
  z.strictObject({ kind: z.literal('list'), title: shortText, items: z.array(shortText).min(1).max(30) }),
  z.strictObject({ kind: z.literal('table'), columns: z.array(shortText).min(1).max(8), rows: z.array(z.array(shortText).max(8)).max(100) }).refine(block => block.rows.every(row => row.length === block.columns.length), 'Rows must match columns'),
]);
const draftNote = z.literal('Generated view · Working assumptions, not verified business results');
const scenarioNumber = z.union([z.number().finite(), z.string().min(1).refine(value => Number.isFinite(Number(value)), 'Finite decimal required')]);
const scenarioAssumption = z.strictObject({ name: shortText, target_metric: shortText, low_delta_percent: scenarioNumber, base_delta_percent: scenarioNumber, high_delta_percent: scenarioNumber });
const scenarioTrajectory = z.strictObject({ label: z.enum(['low', 'base', 'high']), metrics: z.array(z.strictObject({ metric: shortText, unit: shortText, points: z.tuple([z.strictObject({ day: z.number().int().min(0), value: scenarioNumber }), z.strictObject({ day: z.number().int().min(0), value: scenarioNumber })]) })).min(1).max(20) });
export const panelSchema = z.discriminatedUnion('kind', [
  z.strictObject({ ...basePanel, kind: z.literal('prospects'), rows: z.array(z.strictObject({
    id: z.string(), name: z.string(), area: z.string(), reason: z.string(), fit: z.enum(['High', 'Medium']),
  })).max(100) }),
  z.strictObject({ ...basePanel, kind: z.literal('offer'), customer: z.string(), promise: z.string(),
    price: z.string(), includes: z.array(z.string()).max(20) }),
  z.strictObject({ ...basePanel, kind: z.literal('evidence'), claims: z.array(z.strictObject({
    id: z.string(), claim: z.string(), status: z.enum(['hypothesis', 'needs-check', 'supported']),
    detail: z.string(), sources: z.array(evidenceSourceSchema).max(100),
  }).refine(claim => claim.status !== 'supported' || claim.sources.some(source => source.kind === 'external'), 'Supported claims need external sources')).max(500) }),
  z.strictObject({ ...basePanel, kind: z.literal('launch-plan'), tasks: z.array(z.strictObject({
    id: z.string(), title: z.string(), owner: z.string(), timing: z.string(), detail: z.string(),
  })).max(400).refine(tasks => new Set(tasks.map(task => task.id)).size === tasks.length, 'Task IDs must be unique') }),
  z.strictObject({ provenance: z.record(z.string(), z.unknown()).optional().superRefine((value, context) => { if (value !== undefined) context.addIssue({ code: 'custom', message: 'Generated panels cannot carry backend provenance.' }); }), id: z.string().uuid(), kind: z.literal('declarative'), panel_key: z.string().min(1).max(80).optional(), title: z.string().min(1).max(120), note: draftNote, blocks: z.array(panelBlockSchema).min(1).max(20) }).refine(panel => JSON.stringify(panel).length <= 100000, 'Panel exceeds size limit'),
  z.strictObject({ provenance: z.record(z.string(), z.unknown()).optional().superRefine((value, context) => { if (value !== undefined) context.addIssue({ code: 'custom', message: 'Generated panels cannot carry backend provenance.' }); }), id: z.string().uuid(), kind: z.literal('custom'), title: z.string().min(1).max(120), note: draftNote, html: z.string().min(1).max(60000), css: z.string().max(20000), javascript: z.string().max(20000) }),
  z.strictObject({ ...basePanel, kind: z.literal('pricing'), options: z.array(z.strictObject({
    name: z.string(), price: z.string(), description: z.string(),
  })).max(100) }),
  z.strictObject({ ...basePanel, kind: z.literal('scenario'), provenance: z.record(z.string(), z.unknown()).refine(value => value.label === 'synthetic_scenario_not_validation'), synthetic_label: z.literal('synthetic_scenario_not_validation'), company_revision: z.number().int().min(0), result_sha256: z.string().regex(/^[a-f0-9]{64}$/), horizon_days: z.number().int().min(1).max(365), assumptions: z.array(scenarioAssumption).min(1).max(10), trajectories: z.tuple([scenarioTrajectory, scenarioTrajectory, scenarioTrajectory]), formulas: z.array(z.strictObject({ metric: shortText, expression: z.literal('end = baseline * (1 + delta_percent / 100)'), baseline_input: scenarioNumber, assumption: shortText.nullable() })).max(20), constraints: z.array(z.strictObject({ constraint: shortText, label: z.enum(['low', 'base', 'high']), metric: shortText, operator: z.enum(['minimum', 'maximum']), threshold: scenarioNumber, actual: scenarioNumber, unit: shortText, violated: z.boolean() })).max(30) }),
]);
export type Panel = z.infer<typeof panelSchema>;
export type TeamArea = z.infer<typeof teamAreaSchema>;
export type WorkflowArea = z.infer<typeof workflowAreaSchema>;
export const companyActionIdSchema = z.enum(['brief', 'research', 'strategy', 'plan', 'verify', 'sales', 'builder', 'marketer', 'metrics']);
export const companyActionSchema = z.strictObject({
  id: companyActionIdSchema, label: z.string().min(1).max(100), prompt: z.string().min(1).max(4000),
  operation: z.enum(['journey', 'launch_drafts', 'metrics_analysis']), stage: z.enum(['brief', 'research', 'strategy', 'plan', 'verify']),
  area: teamAreaSchema, eligible: z.boolean(), blocked_reason: z.string().min(1).max(500).nullable(),
}).refine(action => action.eligible === (action.blocked_reason === null), 'Blocked actions need a reason');
export type CompanyAction = z.infer<typeof companyActionSchema>;
export const messageSchema = z.object({
  id: z.string(), role: z.enum(['user', 'assistant']), text: z.string(), panel: panelSchema.optional(), backendRunId: z.string().optional(), area: teamAreaSchema.optional(), aspect: ideaAreaSchema.optional(), handoff: teamAreaSchema.optional(), handoffPrerequisite: z.boolean().optional(),
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
export const companyBriefSchema = z.object({
  idea: z.string().trim().min(8).max(1500),
  customer: z.string().trim().min(3).max(300).or(z.literal('')).default(''),
  location: z.string().trim().min(2).max(120).or(z.literal('')).default(''),
  budget: z.string().trim().min(1).max(120).or(z.literal('')).default(''),
  goal: z.string().trim().min(3).max(500).or(z.literal('')).default(''),
  founderSkills: z.string().trim().min(3).max(500).or(z.literal('')).optional(),
});
export type CompanyBrief = z.infer<typeof companyBriefSchema>;
const backendRunStatusSchema = z.enum(['submitting', 'queued', 'running', 'recovering', 'paused', 'completed', 'cancelled', 'failed']);
export const backendRunSchema = z.object({
  submissionId: z.string().uuid().optional(), runId: z.string().min(1).optional(), status: backendRunStatusSchema,
  companyId: z.string().uuid().optional(), revision: z.number().int().min(0).optional(), lastEventIndex: z.number().int().min(0).optional(),
  attempt: z.number().int().min(0).optional(), maxAttempts: z.number().int().min(1).optional(), failureReason: z.string().min(1).max(2000).optional(), area: teamAreaSchema.optional(), aspect: ideaAreaSchema.optional(),
}).refine(run => Boolean(run.runId) || (['submitting', 'recovering'].includes(run.status) && Boolean(run.submissionId)), 'A backend run needs a run or submission ID');
export type BackendRun = z.infer<typeof backendRunSchema>;
export const workspaceSchema = z.object({
  executionMode: z.enum(['preview', 'live']).default('preview'), backendRun: backendRunSchema.optional(),
  companyId: z.string().uuid().optional(), currentRevision: z.number().int().min(0).optional(), stateSha256: z.string().regex(/^[a-f0-9]{64}$/).optional(),
  currentArtifactIds: z.array(z.string().uuid()).max(100).optional(),
  actions: z.array(companyActionSchema).max(9).default([]), nextAction: companyActionIdSchema.nullable().default(null),
  brief: companyBriefSchema.optional(),
  selectedArea: teamAreaSchema.default("overview"),
  selectedAreas: z.array(workflowAreaSchema).max(6).refine(items => new Set(items).size === items.length).optional(), aspectChecks: aspectChecksSchema, aspectFormDrafts: aspectFormDraftsSchema,
  drafts: z.partialRecord(ideaAreaSchema, z.string().max(4000)).default({}),
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
  currentRevision: z.number().int().min(0).optional(), stateSha256: z.string().regex(/^[a-f0-9]{64}$/).optional(), createdAt: z.number().int().min(0).optional(),
  role: z.enum(['owner', 'editor', 'viewer']).optional(),
});
export const portfolioSchema = z.object({
  version: z.literal(2), companies: z.array(companySchema).max(50), activeId: z.string().nullable(), mode: z.enum(['light', 'dark']),
  legacyCompanies: z.array(companySchema).max(50).optional(),
}).refine(value => new Set(value.companies.map(company => company.id)).size === value.companies.length &&
  (value.legacyCompanies?.length ?? 0) + value.companies.filter(company => company.workspace.executionMode !== 'live').length <= 50 &&
  (value.activeId === null || value.companies.some(company => company.id === value.activeId)));
export type Portfolio = z.infer<typeof portfolioSchema>;
export function emptyWorkspace(): Workspace {
  return { actions: [], nextAction: null, selectedArea: 'overview', selectedAreas: [], aspectChecks: {}, drafts: {}, executionMode: 'live', activityLog: [], version: 1, messages: [], pinned: [], completedTasks: [], panelOrder: [], shortlist: [], approvedOffers: [], theme: 'sky' };
}
export const emptyCompanyView = emptyWorkspace;
export function continueCompanyView(workspace: CompanyView, companyId: string, revision: number): CompanyView {
  return { ...workspace, executionMode: 'live', companyId: z.string().uuid().parse(companyId), currentRevision: z.number().int().min(0).parse(revision) };
}
export function restorePortfolio(saved: string | null, legacy: string | null): Portfolio {
  if (saved) {
    try {
      const portfolio = portfolioSchema.parse(JSON.parse(saved));
      const legacyCompanies = portfolio.companies.filter(company => company.workspace.executionMode !== 'live');
      if (!legacyCompanies.length) return portfolio;
      const companies = portfolio.companies.filter(company => company.workspace.executionMode === 'live');
      return { ...portfolio, companies, activeId: companies.some(company => company.id === portfolio.activeId) ? portfolio.activeId : null, legacyCompanies: [...(portfolio.legacyCompanies ?? []), ...legacyCompanies] };
    } catch { /* Recover valid legacy data if available. */ }
  }
  if (legacy) {
    try {
      const workspace = workspaceSchema.parse(JSON.parse(legacy));
      return { version: 2, activeId: null, mode: 'light', companies: [], legacyCompanies: [{ id: 'legacy-dental', name: 'Dental receptionist', workspace }] };
    } catch { /* Invalid browser data starts a fresh portfolio. */ }
  }
  return { version: 2, companies: [], activeId: null, mode: 'light' };
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
  if (workspace.backendRun?.submissionId && run.submissionId && workspace.backendRun.submissionId !== run.submissionId) throw new Error('The backend result belongs to another submission.');
  if (workspace.backendRun?.companyId && run.companyId && workspace.backendRun.companyId !== run.companyId) throw new Error('The backend result belongs to another company.');
  return { ...workspace, backendRun: backendRunSchema.parse({ ...workspace.backendRun, ...run }), messages: run.area && run.runId ? workspace.messages.map(message => message.role === 'assistant' && message.backendRunId === run.runId && message.area !== run.area ? { ...message, area: run.area } : message) : workspace.messages };
}
export function beginBackendRun(workspace: Workspace, submissionId: string, area?: TeamArea, aspect?: IdeaArea): Workspace {
  if (hasActiveBackendRun(workspace.backendRun)) throw new Error('A backend run is already active.');
  return { ...workspace, backendRun: backendRunSchema.parse({
    submissionId, status: 'submitting', ...(area ? { area } : {}), ...(aspect ? { aspect } : {}),
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
export function panelIsOutdated(panel: Panel, workspace: Workspace): boolean {
  const provenance = panel.provenance;
  return workspace.executionMode === 'live' && workspace.currentArtifactIds !== undefined && provenance !== undefined && provenance.company_id === workspace.companyId
    && typeof provenance.artifact_id === 'string' && typeof provenance.revision === 'number' && provenance.revision <= (workspace.currentRevision ?? -1)
    && !workspace.currentArtifactIds.includes(provenance.artifact_id);
}
export function currentCompanyActions(workspace: Workspace): CompanyAction[] {
  if (hasActiveBackendRun(workspace.backendRun) || !workspace.companyId || workspace.currentRevision === undefined
    || (workspace.backendRun?.revision ?? 0) > workspace.currentRevision) return [];
  return workspace.actions;
}
export type JourneyApproval = { readonly stage: CompanyAction['stage']; readonly expectedRevision: number; readonly companyId: string };
export function nextJourneyApproval(workspace: Workspace): JourneyApproval | undefined {
  const action = currentCompanyActions(workspace).find(item => item.id === workspace.nextAction);
  if (!action?.eligible || action.operation !== 'journey' || !workspace.companyId || workspace.currentRevision === undefined) return undefined;
  return { stage: action.stage, expectedRevision: workspace.currentRevision, companyId: workspace.companyId };
}
export function applyBackendEvent(workspace: Workspace, runId: string, event: Extract<WorkEvent, { type: 'message' }>): Workspace {
  if (workspace.messages.some(message => message.backendRunId === runId && message.text === event.text && JSON.stringify(message.panel) === JSON.stringify(event.panel))) return workspace;
  const message: Message = { id: crypto.randomUUID(), backendRunId: runId, area: workspace.backendRun?.area || 'overview', ...(workspace.backendRun?.aspect ? { aspect: workspace.backendRun.aspect } : {}), ...(event.handoff ? { handoff: event.handoff, handoffPrerequisite: event.handoffPrerequisite } : {}), role: 'assistant', text: event.text, ...(event.panel ? { panel: event.panel } : {}) };
  return fillAspectStartingPoints({ ...workspace, messages: [...workspace.messages, message].slice(-200), pinned: event.panel ? workspace.pinned.map(panel => panel.id === event.panel?.id ? event.panel : panel) : workspace.pinned }, event.panel);
}
export function initialCompanyPrompt(brief: CompanyBrief): string {
  return `Welcome me as my software-idea mentor. Use stage="brief" to save my idea and produce idea_analysis: a concise first pass and useful starting points across the six aspects. Infer draft hypotheses where reasonable and preserve genuine gaps. Do not run research, strategy, planning or external actions. These inputs and drafts are not verified facts.\n${JSON.stringify({ idea: brief.idea, target_customer: brief.customer || null, geography: brief.location || null, budget: brief.budget || null, founder_skills: brief.founderSkills || null, goal: brief.goal || null })}`;
}

export function toggleSavedSelection(ids: readonly string[], id: string, limit: number): string[] {
  return ids.includes(id) ? ids.filter(item => item !== id) : [...ids, id].slice(-limit);
}

export function finishActivities(history: Workspace['activityLog'], status: BackendRun['status']): Workspace['activityLog'] {
  if (['submitting', 'queued', 'running', 'recovering', 'paused'].includes(status)) return history;
  const latest = Object.values(Object.fromEntries(history.map(activity => [activity.agent, activity])));
  const pending = latest.filter(activity => activity.state === 'working');
  const state = status === 'cancelled' || status === 'failed' ? 'stopped' : 'waiting';
  const detail = status === 'cancelled' ? 'The backend acknowledged cancellation.' : status === 'failed' ? 'The backend run failed.' : 'The run finished without a completion event for this step.';
  return [...history, ...pending.map(activity => ({ ...activity, state, detail } satisfies z.infer<typeof activitySchema>))].slice(-100);
}
