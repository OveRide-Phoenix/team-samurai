import { createContext, useContext } from 'react';
import { createLibrary, defineComponent } from '@openuidev/react-lang';
import { ArrowRight, Leaf } from 'lucide-react';
import { z } from 'zod';
import { OpenUIRender } from './OpenUIRender';
import { aspectCatalog } from './ideaAspectCatalog';
import { aspectOrder } from './aspectJourney';
import { ideaAnalysisSchema, type IdeaAnalysis } from './ideaAnalysis';
import type { WorkflowArea } from './model';

const AnalysisContext = createContext<((area: WorkflowArea) => void) | null>(null);
const analysisProps = z.object({ analysis: ideaAnalysisSchema.optional(), pending: z.boolean() });
const basisLabels = { provided: 'From your idea', inferred: 'Mentor assumption' } as const;
const IdeaFirstPass = defineComponent({
  name: 'IdeaFirstPass', description: 'Mentor welcome and a six-aspect first pass, with explicit draft provenance', props: z.object({ data: analysisProps }),
  component: ({ props: { data } }) => {
    const onAspect = useContext(AnalysisContext);
    const analysis = data.analysis;
    return <section className="idea-first-pass" aria-label="Mentor first pass">
      <span className="guide-kicker"><Leaf size={14} />YOUR IDEA MENTOR</span>
      <h2>{analysis ? 'Here’s how I’m understanding your idea.' : 'I’m Proofseed. Let’s explore your idea.'}</h2>
      <p>{analysis?.summary ?? (data.pending ? 'I’m making a first pass across the problem, market, sales, product, budget and validation. I’ll fill what I can and ask you about the gaps.' : 'We can work through all six aspects together. Start with what you know; we’ll make the assumptions clear.')}</p>
      {analysis && <>
        <p>I’ve drafted {analysis.starting_points.length} of 18 starting points across your six aspects. Here’s my starting view of each. “From your idea” is what you shared; “Mentor assumption” is my inference. These drafts still need validation.</p>
        <div className="analysis-aspects">{aspectOrder.map((area, index) => {
        const aspect = aspectCatalog[area];
        const checks = aspect.checkpoints.map(check => ({ ...check, point: analysis.starting_points.find(point => point.checkpoint_id === check.id) }));
        const preview = checks.find(check => check.point);
        const drafted = checks.filter(check => check.point).length;
        return <section className="analysis-aspect" aria-label={aspect.name} key={area}>
          <div className="analysis-aspect-heading">
            <span className="analysis-number">{index + 1}</span><h3>{aspect.name}</h3><span>{drafted} / 3 drafted</span>
          </div>
          <div className="analysis-starting-point" data-basis={preview?.point?.basis ?? 'unknown'}>
            <span>{preview?.title ?? 'Let’s clarify this'}<small>{preview?.point ? basisLabels[preview.point.basis] : 'Needs your input'}</small></span>
            <p>{preview?.point?.answer ?? aspect.goal}</p>
          </div>
          <details>
            <summary>Review all starting points<ArrowRight size={14} aria-hidden="true" /></summary>
            <div className="analysis-aspect-body">
              {checks.map(check => <div className="analysis-starting-point" key={check.id}>
                <span>{check.title}<small>{check.point ? basisLabels[check.point.basis] : 'Needs your input'}</small></span>
                <p>{check.point?.answer ?? check.question}</p>
              </div>)}
              <button className="soft-button" onClick={() => onAspect?.(area)}>Explore in chat<ArrowRight size={14} /></button>
            </div>
          </details>
        </section>;
      })}</div>
        <p className="guide-local-note">First-pass drafts, not verified research. Tell me what I’ve misunderstood or choose an aspect to explore next. We can improve these answers together in chat; readiness stays in progress until you assess it.</p>
      </>}
    </section>;
  },
});
export const ideaAnalysisLibrary = createLibrary({ root: 'IdeaFirstPass', components: [IdeaFirstPass] });
export function OpenUIIdeaAnalysis({ analysis, pending, onAspect }: { readonly analysis?: IdeaAnalysis; readonly pending: boolean; readonly onAspect: (area: WorkflowArea) => void }) {
  return <AnalysisContext.Provider value={onAspect}><OpenUIRender response={`root = IdeaFirstPass(${JSON.stringify(analysisProps.parse({ analysis, pending }))})`} library={ideaAnalysisLibrary} /></AnalysisContext.Provider>;
}
