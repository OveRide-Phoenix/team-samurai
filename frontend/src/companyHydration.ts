import { companySnapshotEvents } from './agentos';
import { fillAspectStartingPoints } from './ideaAnalysis';
import type { CompanyView, Message, WorkEvent } from './model';

export function hydrateCompanyView(current: CompanyView, snapshot: unknown, companyId: string): CompanyView {
  const events = companySnapshotEvents(snapshot, companyId);
  const messages: Message[] = events.flatMap((event, index) => {
    if (event.type !== 'message') return [];
    const saved = event.panel ? current.messages.slice().reverse().find(message => message.panel?.id === event.panel?.id) : undefined;
    return [{
      ...saved, id: saved?.id ?? (event.panel ? `snapshot-${event.panel.id}` : `snapshot-${companyId}-${index}`),
      role: 'assistant' as const, text: event.text, ...(event.panel ? { panel: event.panel } : {}),
    }];
  });
  const panels = messages.flatMap(message => message.panel ? [message.panel] : []);
  const panelIds = new Set(panels.map(panel => panel.id));
  const activities = events.filter((event): event is Extract<WorkEvent, { type: 'activity' }> => event.type === 'activity');
  const hydrated: CompanyView = {
    ...current, executionMode: 'live',
    messages: [...current.messages.filter(message => !message.panel || !panelIds.has(message.panel.id)), ...messages].slice(-200),
    pinned: [...current.pinned.filter(panel => !panelIds.has(panel.id)), ...panels].slice(-12),
    ...(activities.length ? { activityLog: activities } : {}),
  };
  return panels.reduce(fillAspectStartingPoints, hydrated);
}
