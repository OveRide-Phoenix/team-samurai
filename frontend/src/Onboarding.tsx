import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight } from 'lucide-react';
import { companyBriefSchema, type CompanyBrief } from './model';
import { TransitionGrain } from './TransitionGrain';

type Question = { id: keyof CompanyBrief; label: string; placeholder: string; multiline?: boolean };
// Founder inputs map to the backend brief; they are not research evidence.
export const intakePages: { title: string; questions: Question[] }[] = [
  { title: "What do you want to build?", questions: [{ id: 'idea', label: 'Business idea', placeholder: 'The problem you want to solve, and how.', multiline: true }] },
  { title: "Who is it for?", questions: [
    { id: 'customer', label: 'Your first customers', placeholder: 'For example, independent dental clinics' },
    { id: 'location', label: 'Where will you start?', placeholder: 'City, country or online market' },
  ] },
  { title: "What are you working with?", questions: [
    { id: 'budget', label: 'Starting budget', placeholder: 'Amount and currency, or no budget yet' },
    { id: 'goal', label: 'Your first milestone', placeholder: 'What would progress look like in 30 days?', multiline: true },
  ] },
];
export function Onboarding({ name, onCancel, onComplete }: { name: string; onCancel: () => void; onComplete: (brief: CompanyBrief) => void }) {
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<CompanyBrief>({ idea: '', customer: '', location: '', budget: '', goal: '' });
  const [error, setError] = useState('');
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, [step]);
  const page = intakePages[step];
  return <div className="onboarding-shell">
    <button className="onboarding-cancel soft-button" onClick={onCancel}><ArrowLeft size={15} />Home</button>
    <TransitionGrain key={`grain-${step}`} />
    <form key={`page-${step}`} className="onboarding-page" onSubmit={event => {
      event.preventDefault();
      for (const question of page.questions) {
        if (!companyBriefSchema.shape[question.id].safeParse(answers[question.id]).success) {
          setError(`Please add a little more detail for ${question.label.toLowerCase()}.`); return;
        }
      }
      setError('');
      if (step === intakePages.length - 1) onComplete(companyBriefSchema.parse(answers));
      else setStep(step + 1);
    }}>
      <div className="onboarding-progress"><span>{name}</span><span>{step + 1} / {intakePages.length}</span></div>
      <h1 ref={heading} tabIndex={-1}>{page.title}</h1>
      <div className="onboarding-fields">{page.questions.map(question => {
        const limits = { idea: 1500, customer: 300, location: 120, budget: 120, goal: 500 };
        const props = { id: question.id, value: answers[question.id], required: true, maxLength: limits[question.id], placeholder: question.placeholder, 'aria-describedby': error ? 'intake-error' : undefined, onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => { setAnswers({ ...answers, [question.id]: event.target.value }); setError(''); }, className: 'intake-input' };
        return <div key={question.id}><label htmlFor={question.id}>{question.label}</label>{question.multiline ? <textarea {...props} rows={4} /> : <input {...props} />}</div>;
      })}</div>
      {error && <p id="intake-error" className="intake-error" role="alert">{error}</p>}
      <div className="onboarding-actions">{step > 0 && <button type="button" className="soft-button" onClick={() => { setError(''); setStep(step - 1); }}><ArrowLeft size={16} />Back</button>}<button className="primary-button" type="submit">{step === intakePages.length - 1 ? 'Build my company' : 'Continue'}<ArrowRight size={17} /></button></div>
      <p className="intake-preview-note">Live Samurai workflow · Nothing is sent or published</p>
    </form>
  </div>;
}
