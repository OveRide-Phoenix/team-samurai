import { Onboarding } from './Onboarding';
import { TransitionGrain } from './TransitionGrain';
import { Atmosphere } from './Atmosphere';
import { useEffect, useRef, useState } from 'react';
import { MotionConfig } from 'motion/react';
import { ArrowRight, ArrowUp, Building2 } from 'lucide-react';
import { CompanyWorkspace } from './App';
import { companySnapshotEvents } from './agentos';
import { continueCompanyView, emptyCompanyView, restorePortfolio, type CompanyBrief, type CompanyView, type Message, type Portfolio, type WorkEvent } from './model';
import { loadPortfolio, persistPortfolio, portfolioStorageKey, type BrowserScope } from './browserStorage';
import { createLatestRequestGuard, createOneAtATimeGate, createWorkspace, createWorkspaceCompany, firstWritableWorkspace, listWorkspaceCompanies, listWorkspaces, openWorkspaceCompany, shouldLoadWorkspaceDirectory, type DirectoryCompany, type WorkspaceDirectory } from './workspaces';
import { ModeToggle } from './ShellParts';

type Reservation = { readonly workspace: WorkspaceDirectory; readonly company: DirectoryCompany };
type CompanyCreationRetry = { readonly workspace: WorkspaceDirectory; readonly submissionId: string };

function companyName(workspace: WorkspaceDirectory, company: DirectoryCompany): string {
  return `${workspace.display_name} · ${company.company_id.slice(0, 8)}`;
}

function hydrateCompanyView(current: CompanyView, snapshot: unknown, companyId: string): CompanyView {
  const events = companySnapshotEvents(snapshot, companyId);
  const messages: Message[] = events.flatMap((event, index) => event.type === 'message' ? [{
    id: event.panel ? `snapshot-${event.panel.id}` : `snapshot-${companyId}-${index}`,
    role: 'assistant' as const, text: event.text, ...(event.panel ? { panel: event.panel } : {}),
  }] : []);
  const panels = messages.flatMap(message => message.panel ? [message.panel] : []);
  const panelIds = new Set(panels.map(panel => panel.id));
  const activities = events.filter((event): event is Extract<WorkEvent, { type: 'activity' }> => event.type === 'activity');
  return {
    ...current, executionMode: 'live',
    messages: [...current.messages.filter(message => !message.panel || !panelIds.has(message.panel.id)), ...messages].slice(-200),
    pinned: [...current.pinned.filter(panel => !panelIds.has(panel.id)), ...panels].slice(-12),
    ...(activities.length ? { activityLog: activities } : {}),
  };
}

