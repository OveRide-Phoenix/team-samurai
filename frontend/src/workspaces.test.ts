import { canonicalCompanyFields, directoryCompanySchema, needsCompanyIntake } from './workspaces';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createLatestRequestGuard, createOneAtATimeGate, createWorkspaceCompany, firstWritableWorkspace, listWorkspaces, openWorkspaceCompany, shouldLoadWorkspaceDirectory } from './workspaces';

const workspaceId = '00000000-0000-4000-8000-000000000001';
const companyId = '00000000-0000-4000-8000-000000000002';
const workspace = { workspace_id: workspaceId, display_name: 'Founders', role: 'editor', authorization_epoch: 2 };
const company = { workspace_id: workspaceId, company_id: companyId, current_revision: 1, state_sha256: 'a'.repeat(64), created_at: 1, parent_session_id: 'parent-a', child_session_id: 'child-a', snapshot: null };

afterEach(() => vi.unstubAllGlobals());

describe('workspace directory client', () => {
  it('loads the remote directory only on Home and chooses a writable empty workspace', () => {
    expect(shouldLoadWorkspaceDirectory(null)).toBe(true);
    expect(shouldLoadWorkspaceDirectory('cached-parent-session')).toBe(false);
    expect(firstWritableWorkspace([{ ...workspace, role: 'viewer' }, { ...workspace, workspace_id: '00000000-0000-4000-8000-000000000003', role: 'editor' }])).toMatchObject({ role: 'editor' });
  });
  it('uses fixed directory paths and maps a reservation submission ID to the company request', async () => {
    const request = vi.fn(async () => Response.json(company));
    vi.stubGlobal('fetch', request);
    const submissionId = '00000000-0000-4000-8000-000000000003';
    await expect(createWorkspaceCompany(workspaceId, submissionId)).resolves.toEqual(company);
    await expect(openWorkspaceCompany(workspaceId, companyId)).resolves.toEqual(company);
    expect(request.mock.calls).toEqual([
      [`/api/agentos/samurai/workspaces/${workspaceId}/companies`, expect.objectContaining({ method: 'POST', body: '{}', credentials: 'same-origin', headers: expect.objectContaining({ 'X-Samurai-Submission-Id': submissionId }) })],
      [`/api/agentos/samurai/workspaces/${workspaceId}/companies/${companyId}/open`, expect.objectContaining({ method: 'POST', body: '{}', credentials: 'same-origin' })],
    ]);
  });

  it('reuses the same company request contract after an ambiguous transport loss', async () => {
    const submissionId = '00000000-0000-4000-8000-000000000003';
    const request = vi.fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError('network lost after reservation'))
      .mockResolvedValueOnce(Response.json(company));
    vi.stubGlobal('fetch', request);
    await expect(createWorkspaceCompany(workspaceId, submissionId)).rejects.toThrow('network lost after reservation');
    await expect(createWorkspaceCompany(workspaceId, submissionId)).resolves.toEqual(company);
    expect(request.mock.calls.map(([, init]) => init?.headers)).toEqual([
      expect.objectContaining({ 'X-Samurai-Submission-Id': submissionId }),
      expect.objectContaining({ 'X-Samurai-Submission-Id': submissionId }),
    ]);
  });

  it('parses only the server directory response shape', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json([workspace])));
    await expect(listWorkspaces()).resolves.toEqual([workspace]);
    vi.stubGlobal('fetch', vi.fn(async () => Response.json([{ ...workspace, user_id: 'forged' }])));
    await expect(listWorkspaces()).rejects.toThrow();
  });

  it('admits one reservation for a rapid double submit', () => {
    const gate = createOneAtATimeGate();
    const reserve = vi.fn();
    const submit = () => { if (gate.tryBegin()) reserve(); };
    submit();
    submit();
    expect(reserve).toHaveBeenCalledTimes(1);
    expect(gate.isPending()).toBe(true);
    gate.finish();
    expect(gate.isPending()).toBe(false);
  });

  it('ignores a late shared-company open after a newer selection', () => {
    const guard = createLatestRequestGuard();
    const first = guard.begin();
    const second = guard.begin();
    let selected = '';
    const resolve = (request: number, company: string) => { if (guard.isCurrent(request)) selected = company; guard.finish(request); };
    resolve(second, 'newer-company');
    resolve(first, 'older-company');
    expect(selected).toBe('newer-company');
    expect(guard.isPending()).toBe(false);
  });
});

it('resumes intake only for writable companies without an accepted revision', () => {
  expect(needsCompanyIntake({ ...company, current_revision: 0 }, 'owner')).toBe(true);
  expect(needsCompanyIntake({ ...company, current_revision: 0 }, 'editor')).toBe(true);
  expect(needsCompanyIntake({ ...company, current_revision: 0 }, 'viewer')).toBe(false);
  expect(needsCompanyIntake(company, 'owner')).toBe(false);
});

it('refreshes action eligibility and operation pins from one matching canonical snapshot', () => {
  const action = { id: 'plan', label: 'Plan delivery', prompt: 'Plan delivery', operation: 'journey', stage: 'plan', area: 'strategy', eligible: true, blocked_reason: null };
  const opened = directoryCompanySchema.parse({ ...company, current_revision: 4, snapshot: { summary: { company_id: companyId, revision: 4, artifact_count: 4, status: 'active', actions: [action], next_action: 'plan' }, artifacts: [] } });
  expect(canonicalCompanyFields(opened)).toEqual({ companyId, currentRevision: 4, stateSha256: company.state_sha256, actions: [action], nextAction: 'plan' });
  expect(() => canonicalCompanyFields({ ...opened, current_revision: 5 })).toThrow('canonical revision');
  expect(() => canonicalCompanyFields({ ...opened, company_id: workspaceId })).toThrow('canonical revision');
});
