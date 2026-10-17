import { ArrowLeft, ArrowRight, MessageCircle } from 'lucide-react';
import { aspectCatalog } from './ideaAspectCatalog';
import { aspectReadiness } from './teamAreas';
import { checkpointStatusSchema, readinessLabels, type CheckpointStatus, type IdeaArea } from './aspectState';
import type { WorkflowArea, Workspace } from './model';

export function AspectReview({ area, workspace, readOnly, onChange, onDiscuss, onSelect }: {
  readonly area: WorkflowArea; readonly workspace: Workspace; readonly readOnly: boolean;
  readonly onChange: (id: string, value: { status: CheckpointStatus; note: string }) => void;
  readonly onDiscuss: (text: string) => void; readonly onSelect: (area: IdeaArea) => void;
}) {
  const aspect = aspectCatalog[area];
  const status = aspectReadiness(area, workspace);
  return <section className="aspect-review" id="aspect-detail" aria-label={aspect.name}>
    <button className="soft-button aspect-back" onClick={() => onSelect('overview')}><ArrowLeft size={14} />Idea overview</button>
    <div className="aspect-review-heading"><div><span className="eyebrow">EXPLORE THIS ASPECT</span><h2 tabIndex={-1}>{aspect.name}</h2><p>{aspect.goal}</p></div><span className="aspect-status" data-status={status}><i className="readiness-light" />{readinessLabels[status]}</span></div>
    <div className="aspect-checkpoints">{aspect.checkpoints.map(check => {
      const saved = workspace.aspectChecks[check.id] ?? { status: 'in-progress', note: '' };
      return <article key={check.id} className="aspect-checkpoint" data-status={saved.status}>
        <div className="aspect-checkpoint-heading"><h3>{check.title}</h3><i className="readiness-light" aria-label={readinessLabels[saved.status]} /></div>
        <p>{check.question}</p>
        <label className="aspect-field"><span>Your assessment</span><select value={saved.status} disabled={readOnly} onChange={event => { const parsed = checkpointStatusSchema.safeParse(event.target.value); if (parsed.success) onChange(check.id, { ...saved, status: parsed.data }); }}>{Object.entries(readinessLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
        <label className="aspect-field"><span>Notes & evidence</span><textarea value={saved.note} maxLength={4000} disabled={readOnly} placeholder="What do you know? What still needs testing?" onChange={event => onChange(check.id, { ...saved, note: event.target.value })} /></label>
        <button className="soft-button" disabled={readOnly} onClick={() => onDiscuss(`${check.question}${saved.note ? '\nMy notes: ' + saved.note : ''}\nUse our existing idea context. Label assumptions and suggest one concrete next step.`)}><MessageCircle size={14} />Explore with mentor<ArrowRight size={14} /></button>
      </article>;
    })}</div>
    <div className="aspect-related"><span>Connected to</span>{aspect.related.map(id => <button className="soft-button" key={id} onClick={() => onSelect(id)}>{aspectCatalog[id].name}<ArrowRight size={12} /></button>)}</div>
    <p className="aspect-save-note">Your assessments and notes save in this browser. Ready is your assessment, not independently verified evidence.</p>
  </section>;
}
