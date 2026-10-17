import { StandardPanelBody, FounderContext } from './StandardPanelBody';
import { lazy, Suspense } from 'react';
const DeclarativePanel = lazy(() => import('./DeclarativePanel').then(module => ({ default: module.DeclarativePanel })));
import { CustomPanel } from './CustomPanel';
import type { Panel } from './model';
import { ScenarioPanelBody } from './ScenarioPanelBody';

export function GenerativePanelBody({ panel, compact, completedTasks, onComplete, mode = 'light', shortlisted = [], onShortlist = () => undefined, approved = false, onApprove = () => undefined, onDiscuss, workspaceId }: {
  panel: Panel; mode?: 'light' | 'dark'; compact: boolean; completedTasks: string[]; onComplete: (id: string) => void;
  shortlisted?: string[]; onShortlist?: (id: string) => void; approved?: boolean; onApprove?: () => void; onDiscuss?: (prompt: string) => void; workspaceId?: string;
}) {
  if (panel.kind === 'declarative') return <Suspense fallback={<p>Preparing view…</p>}><DeclarativePanel panel={panel} /></Suspense>;
  if (panel.kind === 'custom') return <CustomPanel mode={mode} panel={panel} compact={compact} />;
  if (panel.kind === 'scenario') return <ScenarioPanelBody panel={panel} />;
  return <><StandardPanelBody panel={panel} compact={compact} completedTasks={completedTasks} onComplete={onComplete} shortlisted={shortlisted} onShortlist={onShortlist} approved={approved} onApprove={onApprove} onDiscuss={onDiscuss} workspaceId={workspaceId} />{panel.founder_context && !(panel.kind === 'evidence' && panel.title === 'Company brief') && <FounderContext context={panel.founder_context} />}</>;
}
