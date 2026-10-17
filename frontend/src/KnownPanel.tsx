import { createContext, useContext, useMemo, type ComponentType } from 'react';
import { z } from 'zod';
import { createLibrary, defineComponent } from '@openuidev/react-lang';
import { OpenUIRender } from './OpenUIRender';
import { isWorkDraft } from './WorkDraftPanel';
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
const extraPanels = { WorkDraft: 'Step-by-step launch drafts and founder-supplied results', Composition: 'Composed business blocks', SandboxedView: 'Isolated requested interactive view', Scenario: 'Synthetic scenario result' };
export function knownPanelComponent(panel: Panel): keyof typeof onboardingPanelCatalog | keyof typeof extraPanels {
  if (isWorkDraft(panel)) return 'WorkDraft';
  if (panel.kind === 'evidence') return panel.title === 'Company brief' ? 'CompanyBrief' : 'ResearchEvidence';
  if (panel.kind === 'offer') return 'Offer';
  if (panel.kind === 'pricing') return 'Pricing';
  if (panel.kind === 'launch-plan') return 'DeliveryPlan';
  if (panel.kind === 'prospects') return 'ProspectList';
  return panel.kind === 'declarative' ? 'Composition' : panel.kind === 'custom' ? 'SandboxedView' : 'Scenario';
}
const ViewContext = createContext<Omit<Props, 'panel'> | null>(null);
export const businessPanelLibrary = createLibrary({ components: Object.entries({ ...onboardingPanelCatalog, ...extraPanels }).map(([name, description]) => defineComponent({ name, description, props: z.object({ panel: z.unknown() }), component: ({ props }) => <PanelContent name={name} value={props.panel} /> })) });
export function businessPanelResponse(panel: Panel) {
  const checked = panelSchema.parse(panel);
  return `root = ${knownPanelComponent(checked)}(${JSON.stringify(checked)})`;
}
function PanelContent({ name, value }: { name: string; value: unknown }) {
  const view = useContext(ViewContext);
  const parsed = panelSchema.safeParse(value);
  if (!view || !parsed.success || knownPanelComponent(parsed.data) !== name) return <p className="error-note" role="alert">This idea panel contains incomplete data.</p>;
  const { render: Render, ...options } = view;
  return <Render {...options} panel={parsed.data} />;
}
export default function KnownPanel({ panel, render, compact, expanded, expandable }: Props) {
  const view = useMemo(() => ({ render, compact, expanded, expandable }), [render, compact, expanded, expandable]);
  return <ViewContext.Provider value={view}><OpenUIRender response={businessPanelResponse(panel)} library={businessPanelLibrary} /></ViewContext.Provider>;
}
