import { TransitionGrain } from './TransitionGrain';
import { Atmosphere } from './Atmosphere';
import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  AssistantRuntimeProvider, ComposerPrimitive, MessagePrimitive, ThreadPrimitive,
  useAuiState, useExternalStoreRuntime, type AppendMessage, type ThreadMessageLike, type ToolCallMessagePartComponent,
} from '@assistant-ui/react';
import { LiquidBackdrop } from './LiquidBackdrop';
import { Tabs, TabsList, TabsTrigger } from './components/beui/tabs';
import * as Dialog from '@radix-ui/react-dialog';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { TeamPanel, SearchBar, ModeToggle, type Activity } from './ShellParts';
import {
  ArrowDown, ArrowRight, ArrowUp, Check, CheckCheck, CircleHelp,
  Compass, GripVertical, Home, Leaf, LoaderCircle, Maximize2, Minimize2, MessageCircle, Pin,
  Moon, Sun, Plus, Search, ShieldCheck, SlidersHorizontal, Square, Users, X,
} from 'lucide-react';
import { GenerativePanelBody } from './GenerativePanelBody';
import { demoTransport, onboardingPreview } from './demo';
import { presentMessages, createAgentosTransport, readAgentosRun, cancelAgentosRun, type AgentosRun } from './agentos';
import { finishActivities, toggleSavedSelection, applyBackendEvent, recordBackendRun, initialCompanyPrompt, eventSchema, panelSchema, latestPanels, orderedPanels, movePanel, type Agent, type Message, type Panel, type Workspace, type Portfolio, type Transport, type WorkEvent }  from './model';

type WorkspaceContextValue = {
  workspace: Workspace;
  pin: (panel: Panel) => void;
  shortlist: (id: string) => void;
  approve: (id: string) => void;
  completeTask: (id: string) => void;
  open: (panel: Panel | null) => void;
};
const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);
function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error('Workspace provider is missing');
  return value;
}

