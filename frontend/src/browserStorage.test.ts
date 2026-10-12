import { expect, it, vi } from 'vitest';
import { loadPortfolio, persistPortfolio, portfolioStorageKey, resolveBrowserScope } from './browserStorage';
import { emptyWorkspace, portfolioKey, storageKey } from './model';

it('does not request identity in development', async () => {
  const request = vi.fn<typeof fetch>();
  const scope = await resolveBrowserScope(false, request);
  expect(scope).toEqual({ kind: 'development' });
  expect(request).not.toHaveBeenCalled();
});

it('isolates saved companies for two authenticated identities without migrating shared data', async () => {
  const first = await resolveBrowserScope(true, async () => Response.json({ storageNamespace: 'a'.repeat(64), configured: true }));
  const second = await resolveBrowserScope(true, async () => Response.json({ storageNamespace: 'b'.repeat(64), configured: true }));
  const saved = JSON.stringify({ version: 2, mode: 'light', activeId: null, companies: [{ id: 'first', name: 'Private company', workspace: emptyWorkspace() }] });
  const values = new Map([[portfolioStorageKey(first), saved], [portfolioKey, saved], [storageKey, JSON.stringify(emptyWorkspace())]]);
  const storage = { getItem: (key: string) => values.get(key) ?? null };
  expect(loadPortfolio(storage, first).companies.map(company => company.id)).toEqual(['first']);
  expect(loadPortfolio(storage, second).companies).toEqual([]);
});

it('preserves development legacy migration', async () => {
  const scope = await resolveBrowserScope(false);
  const storage = { getItem: (key: string) => key === storageKey ? JSON.stringify(emptyWorkspace()) : null };
  expect(loadPortfolio(storage, scope).companies[0].id).toBe('legacy-dental');
  expect(portfolioStorageKey(scope)).toBe(portfolioKey);
});

for (const status of [401, 403, 503]) it(`fails closed when identity returns ${status}`, async () => {
  await expect(resolveBrowserScope(true, async () => new Response('{}', { status }))).rejects.toThrow();
});

it('fails closed when a production server omits the identity namespace', async () => {
  await expect(resolveBrowserScope(true, async () => Response.json({ configured: true }))).rejects.toThrow();
});

it('fetches identity without caching before returning the user scope', async () => {
  const request = vi.fn<typeof fetch>(async () => Response.json({ configured: true, storageNamespace: 'c'.repeat(64) }));
  const scope = await resolveBrowserScope(true, request);
  expect(scope.kind).toBe('user');
  expect(request).toHaveBeenCalledWith('/api/agentos/connection', expect.objectContaining({ cache: 'no-store', credentials: 'same-origin', redirect: 'error', headers: { 'X-Samurai-Client': '1' } }));
});

it('reports synchronous portfolio persistence failure before a caller can submit', () => {
  const portfolio = { version: 2 as const, mode: 'light' as const, activeId: null, companies: [] };
  const saved = new Map<string, string>();
  expect(persistPortfolio({ setItem: (key, value) => { saved.set(key, value); } }, 'owner-key', portfolio)).toBe(true);
  expect(JSON.parse(saved.get('owner-key') ?? '{}')).toEqual(portfolio);
  expect(persistPortfolio({ setItem: () => { throw new DOMException('Quota exceeded', 'QuotaExceededError'); } }, 'owner-key', portfolio)).toBe(false);
});
