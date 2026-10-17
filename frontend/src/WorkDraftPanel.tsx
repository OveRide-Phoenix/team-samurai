import { useState } from 'react';
import { ArrowLeft, ArrowRight, FileText } from 'lucide-react';
import { artifactSchema } from './agentos';
import type { Panel } from './model';

export function isWorkDraft(panel: Panel) {
  const kind = panel.provenance?.artifact_type;
  return panel.kind === 'evidence' && typeof kind === 'string' && ['builder_draft', 'marketing_draft', 'sales_draft', 'analysis'].includes(kind);
}
export function WorkDraftPanel({ panel, onDiscuss }: { panel: Panel; onDiscuss?: (prompt: string) => void }) {
  const [page, setPage] = useState(0);
  const checked = artifactSchema.safeParse(panel.provenance);
  if (!checked.success) return <p className="error-note" role="alert">This draft could not be displayed. Its saved data is incomplete.</p>;
  const item = checked.data, data = item.payload;
  const sections: [string, string[]][] = data.artifact_type === 'builder_draft' ? [['Architecture', data.architecture], ['Data', data.database_schema], ['Connections', data.apis], ['Screens', data.user_interface], ['Deployment', data.deployment_configuration]]
    : data.artifact_type === 'marketing_draft' ? [['Website', [data.landing_page]], ['Ads', data.ads], ['Social', data.social_posts], ['Email', data.emails]]
      : data.artifact_type === 'sales_draft' ? [['Who to approach', data.prospect_criteria], ['Outreach', data.outreach], ['Sales conversation', data.scripts], ['Objections', data.objection_handling]]
        : data.artifact_type === 'analysis' ? [['Your results', item.measurements.map(metric => metric.name)], ['Findings', data.findings], ['Next actions', data.recommendations]] : [];
  const pages = sections.flatMap(([section, entries]) => entries.map((text, index) => ({ section, text, index })));
  const currentPage = Math.min(page, Math.max(0, pages.length - 1));
  const current = pages[currentPage];
  if (!current) return <p className="empty-note">There is no draft content to review yet.</p>;
  const measurement = data.artifact_type === 'analysis' && current.section === 'Your results' ? item.measurements[current.index] : undefined;
  const long = current.text.length > 260;
  return <div className="work-draft">
    <p className="panel-note">{data.artifact_type === 'analysis' ? 'Your supplied numbers · Not independently verified' : 'Draft only · Nothing sent, published or deployed'}</p>
    <nav className="work-draft-sections" aria-label="Draft sections">{sections.filter(([, entries]) => entries.length).map(([section]) => <button key={section} type="button" aria-current={section === current.section ? 'step' : undefined} onClick={() => setPage(pages.findIndex(entry => entry.section === section))}>{section}</button>)}</nav>
    <div className="work-draft-content" aria-live="polite" aria-atomic="true">
      <span className="brief-step-count">{currentPage + 1} of {pages.length} · {current.section}</span>
      {measurement ? <div className="work-measurement"><h4>{measurement.name}</h4><strong>{measurement.value.toLocaleString(undefined, { maximumSignificantDigits: 21 })} <small>{measurement.unit}</small></strong><p>{measurement.window_start.slice(0, 10)} — {measurement.window_end.slice(0, 10)}</p><details className="panel-details"><summary>Measurement source</summary><p>{measurement.source_label}</p><p>Window: {measurement.window_start} — {measurement.window_end}</p><p>Recorded {measurement.collected_at}</p></details></div> : <>
        <h4>{current.section}</h4>
        <p className="work-draft-copy">{long ? `${Array.from(current.text).slice(0, 260).join('').trimEnd()}…` : current.text}</p>
        {long && <details key={currentPage} className="panel-details"><summary>Read full draft</summary><p className="work-draft-copy">{current.text}</p></details>}
      </>}
    </div>
    <div className="brief-step-actions"><button className="soft-button" type="button" aria-label="Previous draft step" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}><ArrowLeft size={14} />Back</button><button className="soft-button" type="button" aria-label={currentPage < pages.length - 1 ? 'Next draft step' : 'Back to draft start'} onClick={() => setPage(currentPage < pages.length - 1 ? currentPage + 1 : 0)}>{currentPage < pages.length - 1 ? 'Next' : 'Back to start'}<ArrowRight size={14} /></button></div>
    {onDiscuss && <button className="panel-discuss" onClick={() => onDiscuss(`Help me review the ${current.section.toLowerCase()} in this ${data.artifact_type === 'analysis' ? 'analysis of my supplied measurements' : 'draft'}. Preserve its uncertainties and ask before changing it or taking external action.`)}><FileText size={14} />Talk it through<ArrowRight size={14} /></button>}
    <details className="panel-details"><summary>Review notes</summary>{item.assumptions.map(assumption => <p key={assumption.assumption_id}>{assumption.text}</p>)}{item.verification_findings.map((finding, index) => <p key={index}>{finding.message}</p>)}{item.claims.map(claim => <p key={claim.claim_id}>{claim.text} · {claim.verification_status === 'supported' && claim.support_status === 'mapped' ? 'Source support recorded' : 'Needs checking'}</p>)}{item.sources.map(source => <p key={source.source_id}><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a></p>)}</details>
  </div>;
}
