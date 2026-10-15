import { z } from 'zod';

const base = '/api/agentos/samurai';
const uuid = z.string().uuid();
const states = ['quarantined', 'ready', 'rejected', 'deleted'] as const;
const fileSchema = z.strictObject({
  file_id: uuid,
  workspace_id: uuid,
  company_id: uuid.nullable(),
  state: z.enum(states),
  display_name: z.string().min(1).max(200),
  media_type: z.string().min(1).max(100),
  byte_size: z.number().int().min(0).max(10 * 1024 * 1024),
  content_sha256: z.string().regex(/^[a-f0-9]{64}$/),
  created_at: z.number().int().min(0),
  updated_at: z.number().int().min(0),
});
export type WorkspaceFile = z.infer<typeof fileSchema>;

export class WorkspaceFileError extends Error {
  readonly name = 'WorkspaceFileError';
  constructor(readonly status: number) { super(`Workspace file request failed (${status}).`); }
}

function filesPath(workspaceId: string): string {
  return `${base}/workspaces/${uuid.parse(workspaceId)}/files`;
}

async function request<T>(path: string, schema: z.ZodType<T>, init: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, credentials: 'same-origin', headers: { 'X-Samurai-Client': '1', ...init.headers } });
  if (!response.ok) throw new WorkspaceFileError(response.status);
  return schema.parse(await response.json());
}

export function listWorkspaceFiles(workspaceId: string): Promise<WorkspaceFile[]> {
  return request(filesPath(workspaceId), z.array(fileSchema), { method: 'GET' });
}

export function uploadWorkspaceFile(workspaceId: string, file: File, companyId?: string): Promise<WorkspaceFile> {
  const form = new FormData();
  form.set('file', file);
  if (companyId) form.set('company_id', uuid.parse(companyId));
  return request(filesPath(workspaceId), fileSchema, { method: 'POST', body: form });
}

export async function deleteWorkspaceFile(workspaceId: string, fileId: string): Promise<void> {
  const response = await fetch(`${filesPath(workspaceId)}/${uuid.parse(fileId)}`, { method: 'DELETE', credentials: 'same-origin', headers: { 'X-Samurai-Client': '1' } });
  if (!response.ok) throw new WorkspaceFileError(response.status);
}

export async function downloadWorkspaceFile(workspaceId: string, fileId: string): Promise<Response> {
  const response = await fetch(`${filesPath(workspaceId)}/${uuid.parse(fileId)}/download`, { method: 'GET', credentials: 'same-origin', headers: { 'X-Samurai-Client': '1' } });
  if (!response.ok) throw new WorkspaceFileError(response.status);
  return response;
}
