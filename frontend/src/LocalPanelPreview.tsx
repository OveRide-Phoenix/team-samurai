import { useEffect, useState } from 'react';
import { MotionConfig } from 'motion/react';
import { ArrowRight } from 'lucide-react';
import { Atmosphere } from './Atmosphere';
import { CompanyWorkspace } from './App';
import { Onboarding } from './Onboarding';
import { ModeToggle } from './ShellParts';
import { evidence, launchPlan, offer, pricing, prospects, previewBrief, verificationPreview } from './demo';
import { emptyWorkspace, panelSchema, workspaceSchema, type CompanyBrief, type Workspace } from './model';
import intakePages from './preview-intake';

const exampleBrief: CompanyBrief = { idea: 'An AI receptionist that turns missed clinic calls into booked appointments.', customer: 'Independent dental clinics', location: 'Bengaluru, India', budget: '₹50,000', founderSkills: 'Customer interviews, Python and product design', goal: 'Find one clinic willing to test a two-week pilot.' };
export const previewCalculator = panelSchema.parse({
  id: '13a133b4-5bb6-4bc2-9978-de3553c43711', kind: 'custom', title: 'Explore pilot revenue', note: 'Generated view · Working assumptions, not verified business results',
  html: '<div class="calculator-fields"><label>Pilot customers<input id="customers" type="range" min="1" max="20" value="5"><small id="customer-count">5 clinics</small></label><label>Monthly price · ₹<input id="price" type="number" min="0" max="1000000" value="4999"></label></div><div class="calculator-result"><small>Monthly scenario</small><output id="revenue">₹24,995</output><small>Before costs · Hypothesis</small></div><button id="reset" type="button">Reset</button>',
  css: '.calculator-fields{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:20px 0}.calculator-result{padding:18px 0 22px;border-top:1px solid var(--border)}.calculator-result output{margin:6px 0 8px}@media(max-width:320px){.calculator-fields{grid-template-columns:1fr}}',
  javascript: `const customers=document.getElementById('customers'),price=document.getElementById('price');const update=()=>{document.getElementById('customer-count').textContent=customers.value+' clinics';const total=Math.max(0,Number(customers.value))*Math.max(0,Number(price.value));document.getElementById('revenue').textContent=new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:0}).format(total)};customers.addEventListener('input',update);price.addEventListener('input',update);document.getElementById('reset').onclick=()=>{customers.value='5';price.value='4999';update()};update();`,
});
const stressStyles = new URLSearchParams(location.search).get('stress') === 'styles';
const calculator = stressStyles && previewCalculator.kind === 'custom' ? { ...previewCalculator, css: previewCalculator.css + 'body{background:blue!important;font-family:monospace!important;padding:40px!important}button{background:red!important;color:lime!important;border-radius:0!important;font-family:monospace!important}input{background:blue!important;color:yellow!important;border-radius:0!important}' } : previewCalculator;
const catalog = [previewBrief(exampleBrief), { ...evidence, title: 'Research evidence' }, { ...offer, title: 'Offer' }, { ...pricing, title: 'Pricing' }, { ...launchPlan, title: 'Delivery plan' }, { ...prospects, title: 'Prospects' }, verificationPreview, calculator];
const catalogWorkspace: Workspace = { ...emptyWorkspace(), messages: catalog.map((panel, index) => ({ id: `preview-panel-${index}`, role: 'assistant', text: '', panel })) };
const cacheKey = 'samurai-generative-panel-preview-v1';

// Loaded only from the development entry point; production identity and company storage are untouched.
export default function LocalPanelPreview() {
  const [view, setView] = useState<'panels' | 'intake' | 'company' | 'home'>(() => new URLSearchParams(location.search).get('preview') === 'intake' ? 'intake' : 'panels');
  const [mode, setMode] = useState<'light' | 'dark'>('light');
  const [workspace, updateWorkspace] = useState<Workspace>(() => {
    try { const saved = workspaceSchema.parse(JSON.parse(localStorage.getItem(cacheKey) || 'null')); return { ...catalogWorkspace, selectedArea: saved.selectedArea, selectedAreas: saved.selectedAreas, drafts: saved.drafts, messages: [...catalogWorkspace.messages, ...saved.messages.filter(message => !message.id.startsWith('preview-panel-'))], shortlist: saved.shortlist, completedTasks: saved.completedTasks, approvedOffers: saved.approvedOffers, panelOrder: saved.panelOrder, pinned: catalog.filter(panel => saved.pinned.some(entry => entry.id === panel.id)) }; }
    catch { return catalogWorkspace; }
  });
  const [fresh, updateFresh] = useState<Workspace>(emptyWorkspace);
  useEffect(() => {
    document.documentElement.dataset.mode = mode;
    document.documentElement.style.colorScheme = mode;
  }, [mode]);
  useEffect(() => { try { localStorage.setItem(cacheKey, JSON.stringify(workspace)); } catch { /* The preview still works without persistence. */ } }, [workspace]);
  const toggleMode = () => setMode(current => current === 'light' ? 'dark' : 'light');
  const selected = view === 'company' ? fresh : workspace;
  if (view === 'panels' || view === 'company') return <MotionConfig reducedMotion="user"><CompanyWorkspace key={view} company={{ id: `local-preview-${view}`, name: view === 'panels' ? 'Your company · UI preview' : 'Your new company · UI preview', workspace: selected }} workspace={selected} setWorkspace={view === 'company' ? updateFresh : updateWorkspace} mode={mode} toggleMode={toggleMode} onOpen={() => setView('home')} initialView={view === 'panels' ? 'company' : 'chat'} storageError={false} /></MotionConfig>;
  return <MotionConfig reducedMotion="user"><div className="workspace landing"><Atmosphere mode={mode} /><header className="topbar"><span className="wordmark">Samurai</span><ModeToggle mode={mode} onToggle={toggleMode} /></header><main className="landing-content"><div className="landing-main">{view === 'intake' ? <Onboarding name="Your new company" previewPages={intakePages} onCancel={() => setView('home')} onComplete={brief => { updateFresh({ ...emptyWorkspace(), brief }); setView('company'); }} /> : <><h1>Your company,<br />taking shape.</h1><p className="landing-description">Explore the interactive UI with illustrative data.</p><div className="preview-entry-choices"><button className="primary-button" onClick={() => setView('panels')}>Explore all panels<ArrowRight size={16} /></button><button className="soft-button" onClick={() => setView('intake')}>Start fresh<ArrowRight size={16} /></button></div></>}</div></main></div></MotionConfig>;
}
