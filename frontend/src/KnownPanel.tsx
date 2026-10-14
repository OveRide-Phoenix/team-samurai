import { createContext, useContext, useEffect, useMemo, type ComponentType } from 'react';
import { z } from 'zod-v3';
import { A2UIProvider, A2UIRenderer, createCatalog, useA2UI, useA2UIError } from '@copilotkit/a2ui-renderer';
import { panelSchema, type Panel } from './model';

type PanelProps = { panel: Panel; compact?: boolean; expanded?: boolean; expandable?: boolean };
type Props = PanelProps & { render: ComponentType<PanelProps> };
export const onboardingPanelCatalog = {
  CompanyBrief: 'Founder idea, customers, market, resources and first milestone',
  ResearchEvidence: 'Sourced findings, assumptions, conflicts and verification review',
  Offer: 'Customer, positioning, promise, inclusions and draft price',
  Pricing: 'Pricing hypotheses and comparison',
  DeliveryPlan: 'Minimum offering, delivery steps and founder progress',
  ProspectList: 'Customer qualification and shortlist',
} as const;
export function knownPanelComponent(panel: Panel): keyof typeof onboardingPanelCatalog {
  if (panel.kind === 'evidence') return panel.title === 'Company brief' ? 'CompanyBrief' : 'ResearchEvidence';
  if (panel.kind === 'offer') return 'Offer';
  if (panel.kind === 'pricing') return 'Pricing';
  if (panel.kind === 'launch-plan') return 'DeliveryPlan';
  if (panel.kind === 'prospects') return 'ProspectList';
  throw new Error('Custom and composed panels use their own surfaces.');
}
function Surface({ panel }: { panel: Panel }) {
  const { processMessages, clearSurfaces } = useA2UI();
  const error = useA2UIError();
  const content = JSON.stringify(panel);
  useEffect(() => {
    clearSurfaces();
    processMessages([
      { version: 'v0.9', createSurface: { surfaceId: panel.id, catalogId: 'samurai://onboarding/v1' } },
      { version: 'v0.9', updateComponents: { surfaceId: panel.id, components: [{ id: 'root', component: knownPanelComponent(panel), panel }] } },
    ]);
  }, [panel.id, content, processMessages, clearSurfaces]);
  return error ? <p className="error-note" role="alert">This business panel could not be displayed.</p> : <A2UIRenderer surfaceId={panel.id} />;
}
const ViewContext = createContext<Omit<Props, 'panel'> | null>(null);
const definitions = Object.fromEntries(Object.entries(onboardingPanelCatalog).map(([name, description]) => [name, { description, props: z.object({ panel: z.unknown() }) }]));
const catalog = createCatalog(definitions, Object.fromEntries(Object.keys(onboardingPanelCatalog).map(name => [name, ({ props }: { props: { panel?: unknown } }) => <PanelContent name={name} value={props.panel} />])), { catalogId: 'samurai://onboarding/v1' });
function PanelContent({ name, value }: { name: string; value: unknown }) {
  const view = useContext(ViewContext);
  const parsed = panelSchema.safeParse(value);
  if (!view || !parsed.success || ['custom', 'declarative'].includes(parsed.data.kind) || knownPanelComponent(parsed.data) !== name) return <p className="error-note" role="alert">This business panel contains incomplete data.</p>;
  const { render: Render, ...options } = view;
  return <Render {...options} panel={parsed.data} />;
}
export default function KnownPanel({ panel, render, compact, expanded, expandable }: Props) {
  const view = useMemo(() => ({ render, compact, expanded, expandable }), [render, compact, expanded, expandable]);
  return <ViewContext.Provider value={view}><A2UIProvider catalog={catalog}><Surface panel={panel} /></A2UIProvider></ViewContext.Provider>;
}
