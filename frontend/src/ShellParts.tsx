import { ArrowRight, Moon, Sun } from 'lucide-react';
import type { Agent, WorkEvent } from './model';
import type { IdeaArea } from './aspectState';
import { workflowAreas } from './teamAreas';

export type Activity = Extract<WorkEvent, { type: 'activity' }>;
export function TeamPanel({ activities = {}, history = [], expanded = false, executionMode = 'preview', onSelect }: { activities?: Partial<Record<Agent, Activity>>; history?: readonly Activity[]; expanded?: boolean; executionMode?: 'preview' | 'live'; onSelect?: (area: IdeaArea) => void }) {
  return <section className={`team-panel glass ${expanded ? 'team-expanded' : ''}`} aria-label="Idea aspects">
    <div className="panel-heading"><h2>Aspects</h2><span className="tiny-label">{executionMode === 'live' ? 'Live' : 'Preview'}</span></div>
    <div className="activity-list">{workflowAreas.map(aspect => <div key={aspect.id}>
      <button className="activity-row team-open" onClick={() => onSelect?.(aspect.id)}><span><strong>{aspect.name}</strong></span><ArrowRight size={14} /></button>
      {aspect.agent && activities[aspect.agent]?.state === 'working' && <p className="team-open-detail" role="status">{activities[aspect.agent]?.detail}</p>}
      {expanded && <details className="agent-history"><summary>Details</summary><p>{aspect.goal}</p>{history.filter(item => item.agent === aspect.agent).map((item, index) => <p key={index}>{item.detail}</p>)}</details>}
    </div>)}</div>
  </section>;
}
export function ModeToggle({ mode, onToggle }: { mode: 'light' | 'dark'; onToggle: () => void }) {
  return <button className="mode-toggle" onClick={onToggle} aria-label={`Switch to ${mode === 'light' ? 'dark' : 'light'} mode`} title={`${mode === 'light' ? 'Dark' : 'Light'} mode`}>
    {mode === 'light' ? <Moon size={18} /> : <Sun size={18} />}
  </button>;
}
