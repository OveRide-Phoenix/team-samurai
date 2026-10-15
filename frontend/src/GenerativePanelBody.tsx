import { StandardPanelBody } from './StandardPanelBody';
import { lazy, Suspense } from 'react';
const DeclarativePanel = lazy(() => import('./DeclarativePanel').then(module => ({ default: module.DeclarativePanel })));
import { CustomPanel } from './CustomPanel';
import type { Panel } from './model';

type StandardPanel = Exclude<Panel, { kind: 'custom' | 'declarative' }>;

function FounderContext({ context }: { context: NonNullable<StandardPanel['founder_context']> }) {
  return <aside className="founder-context" aria-label="Founder decision context">
    {context.next_decision && <div className="founder-next-decision"><span className="panel-kicker">Next decision</span><strong>{context.next_decision}</strong></div>}
    {context.evidence_gaps.length > 0 && <div className="founder-evidence-gaps"><span className="panel-kicker">Evidence still needed</span><p>{context.evidence_gaps[0]}</p>{context.evidence_gaps.length > 1 && <details className="panel-details"><summary>More evidence to collect ({context.evidence_gaps.length - 1})</summary><ul>{context.evidence_gaps.slice(1).map(gap => <li key={gap}>{gap}</li>)}</ul></details>}</div>}
    {context.framework && <details className="panel-details founder-attribution"><summary>Framework attribution</summary><p>{context.framework.attribution}</p><a href={context.framework.source_url} target="_blank" rel="noopener noreferrer">{context.framework.id} {context.framework.version}</a></details>}
  </aside>;
}

export function GenerativePanelBody({ panel, compact, completedTasks, onComplete, mode = 'light', shortlisted = [], onShortlist = () => undefined, approved = false, onApprove = () => undefined, onDiscuss, workspaceId }: {
  panel: Panel; mode?: 'light' | 'dark'; compact: boolean; completedTasks: string[]; onComplete: (id: string) => void;
  shortlisted?: string[]; onShortlist?: (id: string) => void; approved?: boolean; onApprove?: () => void; onDiscuss?: (prompt: string) => void; workspaceId?: string;
}) {
  if (panel.kind === 'declarative') return <Suspense fallback={<p>Preparing view…</p>}><DeclarativePanel panel={panel} /></Suspense>;
  if (panel.kind === 'custom') return <CustomPanel mode={mode} panel={panel} compact={compact} />;
  return <><StandardPanelBody panel={panel} compact={compact} completedTasks={completedTasks} onComplete={onComplete} shortlisted={shortlisted} onShortlist={onShortlist} approved={approved} onApprove={onApprove} onDiscuss={onDiscuss} workspaceId={workspaceId} />{panel.founder_context && <FounderContext context={panel.founder_context} />}</>;
}
