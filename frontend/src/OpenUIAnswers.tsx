import { createContext, useContext } from 'react';
import { createLibrary, defineComponent } from '@openuidev/react-lang';
import { z } from 'zod';
import { OpenUIRender } from './OpenUIRender';
import type { CompanyBrief } from './model';
import { ArrowUp } from 'lucide-react';

const fieldSchema = z.object({ id: z.enum(['idea', 'customer', 'location', 'budget', 'founderSkills', 'goal']), label: z.string().min(1).max(120), placeholder: z.string().max(200), multiline: z.boolean() });
type Question = z.infer<typeof fieldSchema>;
type Answers = { answers: CompanyBrief; error: boolean; onAnswer: (id: Question['id'], value: string) => void };
const AnswerContext = createContext<Answers | null>(null);
const limits = { idea: 1500, customer: 300, location: 120, budget: 120, goal: 500, founderSkills: 500 };
const AnswerFields = defineComponent({
  name: 'AnswerFields', description: 'Validated founder questions using Samurai answer controls', props: z.object({ questions: z.array(fieldSchema).min(1).max(6) }),
  component: ({ props }) => {
    const controls = useContext(AnswerContext);
    if (!controls) return null;
    return <div className="onboarding-fields">{props.questions.map(question => {
      const field = { id: question.id, value: controls.answers[question.id] ?? '', required: true, maxLength: limits[question.id], placeholder: question.placeholder, 'aria-describedby': controls.error ? 'intake-error' : undefined, onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => controls.onAnswer(question.id, event.target.value), className: 'intake-input' };
      return <div key={question.id}><label htmlFor={question.id}>{question.label}</label>{question.multiline ? <textarea {...field} rows={4} /> : <input {...field} />}</div>;
    })}</div>;
  },
});
export const answerLibrary = createLibrary({ root: 'AnswerFields', components: [AnswerFields] });
export function answerResponse(questions: Question[]) {
  return `root = AnswerFields(${JSON.stringify(z.array(fieldSchema).min(1).max(6).parse(questions))})`;
}
export function OpenUIAnswers({ questions, ...controls }: Answers & { questions: Question[] }) {
  return <AnswerContext.Provider value={controls}><OpenUIRender response={answerResponse(questions)} library={answerLibrary} /></AnswerContext.Provider>;
}

type CompanyNameControls = { name: string; pending: boolean; disabled: boolean; onName: (name: string) => void; onStart: () => void };
const CompanyNameContext = createContext<CompanyNameControls | null>(null);
const CompanyName = defineComponent({
  name: 'CompanyName', description: 'Company name answer and the existing start action', props: z.object({ label: z.string() }),
  component: ({ props }) => {
    const controls = useContext(CompanyNameContext);
    if (!controls) return null;
    return <form className="company-intake" onSubmit={event => { event.preventDefault(); controls.onStart(); }}><input aria-label={props.label} placeholder="Give your software idea a name" value={controls.name} onChange={event => controls.onName(event.target.value)} maxLength={80} className="intake-input" /><button type="submit" className="send-button intake-send" aria-label="Start idea" aria-busy={controls.pending} disabled={controls.disabled}><ArrowUp size={20} /></button></form>;
  },
});
const companyNameLibrary = createLibrary({ root: 'CompanyName', components: [CompanyName] });
export function OpenUICompanyName(controls: CompanyNameControls) {
  return <CompanyNameContext.Provider value={controls}><OpenUIRender library={companyNameLibrary} response={'root = CompanyName("Idea name")'} /></CompanyNameContext.Provider>;
}
