import { useEffect, useState, type FormEvent } from 'react';
import { Brain, CalendarClock, FlaskConical, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { createLearning, createScenario, createSchedule, disableSchedule, getScenarioResult, listLearning, listScheduleRuns, listSchedules, listScenarios, runScenario, scenarioPanel, supersedeLearning, type LearningRecord, type ScenarioDefinition, type Schedule, type ScheduleRun } from './founderOperations';
import { GenerativePanelBody } from './GenerativePanelBody';

type Props = { readonly workspaceId: string; readonly companyId: string; readonly revision: number; readonly stateSha256: string; readonly readOnly: boolean };
const inputValue = (form: FormData, name: string) => String(form.get(name) ?? '').trim();

export function FounderOperationsPanel({ workspaceId, companyId, revision, stateSha256, readOnly }: Props) {
  const [learning, setLearning] = useState<LearningRecord[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [runs, setRuns] = useState<Record<string, ScheduleRun[]>>({});
  const [scenarios, setScenarios] = useState<ScenarioDefinition[]>([]);
  const [panel, setPanel] = useState<ReturnType<typeof scenarioPanel>>();
  const [status, setStatus] = useState('Loading founder operations…');
  const [pending, setPending] = useState(false);
  const refresh = async () => {
    setStatus('Refreshing founder operations…');
    try {
      const [context, savedSchedules, savedScenarios] = await Promise.all([listLearning(workspaceId, companyId), listSchedules(workspaceId), listScenarios(workspaceId, companyId)]);
      const companySchedules = savedSchedules.filter(item => item.company_id === companyId);
      setLearning(context.records); setSchedules(companySchedules); setScenarios(savedScenarios);
      const receipts = await Promise.all(companySchedules.map(async item => [item.schedule_id, await listScheduleRuns(workspaceId, item.schedule_id)] as const));
      setRuns(Object.fromEntries(receipts));
      for (const definition of savedScenarios) {
        const result = await getScenarioResult(workspaceId, companyId, definition.scenario_id);
        if (result) { setPanel(scenarioPanel(definition, result)); break; }
      }
      setStatus('Founder operations are up to date.');
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Request failed.'); }
  };
  useEffect(() => { void refresh(); }, [workspaceId, companyId]);
  const submit = async (action: () => Promise<void>, success: string) => {
    if (readOnly || pending) return;
    setPending(true); setStatus('Saving…');
    try { await action(); await refresh(); setStatus(success); }
    catch (error) { setStatus(error instanceof Error ? error.message : 'Request failed.'); }
    finally { setPending(false); }
  };
  const saveLearning = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement);
    void submit(async () => { await createLearning(workspaceId, { company_id: companyId, kind: inputValue(form, 'kind') === 'correction' ? 'correction' : 'preference', source_revision: revision, founder_text: inputValue(form, 'founder_text'), shared: form.get('shared') === 'on' }); formElement.reset(); }, 'Learning saved as untrusted preference context.');
  };
  const replaceLearning = (record: LearningRecord) => {
    const replacement = window.prompt('Replacement founder statement', record.founder_text);
    if (!replacement?.trim()) return;
    void submit(async () => { await supersedeLearning(workspaceId, record.learning_id, { company_id: companyId, source_revision: revision, founder_text: replacement.trim(), shared: record.shared }); }, 'Learning superseded; history retained.');
  };
  const saveScenario = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement); const metric = inputValue(form, 'metric').toLowerCase().replaceAll(' ', '_'); const unit = inputValue(form, 'unit').toLowerCase().replaceAll(' ', '_');
    void submit(async () => { await createScenario(workspaceId, companyId, { title: inputValue(form, 'title'), company_revision: revision, company_state_sha256: stateSha256, horizon_days: Number(inputValue(form, 'days')), baseline_metrics: [{ name: metric, value: Number(inputValue(form, 'value')), unit }], assumptions: [{ name: `${metric}_change`, target_metric: metric, low_delta_percent: Number(inputValue(form, 'low')), base_delta_percent: Number(inputValue(form, 'base')), high_delta_percent: Number(inputValue(form, 'high')) }], constraints: [{ name: `${metric}_limit`, metric, operator: inputValue(form, 'operator') === 'maximum' ? 'maximum' : 'minimum', threshold: Number(inputValue(form, 'threshold')), unit }] }); formElement.reset(); }, 'Scenario definition saved.');
  };
  const executeScenario = (definition: ScenarioDefinition) => void submit(async () => { setPanel(scenarioPanel(definition, await runScenario(workspaceId, companyId, definition.scenario_id))); }, 'Synthetic scenario result saved.');
  const saveSchedule = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement); const scenarioId = inputValue(form, 'scenario_id'); const common = { cadence: inputValue(form, 'cadence') === 'daily' ? 'daily' as const : inputValue(form, 'cadence') === 'weekly' ? 'weekly' as const : 'once' as const, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, first_run_at: new Date(inputValue(form, 'first_run_at')).toISOString(), pinned_revision: revision };
    void submit(async () => { await createSchedule(workspaceId, companyId, scenarioId ? { ...common, action_kind: 'scenario_recompute', payload: { scenario_id: scenarioId } } : { ...common, action_kind: 'workspace_review', payload: {} }); formElement.reset(); }, 'Schedule saved.');
  };
  return <section className="business-panel operations-panel" aria-label="Founder operations">
    <div className="panel-heading"><div className="panel-title"><span className="panel-icon"><RefreshCw size={16} /></span><h3>Founder operations</h3></div><button className="icon-button" onClick={() => void refresh()} disabled={pending} aria-label="Refresh founder operations"><RefreshCw size={14} /></button></div>
    <p className="file-status" role="status">{status}</p>
    <details open><summary><Brain size={14} />Learning</summary><form className="operations-form" onSubmit={saveLearning}><label>Statement<textarea name="founder_text" required maxLength={2000} disabled={readOnly || pending} /></label><div className="operations-row"><label>Type<select name="kind" disabled={readOnly || pending}><option value="preference">Preference</option><option value="correction">Correction</option></select></label><label className="check-field"><input name="shared" type="checkbox" disabled={readOnly || pending} />Share correction</label><button className="soft-button" disabled={readOnly || pending}><Plus size={14} />Save</button></div></form>{learning.length === 0 ? <p className="empty-note">No explicit learning saved.</p> : <ul className="operations-list">{learning.map(item => <li key={item.learning_id}><div><strong>{item.kind}</strong><span>{item.founder_text}</span><small>{item.shared ? 'Shared correction' : 'Private to you'} · untrusted preference context</small></div><button className="soft-button" onClick={() => replaceLearning(item)} disabled={readOnly || pending}>Replace</button></li>)}</ul>}</details>
    <details><summary><FlaskConical size={14} />Scenarios</summary><p className="scenario-inline-warning">Synthetic scenarios are assumption checks, not validation or observed demand.</p><form className="operations-form" onSubmit={saveScenario}><fieldset disabled={readOnly || pending}><label>Title<input name="title" required maxLength={200} /></label><div className="operations-grid"><label>Metric<input name="metric" required defaultValue="monthly revenue" /></label><label>Baseline<input name="value" type="number" min="0" step="any" required /></label><label>Unit<input name="unit" required defaultValue="INR" /></label><label>Days<input name="days" type="number" min="1" max="365" defaultValue="30" required /></label><label>Low %<input name="low" type="number" min="-100" max="1000" defaultValue="-20" required /></label><label>Base %<input name="base" type="number" min="-100" max="1000" defaultValue="0" required /></label><label>High %<input name="high" type="number" min="-100" max="1000" defaultValue="20" required /></label><label>Constraint<select name="operator"><option value="minimum">Minimum</option><option value="maximum">Maximum</option></select></label><label>Threshold<input name="threshold" type="number" min="0" step="any" required /></label></div><button className="soft-button"><Plus size={14} />Save scenario</button></fieldset></form><ul className="operations-list">{scenarios.map(item => <li key={item.scenario_id}><div><strong>{item.title}</strong><small>{item.horizon_days} days · revision {item.company_revision}</small></div><button className="soft-button" onClick={() => executeScenario(item)} disabled={readOnly || pending}>Run</button></li>)}</ul>{panel && <div className="operations-result"><GenerativePanelBody panel={panel} compact={false} completedTasks={[]} onComplete={() => undefined} /></div>}</details>
    <details><summary><CalendarClock size={14} />Schedules</summary><form className="operations-form" onSubmit={saveSchedule}><fieldset disabled={readOnly || pending}><div className="operations-grid"><label>First run<input name="first_run_at" type="datetime-local" required /></label><label>Cadence<select name="cadence"><option value="once">Once</option><option value="daily">Daily</option><option value="weekly">Weekly</option></select></label><label>Action<select name="scenario_id"><option value="">Workspace review</option>{scenarios.map(item => <option key={item.scenario_id} value={item.scenario_id}>Recompute: {item.title}</option>)}</select></label></div><button className="soft-button"><Plus size={14} />Save schedule</button></fieldset></form><ul className="operations-list">{schedules.map(item => <li key={item.schedule_id}><div><strong>{item.action_kind.replaceAll('_', ' ')}</strong><span>{item.cadence} · {item.enabled ? 'enabled' : 'disabled'}</span><small>{runs[item.schedule_id]?.[0] ? `Last run: ${runs[item.schedule_id][0].status}${runs[item.schedule_id][0].error_code ? ` · ${runs[item.schedule_id][0].error_code}` : ''}` : 'No run receipt yet'}</small></div>{item.enabled && <button className="icon-button" onClick={() => void submit(async () => { await disableSchedule(workspaceId, item.schedule_id); }, 'Schedule disabled.')} disabled={readOnly || pending} aria-label="Disable schedule"><Trash2 size={14} /></button>}</li>)}</ul></details>
  </section>;
}
