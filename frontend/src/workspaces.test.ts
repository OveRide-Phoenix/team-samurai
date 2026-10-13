import { afterEach, describe, expect, it, vi } from 'vitest';
import { createLatestRequestGuard, createOneAtATimeGate, createWorkspaceCompany, firstWritableWorkspace, listWorkspaces, openWorkspaceCompany, shouldLoadWorkspaceDirectory } from './workspaces';

const workspaceId = '00000000-0000-4000-8000-000000000001';
const companyId = '00000000-0000-4000-8000-000000000002';
const workspace = { workspace_id: workspaceId, display_name: 'Founders', role: 'editor', authorization_epoch: 2 };
const company = { workspace_id: workspaceId, company_id: companyId, current_revision: 1, created_at: 1, parent_session_id: 'parent-a', child_session_id: 'child-a', snapshot: null };

afterEach(() => vi.unstubAllGlobals());

describe('workspace directory client', () => {
  it('loads the remote directory only on Home and chooses a writable empty workspace', () => {
    expect(shouldLoadWorkspaceDirectory(null)).toBe(true);
    expect(shouldLoadWorkspaceDirectory('cached-parent-session')).toBe(false);
    expect(firstWritableWorkspace([{ ...workspace, role: 'viewer' }, { ...workspace, workspace_id: '00000000-0000-4000-8000-000000000003', role: 'editor' }])).toMatchObject({ role: 'editor' });
  });
  it('uses fixed directory paths and strict empty POST bodies', async () => {
    const request = vi.fn(async () => Response.json(company));
    vi.stubGlobal('fetch', request);
    await expect(createWorkspaceCompany(workspaceId)).resolves.toEqual(company);
    await expect(openWorkspaceCompany(workspaceId, companyId)).resolves.toEqual(company);
    expect(request.mock.calls).toEqual([
      [`/api/agentos/samurai/workspaces/${workspaceId}/companies`, expect.objectContaining({ method: 'POST', body: '{}', credentials: 'same-origin' })],
      [`/api/agentos/samurai/workspaces/${workspaceId}/companies/${companyId}/open`, expect.objectContaining({ method: 'POST', body: '{}', credentials: 'same-origin' })],
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
