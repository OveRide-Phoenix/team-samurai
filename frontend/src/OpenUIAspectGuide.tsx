import { createContext, useContext } from 'react';
import { createLibrary, defineComponent } from '@openuidev/react-lang';
import { ArrowLeft, ArrowRight, Check, MessageCircle } from 'lucide-react';
import { z } from 'zod';
import { OpenUIRender } from './OpenUIRender';
import { aspectCatalog } from './ideaAspectCatalog';
import { aspectQuestions, aspectFormValue, hasFounderAnswer, nextAspectQuestion, type AspectGuide } from './aspectJourney';
import { readinessLabels, type CheckpointStatus } from './aspectState';
import type { WorkflowArea, Workspace } from './model';

type Controls = {
  readonly disabled: boolean; readonly value: string;
  readonly onChange: (value: string) => void; readonly onSubmit: () => void;
  readonly onAssess: (status: CheckpointStatus) => void;
  readonly onQuestion: (id: string) => void; readonly onResume: () => void; readonly onTalk: () => void;
};
const GuideContext = createContext<Controls | null>(null);
const guideProps = z.object({
  mode: z.enum(['question', 'complete', 'paused']), id: z.string().default(''), name: z.string(), title: z.string(), question: z.string(),
  aspectNumber: z.number(), questionNumber: z.number(), answered: z.number(), answer: z.string(), origin: z.string().default(''),
  completedIds: z.array(z.string()).default([]), status: z.enum(['in-progress', 'ready', 'blocked']), previousId: z.string(), nextId: z.string(),
});
const AspectConversation = defineComponent({
  name: 'AspectConversation', description: 'One guided software-idea form with an explicit answer submission, separate from free chat', props: z.object({ data: guideProps }),
  component: ({ props: { data: props } }) => {
    const controls = useContext(GuideContext);
    if (!controls) return null;
    if (props.mode === 'paused') return <div className="aspect-guide-paused"><span>Want a little structure?</span><button className="soft-button" disabled={controls.disabled} onClick={controls.onResume}>Resume walkthrough<ArrowRight size={14} /></button></div>;
    if (props.mode === 'complete') return <section className="aspect-guide" aria-label="Guided reflection complete"><span className="guide-kicker"><Check size={14} />{props.answered} of 18 questions answered</span><h2>{props.answered === 18 ? 'Now let’s challenge the idea.' : `${props.name} reviewed.`}</h2><p>A complete map is a set of hypotheses. Test the weakest assumptions and revise what does not hold up.</p><div className="guide-actions">{props.nextId && <button className="soft-button" disabled={controls.disabled} onClick={() => controls.onQuestion(props.nextId)}>Continue walkthrough<ArrowRight size={14} /></button>}<button className="soft-button" disabled={controls.disabled} onClick={controls.onResume}>Revisit this aspect</button><button className="guide-text-button" onClick={controls.onTalk}><MessageCircle size={14} />Discuss freely</button></div><p className="guide-local-note">Answered questions are not a go signal or independent validation.</p></section>;
    const inputId = `guide-answer-${props.id}`;
    return <section className="aspect-guide" aria-label="Guided aspect question">
      <div className="guide-heading"><span className="guide-kicker">ASPECT {props.aspectNumber} OF 6 · {props.name}</span><button className="guide-text-button" onClick={controls.onTalk}>Ask freely<ArrowRight size={13} /></button></div>
      <div className="guide-progress" aria-label={`${props.answered} of 18 questions answered`}>{aspectQuestions.map(question => <i key={question.id} data-current={question.id === props.id} data-complete={props.completedIds.includes(question.id)} />)}</div>
      <span className="guide-step">Question {props.questionNumber} of 3 · {props.title}</span>
      <h2>{props.question}</h2>
      <form className="guide-answer-form" aria-label={`Answer ${props.title}`} onSubmit={event => { event.preventDefault(); if (!controls.disabled && controls.value.trim()) controls.onSubmit(); }}>
        <fieldset disabled={controls.disabled}>
          <label htmlFor={inputId}>Your answer</label>
          <textarea id={inputId} className="intake-input" value={controls.value} onChange={event => controls.onChange(event.currentTarget.value)} rows={4} maxLength={4000} required placeholder="What do you know? It’s okay to say you don’t know yet." aria-describedby={`${inputId}-hint`} />
          <button type="submit" className="soft-button guide-submit" disabled={!controls.value.trim()}>Review answer<ArrowRight size={14} /></button>
          <p id={`${inputId}-hint`} className="guide-local-note">Chat below is separate. This form stays available.</p>
          <details className="guide-assessment"><summary>Your assessment · optional</summary><div role="group" aria-label="Your readiness assessment">{(['in-progress', 'ready', 'blocked'] as const).map(status => <button type="button" key={status} className="guide-status-choice" data-status={status} aria-pressed={props.status === status} onClick={() => controls.onAssess(status)}><i className="readiness-light" />{readinessLabels[status]}</button>)}</div></details>
        </fieldset>
      </form>
      {props.answer && <details className="guide-saved-answer"><summary>{props.origin || 'Your saved answer'}</summary><p>{props.answer}</p><button type="button" className="soft-button" disabled={controls.disabled} onClick={() => controls.onChange(props.answer)}>Use this draft<ArrowRight size={13} /></button></details>}
      <div className="guide-footer">{props.previousId && <button type="button" className="guide-text-button" disabled={controls.disabled} onClick={() => controls.onQuestion(props.previousId)}><ArrowLeft size={13} />Previous</button>}{props.nextId && <button type="button" className="guide-text-button" disabled={controls.disabled} onClick={() => controls.onQuestion(props.nextId)}>Skip for now<ArrowRight size={13} /></button>}<span>Saved in this browser · Not verified evidence</span></div>
    </section>;
  },
});
export const aspectGuideLibrary = createLibrary({ root: 'AspectConversation', components: [AspectConversation] });
export const aspectGuideResponse = (props: z.input<typeof guideProps>) => `root = AspectConversation(${JSON.stringify(guideProps.parse(props))})`;

