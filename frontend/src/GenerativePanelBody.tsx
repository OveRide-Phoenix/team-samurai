import { Check, ExternalLink } from 'lucide-react';
import type { Panel } from './model';

export function GenerativePanelBody({ panel, compact, completedTasks, onComplete }: {
  panel: Panel; compact: boolean; completedTasks: string[]; onComplete: (id: string) => void;
}) {
  if (panel.kind === 'evidence') {
    const brief = panel.title === 'Company brief';
    if (brief) {
      const fields = panel.claims.map(claim => { const index = claim.claim.indexOf(':'); return index < 0 ? { label: 'Context', value: claim.claim } : { label: claim.claim.slice(0, index), value: claim.claim.slice(index + 1).trim() }; });
      const primary = fields.filter(field => ['Idea', 'First customers', 'Market', 'Budget', 'Founder skills', 'First milestone'].includes(field.label));
      const extra = fields.filter(field => !primary.includes(field));
      return <div className="company-brief"><dl>{primary.map(field => <div key={field.label}><dt>{field.label === 'Founder skills' ? 'Skills & resources' : field.label}</dt><dd>{field.value}</dd></div>)}</dl>{extra.length > 0 && <details className="panel-details"><summary>Details</summary><dl>{extra.map(field => <div key={field.label}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl></details>}</div>;
    }
    const findings = panel.claims.filter(claim => !/^(info|warning|error):/.test(claim.detail));
    const support = findings.filter(claim => claim.detail && !['Assumption, not sourced fact', 'Research summary; see individual source-backed findings'].includes(claim.detail)).filter((claim, index, entries) => /^(unverified|supported|contradicted);/.test(claim.detail) || entries.findIndex(entry => entry.detail === claim.detail) === index);
    const warnings = panel.claims.filter(claim => /^(warning|error):/.test(claim.detail));
    const render = (claim: typeof panel.claims[number]) => <div className="evidence-row" key={claim.id}>{claim.claim.length > 240 ? <details className="evidence-reading"><summary><strong>{claim.claim.slice(0, 200)}…</strong><span>Read more</span></summary><p>{claim.claim}</p></details> : <strong>{claim.claim}</strong>}{!compact && claim.sources.slice(0, 2).map(source => <a key={source.url} href={source.url} target="_blank" rel="noopener noreferrer">{source.title}<ExternalLink size={12} /></a>)}{!compact && claim.sources.length > 2 && <details className="panel-details"><summary>More sources</summary>{claim.sources.slice(2).map(source => <a key={source.url} href={source.url} target="_blank" rel="noopener noreferrer">{source.title}<ExternalLink size={12} /></a>)}</details>}</div>;
    return <div className="evidence-list"><p className="evidence-summary">{panel.claims.some(claim => claim.sources.length) ? panel.claims.some(claim => claim.status !== 'supported') ? 'Sources collected · Some findings need review' : 'Source-supported findings' : 'Working assumptions · Evidence still needed'}</p>{findings.slice(0, 3).map(render)}{(findings.length > 3 || warnings.length > 0 || support.length > 0) && <details className="panel-details"><summary>Details</summary>{findings.slice(3).map(render)}{warnings.map(claim => <p key={claim.id}>{claim.claim}</p>)}{support.map(claim => <div className="evidence-row" key={`support-${claim.id}`}><strong>{claim.detail.startsWith('contradicted;') ? 'Conflicting evidence' : /^(unverified|supported);/.test(claim.detail) ? 'Source support' : 'Context'}</strong><p className="source-support-claim">{claim.claim}</p><p>{claim.detail.replace(/^(unverified|supported|contradicted); (mapped|unmapped)\.\s*/, '') || 'Source support has not been retained for this finding.'}</p></div>)}</details>}</div>;
  }
  if (panel.kind === 'launch-plan') {
    const completed = panel.tasks.filter(task => completedTasks.includes(JSON.stringify([panel.id, task.id]))).length;
    return <div className="launch-plan"><div className="launch-progress"><span>{completed} of {panel.tasks.length} complete</span><progress aria-label="Launch progress" value={completed} max={panel.tasks.length || 1} /></div>
      {(() => {
        const render = (task: typeof panel.tasks[number]) => {
          const id = JSON.stringify([panel.id, task.id]);
          const done = completedTasks.includes(id);
          return <div className={`launch-task ${done ? 'task-done' : ''}`} key={task.id}><button className="task-check" aria-label={`${done ? 'Reopen' : 'Complete'} ${task.title}`} aria-pressed={done} onClick={() => onComplete(id)}>{done && <Check size={15} />}</button><div><strong>{task.title}</strong>{task.timing !== 'Not scheduled' && <span>{task.timing} · {task.owner}</span>}{!compact && !['complete', 'needs_rework', 'needs_input', 'draft_only'].includes(task.detail) && <p>{task.detail}</p>}</div></div>;
        };
        return <>{panel.tasks.slice(0, 3).map(render)}{panel.tasks.length > 3 && <details className="panel-details"><summary>More steps ({panel.tasks.length - 3})</summary>{panel.tasks.slice(3).map(render)}</details>}</>;
      })()}</div>;
  }
  return null;
}
