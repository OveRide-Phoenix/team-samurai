import { Compass, LoaderCircle, Search, ShieldCheck, Users } from 'lucide-react';
import { LiquidBackdrop } from './LiquidBackdrop';
import { workflowAreas } from './teamAreas';
import type { Activity } from './ShellParts';
import type { Agent, WorkflowArea } from './model';

export function TeamNavigation({ areas, onToggle, activities, executionMode }: {
  areas: readonly WorkflowArea[]; onToggle: (area: WorkflowArea) => void;
  activities: Partial<Record<Agent, Activity>>; executionMode: 'preview' | 'live';
}) {
  const icons = { research: Search, strategy: Compass, verification: ShieldCheck, sales: Users };
  return <section className="team-navigation" aria-label="Team workspace">
    <div className="team-switch">
      <LiquidBackdrop radius={32} displacementScale={55} />
      <div role="group" aria-label="Workflow filters" className="team-tabs">{workflowAreas.map(item => {
        const working = item.agent && activities[item.agent]?.state === 'working';
        const Icon = working ? LoaderCircle : icons[item.id];
        return <button key={item.id} type="button" className="workflow-toggle" aria-pressed={areas.includes(item.id)} aria-controls="team-area-content" onClick={() => onToggle(item.id)}><span className="team-tab-icon"><Icon size={16} className={working ? 'spin' : undefined} /></span><span>{item.name}</span>{working && <span className="sr-only">Working</span>}</button>;
      })}</div>
    </div><span className="tiny-label team-mode">{executionMode === 'live' ? 'Live' : 'Preview'}</span>
  </section>;
}
