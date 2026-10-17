import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { GenerativePanelBody } from './GenerativePanelBody';
import { panelSchema, type Panel } from './model';

function render(panel: Panel) {
  return renderToStaticMarkup(createElement(GenerativePanelBody, { panel, compact: false, completedTasks: [], onComplete: () => undefined }));
}

describe('readable evidence details', () => {
  it('opens a brief at one short step instead of rendering all founder context at once', () => {
    const panel = panelSchema.parse({ id: 'brief', kind: 'evidence', title: 'Company brief', note: '', claims: [
      { id: 'idea', claim: 'Idea: Doorstep bicycle care', status: 'hypothesis', detail: '', sources: [] },
      { id: 'budget', claim: 'Budget: INR 50,000', status: 'hypothesis', detail: '', sources: [] },
      { id: 'milestone', claim: 'First milestone: Ten paying homes', status: 'hypothesis', detail: '', sources: [] },
    ], founder_context: { next_decision: 'Interview residents', evidence_gaps: ['No interviews yet'] } });
    const html = render(panel);
    expect(html).toContain('Doorstep bicycle care');
    expect(html).toContain('aria-current="step"');
    expect(html).toContain('aria-label="Next brief step"');
    expect(html).toContain('Step 5: Next move');
    expect(html).not.toContain('INR 50,000');
    expect(html).not.toContain('Ten paying homes');
    expect(html).not.toContain('Interview residents');
    expect(html).not.toContain('No interviews yet');
  });

  it('keeps long answers available in an explicit disclosure', () => {
    const answer = 'A detailed founder answer. '.repeat(30);
    const html = render(panelSchema.parse({ id: 'long-brief', kind: 'evidence', title: 'Company brief', note: '', claims: [{ id: 'idea', claim: `Idea: ${answer}`, status: 'hypothesis', detail: '', sources: [] }] }));
    expect(html).toContain('<summary>Read full answer</summary>');
    expect(html).toContain(answer.trim());
  });

  it('keeps conflicting source support attached to its finding without repeating draft boilerplate', () => {
    const html = render({ id: 'evidence', kind: 'evidence', title: 'Research', note: '', claims: [
      { id: 'a', claim: 'Claim A', status: 'needs-check', detail: 'contradicted; mapped. Source excerpt A', sources: [{ kind: 'external', title: 'Reference A', url: 'https://example.org/a' }] },
      { id: 'b', claim: 'Draft B', status: 'hypothesis', detail: 'Generated draft; not sent, published or executed', sources: [] },
      { id: 'c', claim: 'Draft C', status: 'hypothesis', detail: 'Generated draft; not sent, published or executed', sources: [] },
    ] });
    expect(html).toMatch(/Conflicting evidence<\/strong><p[^>]*>Claim A<\/p><p>Source excerpt A/);
    expect(html.match(/Generated draft; not sent, published or executed/g)).toHaveLength(1);
    expect(html).not.toContain('contradicted; mapped');
  });

  it('keeps all source links available when extra links are collapsed', () => {
    const sources = ['One', 'Two', 'Three'].map((title, index) => ({ kind: 'external' as const, title, url: `https://example.org/${index}` }));
    const html = render({ id: 'evidence', kind: 'evidence', title: 'Research', note: '', claims: [{ id: 'a', claim: 'A finding', status: 'supported', detail: 'supported; mapped. An excerpt', sources }] });
    expect(html).toContain('More sources');
    for (const source of sources) expect(html).toContain(`href="${source.url}"`);
  });

  it('renders founder decisions and gaps separately from framework attribution', () => {
    const revision = '0'.repeat(40);
    const html = render({ id: 'offer', kind: 'offer', title: 'Offer', note: '', customer: 'Clinics', promise: 'Fewer missed calls', price: '₹4999', includes: [], founder_context: {
      next_decision: 'Interview five clinic owners', evidence_gaps: ['No willingness-to-pay interviews', 'No delivery-cost estimate'],
      framework: { id: 'offer_diagnostic', version: '1.0.0', attribution: 'Adapted from the reviewed offer diagnostic.', source_repository: 'example/repo', source_revision: revision, source_url: `https://github.com/example/repo/tree/${revision}` },
    } });
    expect(html).toContain('Next decision');
    expect(html).toContain('Interview five clinic owners');
    expect(html).toContain('Evidence still needed');
    expect(html).toContain('No willingness-to-pay interviews');
    expect(html).toContain('Framework attribution');
    expect(html).not.toContain('Supported');
  });

  it('renders file download controls and non-downloadable accepted-artifact provenance', () => {
    const html = render({ id: 'strategy', kind: 'offer', title: 'Offer', note: '', customer: 'Clinics', promise: 'Fewer missed calls', price: '₹4999', includes: [], knowledge_sources: [
      { kind: 'workspace_file', file_id: '00000000-0000-4000-8000-000000000001', title: null, chunk_id: '00000000-0000-4000-8000-000000000002', indexed_revision: 7, ordinal: 2, content_sha256: 'a'.repeat(64), trust_class: 'uploaded_file', evidence_status: 'untrusted_context' },
      { kind: 'accepted_artifact', artifact_id: '00000000-0000-4000-8000-000000000003', chunk_id: '00000000-0000-4000-8000-000000000004', indexed_revision: 7, ordinal: 3, content_sha256: 'b'.repeat(64), trust_class: 'accepted_artifact', evidence_status: 'untrusted_context' },
    ] });
    expect(html).toContain('Workspace context');
    expect(html).toContain('Workspace file');
    expect(html).toContain('Accepted artifact details');
    expect(html).toContain('does not independently verify a finding');
    expect(html).not.toContain('00000000-0000-4000-8000-000000000003/download');
  });

  it('keeps the synthetic warning and exact provenance visible beside all three trajectories', () => {
    const metric = (value: string) => [{ metric: 'revenue', unit: 'inr', points: [{ day: 0, value: '100' }, { day: 30, value }] }];
    const panel = panelSchema.parse({ id: 'scenario-a', kind: 'scenario', title: 'Revenue range', note: 'Synthetic scenario', provenance: { label: 'synthetic_scenario_not_validation' }, synthetic_label: 'synthetic_scenario_not_validation', company_revision: 2, result_sha256: 'a'.repeat(64), horizon_days: 30, assumptions: [{ name: 'growth', target_metric: 'revenue', low_delta_percent: '-20', base_delta_percent: '0', high_delta_percent: '20' }], trajectories: [{ label: 'low', metrics: metric('80') }, { label: 'base', metrics: metric('100') }, { label: 'high', metrics: metric('120') }], formulas: [{ metric: 'revenue', expression: 'end = baseline * (1 + delta_percent / 100)', baseline_input: '100', assumption: 'growth' }], constraints: [] });
    const html = render(panel);
    expect(html).toContain('Synthetic scenario, not validation');
    expect(html).toContain('synthetic_scenario_not_validation');
    expect(html).toContain('low'); expect(html).toContain('base'); expect(html).toContain('high');
  });
});

it.each([['verified', 'Review complete'], ['needs_rework', 'Changes needed'], ['needs_input', 'More input needed']])('shows the actual %s review outcome without a zero-of-zero evidence chart', (outcome, label) => {
  const html = render({ id: 'review', kind: 'evidence', title: 'Verification review', note: '', claims: [], provenance: { artifact_type: 'verification', payload: { artifact_type: 'verification', checked_artifact_ids: ['00000000-0000-4000-8000-000000000001'], outcome } } });
  expect(html).toContain(label);
  expect(html).toContain('1 artifacts checked');
  expect(html).toContain('not customer validation');
  expect(html).not.toContain('0/0');
});
