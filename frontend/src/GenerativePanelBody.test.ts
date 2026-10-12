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
      { id: 'a', claim: 'Claim A', status: 'needs-check', detail: 'contradicted; mapped. Source excerpt A', sources: [{ title: 'Reference A', url: 'https://example.org/a' }] },
      { id: 'b', claim: 'Draft B', status: 'hypothesis', detail: 'Generated draft; not sent, published or executed', sources: [] },
      { id: 'c', claim: 'Draft C', status: 'hypothesis', detail: 'Generated draft; not sent, published or executed', sources: [] },
    ] });
    expect(html).toMatch(/Conflicting evidence<\/strong><p[^>]*>Claim A<\/p><p>Source excerpt A/);
    expect(html.match(/Generated draft; not sent, published or executed/g)).toHaveLength(1);
    expect(html).not.toContain('contradicted; mapped');
  });

  it('keeps all source links available when extra links are collapsed', () => {
    const sources = ['One', 'Two', 'Three'].map((title, index) => ({ title, url: `https://example.org/${index}` }));
    const html = render({ id: 'evidence', kind: 'evidence', title: 'Research', note: '', claims: [{ id: 'a', claim: 'A finding', status: 'supported', detail: 'supported; mapped. An excerpt', sources }] });
    expect(html).toContain('More sources');
    for (const source of sources) expect(html).toContain(`href="${source.url}"`);
  });
});
