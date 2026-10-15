import { afterEach, describe, expect, it, vi } from 'vitest';
import { getScenarioResult, listLearning, listScheduleRuns, listSchedules, scenarioPanel } from './founderOperations';
import { panelSchema } from './model';

const workspace = '00000000-0000-4000-8000-000000000001';
const company = '00000000-0000-4000-8000-000000000002';
const scenario = '00000000-0000-4000-8000-000000000003';
const assumption = { name: 'growth', target_metric: 'revenue', low_delta_percent: '-20', base_delta_percent: '0', high_delta_percent: '20' };
const definition = { scenario_id: scenario, workspace_id: workspace, company_id: company, created_by: 'founder', title: 'Revenue range', company_revision: 2, company_state_sha256: 'a'.repeat(64), horizon_days: 30, baseline_metrics: [{ name: 'revenue', value: '100', unit: 'inr' }], assumptions: [assumption], constraints: [{ name: 'floor', metric: 'revenue', operator: 'minimum' as const, threshold: '80', unit: 'inr' }], input_sha256: 'b'.repeat(64) };
const result = { provenance: 'synthetic_scenario_not_validation' as const, company_revision: 2, company_state_sha256: 'a'.repeat(64), input_sha256: 'b'.repeat(64), horizon_days: 30, assumptions: [assumption], trajectories: ['low', 'base', 'high'].map((label, index) => ({ label, metrics: [{ metric: 'revenue', unit: 'inr', points: [{ day: 0, value: '1.2E+2' }, { day: 30, value: String(80 + index * 20) }] }] })), formulas: [{ metric: 'revenue', expression: 'end = baseline * (1 + delta_percent / 100)' as const, baseline_input: '1.2E+2', assumption: 'growth' }], sensitivity: [{ assumption: 'growth', target_metric: 'revenue', delta_range_percent: '40' }], constraint_findings: [{ constraint: 'floor', label: 'low' as const, metric: 'revenue', operator: 'minimum' as const, threshold: '80', actual: '80', unit: 'inr', violated: false }], result_sha256: 'c'.repeat(64) };

afterEach(() => vi.unstubAllGlobals());
describe('founder operation client boundaries', () => {
  it('uses the company-scoped learning query and retains server errors', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'source company revision is stale' }), { status: 409, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetch);
    await expect(listLearning(workspace, company)).rejects.toThrow('source company revision is stale');
    expect(fetch).toHaveBeenCalledWith(`/api/agentos/samurai/workspaces/${workspace}/learning?company_id=${company}`, expect.objectContaining({ method: 'GET', credentials: 'same-origin' }));
  });

  it('accepts exact epoch milliseconds for learning without lossy nanosecond parsing', async () => {
    const learning = { learning_id: scenario, workspace_id: workspace, user_id: 'founder', company_id: company, kind: 'preference', source_revision: 2, founder_text: 'Keep suggestions concise', created_by: 'founder', audit_sha256: 'a'.repeat(64), shared: false, superseded_by: null, active: true, created_at: 1_797_000_000_123, evidence_status: 'untrusted_preference_context' };
    const fetch = vi.fn().mockResolvedValueOnce(Response.json({ context_boundary: 'untrusted_preference_context', records: [learning] })).mockResolvedValueOnce(Response.json({ context_boundary: 'untrusted_preference_context', records: [{ ...learning, created_at: 1_797_000_000_123_456_789 }] }));
    vi.stubGlobal('fetch', fetch);
    await expect(listLearning(workspace, company)).resolves.toMatchObject({ records: [learning] });
    await expect(listLearning(workspace, company)).rejects.toThrow();
  });

  it('rejects schedule payload fields outside the selected action contract', async () => {
    const schedule = { schedule_id: scenario, workspace_id: workspace, company_id: company, created_by: 'founder', creator_authorization_epoch: 1, cadence: 'once', timezone: 'UTC', action_kind: 'workspace_review', payload: { scenario_id: scenario }, pinned_revision: 2, enabled: true, next_run_at: 1_797_000_000, last_run_at: null, created_at: 1_797_000_000, updated_at: 1_797_000_000 };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json([schedule])));
    await expect(listSchedules(workspace)).rejects.toThrow();
  });

  it('parses a persisted result and maps only the allowlisted synthetic panel', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(result), { status: 200, headers: { 'Content-Type': 'application/json' } })));
    const saved = await getScenarioResult(workspace, company, scenario);
    expect(saved.formulas[0]?.baseline_input).toBe('1.2E+2');
    const panel = scenarioPanel(definition, saved);
    expect(panelSchema.parse(panel)).toMatchObject({ kind: 'scenario', synthetic_label: 'synthetic_scenario_not_validation', company_revision: 2 });
    expect(JSON.stringify(panel.provenance)).toContain('company_state_sha256');
  });

  it('parses the full nested scheduled scenario receipt without flattening its result', async () => {
    const receipt = { schedule_id: scenario, scheduled_for: 1_800_000_000, status: 'completed', result: { action_kind: 'scenario_recompute', scenario_id: scenario, ...result }, error_code: null };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json([receipt])));
    await expect(listScheduleRuns(workspace, scenario)).resolves.toEqual([receipt]);
  });
});
