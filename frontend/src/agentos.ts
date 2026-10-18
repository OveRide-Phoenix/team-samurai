import { z } from 'zod';
import { ideaAnalysisSchema } from './ideaAnalysis';
import type { IdeaArea } from './aspectState';
import { companyActionIdSchema, companyActionSchema, agents, panelSchema, teamAreaSchema, type BackendRun, type EvidenceSource, type Message, type Panel, type TeamArea, type WorkEvent } from './model';

const base = '/api/agentos/agents/samurai/runs';
const headers = { 'X-Samurai-Client': '1' } as const;
const limit = 2_000_000;
const htmlTag = /<\/?[a-z][a-z0-9:-]*(?=[\s/>])|<[^>]*\bon[a-z][a-z0-9:-]*\s*=/i;
const text = z.string().min(1).max(20_000).refine(value => !htmlTag.test(value), 'HTML markup is not allowed in AgentOS text.');
const strings = z.array(text).max(100);
const uuid = z.string().uuid();
const date = z.string().datetime({ offset: true });
const outcome = z.enum(['verified', 'needs_input', 'needs_rework', 'insufficient_evidence', 'draft_only', 'requires_metrics', 'based_on_founder_supplied_metrics']);
const roles = z.enum(['intake', 'researcher', 'strategist', 'product_manager', 'builder', 'marketer', 'sales', 'analyst', 'verifier']);
const frameworkMetadata = z.strictObject({
  id: z.enum(['founder_truth', 'offer_diagnostic']), version: z.string().regex(/^\d+\.\d+\.\d+$/),
  source_repository: z.string().regex(/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/), source_revision: z.string().regex(/^[0-9a-f]{40}$/),
  source_url: z.string().url().refine(value => value.startsWith('https://github.com/')), license: z.literal('MIT'), attribution: text,
  allowed_roles: z.array(z.enum(['intake', 'strategist', 'verifier'])).min(1).max(3), sha256: z.string().regex(/^[0-9a-f]{64}$/), review_date: z.iso.date(),
}).refine(value => value.source_url.replace(/\/$/, '') === `https://github.com/${value.source_repository}/tree/${value.source_revision}`
  && new Set(value.allowed_roles).size === value.allowed_roles.length);
const assumption = z.strictObject({ assumption_id: uuid, text });
const offerDiagnostic = z.strictObject({
  market: text, painful_problem: text, purchasing_power_assumption: assumption, draft_offer: text, evidence_needed: strings.min(1), framework: frameworkMetadata,
}).refine(value => value.framework.id === 'offer_diagnostic' && value.framework.allowed_roles.includes('strategist'));
const founderKnownFact = z.strictObject({
  text, basis: z.enum(['founder_context', 'retained_evidence']), context_key: z.enum(['idea', 'target_customer', 'geography', 'budget', 'founder_skills', 'goal', 'supplied_context']).nullable().default(null), evidence_ids: z.array(uuid).max(100).default([]),
}).refine(value => (value.basis === 'founder_context' ? value.context_key !== null && value.evidence_ids.length === 0 : value.context_key === null && value.evidence_ids.length > 0)
  && new Set(value.evidence_ids).size === value.evidence_ids.length);
