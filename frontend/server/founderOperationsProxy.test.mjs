import { Readable } from 'node:stream';
import { describe, expect, it } from 'vitest';
import { founderOperationsBody, founderOperationsError, founderOperationsHeaders, founderOperationsRoute } from './founderOperationsProxy.mjs';

const workspace = '00000000-0000-4000-8000-000000000001';
const company = '00000000-0000-4000-8000-000000000002';
const scenario = '00000000-0000-4000-8000-000000000003';
const request = value => Object.assign(Readable.from([Buffer.from(JSON.stringify(value))]), { headers: { 'content-type': 'application/json' } });

describe('founder operations BFF allowlist', () => {
  it('allows only exact recovery routes and bounded queries', () => {
    expect(founderOperationsRoute(new URL(`http://local/api/agentos/samurai/workspaces/${workspace}/companies/${company}/scenarios`), 'GET')).toMatchObject({ path: `/agentos/samurai/workspaces/${workspace}/companies/${company}/scenarios` });
    expect(founderOperationsRoute(new URL(`http://local/api/agentos/samurai/workspaces/${workspace}/schedules/${scenario}/runs`), 'GET')).toMatchObject({ path: `/agentos/samurai/workspaces/${workspace}/schedules/${scenario}/runs` });
    expect(founderOperationsRoute(new URL(`http://local/api/agentos/samurai/workspaces/${workspace}/companies/${company}/scenarios/${scenario}/result`), 'GET')).toMatchObject({ optional: true });
    expect(() => founderOperationsRoute(new URL(`http://local/api/agentos/samurai/workspaces/${workspace}/learning?company_id=${company}&owner=forged`), 'GET')).toThrow('Query not allowed.');
  });

  it('forwards idempotency only from a canonical submission header', () => {
    const selected = founderOperationsRoute(new URL(`http://local/api/agentos/samurai/workspaces/${workspace}/companies/${company}/scenarios/${scenario}/runs`), 'POST');
    expect(founderOperationsHeaders({ headers: { 'x-samurai-submission-id': scenario } }, selected)).toEqual({ 'content-type': 'application/json', 'idempotency-key': scenario });
    expect(() => founderOperationsHeaders({ headers: { 'idempotency-key': scenario } }, selected)).toThrow('Valid submission id required.');
  });

  it('rejects unknown scenario fields and accepts only the persisted empty run body', async () => {
    const route = founderOperationsRoute(new URL(`http://local/api/agentos/samurai/workspaces/${workspace}/companies/${company}/scenarios/${scenario}/runs`), 'POST');
    await expect(founderOperationsBody(request({ result: 'forged' }), route.body)).rejects.toThrow('Invalid founder operation request.');
    await expect(founderOperationsBody(request({}), route.body)).resolves.toBe('{}');
  });

  it('retains a bounded API detail without exposing arbitrary response fields', async () => {
    await expect(founderOperationsError(new Response(JSON.stringify({ detail: 'Scenario result was not found.' })))).resolves.toBe('Scenario result was not found.');
    await expect(founderOperationsError(new Response(JSON.stringify({ detail: 'Denied', debug: 'secret' })))).resolves.toBe('Founder operation denied.');
  });
});
