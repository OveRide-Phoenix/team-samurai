const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}';
const uuid = new RegExp(`^${UUID}$`, 'i');
const hash = /^[a-f0-9]{64}$/;
const bodyLimit = 64 * 1024;
const upstreamBase = '/agentos/samurai/workspaces';

export class FounderOperationsRequestError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
const fail = (message = 'Invalid founder operation request.') => { throw new FounderOperationsRequestError(400, message); };
const exact = (value, keys) => value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const text = (value, max) => typeof value === 'string' && value.trim().length > 0 && value.length <= max;
const number = (value, min, max) => typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max;
const metric = value => exact(value, ['name', 'value', 'unit']) && text(value.name, 80) && number(value.value, 0, 1e9) && text(value.unit, 40);
const assumption = value => exact(value, ['name', 'target_metric', 'low_delta_percent', 'base_delta_percent', 'high_delta_percent']) && text(value.name, 80) && text(value.target_metric, 80) && [value.low_delta_percent, value.base_delta_percent, value.high_delta_percent].every(item => number(item, -100, 1000)) && value.low_delta_percent <= value.base_delta_percent && value.base_delta_percent <= value.high_delta_percent;
const constraint = value => exact(value, ['name', 'metric', 'operator', 'threshold', 'unit']) && text(value.name, 80) && text(value.metric, 80) && ['minimum', 'maximum'].includes(value.operator) && number(value.threshold, 0, 1e9) && text(value.unit, 40);

export function founderOperationsRoute(url, method) {
  if (!url.pathname.startsWith('/api/agentos/samurai/workspaces/')) return null;
  const learning = new RegExp(`^/api/agentos/samurai/workspaces/(${UUID})/learning(?:/(${UUID})/supersede)?$`).exec(url.pathname);
  if (learning) {
    if (!uuid.test(learning[1])) fail('Route not available.');
    if (!learning[2] && method === 'GET') {
      const companyIds = url.searchParams.getAll('company_id');
      const history = url.searchParams.getAll('include_history');
      if ([...url.searchParams.keys()].some(key => !['company_id', 'include_history'].includes(key)) || companyIds.length !== 1 || !uuid.test(companyIds[0]) || history.length > 1 || (history.length === 1 && !['true', 'false'].includes(history[0]))) fail('Query not allowed.');
      return { kind: 'founder_operation', path: `${upstreamBase}/${learning[1]}/learning${url.search}` };
    }
    if (method === 'POST' && !url.search) return { kind: 'founder_operation', path: `${upstreamBase}/${learning[1]}/learning${learning[2] ? `/${learning[2]}/supersede` : ''}`, body: learning[2] ? 'learning_supersede' : 'learning_create' };
    fail('Route not available.');
  }
  const schedules = new RegExp(`^/api/agentos/samurai/workspaces/(${UUID})(?:/companies/(${UUID}))?/schedules(?:/(${UUID})(/runs)?)?$`).exec(url.pathname);
  if (schedules) {
    if (url.search) fail('Query not allowed.');
    const [, workspaceId, companyId, scheduleId, runs] = schedules;
    if (companyId && !scheduleId && method === 'POST') return { kind: 'founder_operation', path: `${upstreamBase}/${workspaceId}/companies/${companyId}/schedules`, body: 'schedule_create' };
    if (!companyId && !scheduleId && method === 'GET') return { kind: 'founder_operation', path: `${upstreamBase}/${workspaceId}/schedules` };
    if (!companyId && scheduleId && !runs && method === 'DELETE') return { kind: 'founder_operation', path: `${upstreamBase}/${workspaceId}/schedules/${scheduleId}` };
    if (!companyId && scheduleId && runs && method === 'GET') return { kind: 'founder_operation', path: `${upstreamBase}/${workspaceId}/schedules/${scheduleId}/runs` };
    fail('Route not available.');
  }
  const scenarios = new RegExp(`^/api/agentos/samurai/workspaces/(${UUID})/companies/(${UUID})/scenarios(?:/(${UUID})(/runs|/result)?)?$`).exec(url.pathname);
  if (scenarios) {
    if (url.search) fail('Query not allowed.');
    const [, workspaceId, companyId, scenarioId, action] = scenarios;
    const path = `${upstreamBase}/${workspaceId}/companies/${companyId}/scenarios${scenarioId ? `/${scenarioId}${action ?? ''}` : ''}`;
    if (!scenarioId && method === 'GET') return { kind: 'founder_operation', path };
    if (!scenarioId && method === 'POST') return { kind: 'founder_operation', path, body: 'scenario_create', idempotent: true };
    if (scenarioId && !action && method === 'GET') return { kind: 'founder_operation', path };
    if (scenarioId && action === '/runs' && method === 'POST') return { kind: 'founder_operation', path, body: 'scenario_run', idempotent: true };
    if (scenarioId && action === '/result' && method === 'GET') return { kind: 'founder_operation', path };
    fail('Route not available.');
  }
  return null;
}