const founderTruth = z.strictObject({
  known: z.array(founderKnownFact).max(100).default([]), believed: strings.default([]), hoped: strings.default([]), evidence_gaps: strings.default([]), bottleneck: text.nullable().default(null), next_decision: text.nullable().default(null),
}).refine(value => {
  const statements = [...value.known.map(item => item.text), ...value.believed, ...value.hoped].map(item => item.toLocaleLowerCase());
  return statements.length === new Set(statements).size;
});
const brief = z.strictObject({ idea: text, target_customer: text.nullable(), geography: text.nullable(), budget: text.nullable(), founder_skills: text.nullable(), goal: text.nullable(), supplied_context: strings, assumptions: strings, open_questions: strings, next_actions: strings });
const publicUrl = z.string().url().refine(value => /^https?:\/\//.test(value));
const sourceAdjudication = z.strictObject({
  research_artifact_id: uuid, research_revision: z.number().int().min(1), claim_id: uuid, claim_text: text, source_id: uuid, source_url: publicUrl,
  attempted_at: date, fetched_at: date.nullable().default(null), final_url: publicUrl.nullable().default(null), content_sha256: z.string().regex(/^[0-9a-f]{64}$/).nullable().default(null), media_type: z.string().min(1).max(200).nullable().default(null),
  evidence_quote: z.string().max(500), verdict: z.enum(['supported', 'contradicted', 'insufficient', 'inaccessible']), rationale: z.string().min(1).max(2000),
}).refine(value => {
  const fetched = [value.fetched_at, value.final_url, value.content_sha256, value.media_type];
  const hasFetched = fetched.every(Boolean), hasNoFetched = fetched.every(value => value === null);
  if (value.fetched_at !== null && new Date(value.fetched_at).getTime() < new Date(value.attempted_at).getTime()) return false;
  if (value.verdict === 'inaccessible') return hasNoFetched && value.evidence_quote === '';
  if (value.verdict === 'insufficient') return hasFetched && value.evidence_quote === '';
  return hasFetched && value.evidence_quote.trim().length > 0;
});
const researchPayload = z.strictObject({
  artifact_type: z.literal('research'), summary: text, conflicts: strings,
  adjudicated_from_artifact_id: uuid.nullable().optional(), adjudicated_from_revision: z.number().int().min(1).nullable().optional(), adjudications: z.array(sourceAdjudication).max(100).optional(),
}).refine(value => {
  const adjudications = value.adjudications ?? [];
  const hasAdjudication = value.adjudicated_from_artifact_id !== undefined && value.adjudicated_from_artifact_id !== null || value.adjudicated_from_revision !== undefined && value.adjudicated_from_revision !== null || adjudications.length > 0;
  return !hasAdjudication || (value.adjudicated_from_artifact_id !== undefined && value.adjudicated_from_artifact_id !== null && value.adjudicated_from_revision !== undefined && value.adjudicated_from_revision !== null && adjudications.every(item => item.research_artifact_id === value.adjudicated_from_artifact_id && item.research_revision === value.adjudicated_from_revision));
});
export const verificationPayloadSchema = z.strictObject({ artifact_type: z.literal('verification'), checked_artifact_ids: z.array(uuid).min(1).max(100), outcome: z.enum(['verified', 'needs_input', 'needs_rework']) });
const payload = z.discriminatedUnion('artifact_type', [
  z.strictObject({ artifact_type: z.literal('intake'), brief, founder_truth: founderTruth.optional(), frameworks: z.array(frameworkMetadata).max(2).optional(), idea_analysis: ideaAnalysisSchema.nullable().optional() }),
  researchPayload,
  z.strictObject({ artifact_type: z.literal('strategy'), ideal_customer_profile: text, positioning: text, offer: text, pricing_assumptions: strings, offer_diagnostic: offerDiagnostic.nullable().optional() }),
  z.strictObject({ artifact_type: z.literal('product_plan'), minimum_viable_offering: strings, delivery_requirements: strings, user_stories: strings, roadmap: strings }),
  z.strictObject({ artifact_type: z.literal('builder_draft'), architecture: strings, database_schema: strings, apis: strings, user_interface: strings, deployment_configuration: strings }),
  z.strictObject({ artifact_type: z.literal('marketing_draft'), landing_page: text, ads: strings, social_posts: strings, emails: strings }),
  z.strictObject({ artifact_type: z.literal('sales_draft'), prospect_criteria: strings, outreach: strings, scripts: strings, objection_handling: strings }),
  z.strictObject({ artifact_type: z.literal('analysis'), metric_ids: z.array(uuid).min(1).max(100), findings: strings, recommendations: strings, basis: z.enum(['connected_measurements', 'based_on_founder_supplied_metrics']) }),
  verificationPayloadSchema,
]).refine(value => value.artifact_type !== 'intake' || value.frameworks === undefined || (value.frameworks.length === 1
  && value.frameworks[0]?.id === 'founder_truth' && value.frameworks[0].allowed_roles.includes('intake')));
const source = z.strictObject({ source_id: uuid, url: publicUrl, title: text, retrieved_at: date, search_query: text, excerpt: z.string().min(1).max(2000) });
const knowledgeReference = z.strictObject({
  chunk_id: uuid, file_id: uuid.nullable().default(null), artifact_id: uuid.nullable().default(null), indexed_revision: z.number().int().min(0), ordinal: z.number().int().min(0),
  content_sha256: z.string().regex(/^[0-9a-f]{64}$/), trust_class: z.enum(['accepted_artifact', 'uploaded_file']), evidence_status: z.literal('untrusted_context'),
}).refine(value => value.trust_class === 'uploaded_file'
  ? value.file_id !== null && value.artifact_id === null
  : value.artifact_id !== null && value.file_id === null);
const metric = z.strictObject({ metric_id: uuid, name: text, value: z.number().finite(), unit: text, window_start: date, window_end: date, source_label: text, collected_at: date, provenance: z.enum(['connected_measurement', 'founder_supplied', 'demo_fixture']), trusted_connector_receipt: text.nullable().default(null) }).refine(value => Date.parse(value.window_end) > Date.parse(value.window_start) && ((value.provenance === 'connected_measurement') === Boolean(value.trusted_connector_receipt)));
const artifact = z.strictObject({
  artifact_id: uuid, company_id: uuid, artifact_type: text, revision: z.number().int().min(1), input_revision: z.number().int().min(0), producer: roles,
  status: z.enum(['complete', 'insufficient_evidence', 'needs_input', 'needs_rework', 'draft_only', 'requires_metrics', 'based_on_founder_supplied_metrics']), acceptance_status: z.enum(['pending', 'accepted']).default('pending'), payload,
  founder_statements: z.array(z.strictObject({ statement_id: uuid, text })).max(100).default([]), sources: z.array(source).max(100).default([]),
  knowledge_references: z.array(knowledgeReference).max(5).refine(value => new Set(value.map(item => item.chunk_id)).size === value.length).optional(),
  claims: z.array(z.strictObject({ claim_id: uuid, text, source_ids: z.array(uuid).min(1).max(100), support_status: z.enum(['mapped', 'unmapped']), support_segments: strings, verification_status: z.enum(['unverified', 'supported', 'contradicted']) }).refine(value => value.support_status !== 'mapped' || value.support_segments.length > 0)).max(100).default([]),
  measurements: z.array(metric).max(100).default([]), assumptions: z.array(assumption).max(100),
  verification_findings: z.array(z.strictObject({ code: text, message: text, severity: z.enum(['info', 'warning', 'error']) })).min(1).max(100),
}).refine(value => value.artifact_type === value.payload.artifact_type && value.claims.every(claim => claim.source_ids.every(id => value.sources.some(item => item.source_id === id))) && value.measurements.every(item => item.provenance !== 'connected_measurement')).refine(value => {
  if (value.payload.artifact_type !== 'analysis') return true;
  const ids = value.payload.metric_ids;
  return value.payload.basis === 'based_on_founder_supplied_metrics' && value.status === 'based_on_founder_supplied_metrics' && ids.length === new Set(ids).size && value.measurements.length === ids.length && new Set(value.measurements.map(item => item.metric_id)).size === ids.length && value.measurements.every(item => ids.includes(item.metric_id) && item.provenance === 'founder_supplied');
}).refine(value => {
  if (value.payload.artifact_type !== 'research') return true;
  const research = value.payload;
  if (research.adjudicated_from_artifact_id === null || research.adjudicated_from_artifact_id === undefined) return true;
  const adjudications = research.adjudications ?? [];
  const claims = new Map(value.claims.map(claim => [claim.claim_id, claim]));
  const sources = new Map(value.sources.map(entry => [entry.source_id, entry]));
  const expected = new Set(value.claims.flatMap(claim => claim.source_ids.map(sourceId => `${claim.claim_id}:${sourceId}`)));
  const actual = adjudications.map(item => `${item.claim_id}:${item.source_id}`);
  return actual.length === new Set(actual).size && actual.length === expected.size && actual.every(pair => expected.has(pair)) && adjudications.every(item => {
    const claim = claims.get(item.claim_id), source = sources.get(item.source_id);
    const sameFetch = adjudications.filter(other => other.source_id === item.source_id).every(other => other.fetched_at === item.fetched_at && other.final_url === item.final_url && other.content_sha256 === item.content_sha256 && other.media_type === item.media_type);
    return claim?.text === item.claim_text && claim.source_ids.includes(item.source_id) && source?.url === item.source_url && sameFetch && (item.verdict === 'supported' || item.verdict === 'contradicted' ? source.excerpt.includes(item.evidence_quote) : true);
  }) && value.claims.every(claim => {
    const verdicts = adjudications.filter(item => item.claim_id === claim.claim_id).map(item => item.verdict);
    const expectedStatus = verdicts.includes('contradicted') ? 'contradicted' : verdicts.includes('supported') ? 'supported' : 'unverified';
    return claim.verification_status === expectedStatus;
  });
});
const resultSchema = z.strictObject({ company_id: uuid, revision: z.number().int().min(0), outcome, artifacts: z.array(artifact).max(100).default([]), questions: z.array(z.string().min(1).max(200)).max(100).default([]) }).refine(value => (value.outcome === 'needs_input') === (value.questions.length > 0) && value.artifacts.every(item => item.company_id === value.company_id && item.revision <= value.revision));
const learningRecord = z.strictObject({
  learning_id: uuid, workspace_id: uuid, user_id: z.string(), company_id: uuid, kind: z.enum(['preference', 'correction']), source_revision: z.number().int().min(0),
  founder_text: z.string().min(1).max(2000), created_by: z.string(), audit_sha256: z.string().regex(/^[a-f0-9]{64}$/), shared: z.boolean(), superseded_by: uuid.nullable(), active: z.boolean(), created_at: z.number().int().min(0), evidence_status: z.literal('untrusted_preference_context'),
});
const emptyLearningContext = { context_boundary: 'untrusted_preference_context' as const, records: [] };
const learningContext = z.strictObject({ context_boundary: z.literal('untrusted_preference_context'), records: z.array(learningRecord).max(20) }).default(emptyLearningContext);
const summarySchema = z.strictObject({
  current_artifact_ids: z.array(uuid).max(100).nullable().default(null),
  actions: z.array(companyActionSchema).max(9).default([]), next_action: companyActionIdSchema.nullable().default(null),
  company_id: uuid.nullable(), revision: z.number().int().min(0), artifact_count: z.number().int().min(0), status: z.enum(['active', 'not_started']),
  brief: brief.nullable().default(null), sources: z.array(source).max(100).default([]), evidence_conflicts: strings.default([]),
  verification_findings: z.array(z.strictObject({ code: text, message: text, severity: z.enum(['info', 'warning', 'error']) })).max(100).default([]),
  next_decision: text.nullable().default(null), founder_truth: founderTruth.optional(), artifacts: z.array(artifact).max(20).default([]), frameworks: z.array(frameworkMetadata).max(2).default([]), learning_context: learningContext,
}).refine(value => value.artifacts.every(item => item.company_id === value.company_id && item.revision <= value.revision)
  && new Set(value.frameworks.map(item => item.id)).size === value.frameworks.length);
export const companyResultSchema = z.union([resultSchema, summarySchema]);
type WorkflowResult = z.infer<typeof companyResultSchema>;
type FrameworkMetadata = z.infer<typeof frameworkMetadata>;
type FounderTruth = z.infer<typeof founderTruth>;
type StandardPanel = Exclude<Panel, { kind: 'custom' | 'declarative' }>;

function founderContext(truth: FounderTruth, framework?: FrameworkMetadata): NonNullable<StandardPanel['founder_context']> {
  return {
    next_decision: truth.next_decision,
    evidence_gaps: truth.evidence_gaps,
    ...(framework ? { framework: { id: framework.id, version: framework.version, attribution: framework.attribution, source_repository: framework.source_repository, source_revision: framework.source_revision, source_url: framework.source_url } } : {}),
  };
}

function truthClaims(id: string, truth: FounderTruth): Extract<Panel, { kind: 'evidence' }>['claims'] {
  return [
    ...truth.known.map((item, index) => ({ id: `${id}-known-${index}`, claim: `Known: ${item.text}`, status: 'hypothesis' as const, detail: item.basis === 'founder_context' ? 'Founder context, not market evidence' : 'Retained evidence reference; review source support', sources: [] })),
    ...truth.believed.map((item, index) => ({ id: `${id}-believed-${index}`, claim: `Believed: ${item}`, status: 'hypothesis' as const, detail: 'Founder belief, not market evidence', sources: [] })),
    ...truth.hoped.map((item, index) => ({ id: `${id}-hoped-${index}`, claim: `Hoped: ${item}`, status: 'hypothesis' as const, detail: 'Founder hope, not market evidence', sources: [] })),
    ...(truth.bottleneck ? [{ id: `${id}-bottleneck`, claim: `Current bottleneck: ${truth.bottleneck}`, status: 'needs-check' as const, detail: 'Founder assessment; review before acting', sources: [] }] : []),
  ];
}
function knowledgeSources(references: z.infer<typeof knowledgeReference>[]): EvidenceSource[] {
  return references.map(reference => {
    if (reference.trust_class === 'uploaded_file') {
      if (reference.file_id === null || reference.artifact_id !== null) throw new AgentosError('protocol', 'AgentOS returned invalid knowledge provenance.');
      return { kind: 'workspace_file', file_id: reference.file_id, title: null, chunk_id: reference.chunk_id, indexed_revision: reference.indexed_revision, ordinal: reference.ordinal, content_sha256: reference.content_sha256, trust_class: 'uploaded_file', evidence_status: 'untrusted_context' };
    }
    if (reference.artifact_id === null || reference.file_id !== null) throw new AgentosError('protocol', 'AgentOS returned invalid knowledge provenance.');
    return { kind: 'accepted_artifact', artifact_id: reference.artifact_id, chunk_id: reference.chunk_id, indexed_revision: reference.indexed_revision, ordinal: reference.ordinal, content_sha256: reference.content_sha256, trust_class: 'accepted_artifact', evidence_status: 'untrusted_context' };
  });
}
export const companySnapshotSchema = z.strictObject({ summary: summarySchema, artifacts: z.array(artifact).max(100) }).refine(value => value.summary.company_id !== null && value.artifacts.every(item => item.company_id === value.summary.company_id && item.revision <= value.summary.revision) && (value.summary.current_artifact_ids === null || value.summary.current_artifact_ids.every(id => value.artifacts.some(item => item.artifact_id === id))));
type CompanySnapshot = z.infer<typeof companySnapshotSchema>;

export type AgentosRun = BackendRun;
export type AgentosApproval = {
  readonly operation: 'journey' | 'launch_drafts' | 'metrics_analysis';
  readonly stage: 'brief' | 'research' | 'strategy' | 'plan' | 'verify';
  readonly expectedRevision: number;
  readonly teamArea?: TeamArea;
  readonly companyId: string;
};
export type ApprovedWorkDraft = { readonly text: string; readonly area: IdeaArea; readonly label: string; readonly approval: AgentosApproval };
export function editApprovedWorkDraft(draft: ApprovedWorkDraft | undefined, text: string, area: IdeaArea): ApprovedWorkDraft | undefined {
  return draft?.area === area ? { ...draft, text: text.trim() } : undefined;
}
export function approvedWorkForSubmission(draft: ApprovedWorkDraft | undefined, text: string, area: IdeaArea, companyId: string | undefined, revision: number | undefined): AgentosApproval | undefined {
  return draft && draft.text === text.trim() && draft.area === area && draft.approval.companyId === companyId && draft.approval.expectedRevision === revision ? draft.approval : undefined;
}
export type CopilotStart = (input: string, signal: AbortSignal, area?: TeamArea, approval?: AgentosApproval, submissionId?: string) => Promise<Response>;
type AgentosRunResult = { readonly run: AgentosRun; readonly events: readonly WorkEvent[] };
export class AgentosError extends Error {
  readonly name = 'AgentosError';
  constructor(readonly code: 'http' | 'protocol' | 'scope' | 'stream' | 'cancel' | 'storage' | 'admission', message: string) { super(message); }
}

export function admissionError(reason: 'daily' | 'queue' | 'rate'): AgentosError {
  const message = reason === 'daily' ? 'Daily AI allowance reached. Try again after 00:00 UTC.'
    : reason === 'queue' ? "Samurai's queue is full. Try again in a few minutes." : 'Samurai is receiving too many requests. Try again later.';
  return new AgentosError('admission', `${message} Your idea and answers are saved.`);
}

function json(value: string): unknown {
  if (value.length > limit) throw new AgentosError('protocol', 'AgentOS payload exceeds the size limit.');
  try { return JSON.parse(value); } catch (error) {
    if (error instanceof SyntaxError) throw new AgentosError('protocol', 'AgentOS returned malformed JSON.');
    throw error;
  }
}
function workflow(value: unknown): WorkflowResult | undefined {
  if (typeof value === 'string') {
    const marker = '\nSAMURAI_WORKFLOW_RESULT=';
    const index = value.lastIndexOf(marker);
    if (index >= 0) value = json(value.slice(index + marker.length));
    else if (value.trim().startsWith('{')) {
      value = json(value);
      const candidate = recordSchema.safeParse(value);
      if (candidate.success && !('outcome' in candidate.data) && !('artifact_count' in candidate.data)) return undefined;
    }
    else return undefined;
  }
  if (value === undefined || value === null) return undefined;
  const parsed = companyResultSchema.safeParse(value);
  if (!parsed.success) throw new AgentosError('protocol', 'AgentOS returned an invalid workflow result.');
  return parsed.data;
}

function resultEvents(result: WorkflowResult | CompanySnapshot, seen: Set<string>): WorkEvent[] {
  const events: WorkEvent[] = [];
  const summary = 'summary' in result ? result.summary : 'artifact_count' in result ? result : undefined;
  const artifacts = result.artifacts;
  if (summary) {
    const key = `summary:${summary.company_id}:${summary.revision}`;
    if (seen.has(key)) return events;
    seen.add(key);
    if (!summary.company_id) return [{ type: 'message', text: 'No company brief has been saved yet.' }];
    const id = `company-summary-${summary.company_id}`;
    const context = summary.brief;
    const fields = context ? [
      ['Idea', context.idea], ['First customers', context.target_customer], ['Market', context.geography],
      ['Budget', context.budget], ['Skills & resources', context.founder_skills], ['First milestone', context.goal],
      ['Supplied context', context.supplied_context.join('; ')], ['Assumptions', context.assumptions.join('; ')],
      ['Open questions', context.open_questions.join('; ')], ['Proposed next actions', context.next_actions.join('; ')],
    ] as const : [];
    const claims: Extract<Panel, { kind: 'evidence' }>['claims'] = fields.flatMap(([label, value], index) => value ? [{
      id: `${id}-context-${index}`, claim: `${label}: ${value}`, status: 'hypothesis' as const, detail: 'Founder supplied context, not market evidence', sources: [],
    }] : []);
    claims.push(...summary.evidence_conflicts.map((claim, index) => ({ id: `${id}-conflict-${index}`, claim, status: 'needs-check' as const, detail: 'warning: evidence_conflict', sources: [] })));
    claims.push(...summary.verification_findings.map((finding, index) => ({ id: `${id}-finding-${index}`, claim: finding.message, status: 'needs-check' as const, detail: `${finding.severity}: ${finding.code}`, sources: [] })));
    if (summary.sources.length) claims.push({ id: `${id}-sources`, claim: 'Retained research references', status: 'needs-check', detail: 'Source attachment does not independently verify a finding.', sources: summary.sources.map(entry => ({ kind: 'external' as const, title: entry.title, url: entry.url })) });
    if (summary.founder_truth) claims.push(...truthClaims(id, summary.founder_truth));
    events.push({ type: 'message', text: '', panel: panelSchema.parse({ id, kind: 'evidence', title: 'Company context', note: '', claims, ...(summary.founder_truth ? { founder_context: founderContext(summary.founder_truth) } : {}), provenance: summary }) });
  }
  for (const item of artifacts) {
    const key = `${item.artifact_id}:${item.revision}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const id = `artifact-${item.artifact_id}`;
    // Preserve the complete validated lineage even where the existing panel catalog has no dedicated field.
    const note = item.status === 'needs_rework' ? 'Some assumptions still need review.' : 'Draft — review before acting.';
    const data = item.payload;
    const panels: Panel[] = [];
    const knowledge = item.knowledge_references?.length ? { knowledge_sources: knowledgeSources(item.knowledge_references) } : {};
    if (data.artifact_type === 'intake') {
      const brief = data.brief;
      const fields = [['Idea', brief.idea], ['First customers', brief.target_customer], ['Market', brief.geography], ['Budget', brief.budget], ['Founder skills', brief.founder_skills], ['First milestone', brief.goal], ['Supplied context', brief.supplied_context.join('; ')], ['Assumptions', brief.assumptions.join('; ')], ['Open questions', brief.open_questions.join('; ')], ['Proposed next actions', brief.next_actions.join('; ')]] as const;
      const framework = data.frameworks?.[0];
      panels.push({ id, kind: 'evidence', title: 'Company brief', note: '', claims: [...fields.flatMap(([label, value], index) => value ? [{ id: `${id}-brief-${index}`, claim: `${label}: ${value}`, status: 'needs-check' as const, detail: 'Founder supplied context, not market evidence', sources: [] }] : []), ...(data.founder_truth ? truthClaims(id, data.founder_truth) : [])], ...(data.founder_truth ? { founder_context: founderContext(data.founder_truth, framework) } : {}) });
    } else if (data.artifact_type === 'strategy') {
      const diagnostic = data.offer_diagnostic;
      const diagnosticContext = diagnostic ? { next_decision: null, evidence_gaps: [...diagnostic.evidence_needed, `Purchasing power assumption: ${diagnostic.purchasing_power_assumption.text}`], framework: { id: diagnostic.framework.id, version: diagnostic.framework.version, attribution: diagnostic.framework.attribution, source_repository: diagnostic.framework.source_repository, source_revision: diagnostic.framework.source_revision, source_url: diagnostic.framework.source_url } } : undefined;
      panels.push({ id, kind: 'offer', title: 'Business offer', note, customer: data.ideal_customer_profile, promise: data.offer, price: data.pricing_assumptions[0] || 'No pricing assumption supplied', includes: [data.positioning], ...(diagnosticContext ? { founder_context: diagnosticContext } : {}) });
      if (data.pricing_assumptions.length) panels.push({ id: `${id}-pricing`, kind: 'pricing', title: 'Pricing assumptions', note, options: data.pricing_assumptions.map((price, index) => ({ name: `Assumption ${index + 1}`, price, description: '' })), ...(diagnosticContext ? { founder_context: { ...diagnosticContext, framework: undefined } } : {}) });
    } else if (data.artifact_type === 'product_plan') {
      panels.push({ id, kind: 'launch-plan', title: 'Minimum offering and delivery plan', note, tasks: [...data.minimum_viable_offering, ...data.delivery_requirements, ...data.user_stories, ...data.roadmap].map((title, index) => ({ id: `${id}-${index}`, title, owner: item.producer, timing: 'Not scheduled', detail: item.status })) });
    } else if (data.artifact_type === 'research' || data.artifact_type === 'verification') {
      const claims: Extract<Panel, { kind: 'evidence' }>['claims'] = item.claims.map(claim => ({ id: claim.claim_id, claim: claim.text, status: claim.verification_status === 'supported' && claim.support_status === 'mapped' ? 'supported' : 'needs-check', detail: `${claim.verification_status}; ${claim.support_status}. ${claim.support_segments.join('\n')}`, sources: item.sources.filter(entry => claim.source_ids.includes(entry.source_id)).map(entry => ({ kind: 'external' as const, title: entry.title, url: entry.url })) }));
      if (data.artifact_type === 'research' && data.summary && !claims.some(claim => claim.claim === data.summary)) claims.unshift({ id: `${id}-summary`, claim: data.summary, status: 'hypothesis', detail: 'Research summary; see individual source-backed findings', sources: [] });
      if (data.artifact_type === 'research') claims.push(...data.conflicts.map((claim, index) => ({ id: `${id}-conflict-${index}`, claim, status: 'needs-check' as const, detail: 'warning: research_conflict', sources: [] })));
      claims.push(...item.assumptions.map(entry => ({ id: entry.assumption_id, claim: entry.text, status: 'hypothesis' as const, detail: 'Assumption, not sourced fact', sources: [] })));
      claims.push(...item.verification_findings.map((finding, index) => ({ id: `${id}-finding-${index}`, claim: finding.message, status: 'needs-check' as const, detail: `${finding.severity}: ${finding.code}`, sources: [] })));
        panels.push({ id, kind: 'evidence', title: data.artifact_type === 'research' ? 'Research evidence' : 'Verification review', note, claims });
    }
    if (!panels.length) {
      const entries: readonly [string, unknown][] = Object.entries(data);
      const drafts = entries.filter(([field]) => !['artifact_type', 'metric_ids', 'basis'].includes(field)).flatMap(([field, value]) => {
        const values = typeof value === 'string' ? [value] : Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === 'string') : [];
        return values.map(value => `${field.replaceAll('_', ' ')}: ${value}`);
      });
      panels.push({ id, kind: 'evidence', title: data.artifact_type === 'builder_draft' ? 'Build draft' : data.artifact_type === 'marketing_draft' ? 'Marketing drafts' : data.artifact_type === 'sales_draft' ? 'Sales drafts' : 'Performance review', note, claims: drafts.map((claim, index) => ({ id: `${id}-draft-${index}`, claim, status: 'needs-check', detail: data.artifact_type === 'analysis' ? 'Based on founder supplied measurements; review before acting' : 'Generated draft; not sent, published or executed', sources: [] })) });
    }
    for (const panel of panels) events.push({ type: 'message', text: '', panel: panelSchema.parse({ ...panel, ...knowledge, ...(data.artifact_type === 'intake' && data.idea_analysis ? { idea_analysis: data.idea_analysis } : {}), provenance: item }) });
  }
  const outcomeKey = 'outcome' in result ? `outcome:${result.company_id}:${result.revision}:${result.outcome}` : '';
  if ('outcome' in result && result.outcome === 'insufficient_evidence' && !seen.has(outcomeKey)) {
    seen.add(outcomeKey);
    events.push(
      { type: 'activity', agent: 'Researcher', state: 'waiting', detail: 'Research finished without sufficient source evidence.' },
      { type: 'activity', agent: 'Verifier', state: 'waiting', detail: 'Evidence review blocked: source support is missing.' },
      { type: 'activity', agent: 'Strategist', state: 'waiting', detail: 'Waiting for source evidence before strategy can start.' },
    );
  }
  const questionsKey = 'questions' in result ? `questions:${JSON.stringify(result.questions)}` : '';
  if ('questions' in result && result.questions.length && !seen.has(questionsKey)) {
    seen.add(questionsKey);
    events.push({ type: 'message', text: result.questions.join('\n') });
  }
  return events;
}

export function companySnapshotEvents(snapshot: unknown, companyId: string): WorkEvent[] {
  const expectedCompanyId = uuid.parse(companyId);
  const result = companySnapshotSchema.safeParse(snapshot);
  if (!result.success || result.data.summary.company_id !== expectedCompanyId) {
    throw new AgentosError('scope', 'The company snapshot does not match the selected company.');
  }
  return resultEvents(result.data, new Set());
}

// Agno adds versioned metadata to envelopes; project only consumed fields, then validate strictly.
const envelopeSchema = z.strictObject({ event: text, run_id: text, session_id: text, agent_id: z.literal('samurai'), event_index: z.number().int().min(0).optional(), content: z.unknown().optional(), tool: z.unknown().optional(), kind: z.string().optional() });
const recordSchema = z.record(z.string(), z.unknown());
const relevant = new Set(['RunStarted', 'ToolCallCompleted', 'CustomEvent', 'RunCompleted', 'RunCancelled', 'RunError']);
function envelope(raw: string) {
  const value = recordSchema.parse(json(raw));
  if (typeof value.event !== 'string' || !relevant.has(value.event)) return undefined;
  const parsed = envelopeSchema.safeParse({ event: value.event, run_id: value.run_id, session_id: value.session_id, agent_id: value.agent_id, event_index: value.event_index, content: value.content, tool: value.tool, kind: value.kind });
  if (!parsed.success) throw new AgentosError('protocol', 'AgentOS returned an invalid event envelope.');
  return parsed.data;
}
function progressEvent(content: unknown): Extract<WorkEvent, { type: 'activity' }> | undefined {
  if (typeof content !== 'string') {
    const parsed = z.strictObject({ kind: z.literal('workflow_progress'), detail: z.string().max(2000) }).safeParse(content);
    if (!parsed.success) return undefined;
    content = parsed.data.detail;
  }
  if (typeof content !== 'string' || content.length > 2000) return undefined;
  const agent = agents.find(name => new RegExp(`^${name}\\b`, 'i').test(content))
    ?? (/^Research (started|completed)\b/i.test(content) ? 'Researcher'
      : /^Strategy (started|completed)\b/i.test(content) ? 'Strategist'
        : /^Verify (brief|evidence|journey) (started|completed)\b/i.test(content) ? 'Verifier' : undefined);
  return agent ? { type: 'activity', agent, state: /\b(completed|finished|done)\b/i.test(content) ? 'done' : 'working', detail: content } : undefined;
}
async function* frames(body: ReadableStream<Uint8Array>): AsyncIterable<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let buffer = '', bytes = 0;
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) { buffer += decoder.decode(); break; }
      bytes += part.value.byteLength;
      if (bytes > limit) throw new AgentosError('stream', 'AgentOS stream exceeds the size limit.');
      buffer += decoder.decode(part.value, { stream: true });
      let boundary = /\r?\n\r?\n/.exec(buffer);
      while (boundary) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const data = frame.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).replace(/^ /, '')).join('\n');
        if (data) yield data;
        boundary = /\r?\n\r?\n/.exec(buffer);
      }
    }
    if (buffer.trim()) throw new AgentosError('stream', 'AgentOS stream ended inside an event.');
  } finally { await reader.cancel(); reader.releaseLock(); }
}
async function request(url: string, options: RequestInit): Promise<Response> {
  const response = await fetch(url, { ...options, credentials: 'same-origin', headers: { ...headers, ...options.headers } });
  if (response.status === 429) {
    const result = z.object({ detail: z.string() }).safeParse(await response.json().catch(() => null));
    const detail = result.success ? result.data.detail : '';
    throw admissionError(detail === 'Guest daily usage limit reached. Try again tomorrow (UTC).' ? 'daily' : detail === "Samurai's execution queue is full." ? 'queue' : 'rate');
  }
  if (!response.ok) throw new AgentosError('http', `AgentOS request failed (${response.status}).`);
  return response;
}

const receiptSchema = z.strictObject({
  run_id: text, session_id: text,
  status: z.enum(['PENDING', 'RUNNING', 'PAUSED', 'COMPLETED', 'ERROR', 'CANCELLED']),
  attempt: z.number().int().min(0), max_attempts: z.number().int().min(1), recovering: z.boolean(),
  failure_reason: z.string().max(2000).nullable(), company_id: uuid.nullable(), revision: z.number().int().min(0).nullable(), updated_at: z.number().int().nullable(),
});

function receiptRun(submissionId: string, value: z.infer<typeof receiptSchema>): AgentosRun {
  const status: AgentosRun['status'] = value.status === 'PENDING' ? (value.recovering ? 'recovering' : 'queued')
    : value.status === 'RUNNING' ? 'running' : value.status === 'PAUSED' ? 'paused'
      : value.status === 'COMPLETED' ? 'completed' : value.status === 'CANCELLED' ? 'cancelled' : 'failed';
  return { submissionId, runId: value.run_id, status, attempt: value.attempt, maxAttempts: value.max_attempts, ...(value.failure_reason ? { failureReason: value.failure_reason } : {}), ...(value.company_id ? { companyId: value.company_id } : {}), ...(value.revision !== null ? { revision: value.revision } : {}) };
}

export async function readAgentosReceipt(sessionId: string, submissionId: string, signal?: AbortSignal): Promise<AgentosRun> {
  text.parse(sessionId); uuid.parse(submissionId);
  const response = await request(`/api/agentos/work-receipts/${encodeURIComponent(submissionId)}?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET', signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15_000)]) : AbortSignal.timeout(15_000) });
  const receipt = receiptSchema.parse(json(await response.text()));
  if (receipt.session_id !== sessionId) throw new AgentosError('scope', 'AgentOS returned another session receipt.');
  return receiptRun(submissionId, receipt);
}

function resumeRequest(sessionId: string, runId: string, lastEventIndex: number | undefined, signal: AbortSignal): Promise<Response> {
  const form = new FormData();
  form.set('session_id', sessionId);
  if (lastEventIndex !== undefined) form.set('last_event_index', String(lastEventIndex));
  return request(`${base}/${encodeURIComponent(runId)}/resume`, { method: 'POST', body: form, signal });
}

export async function* resumeAgentosRun(
  sessionId: string,
  saved: AgentosRun,
  signal: AbortSignal,
  onRun?: (run: AgentosRun) => unknown,
  savedMessages: readonly Message[] = [],
): AsyncGenerator<WorkEvent> {
  text.parse(sessionId);
  let run = saved;
  if (run.submissionId) {
    const receipt = await readAgentosReceipt(sessionId, run.submissionId, signal);
    if (run.runId && receipt.runId && run.runId !== receipt.runId) throw new AgentosError('scope', 'The work receipt belongs to another run.');
    run = { ...run, ...receipt, submissionId: run.submissionId };
    onRun?.(run);
  } else if (!run.runId) {
    throw new AgentosError('protocol', 'The saved run has no recovery identity.');
  }
  if (!run.runId) throw new AgentosError('protocol', 'The work receipt omitted the run identity.');
  const runId = run.runId;
  if (['completed', 'cancelled', 'failed'].includes(run.status)) {
    const recovered = await readAgentosRun(sessionId, runId, signal, savedMessages);
    onRun?.({ ...run, ...recovered.run, submissionId: run.submissionId });
    for (const event of recovered.events) yield event;
    return;
  }
  if (run.status === 'paused') throw new AgentosError('stream', 'This run is paused and needs an approved recovery action before it can continue.');
  const seen = artifactKeys(savedMessages, runId);
  let companyId = run.companyId, revision = run.revision, lastEventIndex = run.lastEventIndex;
  let response = await resumeRequest(sessionId, runId, lastEventIndex, signal);
  while (true) {
    if (!response.body || !response.headers.get('content-type')?.includes('text/event-stream')) throw new AgentosError('protocol', 'AgentOS did not return an event stream.');
    const startingIndex = lastEventIndex;
    for await (const raw of frames(response.body)) {
      const event = envelope(raw);
      if (!event) continue;
      if (event.session_id !== sessionId || event.run_id !== runId) throw new AgentosError('scope', 'AgentOS returned an event for another session or run.');
      if (event.event_index !== undefined) {
        if (lastEventIndex !== undefined && event.event_index <= lastEventIndex) continue;
        lastEventIndex = event.event_index;
      }
      if (event.event === 'CustomEvent' && (event.kind === 'workflow_progress' || event.kind === undefined)) {
        const activity = progressEvent(event.content);
        if (activity) yield activity;
      }
      if (event.event === 'ToolCallCompleted' || event.event === 'RunCompleted') {
        const tool = event.tool === undefined ? undefined : recordSchema.parse(event.tool);
        const value = event.event === 'ToolCallCompleted' ? tool?.result : event.content;
        const view = presentation(value);
        const handoff = handoffEvents(value, seen);
        if (handoff) for (const output of handoff) yield output;
        if (view) for (const output of presentationEvents(view, seen)) yield output;
        const result = view || handoff ? undefined : workflow(value);
        if (result) {
          if (companyId && result.company_id && companyId !== result.company_id) throw new AgentosError('scope', 'AgentOS returned a result for another company.');
          companyId = result.company_id ?? companyId; revision = result.revision;
          for (const output of resultEvents(result, seen)) yield output;
        } else if (!view && !handoff && event.event === 'RunCompleted' && typeof event.content === 'string' && event.content.trim()) yield { type: 'message', text: event.content };
      }
      const next: AgentosRun = { ...run, runId, status: event.event === 'RunCompleted' ? 'completed' : event.event === 'RunCancelled' ? 'cancelled' : event.event === 'RunError' ? 'failed' : 'running', ...(companyId ? { companyId } : {}), ...(revision !== undefined ? { revision } : {}), ...(lastEventIndex !== undefined ? { lastEventIndex } : {}) };
      run = next; onRun?.(next);
      if (event.event === 'RunError') throw new AgentosError('stream', 'Samurai could not complete this run.');
      if (event.event === 'RunCompleted' || event.event === 'RunCancelled') return;
    }
    if (lastEventIndex === startingIndex) throw new AgentosError('stream', 'AgentOS disconnected without new recoverable events.');
    run = { ...run, status: 'recovering', lastEventIndex };
    onRun?.(run);
    response = await resumeRequest(sessionId, runId, lastEventIndex, signal);
  }
}


export async function cancelAgentosRun(sessionId: string, runId: string, savedMessages: readonly Message[] = []): Promise<AgentosRunResult> {
  text.parse(sessionId); text.parse(runId);
  const signal = AbortSignal.timeout(60_000);
  try {
    const response = await request(`${base}/${encodeURIComponent(runId)}/cancel?session_id=${encodeURIComponent(sessionId)}`, { method: 'POST', signal: AbortSignal.any([signal, AbortSignal.timeout(15_000)]) });
    const receipt = await response.text();
    if (receipt.trim()) z.strictObject({}).parse(json(receipt));
    // Cancellation receipts acknowledge intent; only the scoped stored run establishes completion.
    while (!signal.aborted) {
      const recovered = await readAgentosRun(sessionId, runId, signal, savedMessages);
      if (!['queued', 'running', 'recovering', 'paused'].includes(recovered.run.status)) return recovered;
      await new Promise<void>(resolve => setTimeout(resolve, 500));
    }
  } catch (error) {
    if (!signal.aborted) throw error;
  }
  throw new AgentosError('cancel', 'Stop has not been confirmed. This run may still be active; check again before starting another request.');
}

export function createAgentosTransport(
  sessionId: string,
  onRun?: (run: AgentosRun) => unknown,
  savedMessages: () => readonly Message[] = () => [],
  startOrCreateSubmissionId: CopilotStart | (() => string) = () => crypto.randomUUID(),
): (input: string, signal: AbortSignal, scope?: TeamArea | AgentosApproval) => AsyncIterable<WorkEvent> {
  text.parse(sessionId);
  const start = startOrCreateSubmissionId.length >= 2 ? startOrCreateSubmissionId as CopilotStart : undefined;
  const createSubmissionId = start ? () => crypto.randomUUID() : startOrCreateSubmissionId as () => string;
  let companyId: string | undefined;
  return async function* (input, signal, scope) {
    const approval = typeof scope === 'object' ? scope : undefined;
    const area = teamAreaSchema.safeParse(scope).data ?? approval?.teamArea;
    if (signal.aborted) throw new DOMException('Run was cancelled before starting.', 'AbortError');
    const submissionId = uuid.parse(createSubmissionId());
    if (onRun?.({ submissionId, status: 'submitting', area: area ?? 'overview' }) === false) throw new AgentosError('storage', 'The run was not started because its recovery receipt could not be saved.');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 600_000);
    let runId: string | undefined, revision: number | undefined, lastEventIndex: number | undefined;
    let status: AgentosRun['status'] = 'submitting';
    let terminal = false;
    let cancellation: Promise<AgentosRunResult> | undefined;
    const notify = (nextStatus: AgentosRun['status'], failureReason?: string) => {
      status = nextStatus;
      onRun?.({ submissionId, status, area: area ?? 'overview', ...(failureReason ? { failureReason } : {}), ...(runId ? { runId } : {}), ...(companyId ? { companyId } : {}), ...(revision !== undefined ? { revision } : {}), ...(lastEventIndex !== undefined ? { lastEventIndex } : {}) });
    };
    const cancel = () => {
      if (!runId || terminal || cancellation) return;
      cancellation = cancelAgentosRun(sessionId, runId, savedMessages()).then(recovered => {
        if (companyId && recovered.run.companyId && companyId !== recovered.run.companyId) throw new AgentosError('scope', 'AgentOS returned a result for another company.');
        companyId = recovered.run.companyId ?? companyId; revision = recovered.run.revision ?? revision;
        terminal = true; notify(recovered.run.status);
        return recovered;
      }).catch(error => { notify('running'); throw error; }).finally(() => controller.abort());
      // The generator awaits and surfaces cancellation failures; attach a handler immediately to prevent an unhandled rejection.
      void cancellation.catch(() => undefined);
    };
    signal.addEventListener('abort', cancel);
    if (signal.aborted) cancel();
    const seen = artifactKeys(savedMessages());
    try {
      const form = new FormData();
      form.set('message', text.parse(input)); form.set('session_id', sessionId); form.set('stream', 'true'); form.set('background', 'true');
      let response: Response;
      const runHeaders: Record<string, string> = { 'X-Samurai-Submission-Id': submissionId };
      if (approval) {
        if (!Number.isSafeInteger(approval.expectedRevision) || approval.expectedRevision < 0) throw new AgentosError('protocol', 'The approved revision is invalid.');
        runHeaders['X-Samurai-Company-Id'] = uuid.parse(approval.companyId);
        runHeaders['X-Samurai-Operation'] = approval.operation;
        runHeaders['X-Samurai-Stage'] = approval.stage;
        runHeaders['X-Samurai-Expected-Revision'] = String(approval.expectedRevision);
      }
      try { response = start ? await start(text.parse(input), controller.signal, area, approval, submissionId) : await request(base, { method: 'POST', body: form, signal: controller.signal, headers: runHeaders }); }
      catch (error) {
        if (error instanceof AgentosError && error.code === 'admission') throw error;
        const receipt = await readAgentosReceipt(sessionId, submissionId, controller.signal);
        runId = receipt.runId; companyId = receipt.companyId; revision = receipt.revision; status = receipt.status; onRun?.(receipt);
        if (!runId) throw new AgentosError('protocol', 'The work receipt omitted the run identity.');
        if (signal.aborted) {
          cancel();
          if (cancellation) for (const output of (await cancellation).events) yield output;
          return;
        }
        if (['completed', 'cancelled', 'failed'].includes(receipt.status)) {
          const recovered = await readAgentosRun(sessionId, runId, controller.signal, savedMessages());
          terminal = true; notify(recovered.run.status);
          for (const output of recovered.events) yield output;
          return;
        }
        if (receipt.status === 'paused') throw new AgentosError('stream', 'This run is paused and needs an approved recovery action before it can continue.');
        response = await resumeRequest(sessionId, runId, lastEventIndex, controller.signal);
      }
      stream: while (true) {
        if (!response.body || !response.headers.get('content-type')?.includes('text/event-stream')) throw new AgentosError('protocol', 'AgentOS did not return an event stream.');
        for await (const raw of frames(response.body)) {
          const event = envelope(raw);
          if (!event) continue;
          if (event.session_id !== sessionId || (runId && event.run_id !== runId)) throw new AgentosError('scope', 'AgentOS returned an event for another session or run.');
          if (!runId) {
            if (event.event !== 'RunStarted') throw new AgentosError('protocol', 'AgentOS omitted RunStarted.');
            runId = event.run_id; notify('running');
          }
          if (event.event_index !== undefined) {
            if (lastEventIndex !== undefined && event.event_index <= lastEventIndex) continue;
            lastEventIndex = event.event_index; notify(status);
          }
          if (signal.aborted) { cancel(); break stream; }
          if (event.event === 'CustomEvent' && (event.kind === 'workflow_progress' || event.kind === undefined)) {
            const activity = progressEvent(event.content);
            if (activity) yield activity;
          }
          if (event.event === 'ToolCallCompleted' || event.event === 'RunCompleted') {
            const tool = event.tool === undefined ? undefined : recordSchema.parse(event.tool);
            const value = event.event === 'ToolCallCompleted' ? tool?.result : event.content;
            const view = presentation(value);
            const handoff = handoffEvents(value, seen);
            if (handoff) for (const output of handoff) yield output;
            if (view) for (const output of presentationEvents(view, seen)) yield output;
            const result = view || handoff ? undefined : workflow(value);
            if (result) {
              if (companyId && result.company_id && companyId !== result.company_id) throw new AgentosError('scope', 'AgentOS returned a result for another company.');
              companyId = result.company_id ?? companyId; revision = result.revision; notify(status);
              for (const output of resultEvents(result, seen)) {
                if (signal.aborted) { cancel(); break stream; }
                yield output;
              }
            } else if (!view && !handoff && event.event === 'RunCompleted' && typeof event.content === 'string' && event.content.trim()) yield { type: 'message', text: event.content };
          }
          if (event.event === 'RunError') { terminal = true; notify('failed'); throw new AgentosError('stream', 'Samurai could not complete this run.'); }
          if (event.event === 'RunCompleted' || event.event === 'RunCancelled') { terminal = true; notify(event.event === 'RunCancelled' ? 'cancelled' : 'completed'); return; }
        }
        if (!runId) {
          const receipt = await readAgentosReceipt(sessionId, submissionId, controller.signal);
          runId = receipt.runId; companyId = receipt.companyId; revision = receipt.revision; status = receipt.status; onRun?.(receipt);
          if (!runId) throw new AgentosError('protocol', 'The work receipt omitted the run identity.');
          if (signal.aborted) { cancel(); break stream; }
          if (['completed', 'cancelled', 'failed'].includes(receipt.status)) {
            const recovered = await readAgentosRun(sessionId, runId, controller.signal, savedMessages());
            terminal = true; notify(recovered.run.status);
            for (const output of recovered.events) yield output;
            return;
          }
          if (receipt.status === 'paused') throw new AgentosError('stream', 'This run is paused and needs an approved recovery action before it can continue.');
        } else if (lastEventIndex === undefined) throw new AgentosError('stream', 'AgentOS disconnected before a recoverable event cursor was saved.');
        notify('recovering');
        response = await resumeRequest(sessionId, runId, lastEventIndex, controller.signal);
      }
      if (cancellation) { for (const output of (await cancellation).events) yield output; return; }
    } catch (error) {
      if (cancellation) { for (const output of (await cancellation).events) yield output; return; }
      if (error instanceof AgentosError && error.code === 'admission' && !runId) { terminal = true; notify('failed', error.message); }
      if (!terminal) notify('recovering');
      throw error;
    } finally {
      signal.removeEventListener('abort', cancel); clearTimeout(timeout);
      try { if (cancellation) await cancellation; } finally { controller.abort(); }
    }
  };
}

export async function readAgentosRun(sessionId: string, runId: string, signal?: AbortSignal, savedMessages: readonly Message[] = []): Promise<AgentosRunResult> {
  text.parse(sessionId); text.parse(runId);
  const response = await request(`${base}/${encodeURIComponent(runId)}?session_id=${encodeURIComponent(sessionId)}`, { method: 'GET', signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15_000)]) : AbortSignal.timeout(15_000) });
  const wire = recordSchema.parse(json(await response.text()));
  const run = z.strictObject({ run_id: text, session_id: text, agent_id: z.literal('samurai'), status: z.enum(['RUNNING', 'PENDING', 'PAUSED', 'COMPLETED', 'CANCELLED', 'ERROR']), content: z.unknown().optional() }).parse({ run_id: wire.run_id, session_id: wire.session_id, agent_id: wire.agent_id, status: wire.status, content: wire.content });
  if (run.run_id !== runId || run.session_id !== sessionId) throw new AgentosError('scope', 'AgentOS returned another session or run.');
  const status = run.status === 'COMPLETED' ? 'completed' : run.status === 'CANCELLED' ? 'cancelled' : run.status === 'ERROR' ? 'failed' : run.status === 'PENDING' ? 'queued' : run.status === 'PAUSED' ? 'paused' : 'running';
  const seen = artifactKeys(savedMessages, runId);
  const view = status === 'completed' ? presentation(run.content) : undefined;
  const handoff = status === 'completed' ? handoffEvents(run.content, seen) : undefined;
  const result = status === 'completed' && !view && !handoff ? workflow(run.content) : undefined;
  const savedArea = teamAreaSchema.safeParse(recordSchema.safeParse(wire.metadata).data?.team_area);
  return { run: { runId, status, ...(savedArea.success ? { area: savedArea.data } : {}), ...(result ? { ...(result.company_id ? { companyId: result.company_id } : {}), revision: result.revision } : {}) }, events: [...recoveredActivities(wire.events, sessionId, runId), ...(handoff ? handoff : view ? presentationEvents(view, seen) : result ? resultEvents(result, seen) : status === 'completed' && typeof run.content === 'string' ? [{ type: 'message' as const, text: run.content }] : [])] };
}

