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
const IdeaFirstPass = defineComponent({
  name: 'IdeaFirstPass', description: 'Mentor welcome and a six-aspect first pass, with explicit draft provenance', props: z.object({ data: analysisProps }),
  component: ({ props: { data } }) => {
    const onAspect = useContext(AnalysisContext);
    return <section className="idea-first-pass" aria-label="Mentor first pass">
      <span className="guide-kicker"><Leaf size={14} />YOUR IDEA MENTOR</span>
      <h2>{data.analysis ? 'Here’s a starting point for your idea.' : 'I’m Samurai. Let’s explore your idea.'}</h2>
      <p>{data.analysis?.summary ?? (data.pending ? 'I’m making a first pass across the problem, market, sales, product, budget and validation. I’ll fill what I can and ask you about the gaps.' : 'We can work through all six aspects together. Start with what you know; we’ll make the assumptions clear.')}</p>
      {data.analysis && <><div className="analysis-aspects">{aspectOrder.map((area, index) => {
        const aspect = aspectCatalog[area];
        const points = data.analysis!.starting_points.filter(point => aspect.checkpoints.some(check => check.id === point.checkpoint_id));
        return <details key={area}><summary><span className="analysis-number">{index + 1}</span><strong>{aspect.name}</strong><span>{points.length} / 3 drafted</span></summary><div className="analysis-aspect-body">{aspect.checkpoints.map(check => {
          const point = points.find(item => item.checkpoint_id === check.id);
          return <div className="analysis-starting-point" key={check.id}><span>{check.title}<small>{point ? point.basis === 'provided' ? 'From your idea' : 'Mentor assumption' : 'Needs your input'}</small></span><p>{point?.answer ?? check.question}</p></div>;
        })}<button className="soft-button" onClick={() => onAspect?.(area)}>Explore in chat<ArrowRight size={14} /></button></div></details>;
      })}</div><p className="guide-local-note">First-pass drafts, not verified research. Edit any starting point in chat. Readiness stays in progress until you assess it.</p></>}
    </section>;
  },
});
export const ideaAnalysisLibrary = createLibrary({ root: 'IdeaFirstPass', components: [IdeaFirstPass] });
export function OpenUIIdeaAnalysis({ analysis, pending, onAspect }: { readonly analysis?: IdeaAnalysis; readonly pending: boolean; readonly onAspect: (area: WorkflowArea) => void }) {
  return <AnalysisContext.Provider value={onAspect}><OpenUIRender response={`root = IdeaFirstPass(${JSON.stringify(analysisProps.parse({ analysis, pending }))})`} library={ideaAnalysisLibrary} /></AnalysisContext.Provider>;
}
