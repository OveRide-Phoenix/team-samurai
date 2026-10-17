import { ArrowUpRight, Code2, Layers3, Lightbulb, Megaphone, Route, Search, Wallet } from 'lucide-react';
import { aspectReadiness, workflowAreas } from './teamAreas';
import { readinessLabels, type IdeaArea } from './aspectState';
import type { WorkflowArea, Workspace } from './model';
import './idea-aspects.css';

const positions = [{ x: 25, y: 18 }, { x: 75, y: 18 }, { x: 85, y: 51 }, { x: 75, y: 84 }, { x: 25, y: 84 }, { x: 15, y: 51 }] as const;
const icons = { research: Search, market: Layers3, sales: Megaphone, strategy: Code2, resources: Wallet, verification: Route };

export function TeamNavigation({ areas, workspace, ideaName, onSelect }: {
  readonly areas: readonly WorkflowArea[]; readonly workspace: Workspace; readonly ideaName: string; readonly onSelect: (area: IdeaArea) => void;
}) {
  return <section className="idea-map-shell" aria-label="Idea aspect map">
    <div className="idea-map-heading"><div><h2>Explore your idea</h2><p>Six connected aspects. Start anywhere.</p></div><span className="tiny-label">Your thinking space</span></div>
    <div className="idea-map">
      <svg className="idea-map-edges" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        {positions.map((point, index) => <path key={index} d={`M50 51 Q50 ${point.y} ${point.x} ${point.y}`} />)}
        {workflowAreas.flatMap((aspect, index) => aspect.related.flatMap(id => {
          const targetIndex = workflowAreas.findIndex(item => item.id === id);
          const source = positions[index], target = positions[targetIndex];
          return targetIndex > index ? [<line key={`${aspect.id}-${id}`} className="idea-soft-link" x1={source.x} y1={source.y} x2={target.x} y2={target.y} />] : [];
        }))}
      </svg>
      <button className="idea-map-center" aria-label={`Show idea overview: ${ideaName}`} title={ideaName} aria-pressed={!areas.length} onClick={() => onSelect('overview')}><span><Lightbulb size={26} strokeWidth={1.6} /></span><strong>{ideaName}</strong><small>Software idea</small></button>
      {workflowAreas.map((aspect, index) => {
        const status = aspectReadiness(aspect.id, workspace);
        const count = aspect.checkpoints.filter(check => workspace.aspectChecks[check.id]?.status === 'ready').length;
        const point = positions[index];
        const Icon = icons[aspect.id];
        return <button key={aspect.id} className={`idea-map-node ${point.y === 51 ? 'idea-map-node-side' : ''}`} style={{ left: `${point.x}%`, top: `${point.y}%` }} data-status={status} aria-label={`${aspect.name}: ${readinessLabels[status]}, ${count} of ${aspect.checkpoints.length} checkpoints ready`} aria-pressed={areas.includes(aspect.id)} aria-controls="aspect-detail" onClick={() => onSelect(aspect.id)}>
          <span className="aspect-orbit" aria-hidden="true"><Icon size={20} strokeWidth={1.6} /><span className="readiness-light" /></span>
          <span className="idea-node-copy"><strong className="aspect-full-name">{aspect.name}</strong><strong className="aspect-short-name">{aspect.shortName}</strong><span className="idea-node-progress"><span className="idea-check-marks" aria-hidden="true">{aspect.checkpoints.map(check => <i key={check.id} data-status={workspace.aspectChecks[check.id]?.status ?? 'in-progress'} className={workspace.aspectChecks[check.id]?.status === 'ready' ? 'is-ready' : ''} />)}</span><small>{count}/{aspect.checkpoints.length} ready</small></span></span><ArrowUpRight className="idea-node-arrow" size={14} aria-hidden="true" />
        </button>;
      })}
    </div>
    <div className="idea-map-caption"><p>Explore in any order. Connections share context, never lock a conversation.</p><div className="readiness-legend" aria-label="Your readiness assessment">{Object.entries(readinessLabels).map(([status, label]) => <span key={status} data-status={status}><i className="readiness-light" />{label}</span>)}</div></div>
  </section>;
}