function BusinessPanel({ panel, compact = false, expanded = false, expandable = false }: { panel: Panel; compact?: boolean; expanded?: boolean; expandable?: boolean }) {
  const { workspace, pin, shortlist, approve, completeTask, open } = useWorkspace();
  const [filter, setFilter] = useState('All');
  const pinned = workspace.pinned.some(item => item.id === panel.id);
  const approved = workspace.approvedOffers.includes(panel.id);
  return (
    <section className={`business-panel ${compact ? 'compact-panel' : ''} ${expanded ? 'expanded-panel' : ''}`} aria-label={panel.title}>
      <div className="panel-heading">
        <div className="panel-title"><span className="panel-icon">{panel.kind === 'prospects' ? <Users size={16} /> : panel.kind === 'offer' ? <Compass size={16} /> : panel.kind === 'evidence' ? <ShieldCheck size={16} /> : panel.kind === 'launch-plan' ? <CheckCheck size={16} /> : <SlidersHorizontal size={16} />}</span><h3>{panel.title}</h3></div>
        <div className="panel-tools">
          <button className={`icon-button ${pinned ? 'is-pinned' : ''}`} onClick={() => pin(panel)} aria-label={`${pinned ? 'Unpin' : 'Pin'} ${panel.title}`} title={pinned ? 'Unpin panel' : 'Keep on Home'}><Pin size={15} /></button>
          {expandable && <button className="icon-button" onClick={() => open(expanded ? null : panel)} aria-expanded={expanded} aria-label={`${expanded ? 'Collapse' : 'Expand'} ${panel.title}`}>{expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}</button>}
        </div>
      </div>
      {panel.kind === 'offer' && <>
        <p className="eyebrow">{panel.customer}</p>
        <p className="offer-promise">{panel.promise}</p>
        {(!compact || expanded) && <ul className="offer-includes">{panel.includes.map(item => <li key={item}><Check size={14} />{item}</li>)}</ul>}
        <div className="offer-footer"><span><strong>{panel.price}</strong></span><button className={`soft-button ${approved ? 'approved-button' : ''}`} onClick={() => approve(panel.id)} aria-pressed={approved}>{approved ? <><CheckCheck size={15} /> Reviewed</> : <>Review draft <ArrowRight size={14} /></>}</button></div>
      </>}
      {panel.kind === 'prospects' && <>
        <div className="panel-filter"><span>{compact ? `${workspace.shortlist.length} shortlisted` : 'Start with a conversation.'}</span><select aria-label="Filter prospects" value={filter} onChange={event => setFilter(event.target.value)}>{["All", "High fit", "Shortlisted"].map(value => <option key={value}>{value}</option>)}</select></div>
        <div className="prospect-list">{panel.rows.filter(row => filter === 'All' || (filter === 'High fit' ? row.fit === 'High' : workspace.shortlist.includes(row.id))).map(row => <div className="prospect-row" key={row.id}><div><strong>{row.name}</strong><span>{row.area} · {row.fit} fit</span>{(!compact || expanded) && <p>{row.reason}</p>}</div><button className={`shortlist-button ${workspace.shortlist.includes(row.id) ? 'selected' : ''}`} onClick={() => shortlist(row.id)} aria-label={`${workspace.shortlist.includes(row.id) ? 'Remove' : 'Shortlist'} ${row.name}`} aria-pressed={workspace.shortlist.includes(row.id)}>{workspace.shortlist.includes(row.id) ? <Check size={16} /> : <Plus size={16} />}</button></div>)}</div>
        {filter === 'Shortlisted' && !panel.rows.some(row => workspace.shortlist.includes(row.id)) && <p className="empty-note">Choose a clinic with the + button to start your shortlist.</p>}
      </>}
      {panel.kind === 'pricing' && <div className="pricing-options">{(() => {
        const render = (option: typeof panel.options[number]) => <div key={option.name}><span>{option.name}</span><strong>{option.price}</strong>{(!compact || expanded) && option.description && <p>{option.description}</p>}</div>;
        return <>{panel.options.slice(0, 3).map(render)}{panel.options.length > 3 && <details className="panel-details"><summary>More options ({panel.options.length - 3})</summary>{panel.options.slice(3).map(render)}</details>}</>;
      })()}</div>}
      <GenerativePanelBody panel={panel} compact={compact && !expanded} completedTasks={workspace.completedTasks} onComplete={completeTask} />
      {!panel.provenance && panel.note && <p className="panel-note"><CircleHelp size={12} />{panel.note}</p>}
      {panel.provenance && panel.kind !== 'evidence' && <p className="panel-note">Draft · Review before acting</p>}
    </section>
  );
}

const BusinessPanelTool: ToolCallMessagePartComponent = ({ result }) => {
  const parsed = panelSchema.safeParse(result);
  return parsed.success ? <BusinessPanel panel={parsed.data} /> : <p className="error-note" role="alert">This view could not be displayed. Its data is incomplete.</p>;
};
function AssistantMessage() {
  const id = useAuiState(state => state.message.id);
  return <MessagePrimitive.Root className="assistant-message" data-message-id={id}><div className="message-author"><span className="author-mark"><Leaf size={12} /></span>Samurai</div><MessagePrimitive.Parts components={{ tools: { by_name: { business_panel: BusinessPanelTool } } }} /></MessagePrimitive.Root>;
}
function UserMessage() {
  const id = useAuiState(state => state.message.id);
  return <MessagePrimitive.Root className="user-message" data-message-id={id}><MessagePrimitive.Parts /></MessagePrimitive.Root>;
}
function convertMessage(message: Message): ThreadMessageLike {
  return {
    id: message.id, role: message.role,
    content: [
      ...(message.text ? [{ type: 'text' as const, text: message.text }] : []),
      ...(message.panel ? [{ type: 'tool-call' as const, toolCallId: `${message.id}-panel`, toolName: 'business_panel', args: {}, argsText: '{}', result: message.panel }] : []),
    ],
  };
}