export function OpenUIAspectGuide({ area, guide, workspace, ...controls }: Omit<Controls, 'value'> & { readonly area: WorkflowArea; readonly guide?: AspectGuide; readonly workspace: Workspace }) {
  const question = aspectQuestions.find(item => item.id === guide?.questionId);
  const saved = question ? workspace.aspectChecks[question.id] : undefined;
  const answered = aspectQuestions.filter(item => hasFounderAnswer(workspace, item.id)).length;
  const position = aspectQuestions.findIndex(item => item.id === question?.id);
  const props = {
    mode: guide ? question ? 'question' as const : 'complete' as const : 'paused' as const,
    id: question?.id ?? '', name: aspectCatalog[area].name, title: question?.title ?? '', question: question?.question ?? '',
    aspectNumber: (question?.aspectIndex ?? 0) + 1, questionNumber: (question?.index ?? 0) + 1,
    completedIds: aspectQuestions.filter(item => hasFounderAnswer(workspace, item.id)).map(item => item.id), answered, answer: saved?.note ?? '', origin: saved?.origin === 'mentor' ? saved.basis === 'provided' ? 'Draft from your idea' : 'Mentor suggestion · review before using' : '', status: saved?.status ?? 'in-progress' as const,
    previousId: position > 0 ? aspectQuestions[position - 1].id : '',
    nextId: question ? aspectQuestions[position + 1]?.id ?? '' : nextAspectQuestion(workspace)?.id ?? '',
  };
  const value = question ? aspectFormValue(workspace, question.id) : '';
  return <GuideContext.Provider value={{ ...controls, value }}><OpenUIRender response={aspectGuideResponse(props)} library={aspectGuideLibrary} /></GuideContext.Provider>;
}
