import { TransitionGrain } from './TransitionGrain';
import { Atmosphere } from './Atmosphere';
import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, lazy, Suspense } from 'react';
import {
  AssistantRuntimeProvider, MessagePrimitive, ThreadPrimitive,
  useAuiState, useExternalStoreRuntime, type AppendMessage, type ThreadMessageLike, type ToolCallMessagePartComponent,
} from '@assistant-ui/react';
import { motion, useReducedMotion } from 'motion/react';
import { pageRevealFrames, pageRevealTiming } from './panelLayout';
import { LiquidBackdrop } from './LiquidBackdrop';
import { Tabs, TabsList, TabsTrigger } from './components/beui/tabs';
import * as Dialog from '@radix-ui/react-dialog';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { TeamNavigation } from './TeamNavigation';
import { actionAreas, areaForPanel, panelChoiceAreas, panelsForAreas, selectedWorkflowAreas, scopeForAspect, teamAreas } from './teamAreas';
import { OpenUIAspectGuide } from './OpenUIAspectGuide';
import { OpenUIIdeaAnalysis } from './OpenUIIdeaAnalysis';
import { fillAspectStartingPoints, latestIdeaAnalysis } from './ideaAnalysis';
import { bindAspectReview, recoveredAspectReview, completeAspectReview, aspectMentorPrompt, aspectFormValue, aspectQuestions, guidedAnswerPrompt, isGuidedReview, nextAspectQuestion, recordAspectAnswer, resumeAspect, type AspectGuide, type AspectQuestion } from './aspectJourney';
import type { IdeaArea } from './aspectState';
import { ModeToggle, type Activity } from './ShellParts';
import {
  ArrowDown, ArrowRight, ArrowUp, Check, CheckCheck, ChevronDown, CircleHelp,
  Compass, GripVertical, Home, Leaf, LoaderCircle, Maximize2, Minimize2, Pin,
  Download, FileText, Moon, Sun, Plus, ShieldCheck, SlidersHorizontal, Trash2, Upload, Users, X,
} from 'lucide-react';
import { GenerativePanelBody } from './GenerativePanelBody';
import { presentMessages, editApprovedWorkDraft, approvedWorkForSubmission, createAgentosTransport, readAgentosRun, readAgentosReceipt, cancelAgentosRun, type CopilotStart, type ApprovedWorkDraft, type AgentosApproval, type AgentosRun } from './agentos';
import { finishActivities, hasActiveBackendRun, toggleSavedSelection, applyBackendEvent, recordBackendRun, beginBackendRun, panelIsOutdated, currentCompanyActions, initialCompanyPrompt, eventSchema, panelSchema, latestPanels, orderedPanels, movePanel, type CompanyAction, type TeamArea, type WorkflowArea, type Agent, type Message, type WorkEvent, type Panel, type Workspace, type Portfolio }  from './model';
import { deleteWorkspaceFile, downloadWorkspaceFile, listWorkspaceFiles, uploadWorkspaceFile, type WorkspaceFile } from './files';
import { FounderOperationsPanel } from './FounderOperationsPanel';
import { canonicalCompanyFields, openWorkspaceCompany } from './workspaces';

type WorkspaceContextValue = {
  workspace: Workspace;
  mode: 'light' | 'dark';
  pin: (panel: Panel) => void;
  shortlist: (id: string) => void;
  approve: (id: string) => void;
  completeTask: (id: string) => void;
  open: (panel: Panel | null) => void;
  discuss: (prompt: string, panel?: Panel) => void;
  selectArea: (area: IdeaArea, draft?: string) => void;
  area: TeamArea; workspaceId?: string;
  grouped: boolean;
};
const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);
function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error('Workspace provider is missing');
  return value;
}

import KnownPanel from './KnownPanel';
import { OpenUIComposer, OpenUIMessageText } from './OpenUIChat';
import { OpenUIMeasurements } from './OpenUIMeasurements';
import { isWorkDraft } from './WorkDraftPanel';
function BusinessPanel(props: { panel: Panel; compact?: boolean; expanded?: boolean; expandable?: boolean }) {
  return <KnownPanel {...props} render={BusinessPanelContent} />;
}
function BusinessPanelContent({ panel, compact = false, expanded = false, expandable = false }: { panel: Panel; compact?: boolean; expanded?: boolean; expandable?: boolean }) {
  const { workspace, mode, pin, shortlist, approve, completeTask, open, discuss, workspaceId } = useWorkspace();
  const pinned = workspace.pinned.some(item => item.id === panel.id);
  const approved = workspace.approvedOffers.includes(panel.id);
  return (
    <section className={`business-panel ${compact ? 'compact-panel' : ''} ${expanded ? 'expanded-panel' : ''}`} aria-label={panel.title.replace(/^Company /, 'Idea ')}>
      <div className="panel-heading">
        <div className="panel-title"><span className="panel-icon">{panel.kind === 'prospects' ? <Users size={16} /> : panel.kind === 'offer' ? <Compass size={16} /> : panel.kind === 'evidence' ? <ShieldCheck size={16} /> : panel.kind === 'launch-plan' ? <CheckCheck size={16} /> : <SlidersHorizontal size={16} />}</span><h3>{panel.title.replace(/^Company /, 'Idea ')}</h3></div>
        <div className="panel-tools">
          <button className={`icon-button ${pinned ? 'is-pinned' : ''}`} onClick={() => pin(panel)} aria-label={`${pinned ? 'Unpin' : 'Pin'} ${panel.title}`} title={pinned ? 'Unpin panel' : 'Keep on Home'}><Pin size={15} /></button>
          {expandable && <button className="icon-button" onClick={() => open(expanded ? null : panel)} aria-expanded={expanded} aria-label={`${expanded ? 'Collapse' : 'Expand'} ${panel.title}`}>{expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}</button>}
        </div>
      </div>
      {panelIsOutdated(panel, workspace) && <p className="panel-note" role="note">Earlier version · Update before using</p>}
      <GenerativePanelBody mode={mode} panel={panel} compact={compact && !expanded} completedTasks={workspace.completedTasks} onComplete={completeTask} shortlisted={workspace.shortlist} onShortlist={shortlist} approved={approved} onApprove={() => approve(panel.id)} onDiscuss={prompt => discuss(prompt, panel)} workspaceId={workspaceId} />
      {!panel.provenance && panel.note && <details className="panel-note panel-note-details"><summary><CircleHelp size={12} />{panel.kind === 'custom' || panel.kind === 'declarative' ? 'Working assumptions' : 'Draft notes'}</summary><p>{panel.note}</p></details>}
      {panel.provenance && !isWorkDraft(panel) && panel.kind !== 'evidence' && panel.kind !== 'scenario' && <p className="panel-note">Draft · Review before acting</p>}
    </section>
  );
}

