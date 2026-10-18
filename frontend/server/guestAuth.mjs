import { randomUUID, sign, verify } from 'node:crypto';
import { RequestError } from './iapAuth.mjs';

const cookieName = '__Host-samurai_guest';
const lifetime = 7 * 24 * 60 * 60;

export function guestIdentity(req, res, key, now = Math.floor(Date.now() / 1000)) {
  const cookies = (req.headers.cookie ?? '').split(';').map(value => value.trim()).filter(value => value.startsWith(`${cookieName}=`));
  if (cookies.length) {
    try {
      const token = cookies[0].slice(cookieName.length + 1);
      if (cookies.length !== 1 || token.length > 1024) throw new Error('Invalid cookie');
      const [id, issued, signature, extra] = token.split('.');
      if (extra !== undefined || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(id) || !/^\d{10}$/.test(issued)) throw new Error('Invalid cookie');
      if (!signature || Buffer.from(signature, 'base64url').toString('base64url') !== signature) throw new Error('Invalid cookie');
      const age = now - Number(issued);
      if (age < 0 || age >= lifetime || !verify('RSA-SHA256', Buffer.from(`samurai-guest-v1:${id}.${issued}`), key, Buffer.from(signature, 'base64url'))) throw new Error('Invalid cookie');
      return `guest:${id}`;
    } catch {
      res.setHeader('Set-Cookie', `${cookieName}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`);
      throw new RequestError(401, 'Guest session expired or invalid. Reload to start a new session.');
    }
  }
  // Establish identity on page navigation, before parallel API calls can race to mint cookies.
  if (req.method !== 'GET' || req.url.startsWith('/api')) throw new RequestError(401, 'Open Proofseed to start a guest session.');
  const id = randomUUID();
  const data = `${id}.${now}`;
  const signature = sign('RSA-SHA256', Buffer.from(`samurai-guest-v1:${data}`), key).toString('base64url');
  res.setHeader('Set-Cookie', `${cookieName}=${data}.${signature}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${lifetime}`);
  return `guest:${id}`;
}
