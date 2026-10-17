import { Code2, Layers3, Lightbulb, Megaphone, Route, Search, Wallet } from 'lucide-react';
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
    <div className="idea-map-heading"><div><h2>One idea. Six perspectives.</h2><p>A starting point, then a conversation. Every aspect stays open.</p></div></div>
    <div className="idea-map">
      <svg className="idea-map-edges" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <ellipse className="idea-orbit-ring" cx="50" cy="51" rx="35" ry="38" />
        {positions.map((point, index) => <path key={index} d={`M50 51 L${point.x} ${point.y}`} />)}
      </svg>
      <button className="idea-map-center" aria-label={`Select idea: ${ideaName}`} title={ideaName} aria-pressed={!areas.length} onClick={() => onSelect('overview')}><span><Lightbulb size={26} strokeWidth={1.6} /></span><strong>{ideaName}</strong><small>Software idea</small></button>
      {workflowAreas.map((aspect, index) => {
        const status = aspectReadiness(aspect.id, workspace);
        const count = aspect.checkpoints.filter(check => workspace.aspectChecks[check.id]?.note.trim()).length;
        const point = positions[index];
        const Icon = icons[aspect.id];
        return <button key={aspect.id} style={{ left: `${point.x}%`, top: `${point.y}%` }} className={`idea-map-node ${point.y === 51 ? 'idea-map-node-side' : ''}`} data-status={status} title={readinessLabels[status]} aria-label={`${aspect.name}: ${readinessLabels[status]}, ${count} of ${aspect.checkpoints.length} starting points filled`} aria-pressed={areas.includes(aspect.id)} onClick={() => onSelect(aspect.id)}>
          <span className="aspect-orbit" aria-hidden="true"><Icon size={20} strokeWidth={1.6} /><span className="readiness-light" /></span>
          <span className="idea-node-copy"><strong className="aspect-full-name">{aspect.name}</strong><strong className="aspect-short-name">{aspect.shortName}</strong></span><small className="idea-node-count" aria-hidden="true">{count}/{aspect.checkpoints.length}</small>
        </button>;
      })}
    </div>
    <div className="idea-map-caption"><p>Bring any aspect into the conversation using the mentor picker in chat.</p><div className="readiness-legend" aria-label="Your readiness assessment">{Object.entries(readinessLabels).map(([status, label]) => <span key={status} data-status={status}><i className="readiness-light" />{label}</span>)}</div></div>
  </section>;
}