const BusinessPanelTool: ToolCallMessagePartComponent = ({ result }) => {
  const parsed = panelSchema.safeParse(result);
  return parsed.success ? <BusinessPanel panel={parsed.data} /> : <p className="error-note" role="alert">This view could not be displayed. Its data is incomplete.</p>;
};
function AssistantMessage() {
  const id = useAuiState(state => state.message.id);
  const { workspace, selectArea } = useWorkspace();
  const message = workspace.messages.find(item => item.id === id);
  const analysis = message?.panel && 'idea_analysis' in message.panel ? message.panel.idea_analysis : undefined;
  return <MessagePrimitive.Root className="assistant-message" data-message-id={id}><div className="message-author"><span className="author-mark"><Leaf size={12} /></span>Proofseed</div><MessagePrimitive.Parts components={{ Text: OpenUIMessageText, tools: { by_name: { business_panel: BusinessPanelTool } } }} />{analysis && <OpenUIIdeaAnalysis analysis={analysis} pending={false} onAspect={selectArea} />}{message?.handoff && <button className="soft-button team-handoff" onClick={() => selectArea(message.handoff!, message.handoffPrerequisite ? message.handoff === 'overview' ? 'Save my idea brief' : teamAreas.find(item => item.id === message.handoff)!.prompt : workspace.messages.slice(0, workspace.messages.indexOf(message)).reverse().find(item => item.role === 'user' && item.area === message.area)?.text)}>Open {teamAreas.find(item => item.id === message.handoff)!.name}<ArrowRight size={14} /></button>}</MessagePrimitive.Root>;
}
function UserMessage() {
  const id = useAuiState(state => state.message.id);
  return <MessagePrimitive.Root className="user-message" data-message-id={id}><MessagePrimitive.Parts components={{ Text: OpenUIMessageText }} /></MessagePrimitive.Root>;
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
  persistWorkspace?: (update: Workspace | ((current: Workspace) => Workspace)) => boolean;
  initialView?: 'chat' | 'company';
  mode: 'light' | 'dark'; toggleMode: () => void; onOpen: (id: string | null) => void; storageError: boolean; readOnly?: boolean;
};
function FilePanel({ workspaceId, companyId, readOnly }: { workspaceId?: string; companyId?: string; readOnly: boolean }) {
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [status, setStatus] = useState('');
  const [pending, setPending] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const refresh = async () => {
    if (!workspaceId) return;
    setLoaded(false); setStatus('');
    try { setFiles(await listWorkspaceFiles(workspaceId)); setLoaded(true); }
    catch { setFiles([]); setStatus('Files could not be loaded.'); setLoaded(true); }
  };
  useEffect(() => { void refresh(); }, [workspaceId]);
  if (!workspaceId) return null;
  const upload = async (file: File | undefined) => {
    if (!file || readOnly || pending) return;
    setPending(true); setStatus('Uploading file…');
    try { const saved = await uploadWorkspaceFile(workspaceId, file, companyId); setFiles(current => [saved, ...current]); setStatus(`${saved.display_name} is ${saved.state}.`); }
    catch { setStatus('File upload failed.'); }
    finally { setPending(false); }
  };
  const download = async (file: WorkspaceFile) => {
    setPending(true); setStatus(`Downloading ${file.display_name}…`);
    try {
      const response = await downloadWorkspaceFile(workspaceId, file.file_id);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a'); link.href = url; link.download = file.display_name; link.click(); URL.revokeObjectURL(url);
      setStatus(`${file.display_name} downloaded.`);
    } catch { setStatus('File download failed.'); }
    finally { setPending(false); }
  };
  const remove = async (file: WorkspaceFile) => {
    if (readOnly || pending) return;
    setPending(true); setStatus(`Deleting ${file.display_name}…`);
    try { await deleteWorkspaceFile(workspaceId, file.file_id); setFiles(current => current.filter(item => item.file_id !== file.file_id)); setStatus(`${file.display_name} deleted.`); }
    catch { setStatus('File deletion failed.'); }
    finally { setPending(false); }
  };
  return <section className="business-panel file-panel" aria-label="Workspace files">
    <div className="panel-heading"><div className="panel-title"><span className="panel-icon"><FileText size={16} /></span><h3>Workspace files</h3></div>{!readOnly && <label className="soft-button file-upload"><Upload size={14} />Upload idea file<input type="file" onChange={event => { void upload(event.currentTarget.files?.[0]); event.currentTarget.value = ''; }} disabled={pending} /></label>}</div>
    {readOnly && <p className="panel-note">Viewer access can download ready files.</p>}
    {status && <p className="file-status" role="status">{status}</p>}
    {!loaded ? <p className="empty-note">Loading files…</p> : status === 'Files could not be loaded.' ? null : files.length === 0 ? <p className="empty-note">No files have been uploaded.</p> : <ul className="file-list">{files.map(file => <li key={file.file_id}><div><strong>{file.display_name}</strong><span>{file.state} · {file.byte_size.toLocaleString()} bytes · {file.content_sha256.slice(0, 12)}</span></div><div className="file-actions">{file.state === 'ready' && <button className="icon-button" onClick={() => void download(file)} disabled={pending} aria-label={`Download ${file.display_name}`}><Download size={15} /></button>}<button className="icon-button" onClick={() => void remove(file)} disabled={readOnly || pending} aria-label={`Delete ${file.display_name}`}><Trash2 size={15} /></button></div></li>)}</ul>}
  </section>;
}
const CopilotCompany = lazy(() => import('./CopilotCompany'));
export function CompanyWorkspace(props: CompanyProps) {
  return <Suspense fallback={<CompanyWorkspaceContent {...props} />}><CopilotCompany companyId={props.company.id}>{(start, error) => <CompanyWorkspaceContent {...props} copilotStart={start} connectionError={error} />}</CopilotCompany></Suspense>;
}
function CompanyWorkspaceContent({ company, workspace, setWorkspace, persistWorkspace, initialView, mode, toggleMode, onOpen, storageError, readOnly = false, copilotStart, connectionError }: CompanyProps & { copilotStart?: CopilotStart; connectionError?: string }) {
  const recoveringRef = useRef(Boolean(workspace.backendRun && (workspace.backendRun.status !== 'failed' || workspace.backendRun.runId)));
  const [recovering, setRecovering] = useState(recoveringRef.current);
  const [isRunning, setRunning] = useState(recoveringRef.current);
  const [activities, setActivities] = useState<Partial<Record<Agent, Activity>>>(() => Object.fromEntries(workspace.activityLog.map(activity => [activity.agent, activity])));
  const [view, setView] = useState<'chat' | 'company'>(initialView ?? 'chat');
  const [generalChat, setGeneralChat] = useState(false);
  const [initialising, setInitialising] = useState(Boolean(workspace.brief && !workspace.messages.length && !workspace.backendRun));
  const [firstPassInFocus, setFirstPassInFocus] = useState(initialising);
  const analysis = latestIdeaAnalysis(workspace);
  const selectedAreas = selectedWorkflowAreas(workspace);
  const initialBriefPending = initialising;
  const selectedAspect = selectedAreas.length === 1 ? selectedAreas[0] : !generalChat && !initialBriefPending ? nextAspectQuestion(workspace)?.area ?? 'research' : undefined;
  const area = selectedAspect ? scopeForAspect(selectedAspect) : 'overview';
  const uiArea = selectedAspect ?? 'overview';
  const [mapAspect, setMapAspect] = useState<IdeaArea>(uiArea);
  const [guide, setGuide] = useState<AspectGuide | undefined>(() => resumeAspect(selectedAspect ?? 'research', workspace));
  const guideRef = useRef(guide);
  guideRef.current = guide;
  const activeGuide = guide?.area === selectedAspect ? guide : undefined;
  const guidedQuestion = aspectQuestions.find(question => question.id === activeGuide?.questionId);
  const runAspectRef = useRef<IdeaArea>(workspace.backendRun?.aspect ?? uiArea);
  const runQuestionRef = useRef<string | undefined>(undefined);
  const reduceMotion = useReducedMotion();
  const panelTransition = reduceMotion ? { duration: 0 } : { type: 'spring' as const, stiffness: 240, damping: 23, mass: .85 };
  const focused = Boolean(selectedAspect);
  const team = teamAreas.find(item => item.id === (selectedAspect ?? 'overview')) ?? teamAreas[0];
  const [dialog, setDialog] = useState<'panels' | null>(null);
  const [measurementsOpen, setMeasurementsOpen] = useState(false);
  const [editingOrder, setEditingOrder] = useState(false);
  useEffect(() => { setEditingOrder(false); }, [view]);
  const [expandedPanel, setExpandedPanel] = useState<Panel | null>(null);
  const [runError, setRunError] = useState('');
  const controllerRef = useRef<AbortController | null>(null);
  const backendRunRef = useRef(workspace.backendRun);
  const messagesRef = useRef(workspace.messages);
  messagesRef.current = workspace.messages;
  const transportRef = useRef<ReturnType<typeof createAgentosTransport> | null>(null);
  const approvedDraft = useRef<ApprovedWorkDraft | undefined>(undefined);
  const [workLabel, setWorkLabel] = useState('');
  const armDraft = (draft?: ApprovedWorkDraft) => { approvedDraft.current = draft; setWorkLabel(draft?.label || ''); };
  useEffect(() => {
    const draft = approvedDraft.current;
    if (draft && (draft.area !== uiArea || draft.approval.companyId !== workspace.companyId || draft.approval.expectedRevision !== workspace.currentRevision)) armDraft();
  }, [uiArea, workspace.companyId, workspace.currentRevision]);
  const backendRunning = () => hasActiveBackendRun(backendRunRef.current);
  const completionRef = useRef<Promise<void> | null>(null);
  const recordRun = (run: AgentosRun) => {
    const record = (current: Workspace) => {
      const next = run.status === 'submitting' && run.submissionId && current.backendRun?.submissionId !== run.submissionId ? beginBackendRun(current, run.submissionId, run.area, runAspectRef.current) : recordBackendRun(current, run);
      return run.status === 'submitting' && run.submissionId && runQuestionRef.current ? bindAspectReview(next, runQuestionRef.current, run.submissionId) : next;
    };
    const checked = record({ ...workspace, backendRun: backendRunRef.current });
    backendRunRef.current = checked.backendRun;
    const update = (current: Workspace) => ({ ...record(current), activityLog: finishActivities(current.activityLog, run.status) });
    if (run.status === 'submitting' && persistWorkspace && !persistWorkspace(update)) return false;
    setWorkspace(update);
    if (!hasActiveBackendRun(run)) setActivities(current => Object.fromEntries(finishActivities(Object.values(current).filter((activity): activity is Activity => Boolean(activity)), run.status).map(activity => [activity.agent, activity])));
    return true;
  };
  const restoreGuidedReview = (run: AgentosRun, events: readonly WorkEvent[]) => {
    const review = recoveredAspectReview({ ...workspace, backendRun: backendRunRef.current }, run, events);
    if (!review) return;
    setWorkspace(current => completeAspectReview(current, review.questionId));
    if (guideRef.current?.questionId !== review.questionId) return;
    setWorkspace(current => ({ ...current, selectedAreas: [review.guide.area], selectedArea: scopeForAspect(review.guide.area) }));
    setGuide(review.guide);
  };
  if (copilotStart && !transportRef.current) transportRef.current = createAgentosTransport(company.id, recordRun, () => messagesRef.current, copilotStart);
  const [snapshotError, setSnapshotError] = useState('');
  const [snapshotPending, setSnapshotPending] = useState(true);
  useEffect(() => {
    if (!company.workspaceId || !company.companyId || hasActiveBackendRun(workspace.backendRun)) return;
    let active = true;
    setSnapshotPending(true);
    void openWorkspaceCompany(company.workspaceId, company.companyId).then(opened => {
      const fields = canonicalCompanyFields(opened);
      if (active) { setWorkspace(current => ({ ...current, ...fields })); setSnapshotError(''); setSnapshotPending(false); }
    }).catch(() => { if (active) { setSnapshotError('Could not refresh idea actions. Reopen this idea to try again.'); setSnapshotPending(false); } });
    return () => { active = false; };
  }, [company.workspaceId, company.companyId, workspace.backendRun?.runId, workspace.backendRun?.status, workspace.backendRun?.revision]);
  const viewportRef = useRef<HTMLDivElement>(null);
  const homeRef = useRef<HTMLElement>(null);
  const chatRef = useRef<HTMLElement>(null);
  const previousView = useRef(view);
  useLayoutEffect(() => {
    if (previousView.current === view) return;
    previousView.current = view;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const animations = [homeRef.current, ...(view === 'chat' ? [chatRef.current] : [])].flatMap(element => element ? [element.animate(pageRevealFrames, pageRevealTiming)] : []);
    return () => animations.forEach(animation => animation.cancel());
  }, [view]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const append = (message: Message) => setWorkspace(current => fillAspectStartingPoints({ ...current, messages: [...current.messages, { ...message, area: message.area || area, aspect: message.aspect ?? uiArea }].slice(-200), pinned: message.panel ? current.pinned.map(panel => panel.id === message.panel!.id ? message.panel! : panel) : current.pinned }, message.panel));
  const sendMessage = async (input: string, answering?: AspectQuestion) => {
    if (readOnly || !input || recoveringRef.current || controllerRef.current || completionRef.current || backendRunning()) return;
    const initialRequest = !answering && input === 'Save my idea brief';
    if (initialRequest) { setInitialising(true); setFirstPassInFocus(true); }
    if (!initialRequest) {
      setFirstPassInFocus(false);
      setGuide(current => current ? { ...current, showFeedback: true } : current);
      setConversationAtBottom(true);
    }
    if (answering) {
      const ids = [crypto.randomUUID(), crypto.randomUUID()] as const;
      setWorkspace(current => recordAspectAnswer(current, answering, input, ids));
      setConversationAtBottom(true);
    }
    const controller = new AbortController();
    controllerRef.current = controller;
    let finish: (() => void) | undefined;
    completionRef.current = new Promise<void>(resolve => { finish = resolve; });
    setRunning(true); setRunError(''); setActivities({});
    runAspectRef.current = uiArea;
    runQuestionRef.current = answering?.id;
    setWorkspace(current => ({ ...current, activityLog: [], drafts: answering || initialRequest ? current.drafts : { ...current.drafts, [uiArea]: '' } }));
    if (!answering && !(initialRequest && workspace.backendRun)) append({ id: crypto.randomUUID(), role: 'user', text: initialRequest ? workspace.brief?.idea ?? input : input });
    try {
      const initial = initialRequest && workspace.brief;
      const transport = transportRef.current;
      if (!transport) throw new Error('The live backend transport is unavailable.');
      const approval: AgentosApproval | undefined = initial && (workspace.companyId ?? company.companyId) ? { operation: 'journey', stage: 'brief', companyId: (workspace.companyId ?? company.companyId)!, expectedRevision: workspace.currentRevision ?? company.currentRevision ?? 0 } : approvedWorkForSubmission(approvedDraft.current, input, uiArea, workspace.companyId, workspace.currentRevision);
      armDraft();
      const events = transport(initial ? initialCompanyPrompt(initial) : answering ? guidedAnswerPrompt(answering, input) : aspectMentorPrompt(input, uiArea, approval), controller.signal, approval ?? (initial ? 'overview' : area));
      let structuredReview = false;
      for await (const raw of events) {
        const event = eventSchema.parse(raw);
        if (event.type === 'activity') {
          setActivities(current => ({ ...current, [event.agent]: event }));
          setWorkspace(current => ({ ...current, activityLog: [...current.activityLog, event].slice(-100) }));
        }
        else {
          if (answering && isGuidedReview(event, answering)) structuredReview = true;
          const runId = backendRunRef.current?.runId;
          if (!runId) throw new Error('The backend omitted the run identity.');
          setWorkspace(current => applyBackendEvent(current, runId, event));
        }
      }
      if (backendRunRef.current?.status === 'cancelled') append({ id: crypto.randomUUID(), role: 'assistant', text: 'The backend confirmed cancellation.' });
      if (answering && !structuredReview && backendRunRef.current?.status === 'completed') setRunError('Your answer is saved, but the guided review is incomplete. Try Review answer again, or continue in chat.');
      if (answering && structuredReview && !controller.signal.aborted && backendRunRef.current?.status === 'completed') setWorkspace(current => completeAspectReview(current, answering.id));
      if (answering && structuredReview && guideRef.current?.questionId === answering.id && guideRef.current.area === answering.area && !controller.signal.aborted && backendRunRef.current?.status === 'completed') {
        const next = nextAspectQuestion({ ...workspace, aspectChecks: { ...workspace.aspectChecks, [answering.id]: { origin: 'founder', note: input, status: workspace.aspectChecks[answering.id]?.status ?? 'in-progress' } } }, answering.id);
        const nextArea = next?.area ?? answering.area;
        setWorkspace(current => ({ ...current, selectedAreas: [nextArea], selectedArea: scopeForAspect(nextArea) }));
        setGuide({ area: nextArea, questionId: next?.id, showFeedback: true });
      }
    } catch (error) {
      setRunError(error instanceof Error ? error.message : 'Proofseed could not complete this request.');
    } finally {
      controllerRef.current = null;
      if (backendRunRef.current) recordRun(backendRunRef.current);
      setRunning(backendRunning()); finish?.(); completionRef.current = null;
      if (initialRequest) setInitialising(false);
    }
  };
  const onCancel = async () => {
    if (recoveringRef.current) return;
    if (controllerRef.current) { controllerRef.current.abort(); await completionRef.current; return; }
    if (completionRef.current) { await completionRef.current; return; }
    const saved = backendRunRef.current;
    if (saved?.runId && hasActiveBackendRun(saved)) {
      const runId = saved.runId;
      setRunError('');
      const stopping = cancelAgentosRun(company.id, runId, messagesRef.current).then(recovered => {
        recordRun(recovered.run);
        for (const event of recovered.events) if (event.type === 'message') setWorkspace(current => applyBackendEvent(current, runId, event));
        restoreGuidedReview(recovered.run, recovered.events);
        if (recovered.run.status === 'cancelled') append({ id: crypto.randomUUID(), role: 'assistant', text: 'The backend confirmed cancellation of the saved run.' });
        if (recovered.run.status === 'failed') setRunError('The saved backend run failed. You can send a new request.');
        setRunning(false);
      }).catch(error => { setRunError(error instanceof Error ? error.message : 'Cancellation was not confirmed.'); });
      completionRef.current = stopping;
      try { await stopping; } finally { completionRef.current = null; }
    }
  };
  const onNew = async (message: AppendMessage) => sendMessage(message.content.filter(part => part.type === 'text').map(part => part.text).join('\n').trim());
  const chatMessages = presentMessages(workspace.messages);
  const areaMessages = chatMessages;
  const runtime = useExternalStoreRuntime({ messages: areaMessages, convertMessage, isRunning: isRunning || (!activeGuide && !copilotStart && !connectionError), onNew, onCancel });
  useEffect(() => { if (analysis && !initialising) setGuide(resumeAspect(selectedAspect ?? nextAspectQuestion(workspace)?.area ?? 'research', workspace)); }, [analysis, initialising]);
  useEffect(() => {
    const saved = backendRunRef.current;
    if (!saved) return;
    if (saved.status === 'failed' && !saved.runId) { setRunError(saved.failureReason ?? 'The request was not accepted. You can try again.'); return; }
    let runId = saved.runId;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setRunning(true);
      void (async () => {
        if (!runId && saved.submissionId) {
          const receipt = await readAgentosReceipt(company.id, saved.submissionId, controller.signal);
          recordRun(receipt); runId = receipt.runId;
        }
        if (!runId) throw new Error('The saved work has no recoverable run identity.');
        return readAgentosRun(company.id, runId, controller.signal, messagesRef.current);
      })().then(recovered => {
        if (controller.signal.aborted) return;
        // Check authoritative company binding before applying any recovered artifact.
        recordRun(recovered.run);
        const history = recovered.events.filter((event): event is Activity => event.type === 'activity');
        if (history.length) {
          setActivities(Object.fromEntries(finishActivities(history, recovered.run.status).map(activity => [activity.agent, activity])));
          setWorkspace(current => ({ ...current, activityLog: finishActivities(history, recovered.run.status) }));
        }
        for (const event of recovered.events) if (event.type === 'message') setWorkspace(current => applyBackendEvent(current, recovered.run.runId!, event));
        restoreGuidedReview(recovered.run, recovered.events);
        setRunning(hasActiveBackendRun(recovered.run));
        if (hasActiveBackendRun(recovered.run)) setRunError('The saved backend run is still running. Stop it or reopen this idea later to check its saved result.');
        if (recovered.run.status === 'failed') setRunError('The saved backend run failed. You can send a new request.');
      }).catch(error => {
        if (controller.signal.aborted) return;
        setRunning(hasActiveBackendRun(saved)); setRunError(error instanceof Error ? error.message : 'Saved results could not be recovered.');
      }).finally(() => {
        if (controller.signal.aborted) return;
        recoveringRef.current = false; setRecovering(false);
      });
    }, 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, []);
  useEffect(() => {
    if (!workspace.brief || workspace.messages.length || workspace.backendRun || !copilotStart) return;
    // Deferring lets StrictMode cancel its first mount without starting a duplicate run.
    const timer = setTimeout(() => { runtime.thread.composer.setText('Save my idea brief'); runtime.thread.composer.send(); }, 0);
    return () => clearTimeout(timer);
  }, [Boolean(copilotStart)]);
  const selectArea = (next: IdeaArea, draft?: string) => {
    setFirstPassInFocus(false);
    const nextScope = scopeForAspect(next);
    const currentDraft = runtime.thread.composer.getState().text;
    setWorkspace(current => ({ ...current, selectedArea: nextScope, selectedAreas: next === 'overview' ? [] : [next], drafts: { ...current.drafts, [uiArea]: currentDraft, ...(draft !== undefined ? { [next]: draft } : {}) } }));
    if (window.matchMedia('(max-width: 760px)').matches) setView('chat');
    setGeneralChat(next === 'overview');
    setConversationAtBottom(true);
    setGuide(next !== 'overview' ? resumeAspect(next, workspace) : undefined);
    if (draft === undefined) armDraft();
    if (next === uiArea && draft !== undefined) runtime.thread.composer.setText(draft);
    setEditingOrder(false); setDialog(null);
    if (next !== 'overview') requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('.composer-input')?.focus());
    else requestAnimationFrame(() => { homeRef.current?.scrollTo({ top: 0 }); document.querySelector<HTMLElement>('.idea-map-center')?.focus({ preventScroll: true }); });
  };
  useEffect(() => { runtime.thread.composer.setText(workspace.drafts[uiArea] || ''); }, [uiArea]);
  const ask = (text: string, stage?: AgentosApproval['stage']) => {
    if (stage) {
      const companyId = workspace.backendRun?.companyId ?? workspace.companyId ?? company.companyId;
      const expectedRevision = workspace.currentRevision ?? workspace.backendRun?.revision ?? company.currentRevision;
      armDraft(companyId && expectedRevision !== undefined ? { text, area: uiArea, label: 'Run this step', approval: { operation: 'journey', stage, companyId, expectedRevision, teamArea: area } } : undefined);
    }
    if (readOnly || isRunning) return;
    setGuide(undefined);
    setDialog(null);
    runtime.thread.composer.setText(text); runtime.thread.composer.send();
  };
  const discuss = (prompt: string, panel?: Panel) => {
    const briefAction = panel?.provenance?.artifact_type === 'intake' ? currentCompanyActions(workspace).find(action => action.id === 'brief') : undefined;
    if (briefAction) prepareAction(briefAction, false, prompt);
    else { armDraft(); selectArea(panel ? areaForPanel(panel, workspace) : selectedAspect ?? area, prompt); }
  };
  const pin = (panel: Panel) => {
    if (!readOnly) setWorkspace(current => ({
      ...current,
      pinned: current.pinned.some(item => item.id === panel.id)
        ? current.pinned.filter(item => item.id !== panel.id)
        : [...current.pinned, panel].slice(-12),
    }));
  };
  const shortlist = (id: string) => { if (!readOnly) setWorkspace(current => ({ ...current, shortlist: toggleSavedSelection(current.shortlist, id, 100) })); };
  const approve = (id: string) => { if (!readOnly) setWorkspace(current => ({ ...current, approvedOffers: toggleSavedSelection(current.approvedOffers, id, 20) })); };
  const completeTask = (id: string) => { if (!readOnly) setWorkspace(current => ({ ...current, completedTasks: current.completedTasks.includes(id) ? current.completedTasks.filter(item => item !== id) : [...current.completedTasks, id].slice(-400) })); };
  const panels = latestPanels({ ...workspace, messages: chatMessages });
  const actions = snapshotPending ? [] : currentCompanyActions(workspace);
  const canonicalNext = actions.find(action => action.id === workspace.nextAction);
  const nextStage = canonicalNext ?? { label: 'Review idea', prompt: 'Help me review our existing idea context.', eligible: false, blocked_reason: snapshotError || 'Refreshing idea actions…' };
  const prepareAction = (action: CompanyAction, send = false, prompt = action.prompt) => {
    if (!action.eligible || readOnly || isRunning || snapshotPending || snapshotError || !workspace.companyId || workspace.currentRevision === undefined) return;
    const targetAspect = actionAreas[action.id];
    armDraft({ text: prompt.trim(), label: action.label, area: targetAspect, approval: { operation: action.operation, stage: action.stage, companyId: workspace.companyId, expectedRevision: workspace.currentRevision, teamArea: action.area } });
    if (send && uiArea === targetAspect) ask(prompt); else selectArea(targetAspect, prompt);
  };
  const chooseNextStage = (send: boolean) => {
    if (canonicalNext) prepareAction(canonicalNext, send);
  };
  const nextDisabled = isRunning || (!canonicalNext?.eligible || Boolean(snapshotError));
  const nextReason = canonicalNext?.blocked_reason ?? snapshotError;
  const currentPanel = (panel: Panel) => panels.find(item => item.id === panel.id) || panel;
  const dashboardPanels = orderedPanels([...panels, ...(expandedPanel && !panels.some(panel => panel.id === expandedPanel.id) ? [expandedPanel] : [])], workspace.panelOrder);
  const visiblePanels = panelsForAreas(dashboardPanels, workspace, selectedAreas);
  const renderedPanels = view === 'chat' ? orderedPanels([...workspace.pinned, ...(expandedPanel && !workspace.pinned.some(panel => panel.id === expandedPanel.id) ? [expandedPanel] : [])], workspace.panelOrder) : [];
  const utilityCards = view === 'company' && company.workspaceId ? [
    { id: 'utility-files', content: <FilePanel workspaceId={company.workspaceId} companyId={company.companyId} readOnly={readOnly} /> },
    ...(company.companyId && company.currentRevision !== undefined && company.stateSha256 ? [{ id: 'utility-operations', content: <FounderOperationsPanel workspaceId={company.workspaceId} companyId={company.companyId} revision={workspace.currentRevision ?? company.currentRevision} stateSha256={workspace.stateSha256 ?? company.stateSha256} readOnly={readOnly} /> }] : []),
  ] : [];
  const reorder = (id: string, target: string) => setWorkspace(current => {
    const panels = orderedPanels(latestPanels({ ...current, messages: presentMessages(current.messages) }), current.panelOrder);
    const source = panels.find(panel => panel.id === id), destination = panels.find(panel => panel.id === target);
    if (!source || !destination) return current;
    return { ...current, panelOrder: movePanel(panels, id, target) };
  });
  const openPanel = (panel: Panel | null) => {
    setExpandedPanel(panel);
    if (panel && (view === 'company' || window.matchMedia('(max-width: 760px)').matches)) selectArea(areaForPanel(panel, workspace));
    if (panel) requestAnimationFrame(() => document.getElementById(`home-panel-${panel.id}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }));
  };
  const workingAgent = Object.values(activities).find(activity => activity?.state === 'working');
  const [conversationAtBottom, setConversationAtBottom] = useState(true);
  useEffect(() => {
    if (!activeGuide && !firstPassInFocus) return;
    const viewport = viewportRef.current;
    const content = viewport?.querySelector('.conversation-content');
    const scroll = () => {
      if (!viewport) return;
      const reply = activeGuide?.showFeedback ? Array.from(content?.querySelectorAll('.assistant-message') ?? []).at(-1) : undefined;
      const anchor = firstPassInFocus ? content?.querySelector('.idea-first-pass') : reply ?? content?.querySelector('.aspect-guide');
      if (!anchor) return;
      viewport.scrollTo({ top: viewport.scrollTop + anchor.getBoundingClientRect().top - viewport.getBoundingClientRect().top });
    };
    const observer = new ResizeObserver(scroll);
    const stopFollowing = () => observer.disconnect();
    const interactionEvents = ['wheel', 'pointerdown', 'keydown'] as const;
    interactionEvents.forEach(name => viewport?.addEventListener(name, stopFollowing, { passive: true }));
    if (content) observer.observe(content);
    const frame = requestAnimationFrame(scroll);
    return () => {
      cancelAnimationFrame(frame); observer.disconnect();
      interactionEvents.forEach(name => viewport?.removeEventListener(name, stopFollowing));
    };
  }, [activeGuide, view, firstPassInFocus, initialising]);
  const previousMessageCount = useRef(workspace.messages.length);
  useEffect(() => {
    if (previousMessageCount.current === workspace.messages.length) return;
    previousMessageCount.current = workspace.messages.length;
    if (!firstPassInFocus && conversationAtBottom) viewportRef.current?.scrollTo({ top: viewportRef.current.scrollHeight, behavior: 'smooth' });
  }, [workspace.messages.length, firstPassInFocus, conversationAtBottom]);

  return <WorkspaceContext.Provider value={{ workspace, mode, pin, shortlist, approve, completeTask, open: openPanel, discuss, selectArea, area, workspaceId: company.workspaceId, grouped: focused }}><AssistantRuntimeProvider runtime={runtime}>
    <div className={['workspace company-workspace', view === 'company' ? 'mentor-map-layout' : 'mentor-panels-layout', view === 'chat' && focused ? 'aspect-chat-open' : ''].join(' ')}>
      <Atmosphere mode={mode} /><TransitionGrain key={view} /><div className="bottom-blur" aria-hidden="true" />
      <header className="topbar">
        <div className="topbar-brand"><button className="home-button" onClick={() => onOpen(null)} aria-label="All ideas"><Home size={19} /></button><span className="wordmark"><img className="brand-logo" src="/favicon.svg" alt="" />Proofseed</span></div>
        <Tabs className="view-switch" value={view} onValueChange={value => setView(value === 'company' ? 'company' : 'chat')}><LiquidBackdrop /><TabsList aria-label="Workspace view"><TabsTrigger value="chat">Mentor</TabsTrigger><TabsTrigger value="company">Idea map</TabsTrigger></TabsList></Tabs>
        <div className="topbar-actions"><ModeToggle mode={mode} onToggle={toggleMode} /><DropdownMenu.Root><DropdownMenu.Trigger asChild><button className="account-button" aria-label="Workspace settings"><SlidersHorizontal size={17} /></button></DropdownMenu.Trigger><DropdownMenu.Portal><DropdownMenu.Content className="workspace-menu" align="end" sideOffset={8} collisionPadding={14}>
          <DropdownMenu.Item className="workspace-menu-item" disabled={view !== 'chat' || renderedPanels.length < 2} onSelect={() => setEditingOrder(!editingOrder)}><GripVertical size={16} />{editingOrder ? 'Done editing' : 'Edit pinned panel order'}</DropdownMenu.Item>
          <DropdownMenu.Item className="workspace-menu-item" onSelect={toggleMode}>{mode === 'light' ? <Moon size={16} /> : <Sun size={16} />}Switch to {mode === 'light' ? 'dark' : 'light'} mode</DropdownMenu.Item>
        </DropdownMenu.Content></DropdownMenu.Portal></DropdownMenu.Root></div>
      </header>

      <aside id="team-area-content" ref={homeRef} className="home-pane" aria-label={view === 'company' ? 'Idea dashboard' : 'Idea Home'}>
        <div className="home-heading"><h1 className="company-name">{company.name}</h1></div>
        {view === 'company' && <TeamNavigation areas={mapAspect === 'overview' ? [] : [mapAspect]} workspace={workspace} ideaName={company.name} onSelect={setMapAspect} />}
        {view === 'chat' && <div className="pinned-label"><span>Pinned panels</span><button className="icon-button" onClick={() => setDialog('panels')} aria-label="Add an idea panel"><Plus size={17} /></button></div>}
        <div className="home-panels">{renderedPanels.map((panel, index) => <motion.div layout transition={panelTransition} className="home-panel-item" id={`home-panel-${panel.id}`} data-panel-id={panel.id} key={panel.id} onDragOver={event => { if (editingOrder) event.preventDefault(); }} onDrop={event => { if (editingOrder) { event.preventDefault(); reorder(event.dataTransfer.getData('text/plain'), panel.id); } }}>
          {editingOrder && <div className="panel-reorder"><button className="icon-button drag-handle" draggable onDragStart={event => { event.dataTransfer.setData('text/plain', panel.id); event.dataTransfer.effectAllowed = 'move'; }} aria-label={`Drag ${panel.title} to reorder`}><GripVertical size={15} /></button><span /><button className="icon-button" disabled={index === 0} aria-label={`Move ${panel.title} earlier`} onClick={() => reorder(panel.id, renderedPanels[index - 1].id)}><ArrowUp size={14} /></button><button className="icon-button" disabled={index === renderedPanels.length - 1} aria-label={`Move ${panel.title} later`} onClick={() => reorder(panel.id, renderedPanels[index + 1].id)}><ArrowDown size={14} /></button></div>}
          <div className="panel-reveal"><BusinessPanel panel={currentPanel(panel)} compact expandable expanded={expandedPanel?.id === panel.id} /></div></motion.div>)}{utilityCards.map(card => <div className="home-panel-item utility-panel-item" key={card.id} data-panel-id={card.id}><div className="panel-reveal">{card.content}</div></div>)}</div>
        {view === 'chat' && renderedPanels.length === 0 && <p className="empty-note">Pin useful responses here as your idea develops.</p>}
        {<details className="company-actions" aria-label="Saved workflow actions"><summary>Saved workflow actions</summary>{(focused ? actions.filter(action => actionAreas[action.id] === uiArea) : actions.filter(action => ['builder', 'marketer', 'metrics'].includes(action.id) && action.eligible)).map(action => <button key={action.id} className="soft-button team-start" disabled={isRunning || readOnly || !action.eligible || Boolean(snapshotError)} title={action.blocked_reason || undefined} onClick={() => action.id === 'metrics' ? setMeasurementsOpen(true) : prepareAction(action)}>{action.label}<ArrowRight size={15} /></button>)}{(focused ? actions.find(action => actionAreas[action.id] === uiArea && !action.eligible)?.blocked_reason : nextReason) && <p className="empty-note">{focused ? actions.find(action => actionAreas[action.id] === uiArea && !action.eligible)?.blocked_reason : nextReason}</p>}{snapshotError && snapshotError !== nextReason && <p role="status" className="empty-note">{snapshotError}</p>}</details>}
        {focused && team.agent && workspace.activityLog.some(item => item.agent === team.agent) && <details className="team-area-history"><summary>Activity</summary>{workspace.activityLog.filter(item => item.agent === team.agent).map((item, index) => <p key={index}>{item.detail}</p>)}</details>}
        {view === 'company' && <p className="company-footnote">Live backend workflow · Review evidence before acting.</p>}
      </aside>
      <main id="team-conversation" ref={chatRef} className="main-pane" aria-label={focused ? team.name + ' conversation' : 'Idea conversation'}>
        <div className="mentor-pane-heading"><span><Leaf size={17} />Your mentor</span><DropdownMenu.Root><DropdownMenu.Trigger asChild><button className="mentor-aspect-trigger" aria-label="Choose an aspect mentor" disabled={isRunning || recovering || initialising}>{focused ? team.name : 'All aspects'}<ChevronDown size={13} /></button></DropdownMenu.Trigger><DropdownMenu.Portal><DropdownMenu.Content className="workspace-menu" align="end" sideOffset={8} collisionPadding={14} aria-label="Aspect mentors">{teamAreas.map(mentor => <DropdownMenu.Item key={mentor.id} className="workspace-menu-item" onSelect={() => selectArea(mentor.id, runtime.thread.composer.getState().text)}><span className="mentor-choice-check">{uiArea === mentor.id && <Check size={14} />}</span>{mentor.id === 'overview' ? 'All aspects' : mentor.name}</DropdownMenu.Item>)}</DropdownMenu.Content></DropdownMenu.Portal></DropdownMenu.Root></div>
        <ThreadPrimitive.Root className="conversation">
          <ThreadPrimitive.Viewport className="conversation-scroll" ref={viewportRef} autoScroll={false} scrollToBottomOnInitialize={false} scrollToBottomOnThreadSwitch={false} scrollToBottomOnRunStart={false} onScroll={() => {
            const element = viewportRef.current;
            if (element) setConversationAtBottom(element.scrollHeight - element.scrollTop - element.clientHeight < 100);
          }}>
            <div className="conversation-content">{areaMessages.length === 0 && !activeGuide && !initialising && <div className="conversation-intro empty-conversation">{view === 'chat' && <span className="empty-company-name">{company.name}</span>}<h2>{focused ? team.goal : 'Start with your idea.'}</h2><p>What do you want this software idea to solve?</p></div>}
              {initialising && <OpenUIIdeaAnalysis pending onAspect={area => selectArea(area)} />}
              <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
              {selectedAspect && !initialising && <OpenUIAspectGuide area={selectedAspect} guide={activeGuide} workspace={workspace} disabled={readOnly || isRunning || recovering || !copilotStart} onResume={() => {
                const questionId = guidedQuestion?.id ?? resumeAspect(selectedAspect, workspace).questionId ?? aspectQuestions.find(question => question.area === selectedAspect)?.id;
                setGuide({ area: selectedAspect, questionId });
              }} onQuestion={id => {
                const question = aspectQuestions.find(item => item.id === id);
                if (!question) return;
                setFirstPassInFocus(false); setGuide({ area: question.area, questionId: id });
                setWorkspace(current => ({ ...current, selectedAreas: [question.area], selectedArea: scopeForAspect(question.area) }));
              }} onTalk={() => { document.querySelector<HTMLTextAreaElement>('.composer-input')?.focus(); }} onChange={value => {
                if (!readOnly && guidedQuestion) setWorkspace(current => ({ ...current, aspectFormDrafts: { ...current.aspectFormDrafts, [guidedQuestion.id]: value } }));
              }} onSubmit={() => { if (guidedQuestion) { armDraft(); void sendMessage(aspectFormValue(workspace, guidedQuestion.id).trim(), guidedQuestion); } }} onAssess={status => { if (!readOnly && guidedQuestion) setWorkspace(current => ({ ...current, aspectChecks: { ...current.aspectChecks, [guidedQuestion.id]: { ...current.aspectChecks[guidedQuestion.id], note: current.aspectChecks[guidedQuestion.id]?.note ?? '', status } } })); }} />}

              {isRunning && <div className="working-message" role="status"><LoaderCircle size={15} className="spin" />{workingAgent?.detail || (recovering ? 'Recovering the saved backend run…' : 'Waiting for the backend…')}</div>}
              {(runError || connectionError) && <div className="error-note" role="alert">{runError || connectionError}</div>}
              {workspace.brief && !analysis && workspace.backendRun?.status === 'failed' && <button className="soft-button" disabled={readOnly || isRunning || recovering || !copilotStart} onClick={() => { void sendMessage('Save my idea brief'); }}>Retry idea analysis<ArrowRight size={14} /></button>}
              {!focused && workspace.messages.length > 0 && <div className="suggestions"><button onClick={() => chooseNextStage(true)} title={nextReason || undefined} disabled={nextDisabled}>{nextStage.label} <ArrowRight size={13} /></button></div>}
            </div>
          </ThreadPrimitive.Viewport>
          <div className="composer-dock">{!conversationAtBottom && <button className="scroll-bottom" onClick={() => { setConversationAtBottom(true); viewportRef.current?.scrollTo({ top: viewportRef.current.scrollHeight, behavior: 'smooth' }); }} aria-label="Scroll to latest message"><ArrowDown size={16} /></button>}
            <OpenUIComposer label={focused ? 'Message ' + team.name : 'Message Proofseed'} placeholder={guidedQuestion ? 'Ask anything, or discuss this question…' : focused ? 'Ask about ' + team.name.toLowerCase() + '…' : 'What’s our next move?'} running={isRunning} recovering={recovering} stopLabel="Stop backend run" onExplore={() => setDialog('panels')} workLabel={workLabel} onClearWork={() => armDraft()} onInput={value => { armDraft(editApprovedWorkDraft(approvedDraft.current, value, uiArea)); setWorkspace(current => ({ ...current, drafts: { ...current.drafts, [uiArea]: value } })); }} />
            <div className="conversation-caption">{activeGuide ? 'Answer in the form · Chat is always open' : 'Live Proofseed workflow · Generated artifacts need review'}</div>
            {storageError && <p role="status" className="storage-warning">Browser storage is unavailable. This session won’t be saved.</p>}
          </div>
        </ThreadPrimitive.Root>
      </main>

      <Dialog.Root open={measurementsOpen} onOpenChange={setMeasurementsOpen}><Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="dialog-content measurement-dialog"><div className="dialog-heading"><Dialog.Title>Review a real result</Dialog.Title><Dialog.Close className="icon-button" aria-label="Close measurements"><X size={19} /></Dialog.Close></div><Dialog.Description className="dialog-description">Share one measurement. Review the analysis request before running it.</Dialog.Description><OpenUIMeasurements disabled={isRunning || readOnly || snapshotPending || Boolean(snapshotError)} onPrepare={prompt => { const action = actions.find(item => item.id === 'metrics'); if (action?.eligible) { prepareAction(action, false, prompt); setMeasurementsOpen(false); } }} /></Dialog.Content></Dialog.Portal></Dialog.Root>
      <Dialog.Root open={!!dialog} onOpenChange={open => { if (!open) setDialog(null); }}><Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="dialog-content"><Dialog.Title className="sr-only">Idea panels</Dialog.Title><Dialog.Description className="sr-only">Manage this idea workspace.</Dialog.Description><div className="dialog-heading"><h2>What would you like to see?</h2><button className="icon-button" aria-label="Close dialog" onClick={() => setDialog(null)}><X size={19} /></button></div><p className="dialog-description">Ask for a view, then pin it to keep it on Home.</p>
        {dialog === 'panels' && <div className="panel-choices">{[{ title: 'Customer pipeline', detail: 'Find and shortlist your first prospects', icon: Users }, { title: 'Offer & positioning', detail: 'Shape a clear promise for your customers', icon: Compass }, { title: 'Pricing exploration', detail: 'Compare hypotheses before testing demand', icon: SlidersHorizontal }, { title: 'Evidence review', detail: 'Separate assumptions from supported claims', icon: ShieldCheck }, { title: 'Custom view', detail: 'Create your own interactive calculator or component', icon: SlidersHorizontal }, { title: 'Launch plan', detail: 'Track the next steps towards a pilot', icon: CheckCheck }].map(choice => <button key={choice.title} onClick={() => selectArea(panelChoiceAreas[choice.title] ?? selectedAspect ?? area, ({ 'Customer pipeline': 'Research target customers and qualification criteria', 'Offer & positioning': 'Develop our offer and positioning', 'Pricing exploration': 'Review our pricing assumptions', 'Evidence review': 'Review evidence and verification findings', 'Custom view': 'I want to create my own custom interactive idea component. Ask what it should show and do before creating it.', 'Launch plan': 'Develop our minimum offering and delivery plan' }[choice.title] || choice.title))} disabled={isRunning}><choice.icon size={21} /><span><strong>{choice.title}</strong><small>{choice.detail}</small></span><ArrowRight size={16} /></button>)}</div>}
      </Dialog.Content></Dialog.Portal></Dialog.Root>
    </div>
  </AssistantRuntimeProvider></WorkspaceContext.Provider>;
}
