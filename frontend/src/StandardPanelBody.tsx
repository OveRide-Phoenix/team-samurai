import { useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, Check, CheckCheck, ChevronDown, Download, ExternalLink, MapPin, Plus, Sparkles, Target, Users } from 'lucide-react';
import { downloadWorkspaceFile, getWorkspaceFile } from './files';
import type { EvidenceSource, Panel } from './model';
import { ShareRing } from './PanelCharts';
import { verificationPayloadSchema } from './agentos';
import { isWorkDraft, WorkDraftPanel } from './WorkDraftPanel';

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
  const body = isWorkDraft(props.panel) ? <WorkDraftPanel panel={props.panel} onDiscuss={props.onDiscuss} /> : props.panel.kind === 'offer' ? <OfferPanel {...props} panel={props.panel} />
    : props.panel.kind === 'pricing' ? <PricingPanel {...props} panel={props.panel} />
      : props.panel.kind === 'prospects' ? <ProspectPanel {...props} panel={props.panel} />
        : props.panel.kind === 'launch-plan' ? <DeliveryPanel {...props} panel={props.panel} />
          : props.panel.title === 'Company brief' ? <BriefPanel {...props} panel={props.panel} /> : <EvidencePanel {...props} panel={props.panel} />;
  return <>{body}{props.panel.knowledge_sources && <details className="panel-details knowledge-panel-sources"><summary>Workspace context</summary>{props.panel.knowledge_sources.map(source => <EvidenceSourceLink key={source.chunk_id} source={source} workspaceId={props.workspaceId} />)}</details>}</>;
}
export function FounderContext({ context }: { context: NonNullable<StandardPanel['founder_context']> }) {
  return <aside className="founder-context" aria-label="Founder decision context">
    {context.next_decision && <div className="founder-next-decision"><span className="panel-kicker">Next decision</span><strong>{context.next_decision}</strong></div>}
    {context.evidence_gaps.length > 0 && <div className="founder-evidence-gaps"><span className="panel-kicker">Evidence still needed</span><p>{context.evidence_gaps[0]}</p>{context.evidence_gaps.length > 1 && <details className="panel-details"><summary>More evidence to collect ({context.evidence_gaps.length - 1})</summary><ul>{context.evidence_gaps.slice(1).map(gap => <li key={gap}>{gap}</li>)}</ul></details>}</div>}
    {context.framework && <details className="panel-details founder-attribution"><summary>Framework attribution</summary><p>{context.framework.attribution}</p><a href={context.framework.source_url} target="_blank" rel="noopener noreferrer">{context.framework.id} {context.framework.version}</a></details>}
  </aside>;
}

