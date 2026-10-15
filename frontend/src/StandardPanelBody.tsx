import { useEffect, useState } from 'react';
import { ArrowRight, Check, CheckCheck, ChevronDown, Download, ExternalLink, MapPin, Plus, Sparkles, Target, Users, Wallet } from 'lucide-react';
import { downloadWorkspaceFile, getWorkspaceFile } from './files';
import type { EvidenceSource, Panel } from './model';

type StandardPanel = Exclude<Panel, { kind: 'custom' | 'declarative' | 'scenario' }>;
type Props = {
  panel: StandardPanel; compact: boolean; completedTasks: string[]; onComplete: (id: string) => void;
  shortlisted: string[]; onShortlist: (id: string) => void; approved: boolean; onApprove: () => void;
  onDiscuss?: (prompt: string) => void; workspaceId?: string;
};
function Choices({ label, values, selected, onSelect }: { label: string; values: string[]; selected: string; onSelect: (value: string) => void }) {
  return <div className="panel-segments" role="group" aria-label={label}>{values.map(value => <button key={value} type="button" aria-pressed={selected === value} onClick={() => onSelect(value)}>{value}</button>)}</div>;
}
function Discussion({ label, prompt, onDiscuss }: { label: string; prompt: string; onDiscuss?: Props['onDiscuss'] }) {
  return onDiscuss ? <button className="panel-discuss" onClick={() => onDiscuss(prompt)}><Sparkles size={14} />{label}<ArrowRight size={14} /></button> : null;
}
export function StandardPanelBody(props: Props) {
  const body = props.panel.kind === 'offer' ? <OfferPanel {...props} panel={props.panel} />
    : props.panel.kind === 'pricing' ? <PricingPanel {...props} panel={props.panel} />
      : props.panel.kind === 'prospects' ? <ProspectPanel {...props} panel={props.panel} />
        : props.panel.kind === 'launch-plan' ? <DeliveryPanel {...props} panel={props.panel} />
          : props.panel.title === 'Company brief' ? <BriefPanel {...props} panel={props.panel} /> : <EvidencePanel {...props} panel={props.panel} />;
  return <>{body}{props.panel.knowledge_sources && <details className="panel-details knowledge-panel-sources"><summary>Workspace context</summary>{props.panel.knowledge_sources.map(source => <EvidenceSourceLink key={source.chunk_id} source={source} workspaceId={props.workspaceId} />)}</details>}</>;
}
function BriefPanel({ panel, onDiscuss }: Props & { panel: Extract<Panel, { kind: 'evidence' }> }) {
  const [view, setView] = useState('Overview');
  const fields = panel.claims.map(claim => { const index = claim.claim.indexOf(':'); return index < 0 ? { label: 'Context', value: claim.claim } : { label: claim.claim.slice(0, index), value: claim.claim.slice(index + 1).trim() }; });
  const value = (...labels: string[]) => fields.find(field => labels.includes(field.label))?.value;
  const core = ['Idea', 'First customers', 'Market', 'Budget', 'Founder skills', 'Skills & resources', 'First milestone'];
  const extra = fields.filter(field => !core.includes(field.label));
  return <div className="interactive-brief">
    <Choices label="Brief view" values={['Overview', 'Inputs']} selected={view} onSelect={setView} />
    {view === 'Overview' ? <>
      <div className="brief-idea"><p>{value('Idea') || 'Your idea is still taking shape.'}</p></div>
      <div className="brief-context-grid">
        {value('First customers') && <div><Users size={16} /><span>Customers</span><strong>{value('First customers')}</strong></div>}
        {value('Market') && <div><MapPin size={16} /><span>Market</span><strong>{value('Market')}</strong></div>}
      </div>
      {value('Budget') && <div className="brief-budget"><Wallet size={16} /><span>Budget</span><strong>{value('Budget')}</strong></div>}
      {value('First milestone') && <div className="brief-milestone"><span className="milestone-symbol"><Target size={19} /></span><div><span className="panel-kicker">Milestone</span><strong>{value('First milestone')}</strong></div></div>}
    </> : <div className="company-brief"><dl>{fields.filter(field => core.includes(field.label)).map(field => <div key={field.label}><dt>{field.label === 'Founder skills' ? 'Skills & resources' : field.label}</dt><dd>{field.value}</dd></div>)}</dl></div>}
    {extra.length > 0 && <details className="panel-details"><summary>Additional context</summary><dl>{extra.map(field => <div key={field.label}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl></details>}
    <Discussion label="Refine brief" prompt="Help me refine my existing company brief. Ask what I want to change before updating it or starting research." onDiscuss={onDiscuss} />
  </div>;
}
function OfferPanel({ panel, approved, onApprove, onDiscuss }: Props & { panel: Extract<Panel, { kind: 'offer' }> }) {
  const [view, setView] = useState('The offer');
  return <div className="interactive-offer"><Choices label="Offer view" values={['The offer', 'Included']} selected={view} onSelect={setView} />
    {view === 'The offer' ? <><span className="offer-customer"><Users size={14} />{panel.customer}</span><p className="offer-promise">{panel.promise}</p></> : <ul className="offer-feature-list">{panel.includes.map((item, index) => <li key={index}><span><Check size={14} /></span>{item}</li>)}</ul>}
    <div className="offer-review"><div><span className="panel-kicker">Price hypothesis</span><strong>{panel.price}</strong></div><button className="samurai-action" aria-pressed={approved} onClick={onApprove}>{approved ? <><CheckCheck size={15} />Reviewed</> : <>Review draft<ArrowRight size={14} /></>}</button></div>
    <Discussion label="Refine offer" prompt={`Help me review this draft offer: ${panel.promise}. Check the customer need and evidence before changing it.`} onDiscuss={onDiscuss} />
  </div>;
}
function PricingPanel({ panel, onDiscuss }: Props & { panel: Extract<Panel, { kind: 'pricing' }> }) {
  const [selected, setSelected] = useState(0);
  const option = panel.options[selected] || panel.options[0];
  return <div className="interactive-pricing"><div className="pricing-choice-list" role="group" aria-label="Pricing options">{panel.options.map((entry, index) => <button key={index} className="pricing-choice" aria-pressed={selected === index} onClick={() => setSelected(index)}><span className="choice-dot">{selected === index && <Check size={11} />}</span><span><small>{entry.name}</small><strong>{entry.price}</strong></span></button>)}</div>
    {option && <div className="pricing-exploration"><details key={selected} className="panel-details pricing-detail"><summary>{option.name} details</summary><p>{option.description || 'Test willingness to pay and delivery cost before committing to this price.'}</p></details><Discussion label="Test price" prompt={`Help me test the ${option.name} pricing hypothesis: ${option.price}. Preserve uncertainty and do not charge, publish, or make commitments.`} onDiscuss={onDiscuss} /></div>}
  </div>;
}
export function filterProspects(rows: Extract<Panel, { kind: 'prospects' }>['rows'], filter: string, shortlisted: readonly string[]) {
  return rows.filter(row => filter === 'All' || (filter === 'High fit' ? row.fit === 'High' : shortlisted.includes(row.id)));
}
function ProspectPanel({ panel, shortlisted, onShortlist, compact }: Props & { panel: Extract<Panel, { kind: 'prospects' }> }) {
  const [filter, setFilter] = useState('All');
  const rows = filterProspects(panel.rows, filter, shortlisted);
  const saved = panel.rows.filter(row => shortlisted.includes(row.id)).length;
  return <div className="interactive-prospects"><div className="prospect-counts"><strong>{panel.rows.length}<span>to explore</span></strong><strong>{saved}<span>shortlisted</span></strong></div>
    <Choices label="Filter prospects" values={['All', 'High fit', 'Shortlisted']} selected={filter} onSelect={setFilter} />
    <div className="prospect-list">{rows.map(row => {
      const identity = <><strong>{row.name}</strong><span className="prospect-meta"><MapPin size={11} />{row.area}<span className="fit-label">{row.fit} fit</span></span></>;
      return <div className="prospect-contact" key={row.id}><span className="prospect-avatar" aria-hidden="true">{row.name.split(/\s+/).slice(0, 2).map(part => part[0]).join('')}</span><div>{compact ? identity : <details className="prospect-reason"><summary aria-label={`Details for ${row.name}`}><div>{identity}</div><ChevronDown size={12} /></summary><p>{row.reason}</p></details>}</div><button className={`shortlist-button ${shortlisted.includes(row.id) ? 'selected' : ''}`} onClick={() => onShortlist(row.id)} aria-label={`${shortlisted.includes(row.id) ? 'Remove' : 'Shortlist'} ${row.name}`} aria-pressed={shortlisted.includes(row.id)}>{shortlisted.includes(row.id) ? <Check size={16} /> : <Plus size={16} />}</button></div>;
    })}</div>
    {!rows.length && <p className="empty-note">{filter === 'Shortlisted' ? 'Shortlist a prospect to keep it here.' : 'No prospects match these filters.'}</p>}
  </div>;
}
function ExternalSource({ source }: { source: Extract<EvidenceSource, { kind: 'external' }> }) {
  return <a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}<ExternalLink size={12} /></a>;
}
function KnowledgeProvenance({ source, title }: { source: Exclude<EvidenceSource, { kind: 'external' }>; title: string }) {
  return <details className="panel-details knowledge-provenance"><summary>{title}</summary><dl><div><dt>Trust</dt><dd>{source.trust_class === 'uploaded_file' ? 'Uploaded workspace context' : 'Accepted artifact provenance'}</dd></div><div><dt>Revision</dt><dd>{source.indexed_revision}</dd></div><div><dt>Chunk</dt><dd>{source.ordinal + 1} · {source.chunk_id}</dd></div><div><dt>SHA-256</dt><dd>{source.content_sha256}</dd></div></dl><p>Workspace context informs a draft; it does not independently verify a finding.</p></details>;
}
function WorkspaceFileSource({ source, workspaceId }: { source: Extract<EvidenceSource, { kind: 'workspace_file' }>; workspaceId?: string }) {
  const [title, setTitle] = useState(source.title);
  const [status, setStatus] = useState<'idle' | 'unavailable' | 'downloading'>('idle');
  useEffect(() => {
    let active = true;
    setTitle(source.title); setStatus('idle');
    if (!workspaceId) return () => { active = false; };
    void getWorkspaceFile(workspaceId, source.file_id).then(file => { if (active) setTitle(file.display_name); }).catch(() => { if (active) setStatus('unavailable'); });
    return () => { active = false; };
  }, [workspaceId, source.file_id]);
  const download = async () => {
    if (!workspaceId) return;
    setStatus('downloading');
    try {
      const response = await downloadWorkspaceFile(workspaceId, source.file_id);
      const objectUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement('a'); link.href = objectUrl; link.download = title || 'workspace-file'; link.click(); URL.revokeObjectURL(objectUrl);
      setStatus('idle');
    } catch { setStatus('unavailable'); }
  };
  const label = title || 'Workspace file';
  return <div className="knowledge-source"><button type="button" className="evidence-source-link" onClick={() => void download()} disabled={!workspaceId || status === 'downloading'}>{label}<Download size={12} /></button>{status === 'unavailable' && <p className="source-unavailable" role="status">Download unavailable.</p>}<KnowledgeProvenance source={source} title="Workspace context details" /></div>;
}
function EvidenceSourceLink({ source, workspaceId }: { source: EvidenceSource; workspaceId?: string }) {
  if (source.kind === 'external') return <ExternalSource source={source} />;
  if (source.kind === 'workspace_file') return <WorkspaceFileSource source={source} workspaceId={workspaceId} />;
  return <KnowledgeProvenance source={source} title="Accepted artifact details" />;
}
function EvidencePanel({ panel, compact, workspaceId }: Props & { panel: Extract<Panel, { kind: 'evidence' }> }) {
  const [filter, setFilter] = useState('All findings');
  const findings = panel.claims.filter(claim => !/^(info|warning|error):/.test(claim.detail));
  const supported = findings.filter(claim => claim.status === 'supported').length;
  const filtered = findings.filter(claim => filter === 'All findings' || (filter === 'Needs review' ? claim.status !== 'supported' : claim.sources.length > 0));
  const support = findings.filter(claim => claim.detail && !['Assumption, not sourced fact', 'Research summary; see individual source-backed findings'].includes(claim.detail)).filter((claim, index, entries) => /^(unverified|supported|contradicted);/.test(claim.detail) || entries.findIndex(entry => entry.detail === claim.detail) === index);
  const warnings = panel.claims.filter(claim => /^(warning|error):/.test(claim.detail));
  const sourceKey = (source: EvidenceSource) => source.kind === 'external' ? source.url : source.chunk_id;
  const sourceLinks = (sources: EvidenceSource[]) => sources.map(source => <EvidenceSourceLink key={sourceKey(source)} source={source} workspaceId={workspaceId} />);
  const render = (claim: typeof panel.claims[number]) => <div className="evidence-row" key={claim.id}><span className="finding-state"><span />{claim.status === 'supported' ? 'Supported' : claim.status === 'hypothesis' ? 'Hypothesis' : 'Needs review'}</span>{claim.claim.length > 240 ? <details className="evidence-reading"><summary><strong>{claim.claim.slice(0, 200)}…</strong><span>Read more</span></summary><p>{claim.claim}</p></details> : <strong>{claim.claim}</strong>}{!compact && sourceLinks(claim.sources.slice(0, 2))}{!compact && claim.sources.length > 2 && <details className="panel-details"><summary>More sources</summary>{sourceLinks(claim.sources.slice(2))}</details>}</div>;
  return <div className="evidence-list"><div className="evidence-overview"><span className="evidence-number">{findings.length}</span><div><strong>Findings</strong><p>{supported} supported · {findings.length - supported} to review</p></div></div><Choices label="Evidence filters" values={['All findings', 'Needs review', 'With sources']} selected={filter} onSelect={setFilter} />
    {filtered.slice(0, 3).map(render)}{!filtered.length && <p className="empty-note">No findings in this view. Evidence may still be needed.</p>}
    {(filtered.length > 3 || warnings.length > 0 || support.length > 0) && <details className="panel-details"><summary>Details</summary>{filtered.slice(3).map(render)}{warnings.map(claim => <p key={claim.id}>{claim.claim}</p>)}{support.map(claim => <div className="evidence-row" key={`support-${claim.id}`}><strong>{claim.detail.startsWith('contradicted;') ? 'Conflicting evidence' : /^(unverified|supported);/.test(claim.detail) ? 'Source support' : 'Context'}</strong><p className="source-support-claim">{claim.claim}</p><p>{claim.detail.replace(/^(unverified|supported|contradicted); (mapped|unmapped)\.\s*/, '') || 'Source support has not been retained for this finding.'}</p></div>)}</details>}
  </div>;
}
function DeliveryPanel({ panel, completedTasks, onComplete, compact }: Props & { panel: Extract<Panel, { kind: 'launch-plan' }> }) {
  const completed = panel.tasks.filter(task => completedTasks.includes(JSON.stringify([panel.id, task.id]))).length;
  const fraction = panel.tasks.length ? completed / panel.tasks.length : 0;
  const render = (task: typeof panel.tasks[number], index: number) => {
    const id = JSON.stringify([panel.id, task.id]);
    const done = completedTasks.includes(id);
    return <div className={`launch-task ${done ? 'task-done' : ''}`} key={task.id}><button className="task-check" aria-label={`${done ? 'Reopen' : 'Complete'} ${task.title}`} aria-pressed={done} onClick={() => onComplete(id)}>{done ? <Check size={15} /> : index + 1}</button><div><strong>{task.title}</strong>{task.timing !== 'Not scheduled' && <span>{task.timing}</span>}{!compact && <details className="task-detail"><summary aria-label={`Details for ${task.title}`}>Details<ChevronDown size={12} /></summary><p>Owner: {task.owner}</p>{!['complete', 'needs_rework', 'needs_input', 'draft_only'].includes(task.detail) && <p>{task.detail}</p>}</details>}</div></div>;
  };
  return <div className="launch-plan"><div className="delivery-overview"><svg className="delivery-ring" viewBox="0 0 48 48" role="img" aria-label={`${completed} of ${panel.tasks.length} checklist steps complete`}><circle cx="24" cy="24" r="19" /><circle cx="24" cy="24" r="19" pathLength="100" strokeDasharray={`${fraction * 100} 100`} /><text x="24" y="28" textAnchor="middle">{completed}</text></svg><div><strong>Checklist</strong><span>{completed} of {panel.tasks.length} complete</span></div></div><progress className="sr-only" aria-label="Launch progress" value={completed} max={panel.tasks.length || 1} />{panel.tasks.slice(0, 3).map(render)}{panel.tasks.length > 3 && <details className="panel-details"><summary>More steps ({panel.tasks.length - 3})</summary>{panel.tasks.slice(3).map((task, index) => render(task, index + 3))}</details>}</div>;
}
