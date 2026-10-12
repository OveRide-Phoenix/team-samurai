import { Onboarding } from './Onboarding';
import { TransitionGrain } from './TransitionGrain';
import { Atmosphere } from './Atmosphere';
import { useEffect, useRef, useState } from 'react';
import { MotionConfig } from 'motion/react';
import { ArrowRight, ArrowUp, Building2 } from 'lucide-react';
import { CompanyWorkspace } from './App';
import { emptyWorkspace, restorePortfolio, type Portfolio, type Workspace } from './model';
import { loadPortfolio, persistPortfolio, portfolioStorageKey, type BrowserScope } from './browserStorage';
import { ModeToggle, SearchBar } from './ShellParts';

export function App({ scope }: { readonly scope: BrowserScope }) {
  const scopedStorageKey = portfolioStorageKey(scope);
  const [portfolio, setPortfolio] = useState<Portfolio>(() => {
    try { return loadPortfolio(localStorage, scope); }
    catch { return restorePortfolio(null, null); }
  });
  const portfolioRef = useRef(portfolio);
  portfolioRef.current = portfolio;
  const [name, setName] = useState('');
  const [onboarding, setOnboarding] = useState(false);
  const [storageError, setStorageError] = useState(false);
  useEffect(() => {
    document.documentElement.dataset.mode = portfolio.mode;
    document.documentElement.style.colorScheme = portfolio.mode;
    try { localStorage.setItem(scopedStorageKey, JSON.stringify(portfolio)); setStorageError(false); }
    catch { setStorageError(true); }
  }, [portfolio, scopedStorageKey]);
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
  const open = (activeId: string | null) => { setOnboarding(false); updatePortfolio(current => ({ ...current, activeId })); };
  const create = (companyName: string, workspace = emptyWorkspace()) => {
    const id = crypto.randomUUID();
    updatePortfolio(current => ({ ...current, activeId: id, companies: [...current.companies, { id, name: companyName.trim(), workspace }] }));
    setName(''); setOnboarding(false);
  };
  const company = portfolio.companies.find(item => item.id === portfolio.activeId);
  const updateWorkspace = (update: Workspace | ((current: Workspace) => Workspace), persistNow = false): boolean => {
    if (!company) return false;
    return updatePortfolio(current => ({ ...current, companies: current.companies.map(item => item.id === company.id ? {
      ...item, workspace: typeof update === 'function' ? update(item.workspace) : update,
    } : item) }), persistNow);
  };
  const setWorkspace = (update: Workspace | ((current: Workspace) => Workspace)) => { updateWorkspace(update); };
  const persistWorkspace = (update: Workspace | ((current: Workspace) => Workspace)) => updateWorkspace(update, true);
  return <MotionConfig reducedMotion="user">{company ? <CompanyWorkspace key={company.id} company={company} workspace={company.workspace} setWorkspace={setWorkspace} persistWorkspace={persistWorkspace} mode={portfolio.mode} toggleMode={toggleMode} onOpen={open} storageError={storageError} /> :
    <div className="workspace landing"><Atmosphere mode={portfolio.mode} /><div className="bottom-blur" aria-hidden="true" />
      <header className="topbar"><span className="wordmark">Samurai</span><div className="topbar-actions"><SearchBar placeholder="Search companies" items={portfolio.companies.map(item => ({ id: item.id, title: item.name }))} onSelect={open} /><ModeToggle mode={portfolio.mode} onToggle={toggleMode} /></div></header>
      <main key={onboarding ? 'intake' : 'home'} className="landing-content"><div className="landing-main">{onboarding ? <Onboarding name={name.trim()} onCancel={() => setOnboarding(false)} onComplete={brief => create(name, { ...emptyWorkspace(), brief, executionMode: 'live' })} /> : <><h1>An idea is<br />just the beginning.</h1><p className="landing-description">Build a company worth believing in.</p>
        <form className="company-intake" onSubmit={event => { event.preventDefault(); if (name.trim() && portfolio.companies.length < 50) setOnboarding(true); }}>
          <input aria-label="Company name" placeholder="What will you call your company?" value={name} onChange={event => setName(event.target.value)} maxLength={80} className="intake-input" />
          <button type="submit" className="send-button intake-send" aria-label="Start company" disabled={!name.trim() || portfolio.companies.length >= 50}><ArrowUp size={20} /></button>
        </form>
        {portfolio.companies.length >= 50 && <p className="empty-note">This local preview supports up to 50 companies.</p>}
        {portfolio.companies.length > 0 && <section className="company-library" aria-label="Your companies"><h2>Your companies</h2><div className="company-grid">{portfolio.companies.map(item => <div className="company-tile" key={item.id}><button onClick={() => open(item.id)}><Building2 size={20} /><span><strong>{item.name}</strong><small>{item.workspace.messages.length ? `${item.workspace.executionMode === 'live' ? 'Live' : 'Preview'} · Continue building` : 'Ready for your idea'}</small></span><ArrowRight size={16} /></button></div>)}</div></section>}
      </>}</div></main>
      {!onboarding && <TransitionGrain />}{storageError && <p className="storage-warning" role="status">Browser storage is unavailable. This session won’t be saved.</p>}
    </div>}</MotionConfig>;
}