export function App({ scope }: { readonly scope: BrowserScope }) {
  const scopedStorageKey = portfolioStorageKey(scope);
  const [portfolio, setPortfolio] = useState<Portfolio>(() => {
    try { return loadPortfolio(localStorage, scope); }
    catch { return restorePortfolio(null, null); }
  });
  const portfolioRef = useRef(portfolio);
  portfolioRef.current = portfolio;
  const [name, setName] = useState('');
  const [reservation, setReservation] = useState<Reservation | null>(null);
  const [companyCreationRetry, setCompanyCreationRetry] = useState<CompanyCreationRetry | null>(null);
  const [workspaces, setWorkspaces] = useState<readonly WorkspaceDirectory[]>([]);
  const [directory, setDirectory] = useState<readonly Reservation[]>([]);
  const [directoryError, setDirectoryError] = useState('');
  const [storageError, setStorageError] = useState(false);
  const startGate = useRef(createOneAtATimeGate());
  const openGuard = useRef(createLatestRequestGuard());
  const [startingCompany, setStartingCompany] = useState(false);
  const [openingCompanyId, setOpeningCompanyId] = useState<string | null>(null);
  useEffect(() => {
    document.documentElement.dataset.mode = portfolio.mode;
    document.documentElement.style.colorScheme = portfolio.mode;
    try { localStorage.setItem(scopedStorageKey, JSON.stringify(portfolio)); setStorageError(false); }
    catch { setStorageError(true); }
  }, [portfolio, scopedStorageKey]);
  useEffect(() => {
    if (!shouldLoadWorkspaceDirectory(portfolio.activeId)) return;
    let active = true;
    void (async () => {
      try {
        const workspaces = await listWorkspaces();
        const companies = await Promise.all(workspaces.map(async workspace => (await listWorkspaceCompanies(workspace.workspace_id)).map(company => ({ workspace, company }))));
        if (active) { setWorkspaces(workspaces); setDirectory(companies.flat()); setDirectoryError(''); }
      } catch (error) {
        if (active) setDirectoryError(error instanceof Error ? 'Shared companies are unavailable. Try again from Home.' : 'Shared companies are unavailable.');
      }
    })();
    return () => { active = false; };
  }, [portfolio.activeId]);
  const updatePortfolio = (update: (current: Portfolio) => Portfolio, persistNow = false): boolean => {
    const next = update(portfolioRef.current);
    if (persistNow) {
      if (!persistPortfolio(localStorage, scopedStorageKey, next)) { setStorageError(true); return false; }
      setStorageError(false);
    }
    portfolioRef.current = next;
    setPortfolio(next);
    return true;
  };
  const toggleMode = () => { updatePortfolio(current => ({ ...current, mode: current.mode === 'light' ? 'dark' : 'light' })); };
  const open = (activeId: string | null) => { openGuard.current.invalidate(); setReservation(null); setCompanyCreationRetry(null); updatePortfolio(current => ({ ...current, activeId })); };
  const create = (brief: CompanyBrief, pending: Reservation) => {
    const parentSessionId = pending.company.parent_session_id;
    if (!parentSessionId) { setDirectoryError('The company reservation did not include a session. Return Home and try again.'); return; }
    const local = {
      id: parentSessionId, name: name.trim(), workspace: { ...emptyCompanyView(), brief, executionMode: 'live' as const },
      workspaceId: pending.workspace.workspace_id, companyId: pending.company.company_id,
      currentRevision: pending.company.current_revision, stateSha256: pending.company.state_sha256, createdAt: pending.company.created_at, role: pending.workspace.role,
    };
    updatePortfolio(current => ({ ...current, activeId: local.id, companies: [...current.companies, local] }));
    setDirectory(current => [...current, pending]); setName(''); setReservation(null);
  };
  const startCompany = async () => {
    if (!name.trim() || portfolio.companies.length >= 50 || openGuard.current.isPending() || !startGate.current.tryBegin()) return;
    openGuard.current.invalidate();
    setStartingCompany(true);
    const retry = companyCreationRetry;
    const submissionId = retry?.submissionId ?? crypto.randomUUID();
    let workspace = retry?.workspace;
    try {
      workspace ??= firstWritableWorkspace(workspaces) ?? await createWorkspace(`${name.trim()} workspace`);
      const company = await createWorkspaceCompany(workspace.workspace_id, submissionId);
      setCompanyCreationRetry(null); setReservation({ workspace, company }); setDirectoryError('');
    } catch {
      setCompanyCreationRetry(workspace ? { workspace, submissionId } : null);
      setDirectoryError('Could not reserve a company. Try again.');
    } finally { startGate.current.finish(); setStartingCompany(false); }
  };
  const openShared = async (item: Reservation) => {
    if (startGate.current.isPending()) return;
    const request = openGuard.current.begin();
    setOpeningCompanyId(item.company.company_id);
    try {
      const opened = await openWorkspaceCompany(item.workspace.workspace_id, item.company.company_id);
      if (!opened.parent_session_id || !opened.snapshot) throw new Error('The shared company could not be opened.');
      if (!openGuard.current.isCurrent(request)) return;
      const existing = portfolioRef.current.companies.find(company => company.workspaceId === opened.workspace_id && company.companyId === opened.company_id);
      const hydrated = hydrateCompanyView(existing?.workspace ?? emptyCompanyView(), opened.snapshot, opened.company_id);
      const workspace = item.workspace.role === 'viewer' ? hydrated : continueCompanyView(hydrated, opened.company_id, opened.current_revision);
      const local = {
        id: opened.parent_session_id, name: existing?.name ?? companyName(item.workspace, opened), workspace,
        workspaceId: opened.workspace_id, companyId: opened.company_id,
        currentRevision: opened.current_revision, stateSha256: opened.state_sha256, createdAt: opened.created_at, role: item.workspace.role,
      };
      updatePortfolio(current => ({ ...current, activeId: local.id, companies: existing ? current.companies.map(company => company.id === existing.id ? local : company) : [...current.companies, local] }));
      setDirectoryError('');
    } catch (error) {
      if (openGuard.current.isCurrent(request)) setDirectoryError(error instanceof Error ? error.message : 'Could not open the shared company.');
    } finally {
      openGuard.current.finish(request);
      if (openGuard.current.isCurrent(request)) setOpeningCompanyId(null);
    }
  };
  const company = portfolio.companies.find(item => item.id === portfolio.activeId);
  const updateCompanyView = (update: CompanyView | ((current: CompanyView) => CompanyView), persistNow = false): boolean => {
    if (!company) return false;
    return updatePortfolio(current => ({ ...current, companies: current.companies.map(item => item.id === company.id ? {
      ...item, workspace: typeof update === 'function' ? update(item.workspace) : update,
    } : item) }), persistNow);
  };
  const setCompanyView = (update: CompanyView | ((current: CompanyView) => CompanyView)) => { updateCompanyView(update); };
  const persistCompanyView = (update: CompanyView | ((current: CompanyView) => CompanyView)) => updateCompanyView(update, true);
  return <MotionConfig reducedMotion="user">{company ? <CompanyWorkspace key={company.id} company={company} workspace={company.workspace} setWorkspace={setCompanyView} persistWorkspace={persistCompanyView} mode={portfolio.mode} toggleMode={toggleMode} onOpen={open} storageError={storageError} readOnly={company.role === 'viewer'} /> :
    <div className="workspace landing"><Atmosphere mode={portfolio.mode} /><div className="bottom-blur" aria-hidden="true" />
      <header className="topbar"><span className="wordmark">Samurai</span><div className="topbar-actions"><ModeToggle mode={portfolio.mode} onToggle={toggleMode} /></div></header>
      <main key={reservation ? 'intake' : 'home'} className="landing-content"><div className="landing-main">{reservation ? <Onboarding name={name.trim()} onCancel={() => setReservation(null)} onComplete={brief => create(brief, reservation)} /> : <><h1>An idea is<br />just the beginning.</h1><p className="landing-description">Build a company worth believing in.</p>
        <form className="company-intake" onSubmit={event => { event.preventDefault(); void startCompany(); }}>
          <input aria-label="Company name" placeholder="What will you call your company?" value={name} onChange={event => { setName(event.target.value); setCompanyCreationRetry(null); }} maxLength={80} className="intake-input" />
          <button type="submit" className="send-button intake-send" aria-label="Start company" aria-busy={startingCompany} disabled={!name.trim() || portfolio.companies.length >= 50 || startingCompany || openGuard.current.isPending()}><ArrowUp size={20} /></button>
        </form>
        {scope.kind === 'user' && scope.guest && <p className="empty-note">Guest access lasts {scope.guest.sessionDays} days in this browser. Clearing cookies loses access to your companies. Up to {scope.guest.aiSubmissionsPerDay} AI submissions per day, subject to a shared service allowance.</p>}
        {portfolio.companies.length >= 50 && <p className="empty-note">This local preview supports up to 50 companies.</p>}
        {directory.length > 0 && <section className="company-library" aria-label="Shared companies"><h2>Shared companies</h2><div className="company-grid">{directory.map(item => <div className="company-tile" key={item.company.company_id}><button onClick={() => void openShared(item)} disabled={startingCompany || openingCompanyId === item.company.company_id} aria-busy={openingCompanyId === item.company.company_id}><Building2 size={20} /><span><strong>{companyName(item.workspace, item.company)}</strong><small>{item.workspace.role === 'viewer' ? 'Viewer · Read-only' : 'Shared workspace'}</small></span><ArrowRight size={16} /></button></div>)}</div></section>}
        {portfolio.companies.length > 0 && <section className="company-library" aria-label="Your companies"><h2>Your companies</h2><div className="company-grid">{portfolio.companies.map(item => <div className="company-tile" key={item.id}><button onClick={() => open(item.id)}><Building2 size={20} /><span><strong>{item.name}</strong><small>{item.workspace.messages.length ? `${item.workspace.executionMode === 'live' ? 'Live' : 'Preview'} · Continue building` : 'Ready for your idea'}</small></span><ArrowRight size={16} /></button></div>)}</div></section>}
      </>}</div></main>
      {!reservation && <TransitionGrain />}{directoryError && <p className="storage-warning" role="alert">{directoryError}</p>}{storageError && <p className="storage-warning" role="status">Browser storage is unavailable. This session won’t be saved.</p>}
    </div>}</MotionConfig>;
}