function recoveredActivities(value: unknown, sessionId: string, runId: string): WorkEvent[] {
  if (value === undefined || value === null) return [];
  const saved = z.array(recordSchema).max(1000).parse(value);
  return saved.flatMap(event => {
    if (event.event !== 'CustomEvent' || (event.kind !== undefined && event.kind !== 'workflow_progress')) return [];
    if (event.session_id !== sessionId || event.run_id !== runId || event.agent_id !== 'samurai') throw new AgentosError('scope', 'Saved activity belongs to another session or run.');
    const activity = progressEvent(event.content);
    return activity ? [activity] : [];
  }).slice(-100);
}

// Present historical wire responses through the same catalog without replaying work or changing saved data.
export function presentMessages(messages: readonly Message[]): Message[] {
  const panelIds = new Set(messages.flatMap(message => message.panel ? [message.panel.id] : []));
  const output: Message[] = [];
  for (const message of messages) {
    if (message.role !== 'assistant') { output.push(message); continue; }
    const statusOnly = /^[a-z_ ]+: (complete|needs_input|needs_rework|insufficient_evidence|draft_only|requires_metrics|based_on_founder_supplied_metrics)$/.test(message.text.trim());
    if (message.panel) { output.push({ ...message, text: statusOnly ? '' : message.text }); continue; }
    if (statusOnly) continue;
    const candidate = message.text.trim();
    if (candidate.startsWith('{') || candidate.includes('SAMURAI_WORKFLOW_RESULT=')) {
      let value: unknown;
      try { value = json(candidate.includes('SAMURAI_WORKFLOW_RESULT=') ? candidate.slice(candidate.lastIndexOf('SAMURAI_WORKFLOW_RESULT=') + 'SAMURAI_WORKFLOW_RESULT='.length) : candidate); }
      catch (error) { if (error instanceof AgentosError) { output.push({ ...message, text: 'This response could not be displayed. Please try again.' }); continue; } throw error; }
      const result = companyResultSchema.safeParse(value);
      const envelope = artifact.safeParse(value);
      const data = result.success ? result.data : envelope.success ? { company_id: envelope.data.company_id, revision: envelope.data.revision, outcome: 'needs_rework' as const, artifacts: [envelope.data], questions: [] } : undefined;
      if (data) {
        for (const [index, event] of resultEvents(data, new Set()).entries()) {
          if (event.type !== 'message' || (event.panel && panelIds.has(event.panel.id))) continue;
          if (event.panel) panelIds.add(event.panel.id);
          output.push({ ...message, id: `${message.id}-view-${index}`, text: event.text, ...(event.panel ? { panel: event.panel } : {}) });
        }
        continue;
      }
      output.push({ ...message, text: "This response could not be displayed. Its data is incomplete." });
      continue;
    }
    output.push(message);
  }
  return output;
}

