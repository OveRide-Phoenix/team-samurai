import { z } from 'zod';
import type { CompanyView } from './model';
import { companySnapshotSchema } from './agentos';

const base = '/api/agentos/samurai';
const headers = { 'Content-Type': 'application/json', 'X-Samurai-Client': '1' } as const;
const uuid = z.string().uuid();
const role = z.enum(['owner', 'editor', 'viewer']);

export const workspaceDirectorySchema = z.strictObject({
  workspace_id: uuid,
  display_name: z.string().min(1).max(200),
  role,
  authorization_epoch: z.number().int().min(1),
});
export type WorkspaceDirectory = z.infer<typeof workspaceDirectorySchema>;

export const directoryCompanySchema = z.strictObject({
  workspace_id: uuid,
  company_id: uuid,
  current_revision: z.number().int().min(0),
  state_sha256: z.string().regex(/^[a-f0-9]{64}$/),
  created_at: z.number().int().min(0),
  parent_session_id: z.string().min(1).nullable(),
  child_session_id: z.string().min(1).nullable(),
  snapshot: companySnapshotSchema.nullable(),
});
export type DirectoryCompany = z.infer<typeof directoryCompanySchema>;

export function shouldLoadWorkspaceDirectory(activeCompanyId: string | null): boolean {
  return activeCompanyId === null;
}

export function needsCompanyIntake(company: DirectoryCompany, role: WorkspaceDirectory['role']): boolean {
  return company.current_revision === 0 && role !== 'viewer';
}

export function firstWritableWorkspace(workspaces: readonly WorkspaceDirectory[]): WorkspaceDirectory | undefined {
  return workspaces.find(workspace => workspace.role !== 'viewer');
}

export function createOneAtATimeGate() {
  let pending = false;
  return {
    tryBegin: (): boolean => {
      if (pending) return false;
      pending = true;
      return true;
    },
    finish: (): void => { pending = false; },
    isPending: (): boolean => pending,
  };
}

export function createLatestRequestGuard() {
  let latest = 0;
  let pending = false;
  return {
    begin: (): number => { pending = true; latest += 1; return latest; },
    invalidate: (): void => { pending = false; latest += 1; },
    isCurrent: (request: number): boolean => request === latest,
    finish: (request: number): void => { if (request === latest) pending = false; },
    isPending: (): boolean => pending,
  };
}

export class WorkspaceDirectoryError extends Error {
  readonly name = 'WorkspaceDirectoryError';
  constructor(readonly status: number) { super(`Workspace directory request failed (${status}).`); }
}

async function request<T>(path: string, schema: z.ZodType<T>, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    ...init,
    credentials: 'same-origin',
    headers: { ...headers, ...init.headers },
  });
  if (!response.ok) throw new WorkspaceDirectoryError(response.status);
  return schema.parse(await response.json());
}

export function listWorkspaces(): Promise<WorkspaceDirectory[]> {
  return request('/workspaces', z.array(workspaceDirectorySchema), { method: 'GET' });
}

export function createWorkspace(displayName: string): Promise<WorkspaceDirectory> {
  return request('/workspaces', workspaceDirectorySchema, { method: 'POST', body: JSON.stringify({ display_name: displayName }) });
}

export function listWorkspaceCompanies(workspaceId: string): Promise<DirectoryCompany[]> {
  return request(`/workspaces/${uuid.parse(workspaceId)}/companies`, z.array(directoryCompanySchema), { method: 'GET' });
}

export function createWorkspaceCompany(workspaceId: string, submissionId: string): Promise<DirectoryCompany> {
  return request(`/workspaces/${uuid.parse(workspaceId)}/companies`, directoryCompanySchema, { method: 'POST', body: '{}', headers: { 'X-Samurai-Submission-Id': uuid.parse(submissionId) } });
}

export function openWorkspaceCompany(workspaceId: string, companyId: string): Promise<DirectoryCompany> {
  return request(`/workspaces/${uuid.parse(workspaceId)}/companies/${uuid.parse(companyId)}/open`, directoryCompanySchema, { method: 'POST', body: '{}' });
}

export function canonicalCompanyFields(company: DirectoryCompany): Pick<CompanyView, 'companyId' | 'currentRevision' | 'stateSha256' | 'actions' | 'nextAction' | 'currentArtifactIds'> {
  if (!company.snapshot || company.snapshot.summary.company_id !== company.company_id || company.snapshot.summary.revision !== company.current_revision) throw new Error('Company snapshot does not match its canonical revision.');
  return { companyId: company.company_id, currentRevision: company.current_revision, stateSha256: company.state_sha256, currentArtifactIds: company.snapshot.summary.current_artifact_ids ?? undefined, actions: company.snapshot.summary.actions, nextAction: company.snapshot.summary.next_action };
}