function BriefCopy({ text }: { text: string }) {
  if (text.length <= 220) return <p>{text}</p>;
  const preview = Array.from(text).slice(0, 220).join('').replace(/\s+\S*$/, '');
  return <div className="brief-step-copy"><p>{preview}…</p><details className="panel-details"><summary>Read full answer</summary><p>{text}</p></details></div>;
}
const briefStops = ['Idea', 'Customers', 'Resources', 'Milestone', 'Next move'] as const;
function BriefPanel({ panel, onDiscuss }: Props & { panel: Extract<Panel, { kind: 'evidence' }> }) {
  const [step, setStep] = useState(0);
  const fields = panel.claims.map(claim => { const index = claim.claim.indexOf(':'); return index < 0 ? { label: 'Context', value: claim.claim } : { label: claim.claim.slice(0, index), value: claim.claim.slice(index + 1).trim() }; });
  const value = (...labels: string[]) => fields.find(field => labels.includes(field.label))?.value;
  const core = ['Idea', 'First customers', 'Market', 'Budget', 'Founder skills', 'Skills & resources', 'First milestone'];
  const extra = fields.filter(field => !core.includes(field.label));
  const stop = briefStops[step];
  const fact = (label: string, text: string | undefined) => <div className="brief-step-fact"><span className="panel-kicker">{label}</span><BriefCopy text={text || 'Not shared yet'} /></div>;
  return <div className="interactive-brief brief-workflow">
    <nav className="brief-step-track" aria-label="Company brief steps">{briefStops.map((label, index) => <button type="button" key={label} title={label} aria-label={`Step ${index + 1}: ${label}`} aria-current={index === step ? 'step' : undefined} onClick={() => setStep(index)}><span>{index + 1}</span></button>)}</nav>
    <div className="brief-step-content" aria-live="polite" aria-atomic="true">
      <span className="brief-step-count">{step + 1} of {briefStops.length} · {stop}</span>
      <h4>{['Your idea', 'Who is it for?', 'Your starting point', 'Your first milestone', 'One next move'][step]}</h4>
      {step === 0 && <div className="brief-step-lead"><Sparkles size={22} aria-hidden="true" /><BriefCopy text={value('Idea') || 'Your idea is still taking shape.'} /></div>}
      {step === 1 && <div className="brief-step-facts">{fact('Customers', value('First customers'))}{fact('Market', value('Market'))}</div>}
      {step === 2 && <div className="brief-step-facts">{fact('Budget', value('Budget'))}{fact('Skills & resources', value('Founder skills', 'Skills & resources'))}</div>}
      {step === 3 && <div className="brief-step-lead"><Target size={22} aria-hidden="true" /><BriefCopy text={value('First milestone') || 'Choose a small first milestone.'} /></div>}
      {step === 4 && <>
        <div className="brief-step-lead"><ArrowRight size={22} aria-hidden="true" /><BriefCopy text={panel.founder_context?.next_decision || 'Choose what to explore next.'} /></div>
        {(extra.length > 0 || panel.founder_context) && <details className="panel-details brief-step-details"><summary>Evidence & context</summary>{panel.founder_context && <FounderContext context={{ ...panel.founder_context, next_decision: null }} />}<dl>{extra.map((field, index) => <div key={`${field.label}-${index}`}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl></details>}
      </>}
    </div>
    <div className="brief-step-actions"><button type="button" className="soft-button" aria-label="Previous brief step" disabled={step === 0} onClick={() => setStep(current => Math.max(0, current - 1))}><ArrowLeft size={14} />Back</button>{step < briefStops.length - 1 ? <button type="button" className="samurai-action" aria-label="Next brief step" onClick={() => setStep(current => Math.min(briefStops.length - 1, current + 1))}>Next<ArrowRight size={14} /></button> : <button type="button" className="soft-button" onClick={() => setStep(0)}>Back to idea</button>}</div>
    <Discussion label={step === 4 ? 'Talk it through' : 'Change this'} prompt={`Help me refine the ${stop.toLowerCase()} in my existing company brief. Ask what I want to change before updating it or starting research.`} onDiscuss={onDiscuss} />
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
  return <div className="interactive-prospects"><ShareRing value={String(panel.rows.length)} label="to explore" segments={[{ label: 'High fit', value: panel.rows.filter(row => row.fit === 'High').length }, { label: 'Medium fit', value: panel.rows.filter(row => row.fit === 'Medium').length }]} /><p className="visual-footnote">{saved} shortlisted</p>
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
  const review = panel.provenance?.artifact_type === 'verification' ? verificationPayloadSchema.safeParse(panel.provenance.payload) : undefined;
  const reviewLabel = review?.success ? { verified: 'Review complete', needs_input: 'More input needed', needs_rework: 'Changes needed' }[review.data.outcome] : undefined;
  const findings = panel.claims.filter(claim => !/^(info|warning|error):/.test(claim.detail));
  const supported = findings.filter(claim => claim.status === 'supported').length;
  const filtered = findings.filter(claim => filter === 'All findings' || (filter === 'Needs review' ? claim.status !== 'supported' : claim.sources.length > 0));
  const support = findings.filter(claim => claim.detail && !['Assumption, not sourced fact', 'Research summary; see individual source-backed findings'].includes(claim.detail)).filter((claim, index, entries) => /^(unverified|supported|contradicted);/.test(claim.detail) || entries.findIndex(entry => entry.detail === claim.detail) === index);
  const warnings = panel.claims.filter(claim => /^(warning|error):/.test(claim.detail));
  const sourceKey = (source: EvidenceSource) => source.kind === 'external' ? source.url : source.chunk_id;
  const sourceLinks = (sources: EvidenceSource[]) => sources.map(source => <EvidenceSourceLink key={sourceKey(source)} source={source} workspaceId={workspaceId} />);
  const render = (claim: typeof panel.claims[number]) => <div className="evidence-row" key={claim.id}><span className="finding-state"><span />{claim.status === 'supported' ? 'Supported' : claim.status === 'hypothesis' ? 'Hypothesis' : 'Needs review'}</span>{claim.claim.length > 240 ? <details className="evidence-reading"><summary><strong>{claim.claim.slice(0, 200)}…</strong><span>Read more</span></summary><p>{claim.claim}</p></details> : <strong>{claim.claim}</strong>}{!compact && sourceLinks(claim.sources.slice(0, 2))}{!compact && claim.sources.length > 2 && <details className="panel-details"><summary>More sources</summary>{sourceLinks(claim.sources.slice(2))}</details>}</div>;
  return <div className="evidence-list">{review?.success ? <div className="brief-step-lead"><CheckCheck size={24} aria-hidden="true" /><p>{reviewLabel}</p><span className="visual-footnote">{review.data.checked_artifact_ids.length} artifacts checked · This is not customer validation.</span></div> : <ShareRing value={`${supported}/${findings.length}`} label="supported" segments={[{ label: 'Supported', value: supported }, { label: 'Needs review', value: findings.filter(claim => claim.status === 'needs-check').length }, { label: 'Hypotheses', value: findings.filter(claim => claim.status === 'hypothesis').length }]} />}<details className="panel-details visual-findings"><summary>{review?.success ? 'Review notes' : <>Review {findings.length} findings</>}</summary><Choices label="Evidence filters" values={['All findings', 'Needs review', 'With sources']} selected={filter} onSelect={setFilter} />
    {filtered.slice(0, 3).map(render)}{!filtered.length && <p className="empty-note">No findings in this view. Evidence may still be needed.</p>}
    {(filtered.length > 3 || warnings.length > 0 || support.length > 0) && <details className="panel-details"><summary>Details</summary>{filtered.slice(3).map(render)}{warnings.map(claim => <p key={claim.id}>{claim.claim}</p>)}{support.map(claim => <div className="evidence-row" key={`support-${claim.id}`}><strong>{claim.detail.startsWith('contradicted;') ? 'Conflicting evidence' : /^(unverified|supported);/.test(claim.detail) ? 'Source support' : 'Context'}</strong><p className="source-support-claim">{claim.claim}</p><p>{claim.detail.replace(/^(unverified|supported|contradicted); (mapped|unmapped)\.\s*/, '') || 'Source support has not been retained for this finding.'}</p></div>)}</details>}
  </details></div>;
}
function DeliveryPanel({ panel, completedTasks, onComplete, compact }: Props & { panel: Extract<Panel, { kind: 'launch-plan' }> }) {
  const completed = panel.tasks.filter(task => completedTasks.includes(JSON.stringify([panel.id, task.id]))).length;
  const render = (task: typeof panel.tasks[number], index: number) => {
    const id = JSON.stringify([panel.id, task.id]);
    const done = completedTasks.includes(id);
    return <div className={`launch-task ${done ? 'task-done' : ''}`} key={task.id}><button className="task-check" aria-label={`${done ? 'Reopen' : 'Complete'} ${task.title}`} aria-pressed={done} onClick={() => onComplete(id)}>{done ? <Check size={15} /> : index + 1}</button><div><strong>{task.title}</strong>{task.timing !== 'Not scheduled' && <span>{task.timing}</span>}{!compact && <details className="task-detail"><summary aria-label={`Details for ${task.title}`}>Details<ChevronDown size={12} /></summary><p>Owner: {task.owner}</p>{!['complete', 'needs_rework', 'needs_input', 'draft_only'].includes(task.detail) && <p>{task.detail}</p>}</details>}</div></div>;
  };
  return <div className="launch-plan"><ShareRing value={`${completed}/${panel.tasks.length}`} label="steps complete" segments={[{ label: 'Complete', value: completed }, { label: 'Remaining', value: panel.tasks.length - completed }]} /><progress className="sr-only" aria-label="Launch progress" value={completed} max={panel.tasks.length || 1} />{panel.tasks.slice(0, 3).map(render)}{panel.tasks.length > 3 && <details className="panel-details"><summary>More steps ({panel.tasks.length - 3})</summary>{panel.tasks.slice(3).map((task, index) => render(task, index + 3))}</details>}</div>;
}
