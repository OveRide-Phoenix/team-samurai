import { createContext, useContext } from 'react';
import { createLibrary, defineComponent } from '@openuidev/react-lang';
import { ArrowLeft, ArrowRight, Check, MessageCircle } from 'lucide-react';
import { z } from 'zod';
import { OpenUIRender } from './OpenUIRender';
import { aspectCatalog } from './ideaAspectCatalog';
import { aspectQuestions, type AspectGuide } from './aspectJourney';
import { readinessLabels, type CheckpointStatus } from './aspectState';
import type { WorkflowArea, Workspace } from './model';

type Controls = {
  readonly disabled: boolean; readonly onAssess: (status: CheckpointStatus) => void;
  readonly onQuestion: (id: string) => void; readonly onResume: () => void;
  readonly onTalk: () => void; readonly onMap: () => void;
};
const GuideContext = createContext<Controls | null>(null);
const guideProps = z.object({
  mode: z.enum(['question', 'complete', 'paused']), name: z.string(), title: z.string(), question: z.string(),
  aspectNumber: z.number(), questionNumber: z.number(), answered: z.number(), answer: z.string(), origin: z.string().default(''),
  status: z.enum(['in-progress', 'ready', 'blocked']), previousId: z.string(), nextId: z.string(),
});
const AspectConversation = defineComponent({
  name: 'AspectConversation', description: 'One guided software-idea question answered through the existing chat composer', props: z.object({ data: guideProps }),
  component: ({ props: { data: props } }) => {
    const controls = useContext(GuideContext);
    if (!controls) return null;
    if (props.mode === 'paused') return <div className="aspect-guide-paused"><span>Want a little structure?</span><button className="soft-button" onClick={controls.onResume}>Resume guided questions<ArrowRight size={14} /></button></div>;
    if (props.mode === 'complete') return <section className="aspect-guide" aria-label="Guided reflection complete"><span className="guide-kicker"><Check size={14} />{props.answered} of 18 starting points filled</span><h2>Now let’s challenge the idea.</h2><p>A complete map is a set of hypotheses. Review the weakest assumptions, test them, then revise what does not hold up.</p><div className="guide-actions"><button className="soft-button" disabled={controls.disabled} onClick={controls.onTalk}><MessageCircle size={14} />Challenge these assumptions</button><button className="soft-button" onClick={controls.onResume}>Revisit this aspect</button></div><p className="guide-local-note">Filled answers are not a go signal or independent validation.</p></section>;
    return <section className="aspect-guide" aria-label="Guided aspect question">
      <div className="guide-heading"><span className="guide-kicker">ASPECT {props.aspectNumber} OF 6 · {props.name}</span><button className="guide-text-button" disabled={controls.disabled} onClick={controls.onTalk}>Ask freely<ArrowRight size={13} /></button></div>
      <div className="guide-progress" aria-label={`${props.answered} of 18 starting points filled`}>{Array.from({ length: 18 }, (_, index) => <i key={index} data-complete={index < props.answered} />)}</div>
      <span className="guide-step">Question {props.questionNumber} of 3 · {props.title}</span>
      <h2>{props.question}</h2>
      <p>Reply below. It’s okay to say what you don’t know yet.</p>
      {props.answer && <details className="guide-saved-answer"><summary>{props.origin || 'Your saved answer'}</summary><p>{props.answer}</p><button className="soft-button" onClick={controls.onResume}>Edit in chat<ArrowRight size={13} /></button></details>}
      <fieldset className="guide-assessment" disabled={controls.disabled}><legend>Your assessment <span>optional</span></legend><div role="group" aria-label="Your readiness assessment">{(['in-progress', 'ready', 'blocked'] as const).map(status => <button type="button" key={status} className="guide-status-choice" data-status={status} aria-pressed={props.status === status} onClick={() => controls.onAssess(status)}><i className="readiness-light" />{readinessLabels[status]}</button>)}</div></fieldset>
      <div className="guide-footer">{props.previousId && <button className="guide-text-button" onClick={() => controls.onQuestion(props.previousId)}><ArrowLeft size={13} />Previous question</button>}{props.answer && props.nextId && <button className="guide-text-button" onClick={() => controls.onQuestion(props.nextId)}>Next question<ArrowRight size={13} /></button>}<span>Saved in this browser · Not verified evidence</span></div>
    </section>;
  },
});
export const aspectGuideLibrary = createLibrary({ root: 'AspectConversation', components: [AspectConversation] });
export const aspectGuideResponse = (props: z.input<typeof guideProps>) => `root = AspectConversation(${JSON.stringify(guideProps.parse(props))})`;

export function OpenUIAspectGuide({ area, guide, workspace, ...controls }: Controls & { readonly area: WorkflowArea; readonly guide?: AspectGuide; readonly workspace: Workspace }) {
  const question = aspectQuestions.find(item => item.id === guide?.questionId);
  const saved = question ? workspace.aspectChecks[question.id] : undefined;
  const answered = aspectQuestions.filter(item => workspace.aspectChecks[item.id]?.note.trim()).length;
  const props = {
    mode: guide ? question ? 'question' as const : 'complete' as const : 'paused' as const,
    name: aspectCatalog[area].name, title: question?.title ?? '', question: question?.question ?? '',
    aspectNumber: (question?.aspectIndex ?? 0) + 1, questionNumber: (question?.index ?? 0) + 1,
    answered, answer: saved?.note ?? '', origin: saved?.origin === 'mentor' ? saved.basis === 'provided' ? 'Draft from your idea' : 'Mentor assumption · review in chat' : '', status: saved?.status ?? 'in-progress' as const,
    previousId: question && question.index > 0 ? aspectQuestions.find(item => item.area === area && item.index === question.index - 1)?.id ?? '' : '',
    nextId: question ? aspectQuestions.find(item => item.area === area && item.index === question.index + 1)?.id ?? '' : '',
  };
  return <GuideContext.Provider value={controls}><OpenUIRender response={aspectGuideResponse(props)} library={aspectGuideLibrary} /></GuideContext.Provider>;
}
