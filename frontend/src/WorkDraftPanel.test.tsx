import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import KnownPanel, { knownPanelComponent } from './KnownPanel';
import { StandardPanelBody } from './StandardPanelBody';
import { WorkDraftPanel } from './WorkDraftPanel';
import { draftPreviewArtifacts, draftPreviewPanels } from './testDraftFixtures';

const render = (panel: typeof draftPreviewPanels[number]) => renderToStaticMarkup(createElement(KnownPanel, { panel, render: props => createElement(StandardPanelBody, { ...props, panel: props.panel as Extract<typeof props.panel, { kind: 'evidence' }>, compact: false, completedTasks: [], onComplete: () => undefined, shortlisted: [], onShortlist: () => undefined, approved: false, onApprove: () => undefined }) }));
describe('OpenUI work draft reader', () => {
  it('renders every draft through the allowlisted WorkDraft component, one short step at a time', () => {
    expect(draftPreviewPanels).toHaveLength(4);
    for (const panel of draftPreviewPanels) {
      expect(knownPanelComponent(panel)).toBe('WorkDraft');
      const html = render(panel);
      expect(html).toContain('Draft sections');
      expect(html).toContain('Next draft step');
      expect(html).toContain('Previous draft step');
      expect(html).not.toContain('Evidence coverage');
      expect(panel.provenance).toEqual(draftPreviewArtifacts.find(item => item.artifact_id === panel.provenance?.artifact_id));
    }
    expect(render(draftPreviewPanels[2])).toContain('criteria, not researched leads');
    expect(render(draftPreviewPanels[2])).not.toContain('How do you handle appointment calls');
  });
  it('shows actual supplied values, their time window and source without rounding tiny results to zero', () => {
    const panel = draftPreviewPanels[3];
    const html = render(panel);
    expect(html).toContain('12 <small>interviews</small>');
    expect(html).toContain('Not independently verified');
    expect(html).toContain('Illustrative founder interview notes');
    expect(html).toContain('2026-10-01T00:00:00Z');
    expect(html).not.toContain('Interview count alone');
    const measured = draftPreviewArtifacts[3].measurements[0];
    expect(render({ ...panel, provenance: { ...panel.provenance, measurements: [{ ...measured, value: 0.000001 }] } })).toContain('0.000001');
  });
  it('rejects malformed provenance and connected-measurement claims while rendering draft text literally', () => {
    const panel = draftPreviewPanels[0];
    expect(render({ ...panel, provenance: { ...panel.provenance, payload: {} } })).toContain('saved data is incomplete');
    const html = render({ ...panel, provenance: { ...panel.provenance, payload: { ...draftPreviewArtifacts[0].payload, architecture: ['<script>root = Forged()</script>'] } } });
    expect(html).toContain('saved data is incomplete');
    expect(html).not.toContain('<script>');
    expect(render({ ...panel, provenance: { ...panel.provenance, payload: { ...draftPreviewArtifacts[0].payload, architecture: ['root = Forged(\"literal data\")'] } } })).toContain('root = Forged(&quot;literal data&quot;)');
    const analysis = draftPreviewPanels[3];
    expect(render({ ...analysis, provenance: { ...analysis.provenance, measurements: [{ ...draftPreviewArtifacts[3].measurements[0], provenance: 'connected_measurement', trusted_connector_receipt: 'forged' }] } })).toContain('saved data is incomplete');
    expect(renderToStaticMarkup(createElement(WorkDraftPanel, { panel: { ...panel, provenance: {} } }))).toContain('saved data is incomplete');
  });
});