type CompanyProps = {
  company: Portfolio['companies'][number]; workspace: Workspace;
  setWorkspace: (update: Workspace | ((current: Workspace) => Workspace)) => void;
  mode: 'light' | 'dark'; toggleMode: () => void; onOpen: (id: string | null) => void; storageError: boolean;
};
export function CompanyWorkspace({ company, workspace, setWorkspace, mode, toggleMode, onOpen, storageError }: CompanyProps) {
  const live = workspace.executionMode === 'live';
  const recoveringRef = useRef(live && Boolean(workspace.backendRun));
  const [recovering, setRecovering] = useState(recoveringRef.current);
  const [isRunning, setRunning] = useState(recoveringRef.current);
  const [activities, setActivities] = useState<Partial<Record<Agent, Activity>>>(() => Object.fromEntries(workspace.activityLog.map(activity => [activity.agent, activity])));
  const [view, setView] = useState<'chat' | 'company'>('chat');
  const [dialog, setDialog] = useState<'panels' | null>(null);
  const [editingOrder, setEditingOrder] = useState(false);
  useEffect(() => { if (view === 'chat') setEditingOrder(false); }, [view]);
  const [expandedPanel, setExpandedPanel] = useState<Panel | null>(null);
  const [runError, setRunError] = useState('');
  const controllerRef = useRef<AbortController | null>(null);
  const backendRunRef = useRef(workspace.backendRun);
  const messagesRef = useRef(workspace.messages);
  messagesRef.current = workspace.messages;
  const transportRef = useRef<Transport | null>(null);
  const backendRunning = () => backendRunRef.current?.status === 'running';
  const completionRef = useRef<Promise<void> | null>(null);
  const recordRun = (run: AgentosRun) => {
    const checked = recordBackendRun({ ...workspace, backendRun: backendRunRef.current }, run);
    backendRunRef.current = checked.backendRun;
    setWorkspace(current => ({ ...recordBackendRun(current, run), activityLog: finishActivities(current.activityLog, run.status) }));
    if (run.status !== 'running') setActivities(current => Object.fromEntries(finishActivities(Object.values(current).filter((activity): activity is Activity => Boolean(activity)), run.status).map(activity => [activity.agent, activity])));
  };
  if (live && !transportRef.current) transportRef.current = createAgentosTransport(company.id, recordRun, () => messagesRef.current);
  const viewportRef = useRef<HTMLDivElement>(null);
  const homeRef = useRef<HTMLElement>(null);
  const chatRef = useRef<HTMLElement>(null);
  const previousView = useRef(view);
  useLayoutEffect(() => {
    if (previousView.current === view) return;
    previousView.current = view;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const frames = [{ opacity: 0, filter: 'blur(10px)', transform: 'translateY(6px)' }, { opacity: 1, filter: 'blur(0px)', transform: 'translateY(0)' }];
    const animations = [homeRef.current, ...(view === 'chat' ? [chatRef.current] : [])].flatMap(element => element ? [element.animate(frames, { duration: 850, easing: 'ease-in-out' })] : []);
    return () => animations.forEach(animation => animation.cancel());
  }, [view]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const append = (message: Message) => setWorkspace(current => ({ ...current, messages: [...current.messages, message].slice(-200), pinned: message.panel ? current.pinned.map(panel => panel.id === message.panel!.id ? message.panel! : panel) : current.pinned }));
  const onNew = async (message: AppendMessage) => {
    const input = message.content.filter(part => part.type === 'text').map(part => part.text).join('\n').trim();
    if (!input || recoveringRef.current || controllerRef.current || completionRef.current || backendRunning()) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    let finish: (() => void) | undefined;
    completionRef.current = new Promise<void>(resolve => { finish = resolve; });
    setRunning(true); setRunError(''); setActivities({});
    setWorkspace(current => ({ ...current, activityLog: [] }));
    append({ id: crypto.randomUUID(), role: 'user', text: input });
    if (!live && workspace.messages.length === 0 && !workspace.brief && !/sample/i.test(input)) {
      append({ id: crypto.randomUUID(), role: 'assistant', text: 'This preview can explore sample dental customers, offers, pricing, evidence and launch plans. Start a new company from Home for a live workflow.' });
      controllerRef.current = null; completionRef.current = null; setRunning(false); finish?.(); return;
    }
    try {
      const initial = input === 'Start my company' && workspace.brief;
      let events: AsyncIterable<WorkEvent>;
      if (live) {
        const transport = transportRef.current;
        if (!transport) throw new Error('The live backend transport is unavailable.');
        events = transport(initial ? initialCompanyPrompt(initial) : input, controller.signal);
      } else events = initial ? onboardingPreview(initial, controller.signal) : demoTransport(input, controller.signal);
      for await (const raw of events) {
        if (controller.signal.aborted && !live) break;
        const event = eventSchema.parse(raw);
        if (event.type === 'activity') {
          setActivities(current => ({ ...current, [event.agent]: event }));
          setWorkspace(current => ({ ...current, activityLog: [...current.activityLog, event].slice(-100) }));
        }
        else if (live) {
          const runId = backendRunRef.current?.runId;
          if (!runId) throw new Error('The backend omitted the run identity.');
          setWorkspace(current => applyBackendEvent(current, runId, event));
        }
        else append({ id: crypto.randomUUID(), role: 'assistant', text: event.text, panel: event.panel });
      }
      if (live && backendRunRef.current?.status === 'cancelled') append({ id: crypto.randomUUID(), role: 'assistant', text: 'The backend confirmed cancellation.' });
    } catch (error) {
      if (!live && controller.signal.aborted) append({ id: crypto.randomUUID(), role: 'assistant', text: 'Stopped the preview. Nothing was sent or published.' });
      else setRunError(error instanceof Error ? error.message : 'Samurai could not complete this request.');
    } finally { controllerRef.current = null; if (live && backendRunRef.current) recordRun(backendRunRef.current); setRunning(live && backendRunning()); finish?.(); completionRef.current = null; }
  };
  const onCancel = async () => {
    if (recoveringRef.current) return;
    if (controllerRef.current) { controllerRef.current.abort(); await completionRef.current; return; }
    if (completionRef.current) { await completionRef.current; return; }
    const saved = backendRunRef.current;
    if (live && saved?.status === 'running') {
      setRunError('');
      const stopping = cancelAgentosRun(company.id, saved.runId, messagesRef.current).then(recovered => {
        recordRun(recovered.run);
        for (const event of recovered.events) if (event.type === 'message') setWorkspace(current => applyBackendEvent(current, saved.runId, event));
        if (recovered.run.status === 'cancelled') append({ id: crypto.randomUUID(), role: 'assistant', text: 'The backend confirmed cancellation of the saved run.' });
        if (recovered.run.status === 'failed') setRunError('The saved backend run failed. You can send a new request.');
        setRunning(false);
      }).catch(error => { setRunError(error instanceof Error ? error.message : 'Cancellation was not confirmed.'); });
      completionRef.current = stopping;
      try { await stopping; } finally { completionRef.current = null; }
    }
  };
  const chatMessages = presentMessages(workspace.messages);
  const runtime = useExternalStoreRuntime({ messages: chatMessages, convertMessage, isRunning, onNew, onCancel });
  useEffect(() => {
    const saved = backendRunRef.current;
    if (!live || !saved) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setRunning(true);
      void readAgentosRun(company.id, saved.runId, controller.signal, messagesRef.current).then(recovered => {
        if (controller.signal.aborted) return;
        // Check authoritative company binding before applying any recovered artifact.
        recordRun(recovered.run);
        const history = recovered.events.filter((event): event is Activity => event.type === 'activity');
        if (history.length) {
          setActivities(Object.fromEntries(finishActivities(history, recovered.run.status).map(activity => [activity.agent, activity])));
          setWorkspace(current => ({ ...current, activityLog: finishActivities(history, recovered.run.status) }));
        }
        for (const event of recovered.events) if (event.type === 'message') setWorkspace(current => applyBackendEvent(current, saved.runId, event));
        setRunning(recovered.run.status === 'running');
        if (recovered.run.status === 'running') setRunError('The saved backend run is still running. Stop it or reopen this company later to check its saved result.');
        if (recovered.run.status === 'failed') setRunError('The saved backend run failed. You can send a new request.');
      }).catch(error => {
        if (controller.signal.aborted) return;
        setRunning(saved.status === 'running'); setRunError(error instanceof Error ? error.message : 'Saved results could not be recovered.');
      }).finally(() => {
        if (controller.signal.aborted) return;
        recoveringRef.current = false; setRecovering(false);
      });
    }, 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, []);
  useEffect(() => {
    if (!workspace.brief || workspace.messages.length || workspace.backendRun) return;
    // Deferring lets StrictMode cancel its first mount without starting a duplicate run.
    const timer = setTimeout(() => { runtime.thread.composer.setText('Start my company'); runtime.thread.composer.send(); }, 0);
    return () => clearTimeout(timer);
  }, []);
  const ask = (text: string) => {
    if (isRunning) return;
    setView('chat'); setDialog(null);
    runtime.thread.composer.setText(text); runtime.thread.composer.send();
  };
  const pin = (panel: Panel) => setWorkspace(current => ({ ...current, pinned: current.pinned.some(item => item.id === panel.id) ? current.pinned.filter(item => item.id !== panel.id) : [...current.pinned, panel].slice(-12) }));
  const shortlist = (id: string) => setWorkspace(current => ({ ...current, shortlist: toggleSavedSelection(current.shortlist, id, 100) }));
  const approve = (id: string) => setWorkspace(current => ({ ...current, approvedOffers: toggleSavedSelection(current.approvedOffers, id, 20) }));
  const completeTask = (id: string) => setWorkspace(current => ({ ...current, completedTasks: current.completedTasks.includes(id) ? current.completedTasks.filter(item => item !== id) : [...current.completedTasks, id].slice(-400) }));
  const panels = latestPanels({ ...workspace, messages: chatMessages });
  const nextStage = panels.some(panel => panel.provenance?.artifact_type === "product_plan") ? { label: "Review next steps", prompt: "Help me choose the next step from our existing plan." } : panels.some(panel => panel.provenance?.artifact_type === "strategy") ? { label: "Plan first version", prompt: 'Prepare the product and delivery plan.' } : panels.some(panel => panel.provenance?.artifact_type === "research") ? { label: "Shape offer", prompt: 'Shape our offer and positioning. Stop before creating the product plan.' } : { label: "Research market", prompt: 'Research our market. Stop before shaping the offer.' };
  const currentPanel = (panel: Panel) => panels.find(item => item.id === panel.id) || panel;
  const dashboardPanels = orderedPanels([...panels, ...(expandedPanel && !panels.some(panel => panel.id === expandedPanel.id) ? [expandedPanel] : [])], workspace.panelOrder);
  const reorder = (id: string, target: string) => setWorkspace(current => ({ ...current, panelOrder: movePanel(orderedPanels(latestPanels({ ...current, messages: presentMessages(current.messages) }), current.panelOrder), id, target) }));
  const openPanel = (panel: Panel | null) => {
    setExpandedPanel(panel);
    if (panel && window.matchMedia('(max-width: 760px)').matches) setView('company');
    if (panel) requestAnimationFrame(() => document.getElementById(`home-panel-${panel.id}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }));
  };
  const workingAgent = Object.values(activities).find(activity => activity?.state === 'working');
  const [conversationAtBottom, setConversationAtBottom] = useState(true);
  const previousMessageCount = useRef(workspace.messages.length);
  useEffect(() => {
    if (previousMessageCount.current === workspace.messages.length) return;
    previousMessageCount.current = workspace.messages.length;
    if (conversationAtBottom && view === 'chat') viewportRef.current?.scrollTo({ top: viewportRef.current.scrollHeight, behavior: 'smooth' });
  }, [workspace.messages.length, view, conversationAtBottom]);

  return <WorkspaceContext.Provider value={{ workspace, pin, shortlist, approve, completeTask, open: openPanel }}><AssistantRuntimeProvider runtime={runtime}>
    <div className={`workspace company-workspace ${view === 'company' ? 'dashboard-open' : ''}`}>
      <Atmosphere mode={mode} /><TransitionGrain key={view} /><div className="bottom-blur" aria-hidden="true" />
      <header className="topbar">
        <div className="topbar-brand"><button className="home-button" onClick={() => onOpen(null)} aria-label="All companies"><Home size={19} /></button><span className="wordmark">Samurai</span></div>
        <Tabs className="view-switch" value={view} onValueChange={value => setView(value as 'chat' | 'company')}><LiquidBackdrop /><TabsList aria-label="Workspace view"><TabsTrigger value="chat">Chat</TabsTrigger><TabsTrigger value="company">Company</TabsTrigger></TabsList></Tabs>
        <div className="topbar-actions"><SearchBar items={chatMessages.map(message => ({ id: message.id, title: message.panel?.title || message.text, detail: message.text }))} onSelect={id => {
          const message = chatMessages.find(item => item.id === id);
          if (message?.panel) openPanel(message.panel);
          else { setView('chat'); requestAnimationFrame(() => document.querySelector(`[data-message-id="${id}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })); }
        }} /><ModeToggle mode={mode} onToggle={toggleMode} /><DropdownMenu.Root><DropdownMenu.Trigger asChild><button className="account-button" aria-label="Workspace settings"><SlidersHorizontal size={17} /></button></DropdownMenu.Trigger><DropdownMenu.Portal><DropdownMenu.Content className="workspace-menu" align="end" sideOffset={8} collisionPadding={14}>
          <DropdownMenu.Item className="workspace-menu-item" disabled={!dashboardPanels.length} onSelect={() => { setView('company'); setEditingOrder(!editingOrder); }}><GripVertical size={16} />{editingOrder ? 'Done editing' : 'Edit card order'}</DropdownMenu.Item>
          <DropdownMenu.Item className="workspace-menu-item" onSelect={toggleMode}>{mode === 'light' ? <Moon size={16} /> : <Sun size={16} />}Switch to {mode === 'light' ? 'dark' : 'light'} mode</DropdownMenu.Item>
        </DropdownMenu.Content></DropdownMenu.Portal></DropdownMenu.Root></div>
      </header>

      <aside ref={homeRef} className="home-pane" aria-label={view === 'company' ? 'Company dashboard' : 'Company Home'}>
        <div className="home-heading"><div className="home-selector-row"><h1 className={`company-name ${view === 'company' ? 'dashboard-title' : ''}`}>{company.name}</h1>{view === 'company' && <div className="panel-tools">{editingOrder && <button className="soft-button order-done" onClick={() => setEditingOrder(false)}><Check size={14} />Done</button>}<button className="icon-button" onClick={() => setDialog('panels')} aria-label="Add a business panel"><Plus size={17} /></button></div>}<button className="icon-button" onClick={() => setView(view === 'company' ? 'chat' : 'company')} aria-expanded={view === 'company'} aria-label={view === 'company' ? 'Collapse company dashboard' : 'Expand company dashboard'}>{view === 'company' ? <Minimize2 size={17} /> : <Maximize2 size={17} />}</button></div></div>
        {view === 'chat' && workspace.messages.length > 0 && <div className="action-stack">
          {panels.some(panel => panel.kind === 'offer') && <button className="action-card" onClick={() => openPanel(panels.find(panel => panel.kind === 'offer')!)}><Compass size={18} /><span>Review offer</span><ArrowRight size={16} className="action-arrow" /></button>}
          <button className="action-card" onClick={() => ask(live ? 'Research our target customers and qualification criteria' : 'Show sample dental customer prospects')} disabled={isRunning}><Users size={18} /><span>{live ? 'Research customers' : 'Explore sample customers'}</span><ArrowRight size={16} className="action-arrow" /></button>
        </div>}
        <TeamPanel activities={activities} history={workspace.activityLog} expanded={view === 'company'} executionMode={workspace.executionMode} />
        {view === 'chat' && <div className="pinned-label"><span>Pinned</span><button className="icon-button" onClick={() => setDialog('panels')} aria-label="Add a business panel"><Plus size={17} /></button></div>}
        <div className="home-panels">{(view === 'company' ? dashboardPanels : [...workspace.pinned, ...(expandedPanel && !workspace.pinned.some(panel => panel.id === expandedPanel.id) ? [expandedPanel] : [])]).map((panel, index) => <div className="home-panel-item" id={`home-panel-${panel.id}`} key={panel.id} onDragOver={event => { if (view === 'company' && editingOrder) event.preventDefault(); }} onDrop={event => { if (view !== 'company' || !editingOrder) return; event.preventDefault(); reorder(event.dataTransfer.getData('text/plain'), panel.id); }}>
          {view === 'company' && editingOrder && <div className="panel-reorder"><button className="icon-button drag-handle" draggable onDragStart={event => { event.dataTransfer.setData('text/plain', panel.id); event.dataTransfer.effectAllowed = 'move'; }} aria-label={`Drag ${panel.title} to reorder`}><GripVertical size={15} /></button><span /><button className="icon-button" disabled={index === 0} aria-label={`Move ${panel.title} earlier`} onClick={() => reorder(panel.id, dashboardPanels[index - 1].id)}><ArrowUp size={14} /></button><button className="icon-button" disabled={index === dashboardPanels.length - 1} aria-label={`Move ${panel.title} later`} onClick={() => reorder(panel.id, dashboardPanels[index + 1].id)}><ArrowDown size={14} /></button></div>}
          <BusinessPanel panel={currentPanel(panel)} compact={view === 'chat'} expandable={view === 'chat'} expanded={expandedPanel?.id === panel.id} /></div>)}</div>
        {(view === 'company' ? dashboardPanels : workspace.pinned).length === 0 && !expandedPanel && <div className="company-empty"><Compass size={24} /><h3>No panels yet.</h3>{view === 'company' && <button className="soft-button" onClick={() => setView('chat')}>Start a conversation<ArrowRight size={15} /></button>}</div>}
        {view === 'chat' && <button className="create-panel" onClick={() => setDialog('panels')}><Plus size={15} />Add a panel<ArrowRight size={14} /></button>}
        {view === 'company' && <p className="company-footnote">{live ? 'Live backend workflow · Review evidence before acting.' : 'Preview workspace · Sample data.'}</p>}
      </aside>
      {view === 'company' && <button className="dashboard-chat" onClick={() => { setView('chat'); requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('.composer-input')?.focus()); }}><MessageCircle size={18} /><span>Chat with Samurai</span><ArrowRight size={16} /></button>}

      <main ref={chatRef} className="main-pane" hidden={view === 'company'}>
        <ThreadPrimitive.Root className="conversation">
          <ThreadPrimitive.Viewport className="conversation-scroll" ref={viewportRef} autoScroll={false} scrollToBottomOnInitialize={false} scrollToBottomOnThreadSwitch={false} scrollToBottomOnRunStart={false} onScroll={() => {
            const element = viewportRef.current;
            if (element) setConversationAtBottom(element.scrollHeight - element.scrollTop - element.clientHeight < 100);
          }}>
            <div className="conversation-content">{workspace.messages.length === 0 && <div className="conversation-intro empty-conversation"><span className="empty-company-name">{company.name}</span><h2>Start with<br />your idea.</h2><p>What do you want this company to do?</p></div>}
              <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
              {isRunning && <div className="working-message" role="status"><LoaderCircle size={15} className="spin" />{workingAgent?.detail || (recovering ? 'Recovering the saved backend run…' : live ? 'Waiting for the backend…' : 'Preparing the preview…')}</div>}
              {runError && <div className="error-note" role="alert">{live ? 'Backend status: ' : 'Preview status: '}{runError}</div>}
              {workspace.messages.length > 0 && <div className="suggestions"><button onClick={() => ask(live ? nextStage.prompt : 'Show sample dental customer prospects')} disabled={isRunning}>{live ? nextStage.label : 'Sample customers'} <ArrowRight size={13} /></button>{!live && <button onClick={() => ask('Is this pricing viable?')} disabled={isRunning}>Sample pricing <ArrowRight size={13} /></button>}</div>}
            </div>
          </ThreadPrimitive.Viewport>
          <div className="composer-dock">{!conversationAtBottom && <button className="scroll-bottom" onClick={() => { setConversationAtBottom(true); viewportRef.current?.scrollTo({ top: viewportRef.current.scrollHeight, behavior: 'smooth' }); }} aria-label="Scroll to latest message"><ArrowDown size={16} /></button>}
            <ComposerPrimitive.Root className="composer"><LiquidBackdrop /><button type="button" className="composer-plus icon-button" onClick={() => setDialog('panels')} aria-label="Explore business panels"><Plus size={20} /></button><ComposerPrimitive.Input className="composer-input" placeholder="What’s our next move?" aria-label="Message Samurai" maxLength={4000} />{!isRunning && <ComposerPrimitive.Send asChild><button className="send-button" aria-label="Send message"><ArrowUp size={19} /></button></ComposerPrimitive.Send>}{isRunning && <ComposerPrimitive.Cancel asChild><button className="send-button stop-button" disabled={recovering} aria-label={live ? 'Stop backend run' : 'Stop preview'}><Square size={14} fill="currentColor" /></button></ComposerPrimitive.Cancel>}</ComposerPrimitive.Root>
            <div className="preview-caption">{live ? 'Live Samurai workflow · Generated artifacts need review' : 'Preview agents · Sample data · No external actions'}</div>
            {storageError && <p role="status" className="storage-warning">Browser storage is unavailable. This session won’t be saved.</p>}
          </div>
        </ThreadPrimitive.Root>
      </main>

      <Dialog.Root open={!!dialog} onOpenChange={open => { if (!open) setDialog(null); }}><Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="dialog-content"><Dialog.Title className="sr-only">Business panels</Dialog.Title><Dialog.Description className="sr-only">Manage this company workspace.</Dialog.Description><div className="dialog-heading"><h2>What would you like to see?</h2><button className="icon-button" aria-label="Close dialog" onClick={() => setDialog(null)}><X size={19} /></button></div><p className="dialog-description">Ask for a view, then pin it to keep it on Home.</p>
        {dialog === 'panels' && <div className="panel-choices">{[{ title: 'Customer pipeline', detail: 'Find and shortlist your first prospects', prompt: 'Show sample dental customer prospects', icon: Users }, { title: 'Offer & positioning', detail: 'Shape a clear promise for your customers', prompt: 'Show sample dental offer', icon: Compass }, { title: 'Pricing exploration', detail: 'Compare hypotheses before testing demand', prompt: 'Show sample dental pricing', icon: SlidersHorizontal }, { title: 'Evidence review', detail: 'Separate assumptions from supported claims', prompt: 'Show sample validation evidence', icon: ShieldCheck }, { title: 'Launch plan', detail: 'Track the next steps towards a pilot', prompt: 'Show sample launch plan', icon: CheckCheck }].map(choice => <button key={choice.title} onClick={() => ask(live ? ({ 'Customer pipeline': 'Research target customers and qualification criteria', 'Offer & positioning': 'Develop our offer and positioning', 'Pricing exploration': 'Review our pricing assumptions', 'Evidence review': 'Review evidence and verification findings', 'Launch plan': 'Develop our minimum offering and delivery plan' }[choice.title] || choice.title) : choice.prompt)} disabled={isRunning}><choice.icon size={21} /><span><strong>{choice.title}</strong><small>{choice.detail}</small></span><ArrowRight size={16} /></button>)}</div>}
      </Dialog.Content></Dialog.Portal></Dialog.Root>
    </div>
  </AssistantRuntimeProvider></WorkspaceContext.Provider>;
}
