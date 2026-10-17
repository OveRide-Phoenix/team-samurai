import { useState } from 'react';
import type { Panel } from './model';
import { ScenarioLines } from './PanelCharts';

type ScenarioPanel = Extract<Panel, { kind: 'scenario' }>;
const display = (value: number | string) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });

export function ScenarioPanelBody({ panel }: { readonly panel: ScenarioPanel }) {
  const [selected, setSelected] = useState(0);
  const metric = panel.trajectories[0].metrics[selected] || panel.trajectories[0].metrics[0];
  const trajectories = panel.trajectories.flatMap(trajectory => { const value = trajectory.metrics.find(item => item.metric === metric.metric && item.unit === metric.unit); return value ? [{ label: trajectory.label, points: value.points }] : []; });
  return <div className="scenario-result">
    <div className="scenario-warning" role="note"><strong>Synthetic scenario, not validation</strong></div>
    {panel.trajectories[0].metrics.length > 1 && <label className="scenario-metric">Compare <select value={selected} onChange={event => setSelected(Number(event.target.value))}>{panel.trajectories[0].metrics.map((item, index) => <option key={item.metric} value={index}>{item.metric.replaceAll('_', ' ')} · {item.unit}</option>)}</select></label>}
    <p className="scenario-chart-label">{metric.metric.replaceAll('_', ' ')} · {metric.unit}</p>
    <ScenarioLines trajectories={trajectories} horizon={panel.horizon_days} />
    <div className="scenario-grid" aria-label="Low, base, and high scenario results">{panel.trajectories.map(trajectory => <section key={trajectory.label}><span>{trajectory.label}</span>{trajectory.metrics.filter(item => item.metric === metric.metric && item.unit === metric.unit).map(metric => <div key={metric.metric}><strong>{display(metric.points[1].value)}</strong></div>)}</section>)}</div>
    <details className="panel-details"><summary>Assumptions and formulas</summary><p>These values come from your assumptions. They are not observed demand or measured outcomes.</p><dl>{panel.assumptions.map(item => <div key={item.name}><dt>{item.name.replaceAll('_', ' ')}</dt><dd>{display(item.low_delta_percent)}% / {display(item.base_delta_percent)}% / {display(item.high_delta_percent)}%</dd></div>)}</dl>{panel.formulas.map(formula => <p key={formula.metric}><strong>{formula.metric.replaceAll('_', ' ')}:</strong> {formula.expression} · baseline {display(formula.baseline_input)}</p>)}</details>
    <details className="panel-details"><summary>Constraint checks</summary>{panel.constraints.length === 0 ? <p>No constraints were evaluated.</p> : <ul className="scenario-constraints">{panel.constraints.map(item => <li key={`${item.constraint}-${item.label}`} data-violated={item.violated}><strong>{item.label}</strong> {item.metric.replaceAll('_', ' ')} {item.operator} {display(item.threshold)} {item.unit}: {display(item.actual)} {item.violated ? '· outside constraint' : '· within constraint'}</li>)}</ul>}</details>
    <details className="panel-details"><summary>Result details</summary><p className="scenario-provenance">{panel.synthetic_label} · company revision {panel.company_revision} · result {panel.result_sha256.slice(0, 12)}</p></details>
  </div>;
}
