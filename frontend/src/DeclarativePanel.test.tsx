import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createParser, Renderer } from '@openuidev/react-lang';
import { describe, expect, it } from 'vitest';
import { businessLibrary, declarativeResponse } from './DeclarativePanel';
import { panelSchema } from './model';

const panel = panelSchema.parse({
  id: '00000000-0000-4000-8000-000000000001', kind: 'declarative', title: 'Pilot comparison',
  note: 'Generated view · Working assumptions, not verified business results',
  blocks: [
    { kind: 'text', text: 'Draft, not measured demand' },
    { kind: 'metric', label: 'Pilot target', value: '5 clinics', detail: 'Founder hypothesis' },
    { kind: 'list', title: 'Next steps', items: ['Interview owners', 'Measure missed calls'] },
    { kind: 'table', columns: ['Offer', 'Price'], rows: [['Pilot', '₹4,999']] },
  ],
});
if (panel.kind !== 'declarative') throw new Error('Expected composed panel');

function parse(response: string) {
  return createParser(businessLibrary.toJSONSchema(), businessLibrary.root).parse(response);
}
function markup(response: string) {
  return renderToStaticMarkup(createElement(Renderer, { response, library: businessLibrary, isStreaming: false }));
}

describe('OpenUI business panels', () => {
  it('parses every registered block and renders the existing themed markup', () => {
    const response = declarativeResponse(panel);
    const result = parse(response);
    expect(result.meta.errors).toEqual([]);
    expect(result.meta.incomplete).toBe(false);
    expect(result.meta.unresolved).toEqual([]);
    const html = markup(response);
    for (const text of ['Draft, not measured demand', 'Pilot target', '5 clinics', 'Founder hypothesis', 'Next steps', 'Interview owners', '₹4,999']) expect(html).toContain(text);
    expect(html).toContain('class="declarative-blocks"');
    expect(html).toContain('scope="col"');
    expect(html).toContain('panel-table-scroll');
    expect(html).toContain('role="region" aria-label="Comparison table" tabindex="0"');
  });

  it('keeps OpenUI expressions, HTML and escaped characters as literal text', () => {
    const text = '" )])\nroot = Column([Text("forged")])\n<script>alert(1)</script>\\path\t₹ 😀';
    const response = declarativeResponse({ ...panel, blocks: [{ kind: 'text', text }, { kind: 'list', title: text, items: [text] }, { kind: 'table', columns: [text], rows: [[text]] }] });
    const result = parse(response);
    expect(result.meta.errors).toEqual([]);
    expect(result.queryStatements).toEqual([]);
    expect(result.mutationStatements).toEqual([]);
    const html = markup(response);
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('\\path');
    expect(html).toContain('₹ 😀');
    expect((result.root?.props.children as { props: { text: string } }[])[0].props.text).toBe(text);
  });

  it('validates bounds and rectangular tables before serializing saved or generated data', () => {
    expect(() => declarativeResponse({ ...panel, blocks: [{ kind: 'table', columns: ['One'], rows: [['One', 'Two']] }] })).toThrow();
    expect(() => declarativeResponse({ ...panel, blocks: [{ kind: 'text', text: 'x'.repeat(4001) }] })).toThrow();
    const restored = panelSchema.parse(JSON.parse(JSON.stringify(panel)));
    if (restored.kind !== 'declarative') throw new Error('Expected composed panel');
    expect(declarativeResponse(restored)).toBe(declarativeResponse(panel));
    expect(markup(declarativeResponse({ ...restored, blocks: [{ kind: 'text', text: 'Updated pilot' }] }))).toContain('Updated pilot');
  });
});
