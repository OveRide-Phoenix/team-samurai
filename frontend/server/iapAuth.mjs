import { createPrivateKey, sign } from 'node:crypto';
import { OAuth2Client } from 'google-auth-library';

export class RequestError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export function productionConfig(env = process.env) {
  const authMode = env.FRONTEND_AUTH_MODE ?? 'iap';
  if (!['iap', 'guest'].includes(authMode)) throw new Error('Invalid frontend authentication mode');
  const required = ['PUBLIC_ORIGIN', 'AGENTOS_BACKEND_URL', 'AGENTOS_SIGNING_KEY', ...(authMode === 'iap' ? ['IAP_AUDIENCE'] : [])];
  if (required.some(name => !env[name])) throw new Error('Missing production authentication configuration');
  const origin = new URL(env.PUBLIC_ORIGIN);
  const backend = new URL(env.AGENTOS_BACKEND_URL);
  if ([origin, backend].some(url => url.protocol !== 'https:' || url.username || url.password || url.pathname !== '/' || url.search || url.hash)) throw new Error('Production URLs must be HTTPS origins');
  if (authMode === 'iap' && !/^\/projects\/\d+\/locations\/[a-z0-9-]+\/services\/[a-z0-9-]+$/.test(env.IAP_AUDIENCE)) throw new Error('Invalid Cloud Run IAP audience');
  const key = createPrivateKey(env.AGENTOS_SIGNING_KEY);
  if (key.asymmetricKeyType !== 'rsa' || key.asymmetricKeyDetails.modulusLength < 2048) throw new Error('Signing key must be RSA, at least 2048 bits');
  return { origin: origin.origin, backend: backend.origin, audience: env.IAP_AUDIENCE, key, authMode };
}

export function createIapVerifier(audience, client = new OAuth2Client({ transporterOptions: { timeout: 10_000 } })) {
  let cached;
  let pending;
  async function keys() {
    if (cached && Date.now() < cached.until) return cached.keys;
    if (!pending) pending = client.getIapPublicKeys().then(result => {
      const maxAge = /(?:^|,)\s*max-age=(\d+)/i.exec(result.res.headers.get('cache-control') ?? '');
      const seconds = maxAge ? Math.min(Number(maxAge[1]), 3600) : 300;
      cached = { keys: result.pubkeys, until: Date.now() + seconds * 1000 };
      return result.pubkeys;
    }).finally(() => { pending = undefined; });
    return pending;
  }
  return async assertion => {
    try {
      if (typeof assertion !== 'string' || assertion.length > 16000) throw new Error('Missing assertion');
      const header = JSON.parse(Buffer.from(assertion.split('.')[0], 'base64url').toString('utf8'));
      if (header.alg !== 'ES256' || typeof header.kid !== 'string') throw new Error('Invalid algorithm');
      const ticket = await client.verifySignedJwtWithCertsAsync(assertion, await keys(), audience, ['https://cloud.google.com/iap']);
      const payload = ticket.getPayload();
      const now = Date.now() / 1000;
      // Google's generic verifier permits 300s skew; IAP's contract permits only 30s.
      if (!payload || typeof payload.sub !== 'string' || !payload.sub || payload.sub.length > 256 || !Number.isFinite(payload.iat) || !Number.isFinite(payload.exp) || payload.iat > now + 30 || payload.exp < now - 30 || payload.exp <= payload.iat || payload.exp - payload.iat > 660) throw new Error('Invalid IAP claims');
      return `iap:${payload.sub}`;
    } catch { // HTTP authentication boundary: never leak token-bearing library errors.
      throw new RequestError(401, 'Google authentication required.');
    }
  };
}

export function signAgentosToken(subject, key) {
  const now = Math.floor(Date.now() / 1000);
  const encode = value => Buffer.from(JSON.stringify(value)).toString('base64url');
  const data = `${encode({ alg: 'RS256', typ: 'JWT' })}.${encode({ sub: subject, iss: 'samurai-frontend', aud: 'samurai', iat: now, exp: now + 300, scopes: ['agents:samurai:read', 'agents:samurai:run'] })}`;
  return `${data}.${sign('RSA-SHA256', Buffer.from(data), key).toString('base64url')}`;
}
