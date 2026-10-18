import { Onboarding } from './Onboarding';
import { TransitionGrain } from './TransitionGrain';
import { Atmosphere } from './Atmosphere';
import { useEffect, useRef, useState } from 'react';
import { MotionConfig } from 'motion/react';
import { ArrowRight, Building2 } from 'lucide-react';
import { CompanyWorkspace } from './App';
import { OpenUICompanyName } from './OpenUIAnswers';
import { hydrateCompanyView } from './companyHydration';
import { continueCompanyView, emptyCompanyView, restorePortfolio, type CompanyBrief, type CompanyView, type Portfolio } from './model';
import { loadPortfolio, persistPortfolio, portfolioStorageKey, type BrowserScope } from './browserStorage';
import { canonicalCompanyFields, createLatestRequestGuard, createOneAtATimeGate, createWorkspace, createWorkspaceCompany, firstWritableWorkspace, listWorkspaceCompanies, listWorkspaces, needsCompanyIntake, openWorkspaceCompany, shouldLoadWorkspaceDirectory, type DirectoryCompany, type WorkspaceDirectory } from './workspaces';
import { ModeToggle } from './ShellParts';

type Reservation = { readonly workspace: WorkspaceDirectory; readonly company: DirectoryCompany };
type CompanyCreationRetry = { readonly workspace: WorkspaceDirectory; readonly submissionId: string };

