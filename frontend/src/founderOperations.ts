import { z } from 'zod';
import { panelSchema, type Panel } from './model';

const uuid = z.string().uuid();
const hash = z.string().regex(/^[a-f0-9]{64}$/);
const decimal = z.union([z.number().finite(), z.string().min(1).refine(value => value === value.trim() && Number.isFinite(Number(value)), 'Finite decimal required')]);
const learningRecordSchema = z.strictObject({
  learning_id: uuid, workspace_id: uuid, user_id: z.string(), company_id: uuid,
  kind: z.enum(['preference', 'correction']), source_revision: z.number().int().min(0), founder_text: z.string(),
  created_by: z.string(), audit_sha256: hash, shared: z.boolean(), superseded_by: uuid.nullable(), active: z.boolean(),
  created_at: z.number().int().min(0), evidence_status: z.literal('untrusted_preference_context'),
});
const learningContextSchema = z.strictObject({ context_boundary: z.literal('untrusted_preference_context'), records: z.array(learningRecordSchema).max(20) });
const scheduleFields = { schedule_id: uuid, workspace_id: uuid, company_id: uuid, created_by: z.string(), creator_authorization_epoch: z.number().int().min(1), cadence: z.enum(['once', 'daily', 'weekly']), timezone: z.string(), pinned_revision: z.number().int().min(0), enabled: z.boolean(), next_run_at: z.number().nullable(), last_run_at: z.number().nullable(), created_at: z.number(), updated_at: z.number() };
const scheduleSchema = z.discriminatedUnion('action_kind', [
  z.strictObject({ ...scheduleFields, action_kind: z.literal('workspace_review'), payload: z.strictObject({}) }),
  z.strictObject({ ...scheduleFields, action_kind: z.literal('scenario_recompute'), payload: z.strictObject({ scenario_id: uuid }) }),
]);
const metricSchema = z.strictObject({ name: z.string(), value: decimal, unit: z.string() });
const assumptionSchema = z.strictObject({ name: z.string(), target_metric: z.string(), low_delta_percent: decimal, base_delta_percent: decimal, high_delta_percent: decimal });
const constraintSchema = z.strictObject({ name: z.string(), metric: z.string(), operator: z.enum(['minimum', 'maximum']), threshold: decimal, unit: z.string() });
const scenarioDefinitionSchema = z.strictObject({
  scenario_id: uuid, workspace_id: uuid, company_id: uuid, created_by: z.string(), title: z.string(), company_revision: z.number().int().min(0), company_state_sha256: hash,
  horizon_days: z.number().int().min(1).max(365), baseline_metrics: z.array(metricSchema).min(1).max(20), assumptions: z.array(assumptionSchema).min(1).max(10), constraints: z.array(constraintSchema).min(1).max(10), input_sha256: hash,
});
const trajectorySchema = z.strictObject({ label: z.enum(['low', 'base', 'high']), metrics: z.array(z.strictObject({ metric: z.string(), unit: z.string(), points: z.tuple([z.strictObject({ day: z.number().int(), value: decimal }), z.strictObject({ day: z.number().int(), value: decimal })]) })) });
const scenarioResultSchema = z.strictObject({
  provenance: z.literal('synthetic_scenario_not_validation'), company_revision: z.number().int().min(0), company_state_sha256: hash, input_sha256: hash, horizon_days: z.number().int().min(1).max(365), assumptions: z.array(assumptionSchema), trajectories: z.tuple([trajectorySchema, trajectorySchema, trajectorySchema]),
  formulas: z.array(z.strictObject({ metric: z.string(), expression: z.literal('end = baseline * (1 + delta_percent / 100)'), baseline_input: decimal, assumption: z.string().nullable() })),
  sensitivity: z.array(z.strictObject({ assumption: z.string(), target_metric: z.string(), delta_range_percent: decimal })),
  constraint_findings: z.array(z.strictObject({ constraint: z.string(), label: z.enum(['low', 'base', 'high']), metric: z.string(), operator: z.enum(['minimum', 'maximum']), threshold: decimal, actual: decimal, unit: z.string(), violated: z.boolean() })), result_sha256: hash,
}).refine(value => value.trajectories.map(item => item.label).join(',') === 'low,base,high', 'Expected low, base, and high trajectories');
const workspaceReviewResultSchema = z.strictObject({ action_kind: z.literal('workspace_review'), company_id: uuid, revision: z.number().int().min(0), artifact_count: z.number().int().min(0), source_count: z.number().int().min(0), unverified_claim_count: z.number().int().min(0), evidence_gaps: z.array(z.enum(['no_company_artifacts', 'unverified_claims'])).max(2) });
const scenarioRecomputeResultSchema = scenarioResultSchema.extend({ action_kind: z.literal('scenario_recompute'), scenario_id: uuid });
const scheduleRunBase = { schedule_id: uuid, scheduled_for: z.number() };
const scheduleRunSchema = z.discriminatedUnion('status', [
  z.strictObject({ ...scheduleRunBase, status: z.literal('completed'), result: z.union([workspaceReviewResultSchema, scenarioRecomputeResultSchema]), error_code: z.null() }),
  z.strictObject({ ...scheduleRunBase, status: z.literal('failed'), result: z.null(), error_code: z.string().min(1) }),
  z.strictObject({ ...scheduleRunBase, status: z.literal('skipped'), result: z.null(), error_code: z.string().min(1) }),
]);