export async function founderOperationsBody(req, type) {
  const chunks = []; let length = 0;
  for await (const chunk of req.iterator?.({ destroyOnReturn: false }) ?? req) { length += chunk.length; if (length > bodyLimit) throw new FounderOperationsRequestError(413, 'Request too large.'); chunks.push(chunk); }
  if (req.headers['content-type'] !== 'application/json') throw new FounderOperationsRequestError(415, 'JSON required.');
  let value;
  try { value = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { throw new FounderOperationsRequestError(400, 'Invalid JSON.'); }
  if (type === 'learning_create') {
    if (!exact(value, ['company_id', 'kind', 'source_revision', 'founder_text', 'shared']) || !uuid.test(value.company_id) || !['preference', 'correction'].includes(value.kind) || !Number.isInteger(value.source_revision) || value.source_revision < 0 || !text(value.founder_text, 2000) || typeof value.shared !== 'boolean' || (value.shared && value.kind !== 'correction')) fail();
  } else if (type === 'learning_supersede') {
    if (!exact(value, ['company_id', 'source_revision', 'founder_text', 'shared']) || !uuid.test(value.company_id) || !Number.isInteger(value.source_revision) || value.source_revision < 0 || !text(value.founder_text, 2000) || typeof value.shared !== 'boolean') fail();
  } else if (type === 'schedule_create') {
    if (!exact(value, ['cadence', 'timezone', 'first_run_at', 'pinned_revision', 'action_kind', 'payload']) || !['once', 'daily', 'weekly'].includes(value.cadence) || !text(value.timezone, 100) || !text(value.first_run_at, 100) || Number.isNaN(Date.parse(value.first_run_at)) || !Number.isInteger(value.pinned_revision) || value.pinned_revision < 0 || !['workspace_review', 'scenario_recompute'].includes(value.action_kind)) fail();
    if (value.action_kind === 'workspace_review' ? !exact(value.payload, []) : !exact(value.payload, ['scenario_id']) || !uuid.test(value.payload.scenario_id)) fail();
  } else if (type === 'scenario_create') {
    if (!exact(value, ['title', 'company_revision', 'company_state_sha256', 'horizon_days', 'baseline_metrics', 'assumptions', 'constraints']) || !text(value.title, 200) || !Number.isInteger(value.company_revision) || value.company_revision < 0 || !hash.test(value.company_state_sha256) || !Number.isInteger(value.horizon_days) || value.horizon_days < 1 || value.horizon_days > 365 || !Array.isArray(value.baseline_metrics) || value.baseline_metrics.length < 1 || value.baseline_metrics.length > 20 || !value.baseline_metrics.every(metric) || !Array.isArray(value.assumptions) || value.assumptions.length < 1 || value.assumptions.length > 10 || !value.assumptions.every(assumption) || !Array.isArray(value.constraints) || value.constraints.length < 1 || value.constraints.length > 10 || !value.constraints.every(constraint)) fail();
  } else if (type === 'scenario_run') {
    if (!exact(value, [])) fail();
  } else fail();
  return JSON.stringify(value);
}

export function founderOperationsHeaders(req, selected) {
  const headers = { 'content-type': 'application/json' };
  if (selected.idempotent) {
    const key = req.headers['x-samurai-submission-id'];
    if (typeof key !== 'string' || !uuid.test(key)) fail('Valid submission id required.');
    headers['idempotency-key'] = key;
  }
  return headers;
}

export async function founderOperationsError(response) {
  try {
    const value = await response.json();
    return exact(value, ['detail']) && text(value.detail, 2000) ? value.detail : 'Founder operation denied.';
  } catch {
    return 'Founder operation denied.';
  }
}
