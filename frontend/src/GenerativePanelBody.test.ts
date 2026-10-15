import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { GenerativePanelBody } from './GenerativePanelBody';
import type { Panel } from './model';

function render(panel: Panel) {
  return renderToStaticMarkup(createElement(GenerativePanelBody, { panel, compact: false, completedTasks: [], onComplete: () => undefined }));
}

describe('readable evidence details', () => {
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
});
