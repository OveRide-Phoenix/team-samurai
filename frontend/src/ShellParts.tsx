import { Check, Compass, LoaderCircle, Moon, Clock3, Search, ShieldCheck, Sun, Users } from 'lucide-react';
import { agents, type Agent, type WorkEvent, type TeamArea } from './model';
import { teamAreas } from './teamAreas';

export type Activity = Extract<WorkEvent, { type: 'activity' }>;
const agentRoles: Record<Agent, string> = {
  Researcher: 'Explore competitors, customer problems and market evidence.',
  Strategist: 'Shape your offer, positioning and pricing from the evidence.',
  Verifier: 'Check source support and flag assumptions or conflicting claims.',
  Sales: 'Identify prospects and prepare outreach to test your offer.',
};
export function TeamPanel({ activities = {}, history = [], expanded = false, executionMode = 'preview', onSelect }: { activities?: Partial<Record<Agent, Activity>>; history?: readonly Activity[]; expanded?: boolean; executionMode?: 'preview' | 'live'; onSelect?: (area: TeamArea) => void }) {
  return <section className={`team-panel glass ${expanded ? 'team-expanded' : ''}`} aria-label="Team activity">
    <div className="panel-heading"><h2>Team</h2><span className="tiny-label">{executionMode === 'live' ? 'Live' : 'Preview'}</span></div>
    <div className="activity-list" aria-live="polite">{agents.map(agent => {
      const activity = activities[agent];
      if (onSelect) return <button className="activity-row team-open" key={agent} onClick={() => onSelect(teamAreas.find(item => item.agent === agent)!.id)}><span className="agent-symbol">{agent === 'Verifier' ? <ShieldCheck size={16} /> : agent === 'Sales' ? <Users size={16} /> : agent === 'Strategist' ? <Compass size={16} /> : <Search size={16} />}</span><span><strong>{agent}</strong>{activity && <span className="team-open-detail">{activity.detail}</span>}</span></button>;
      return <details className="agent-activity" key={agent}><summary className="activity-row"><span className={`agent-symbol ${activity?.state === 'working' ? 'working' : ''}`}>
        {activity?.state === 'waiting' ? <Clock3 size={16} /> : activity?.state === 'working' ? <LoaderCircle size={16} className="spin" /> : activity?.state === 'done' ? <Check size={16} /> : agent === 'Verifier' ? <ShieldCheck size={16} /> : agent === 'Sales' ? <Users size={16} /> : agent === 'Strategist' ? <Compass size={16} /> : <Search size={16} />}
      </span><div><strong>{agent}</strong>{activity && <p>{activity.detail}</p>}</div></summary><div className="agent-history"><p>{agentRoles[agent]}</p>{history.filter(item => item.agent === agent).length ? <ol>{history.filter(item => item.agent === agent).map((item, index) => <li key={index}><span>{item.state === 'done' ? 'Completed' : item.state === 'working' ? 'Started' : item.state === 'waiting' ? 'Waiting' : 'Stopped'}</span>{item.detail}</li>)}</ol> : <p>No work has started for this role.</p>}</div></details>;
    })}</div>
  </section>;
}
export function ModeToggle({ mode, onToggle }: { mode: 'light' | 'dark'; onToggle: () => void }) {
  return <button className="mode-toggle" onClick={onToggle} aria-label={`Switch to ${mode === 'light' ? 'dark' : 'light'} mode`} title={`${mode === 'light' ? 'Dark' : 'Light'} mode`}>
    {mode === 'light' ? <Moon size={18} /> : <Sun size={18} />}
  </button>;
}
