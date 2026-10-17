import { z } from 'zod';
import { portfolioKey, restorePortfolio, storageKey, type Portfolio } from './model';

const guest = z.object({ sessionDays: z.number().int().positive(), aiSubmissionsPerDay: z.number().int().positive() });
const identity = z.object({ guest: guest.optional(), configured: z.literal(true), storageNamespace: z.string().regex(/^[a-f0-9]{64}$/).brand<'StorageNamespace'>() });
export type BrowserScope = { readonly kind: 'development' } | { readonly kind: 'user'; readonly namespace: z.infer<typeof identity>['storageNamespace']; readonly guest?: z.infer<typeof guest> };
export class BrowserIdentityError extends Error {
  readonly name = 'BrowserIdentityError';
  constructor() { super('Your session could not be opened. Reload Samurai to try again.'); }
}

export async function resolveBrowserScope(production: boolean, request: typeof fetch = fetch): Promise<BrowserScope> {
  if (!production) return { kind: 'development' };
  const response = await request('/api/agentos/connection', {
    credentials: 'same-origin', cache: 'no-store', redirect: 'error',
    headers: { 'X-Samurai-Client': '1' }, signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new BrowserIdentityError();
  const data: unknown = await response.json();
  const result = identity.safeParse(data);
  if (!result.success) throw new BrowserIdentityError();
  return { kind: 'user', namespace: result.data.storageNamespace, ...(result.data.guest ? { guest: result.data.guest } : {}) };
}

export function portfolioStorageKey(scope: BrowserScope): string {
  switch (scope.kind) {
    case 'development': return portfolioKey;
    case 'user': return `${portfolioKey}:${scope.namespace}`;
  }
}

export function loadPortfolio(storage: Pick<Storage, 'getItem'>, scope: BrowserScope): Portfolio {
  return restorePortfolio(storage.getItem(portfolioStorageKey(scope)), scope.kind === 'development' ? storage.getItem(storageKey) : null);
}

export function persistPortfolio(storage: Pick<Storage, 'setItem'>, key: string, portfolio: Portfolio): boolean {
  try { storage.setItem(key, JSON.stringify(portfolio)); return true; }
  catch { return false; }
}
