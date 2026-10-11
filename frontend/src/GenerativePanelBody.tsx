import { Check, ExternalLink } from 'lucide-react';
import type { Panel } from './model';

export function GenerativePanelBody({ panel, compact, completedTasks, onComplete }: {
  panel: Panel; compact: boolean; completedTasks: string[]; onComplete: (id: string) => void;
}) {
  if (panel.kind === 'evidence') return <div className="evidence-list">{panel.claims.map(claim => <div className="evidence-row" key={claim.id}>
    <span className={`evidence-status ${claim.status}`}>{claim.status === 'needs-check' ? 'Needs checking' : claim.status === 'supported' ? 'Source attached' : 'Hypothesis'}</span>
    <strong>{claim.claim}</strong>{!compact && <p>{claim.detail}</p>}
    {!compact && claim.sources.map(source => <a key={source.url} href={source.url} target="_blank" rel="noopener noreferrer">{source.title}<ExternalLink size={12} /></a>)}
  </div>)}</div>;
  if (panel.kind === 'launch-plan') {
    const completed = panel.tasks.filter(task => completedTasks.includes(JSON.stringify([panel.id, task.id]))).length;
    return <div className="launch-plan"><div className="launch-progress"><span>{completed} of {panel.tasks.length} complete</span><progress aria-label="Launch progress" value={completed} max={panel.tasks.length || 1} /></div>
      {panel.tasks.map(task => {
        const id = JSON.stringify([panel.id, task.id]);
        const done = completedTasks.includes(id);
        return <div className={`launch-task ${done ? 'task-done' : ''}`} key={task.id}><button className="task-check" aria-label={`${done ? 'Reopen' : 'Complete'} ${task.title}`} aria-pressed={done} onClick={() => onComplete(id)}>{done && <Check size={15} />}</button><div><strong>{task.title}</strong><span>{task.timing} · {task.owner}</span>{!compact && <p>{task.detail}</p>}</div></div>;
      })}</div>;
  }
  return null;
}