function artifactKeys(messages: readonly Message[], runId?: string): Set<string> {
  return new Set(messages.flatMap(message => {
    if (message.handoff && runId && message.backendRunId === runId) return ['handoff:' + JSON.stringify({ area: message.handoff, text: message.text, ...(message.handoffPrerequisite !== undefined ? { prerequisite: message.handoffPrerequisite } : {}) })];
    if (message.panel && ['declarative', 'custom'].includes(message.panel.kind)) return [`panel:${message.panel.id}:${JSON.stringify(message.panel)}`];
    const item = message.panel?.provenance;
    return item && typeof item.artifact_id === 'string' && typeof item.revision === 'number' ? [`${item.artifact_id}:${item.revision}`] : [];
  }));
}

function presentation(value: unknown): Panel | undefined {
  if (typeof value !== 'string') return undefined;
  const marker = 'SAMURAI_PANEL=';
  const index = value.lastIndexOf(marker);
  if (index < 0) return undefined;
  const panel = panelSchema.parse(json(value.slice(index + marker.length)));
  if (panel.kind !== 'declarative' && panel.kind !== 'custom') throw new AgentosError('protocol', 'Invalid presentation view.');
  return panel;
}
function presentationEvents(panel: Panel, seen: Set<string>): WorkEvent[] {
  const key = `panel:${panel.id}:${JSON.stringify(panel)}`;
  if (seen.has(key)) return [];
  seen.add(key);
  return [{ type: 'message', text: '', panel }];
}
function handoffEvents(value: unknown, seen: Set<string>): WorkEvent[] | undefined {
  if (typeof value !== 'string' || !value.startsWith('SAMURAI_HANDOFF=')) return undefined;
  const handoff = z.strictObject({ area: teamAreaSchema, text: z.string().min(1).max(500), prerequisite: z.boolean().optional() }).parse(json(value.slice('SAMURAI_HANDOFF='.length)));
  const key = 'handoff:' + JSON.stringify(handoff);
  if (seen.has(key)) return [];
  seen.add(key);
  return [{ type: 'message', text: handoff.text, handoff: handoff.area, ...(handoff.prerequisite !== undefined ? { handoffPrerequisite: handoff.prerequisite } : {}) }];
}

export { artifact as artifactSchema };
