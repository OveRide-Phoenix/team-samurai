import { useEffect, useRef, useState } from 'react';
import { LiquidBackdrop } from './LiquidBackdrop';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { Check, Compass, LoaderCircle, Moon, Clock3, Search, ShieldCheck, Sun, Users } from 'lucide-react';
import { agents, type Agent, type WorkEvent } from './model';

export type Activity = Extract<WorkEvent, { type: 'activity' }>;
const agentRoles: Record<Agent, string> = {
  Researcher: 'Explore competitors, customer problems and market evidence.',
  Strategist: 'Shape your offer, positioning and pricing from the evidence.',
  Verifier: 'Check source support and flag assumptions or conflicting claims.',
  Sales: 'Identify prospects and prepare outreach to test your offer.',
};
export function TeamPanel({ activities = {}, history = [], expanded = false, executionMode = 'preview' }: { activities?: Partial<Record<Agent, Activity>>; history?: readonly Activity[]; expanded?: boolean; executionMode?: 'preview' | 'live' }) {
  return <section className={`team-panel glass ${expanded ? 'team-expanded' : ''}`} aria-label="Team activity">
    <div className="panel-heading"><h2>Team</h2><span className="tiny-label">{executionMode === 'live' ? 'Live' : 'Preview'}</span></div>
    <div className="activity-list" aria-live="polite">{agents.map(agent => {
      const activity = activities[agent];
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
export type SearchItem = { id: string; title: string; detail?: string };
export function SearchBar({ items, onSelect, placeholder = 'Search company' }: { items: SearchItem[]; onSelect: (id: string) => void; placeholder?: string }) {
  const [query, setQuery] = useState('');
  const [focused, setFocused] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const reduce = useReducedMotion();
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); input.current?.focus();
      }
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, []);
  const matches = items.filter(item => query.trim() && `${item.title} ${item.detail || ''}`.toLowerCase().includes(query.trim().toLowerCase()));
  return <div className={`inline-search ${focused ? 'search-focused' : ''}`} onFocus={() => setFocused(true)} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false); }}>
    <label className="search-input-field"><LiquidBackdrop /><Search size={16} /><input ref={input} aria-label={placeholder} placeholder="Search" value={query} onChange={event => setQuery(event.target.value)} className="search-input" onKeyDown={event => {
      if (event.key === 'Escape') { setQuery(''); setFocused(false); input.current?.blur(); }
      if (event.key === 'ArrowDown') { event.preventDefault(); event.currentTarget.closest('.inline-search')?.querySelector<HTMLButtonElement>('.search-match')?.focus(); }
    }} /><kbd>⌘K</kbd></label>
    <AnimatePresence>{focused && query.trim() && <motion.div className="inline-search-results" role="region" aria-label="Search results" initial={{ opacity: 0, y: reduce ? 0 : -5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: reduce ? 0 : .18 }}>
      {matches.length ? matches.map(item => <button className="search-match" key={item.id} onClick={() => { onSelect(item.id); setQuery(''); setFocused(false); input.current?.blur(); }}>{item.title}</button>) : <p>No matches.</p>}
    </motion.div>}</AnimatePresence>
  </div>;
}