export type LearningRecord = z.infer<typeof learningRecordSchema>;
export type Schedule = z.infer<typeof scheduleSchema>;
export type ScheduleRun = z.infer<typeof scheduleRunSchema>;
export type ScenarioDefinition = z.infer<typeof scenarioDefinitionSchema>;
export type ScenarioResult = z.infer<typeof scenarioResultSchema>;
export type ScenarioCreate = Omit<ScenarioDefinition, 'scenario_id' | 'workspace_id' | 'company_id' | 'created_by' | 'input_sha256'>;
type ScheduleCreateBase = { readonly cadence: 'once' | 'daily' | 'weekly'; readonly timezone: string; readonly first_run_at: string; readonly pinned_revision: number };
export type ScheduleCreate = ScheduleCreateBase & ({ readonly action_kind: 'workspace_review'; readonly payload: Readonly<Record<string, never>> } | { readonly action_kind: 'scenario_recompute'; readonly payload: { readonly scenario_id: string } });

export class FounderOperationsError extends Error {
  readonly name = 'FounderOperationsError';
  constructor(readonly status: number, message: string) { super(message); }
}
const base = '/api/agentos/samurai/workspaces';
async function request<T>(path: string, schema: z.ZodType<T>, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${base}${path}`, { ...init, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Samurai-Client': '1', ...init.headers } });
  const value: unknown = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    const detail = z.strictObject({ detail: z.string() }).safeParse(value);
    throw new FounderOperationsError(response.status, detail.success ? detail.data.detail : `Request failed (${response.status}).`);
  }
  return schema.parse(value);
}
const scope = (workspaceId: string, companyId?: string) => `/${uuid.parse(workspaceId)}${companyId ? `/companies/${uuid.parse(companyId)}` : ''}`;
export const listLearning = (workspaceId: string, companyId: string) => request(`${scope(workspaceId)}/learning?company_id=${uuid.parse(companyId)}`, learningContextSchema, { method: 'GET' });
export const createLearning = (workspaceId: string, body: { readonly company_id: string; readonly kind: 'preference' | 'correction'; readonly source_revision: number; readonly founder_text: string; readonly shared: boolean }) => request(`${scope(workspaceId)}/learning`, learningRecordSchema, { method: 'POST', body: JSON.stringify(body) });
export const supersedeLearning = (workspaceId: string, learningId: string, body: { readonly company_id: string; readonly source_revision: number; readonly founder_text: string; readonly shared: boolean }) => request(`${scope(workspaceId)}/learning/${uuid.parse(learningId)}/supersede`, learningRecordSchema, { method: 'POST', body: JSON.stringify(body) });
export const listSchedules = (workspaceId: string) => request(`${scope(workspaceId)}/schedules`, z.array(scheduleSchema).max(100), { method: 'GET' });
export const createSchedule = (workspaceId: string, companyId: string, body: ScheduleCreate) => request(`${scope(workspaceId, companyId)}/schedules`, scheduleSchema, { method: 'POST', body: JSON.stringify(body) });
export const disableSchedule = (workspaceId: string, scheduleId: string) => request(`${scope(workspaceId)}/schedules/${uuid.parse(scheduleId)}`, z.null(), { method: 'DELETE' });
export const listScheduleRuns = (workspaceId: string, scheduleId: string) => request(`${scope(workspaceId)}/schedules/${uuid.parse(scheduleId)}/runs`, z.array(scheduleRunSchema).max(50), { method: 'GET' });
export const listScenarios = (workspaceId: string, companyId: string) => request(`${scope(workspaceId, companyId)}/scenarios`, z.array(scenarioDefinitionSchema).max(50), { method: 'GET' });
export const createScenario = (workspaceId: string, companyId: string, body: ScenarioCreate) => request(`${scope(workspaceId, companyId)}/scenarios`, scenarioDefinitionSchema, { method: 'POST', body: JSON.stringify(body), headers: { 'X-Samurai-Submission-Id': crypto.randomUUID() } });
export const runScenario = (workspaceId: string, companyId: string, scenarioId: string) => request(`${scope(workspaceId, companyId)}/scenarios/${uuid.parse(scenarioId)}/runs`, scenarioResultSchema, { method: 'POST', body: '{}', headers: { 'X-Samurai-Submission-Id': crypto.randomUUID() } });
export const getScenarioResult = (workspaceId: string, companyId: string, scenarioId: string) => request(`${scope(workspaceId, companyId)}/scenarios/${uuid.parse(scenarioId)}/result`, scenarioResultSchema.nullable(), { method: 'GET' });
export function scenarioPanel(definition: ScenarioDefinition, result: ScenarioResult): Panel {
  return panelSchema.parse({ id: `scenario-${definition.scenario_id}`, kind: 'scenario', title: definition.title, note: 'Synthetic scenario · Explore assumptions, not observed demand', provenance: { label: result.provenance, company_revision: result.company_revision, company_state_sha256: result.company_state_sha256, input_sha256: result.input_sha256, result_sha256: result.result_sha256 }, synthetic_label: result.provenance, company_revision: result.company_revision, result_sha256: result.result_sha256, horizon_days: result.horizon_days, assumptions: result.assumptions, trajectories: result.trajectories, formulas: result.formulas, constraints: result.constraint_findings });
}
