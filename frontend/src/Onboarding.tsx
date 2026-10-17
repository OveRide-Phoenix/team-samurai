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
type IntakePages = z.infer<typeof pagesSchema>;
export function Onboarding({ name, onCancel, onComplete }: { name: string; onCancel: () => void; onComplete: (brief: CompanyBrief) => void }) {
  const [pages, setPages] = useState<IntakePages>([]);
  useEffect(() => {
    const controller = new AbortController();
    void fetch('/api/agentos/intake', { headers: { 'X-Samurai-Client': '1' }, signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error('Prerequisite questions are unavailable. Return Home and try again.');
      const data = pagesSchema.parse(await response.json());
      if (!controller.signal.aborted) setPages(data);
    }).catch(error => { if (!controller.signal.aborted) setError(error instanceof Error ? error.message : 'Could not load prerequisite questions.'); });
    return () => controller.abort();
  }, []);
  const [answers, setAnswers] = useState<CompanyBrief>({ idea: '', customer: '', location: '', budget: '', goal: '' });
  const [error, setError] = useState('');
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, [pages]);
  const page = pages.find(item => item.questions.some(question => question.id === 'idea'));
  if (!page) return <div className="onboarding-shell"><button className="onboarding-cancel soft-button" onClick={onCancel}><ArrowLeft size={15} />Home</button><div className="onboarding-page"><p role={error ? 'alert' : 'status'}>{error || 'Loading prerequisite questions…'}</p></div></div>;
  return <div className="onboarding-shell">
    <button className="onboarding-cancel soft-button" onClick={onCancel}><ArrowLeft size={15} />Home</button>
    <TransitionGrain />
    <form className="onboarding-page" onSubmit={event => {
      event.preventDefault();
      for (const question of page.questions.filter(question => question.id === 'idea')) {
        if (!companyBriefSchema.shape[question.id].safeParse(answers[question.id] ?? '').success) {
          setError(`Please add a little more detail for ${question.label.toLowerCase()}.`); return;
        }
      }
      setError('');
      onComplete(companyBriefSchema.parse(answers));
    }}>
      <div className="onboarding-progress"><span>{name}</span><span>Start with the idea</span></div>
      <h1 ref={heading} tabIndex={-1}>{page.title}</h1>
      <p>Your mentor will make a first pass across all six aspects. We’ll fill in the gaps together in chat.</p>
      <OpenUIAnswers questions={page.questions.filter(question => question.id === 'idea')} answers={answers} error={Boolean(error)} onAnswer={(id, value) => { setAnswers(current => ({ ...current, [id]: value })); setError(''); }} />
      {error && <p id="intake-error" className="intake-error" role="alert">{error}</p>}
      <div className="onboarding-actions"><button className="primary-button" type="submit">Meet my mentor<ArrowRight size={17} /></button></div>
      <p className="intake-note">Live Samurai workflow · Nothing is sent or published</p>
    </form>
  </div>;
}
