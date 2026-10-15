import type { Panel } from './model';

type ScenarioPanel = Extract<Panel, { kind: 'scenario' }>;
const display = (value: number | string) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });

export function ScenarioPanelBody({ panel }: { readonly panel: ScenarioPanel }) {
  return <div className="scenario-result">
    <div className="scenario-warning" role="note"><strong>Synthetic scenario, not validation</strong><span>These values come from your assumptions. They are not observed demand or measured outcomes.</span></div>
    <div className="scenario-grid" aria-label="Low, base, and high scenario results">{panel.trajectories.map(trajectory => <section key={trajectory.label}><span>{trajectory.label}</span>{trajectory.metrics.map(metric => <div key={metric.metric}><strong>{display(metric.points[1].value)}</strong><small>{metric.metric.replaceAll('_', ' ')} · {metric.unit}</small></div>)}</section>)}</div>
    <details className="panel-details"><summary>Assumptions and formulas</summary><dl>{panel.assumptions.map(item => <div key={item.name}><dt>{item.name.replaceAll('_', ' ')}</dt><dd>{display(item.low_delta_percent)}% / {display(item.base_delta_percent)}% / {display(item.high_delta_percent)}%</dd></div>)}</dl>{panel.formulas.map(formula => <p key={formula.metric}><strong>{formula.metric.replaceAll('_', ' ')}:</strong> {formula.expression} · baseline {display(formula.baseline_input)}</p>)}</details>
    <details className="panel-details"><summary>Constraint checks</summary>{panel.constraints.length === 0 ? <p>No constraints were evaluated.</p> : <ul className="scenario-constraints">{panel.constraints.map(item => <li key={`${item.constraint}-${item.label}`} data-violated={item.violated}><strong>{item.label}</strong> {item.metric.replaceAll('_', ' ')} {item.operator} {display(item.threshold)} {item.unit}: {display(item.actual)} {item.violated ? '· outside constraint' : '· within constraint'}</li>)}</ul>}</details>
    <p className="scenario-provenance">{panel.synthetic_label} · company revision {panel.company_revision} · result {panel.result_sha256.slice(0, 12)}</p>
  </div>;
}
