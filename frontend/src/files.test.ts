import { afterEach, describe, expect, it, vi } from 'vitest';
import { deleteWorkspaceFile, downloadWorkspaceFile, getWorkspaceFile, listWorkspaceFiles, uploadWorkspaceFile } from './files';

const workspaceId = '00000000-0000-4000-8000-000000000001';
const companyId = '00000000-0000-4000-8000-000000000002';
const file = {
  file_id: '00000000-0000-4000-8000-000000000003', workspace_id: workspaceId, company_id: companyId,
  state: 'ready', display_name: 'brief.md', media_type: 'text/markdown', byte_size: 16,
  content_sha256: 'a'.repeat(64), created_at: 1, updated_at: 2,
};

afterEach(() => vi.unstubAllGlobals());

describe('workspace file client', () => {
  it('uses the fixed file collection path and parses only the public DTO', async () => {
    const request = vi.fn<typeof fetch>(async () => Response.json([file]));
    vi.stubGlobal('fetch', request);

    await expect(listWorkspaceFiles(workspaceId)).resolves.toEqual([file]);
    expect(request).toHaveBeenCalledWith(`/api/agentos/samurai/workspaces/${workspaceId}/files`, expect.objectContaining({ method: 'GET', credentials: 'same-origin' }));

    vi.stubGlobal('fetch', vi.fn(async () => Response.json([{ ...file, storage_path: 'private' }])));
    await expect(listWorkspaceFiles(workspaceId)).rejects.toThrow();
  });

  it('submits exactly one file and an optional company binding as multipart form data', async () => {
    const request = vi.fn<typeof fetch>(async () => Response.json(file));
    vi.stubGlobal('fetch', request);

    await uploadWorkspaceFile(workspaceId, new File(['# Founder brief\n'], 'brief.md', { type: 'text/markdown' }), companyId);

    const [, init] = request.mock.calls[0] ?? [];
    expect(init).toMatchObject({ method: 'POST', credentials: 'same-origin' });
    expect(init?.headers).toEqual({ 'X-Samurai-Client': '1' });
    expect(init?.body).toBeInstanceOf(FormData);
    expect((init?.body as FormData).getAll('file')).toHaveLength(1);
    expect((init?.body as FormData).get('company_id')).toBe(companyId);
  });

  it('accepts the backend delete response with no JSON body', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 204 })));
    await expect(deleteWorkspaceFile(workspaceId, file.file_id)).resolves.toBeUndefined();
  });

  it('reads metadata and downloads through the fixed same-origin BFF without a browser token', async () => {
    const request = vi.fn<typeof fetch>(async () => Response.json(file));
    vi.stubGlobal('fetch', request);
    await expect(getWorkspaceFile(workspaceId, file.file_id)).resolves.toEqual(file);
    expect(request).toHaveBeenCalledWith(`/api/agentos/samurai/workspaces/${workspaceId}/files/${file.file_id}`, expect.objectContaining({ method: 'GET', credentials: 'same-origin', headers: { 'X-Samurai-Client': '1' } }));

    vi.stubGlobal('fetch', vi.fn(async () => new Response('founder context', { status: 200 })));
    await expect(downloadWorkspaceFile(workspaceId, file.file_id)).resolves.toBeInstanceOf(Response);
  });
});
