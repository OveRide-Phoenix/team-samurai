import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight } from 'lucide-react';
import { companyBriefSchema, type CompanyBrief } from './model';
import { z } from 'zod';
import { TransitionGrain } from './TransitionGrain';
import { OpenUIAnswers } from './OpenUIAnswers';

const questionSchema = z.strictObject({ id: z.enum(['idea', 'customer', 'location', 'budget', 'founderSkills', 'goal']), label: z.string().min(1).max(120), placeholder: z.string().max(200), multiline: z.boolean() });
const pagesSchema = z.array(z.strictObject({ title: z.string().min(1).max(120), questions: z.array(questionSchema).min(1).max(6) })).min(1).max(6).refine(pages => {
  const ids = pages.flatMap(page => page.questions.map(question => question.id));
  return ids.length === 6 && new Set(ids).size === 6;
}, 'Every prerequisite must appear once');
export type IntakePages = z.infer<typeof pagesSchema>;
export function Onboarding({ name, onCancel, onComplete, previewPages }: { name: string; onCancel: () => void; onComplete: (brief: CompanyBrief) => void; previewPages?: IntakePages }) {
  const [step, setStep] = useState(0);
  const [pages, setPages] = useState<IntakePages>(() => previewPages ? pagesSchema.parse(previewPages) : []);
  useEffect(() => {
    if (previewPages) return;
    const controller = new AbortController();
    void fetch('/api/agentos/intake', { headers: { 'X-Samurai-Client': '1' }, signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error('Prerequisite questions are unavailable. Return Home and try again.');
      const data = pagesSchema.parse(await response.json());
      if (!controller.signal.aborted) setPages(data);
    }).catch(error => { if (!controller.signal.aborted) setError(error instanceof Error ? error.message : 'Could not load prerequisite questions.'); });
    return () => controller.abort();
  }, [previewPages]);
  const [answers, setAnswers] = useState<CompanyBrief>({ idea: '', customer: '', location: '', budget: '', goal: '' });
  const [error, setError] = useState('');
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, [step]);
  const page = pages[step];
  if (!page) return <div className="onboarding-shell"><button className="onboarding-cancel soft-button" onClick={onCancel}><ArrowLeft size={15} />Home</button><div className="onboarding-page"><p role={error ? 'alert' : 'status'}>{error || 'Loading prerequisite questions…'}</p></div></div>;
  return <div className="onboarding-shell">
    <button className="onboarding-cancel soft-button" onClick={onCancel}><ArrowLeft size={15} />Home</button>
    <TransitionGrain key={`grain-${step}`} />
    <form key={`page-${step}`} className="onboarding-page" onSubmit={event => {
      event.preventDefault();
      for (const question of page.questions) {
        if (!companyBriefSchema.shape[question.id].safeParse(answers[question.id] ?? '').success) {
          setError(`Please add a little more detail for ${question.label.toLowerCase()}.`); return;
        }
      }
      setError('');
      if (step === pages.length - 1) onComplete(companyBriefSchema.parse(answers));
      else setStep(step + 1);
    }}>
      <div className="onboarding-progress"><span>{name}</span><span>{step + 1} / {pages.length}</span></div>
      <h1 ref={heading} tabIndex={-1}>{page.title}</h1>
      <OpenUIAnswers questions={page.questions} answers={answers} error={Boolean(error)} onAnswer={(id, value) => { setAnswers(current => ({ ...current, [id]: value })); setError(''); }} />
      {error && <p id="intake-error" className="intake-error" role="alert">{error}</p>}
      <div className="onboarding-actions">{step > 0 && <button type="button" className="soft-button" onClick={() => { setError(''); setStep(step - 1); }}><ArrowLeft size={16} />Back</button>}<button className="primary-button" type="submit">{step === pages.length - 1 ? 'Build my company' : 'Continue'}<ArrowRight size={17} /></button></div>
      <p className="intake-preview-note">{previewPages ? 'UI preview · No provider calls' : 'Live Samurai workflow · Nothing is sent or published'}</p>
    </form>
  </div>;
}
