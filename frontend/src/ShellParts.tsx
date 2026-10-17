import { Moon, Sun } from 'lucide-react';
import type { WorkEvent } from './model';

export type Activity = Extract<WorkEvent, { type: 'activity' }>;
export function ModeToggle({ mode, onToggle }: { mode: 'light' | 'dark'; onToggle: () => void }) {
  return <button className="mode-toggle" onClick={onToggle} aria-label={`Switch to ${mode === 'light' ? 'dark' : 'light'} mode`} title={`${mode === 'light' ? 'Dark' : 'Light'} mode`}>
    {mode === 'light' ? <Moon size={18} /> : <Sun size={18} />}
  </button>;
}