function companyName(workspace: WorkspaceDirectory, company: DirectoryCompany): string {
  return `${workspace.display_name} · ${company.company_id.slice(0, 8)}`;
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
  const [directoryLoaded, setDirectoryLoaded] = useState(false);
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
    setDirectoryLoaded(false);
    void (async () => {
      try {
        const workspaces = await listWorkspaces();
        const companies = await Promise.all(workspaces.map(async workspace => (await listWorkspaceCompanies(workspace.workspace_id)).map(company => ({ workspace, company }))));
        if (active) { setWorkspaces(workspaces); setDirectory(companies.flat()); setDirectoryLoaded(true); setDirectoryError(''); }
      } catch (error) {
        if (active) setDirectoryError(error instanceof Error ? 'Shared ideas are unavailable. Try again from Home.' : 'Shared ideas are unavailable.');
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
    if (!parentSessionId) { setDirectoryError('The idea reservation did not include a session. Return Home and try again.'); return; }
    const local = {
      id: parentSessionId, name: name.trim(), workspace: { ...emptyCompanyView(), brief, executionMode: 'live' as const, companyId: pending.company.company_id, currentRevision: pending.company.current_revision },
      workspaceId: pending.workspace.workspace_id, companyId: pending.company.company_id,
      currentRevision: pending.company.current_revision, stateSha256: pending.company.state_sha256, createdAt: pending.company.created_at, role: pending.workspace.role,
    };
    updatePortfolio(current => ({ ...current, activeId: local.id, companies: [...current.companies.filter(company => company.id !== local.id), local] }));
    setName(''); setReservation(null);
  };
  const startCompany = async () => {
    if (!name.trim() || portfolio.companies.length >= 50 || (!directoryLoaded && !companyCreationRetry) || openGuard.current.isPending() || !startGate.current.tryBegin()) return;
    openGuard.current.invalidate();
    setStartingCompany(true);
    const retry = companyCreationRetry;
    const submissionId = retry?.submissionId ?? crypto.randomUUID();
    let workspace = retry?.workspace;
    try {
      const selectedWorkspace = workspace ?? firstWritableWorkspace(workspaces, directory.map(item => item.company)) ?? await createWorkspace(`${name.trim()} workspace`);
      workspace = selectedWorkspace;
      const company = await createWorkspaceCompany(selectedWorkspace.workspace_id, submissionId);
      setWorkspaces(current => current.some(item => item.workspace_id === selectedWorkspace.workspace_id) ? current : [...current, selectedWorkspace]);
      setDirectory(current => current.some(item => item.company.company_id === company.company_id) ? current : [...current, { workspace: selectedWorkspace, company }]);
      setCompanyCreationRetry(null); setReservation({ workspace: selectedWorkspace, company }); setDirectoryError('');
    } catch {
      setCompanyCreationRetry(workspace ? { workspace, submissionId } : null);
      setDirectoryError('Could not reserve an idea. Try again.');
    } finally { startGate.current.finish(); setStartingCompany(false); }
  };
  const openShared = async (item: Reservation) => {
    if (startGate.current.isPending()) return;
    const request = openGuard.current.begin();
    setOpeningCompanyId(item.company.company_id);
    try {
      const opened = await openWorkspaceCompany(item.workspace.workspace_id, item.company.company_id);
      if (!opened.parent_session_id || !opened.snapshot) throw new Error('The shared idea could not be opened.');
      if (!openGuard.current.isCurrent(request)) return;
      const existing = portfolioRef.current.companies.find(company => company.workspaceId === opened.workspace_id && company.companyId === opened.company_id);
      if (needsCompanyIntake(opened, item.workspace.role)) {
        setName(name.trim() || existing?.name || companyName(item.workspace, opened));
        setReservation({ workspace: item.workspace, company: opened }); setDirectoryError(''); return;
      }
      const hydrated = { ...hydrateCompanyView(existing?.workspace ?? emptyCompanyView(), opened.snapshot, opened.company_id), ...canonicalCompanyFields(opened) };
      const workspace = item.workspace.role === 'viewer' ? hydrated : continueCompanyView(hydrated, opened.company_id, opened.current_revision);
      const local = {
        id: opened.parent_session_id, name: existing?.name ?? companyName(item.workspace, opened), workspace,
        workspaceId: opened.workspace_id, companyId: opened.company_id,
        currentRevision: opened.current_revision, stateSha256: opened.state_sha256, createdAt: opened.created_at, role: item.workspace.role,
      };
      updatePortfolio(current => ({ ...current, activeId: local.id, companies: existing ? current.companies.map(company => company.id === existing.id ? local : company) : [...current.companies, local] }));
      setDirectoryError('');
    } catch (error) {
      if (openGuard.current.isCurrent(request)) setDirectoryError(error instanceof Error ? error.message : 'Could not open the shared idea.');
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
      <header className="topbar"><span className="wordmark"><img className="brand-logo" src="/proofseed-logo.svg" alt="" />Proofseed</span><div className="topbar-actions"><ModeToggle mode={portfolio.mode} onToggle={toggleMode} /></div></header>
      <main key={reservation ? 'intake' : 'home'} className="landing-content"><div className="landing-main">{reservation ? <Onboarding name={name.trim()} onCancel={() => setReservation(null)} onComplete={brief => create(brief, reservation)} /> : <><h1>An idea is<br />just the beginning.</h1><p className="landing-description">Your mentor for software ideas. Explore, validate, then implement.</p>
        <OpenUICompanyName name={name} pending={startingCompany} disabled={!name.trim() || portfolio.companies.length >= 50 || (!directoryLoaded && !companyCreationRetry) || startingCompany || openGuard.current.isPending()} onName={value => { setName(value); setCompanyCreationRetry(null); }} onStart={() => { void startCompany(); }} />
        {scope.kind === 'user' && scope.guest && <p className="empty-note">Guest access lasts {scope.guest.sessionDays} days in this browser. Clearing cookies loses access to your ideas. Up to {scope.guest.aiSubmissionsPerDay} AI submissions per day, subject to a shared service allowance.</p>}
        {portfolio.companies.length >= 50 && <p className="empty-note">You can save up to 50 ideas in this browser.</p>}
        {directory.length > 0 && <section className="company-library" aria-label="Shared ideas"><h2>Shared ideas</h2><div className="company-grid">{directory.map(item => <div className="company-tile" key={item.company.company_id}><button onClick={() => void openShared(item)} disabled={startingCompany || openingCompanyId === item.company.company_id} aria-busy={openingCompanyId === item.company.company_id}><Building2 size={20} /><span><strong>{companyName(item.workspace, item.company)}</strong><small>{item.workspace.role === 'viewer' ? 'Viewer · Read-only' : 'Shared workspace'}</small></span><ArrowRight size={16} /></button></div>)}</div></section>}
        {portfolio.companies.length > 0 && <section className="company-library" aria-label="Your ideas"><h2>Your ideas</h2><div className="company-grid">{portfolio.companies.map(item => <div className="company-tile" key={item.id}><button onClick={() => open(item.id)}><Building2 size={20} /><span><strong>{item.name}</strong><small>{item.workspace.messages.length ? 'Continue exploring' : 'Ready for your idea'}</small></span><ArrowRight size={16} /></button></div>)}</div></section>}
      </>}</div></main>
      {!reservation && <TransitionGrain />}{directoryError && <p className="storage-warning" role="alert">{directoryError}</p>}{storageError && <p className="storage-warning" role="status">Browser storage is unavailable. This session won’t be saved.</p>}
    </div>}</MotionConfig>;
}
