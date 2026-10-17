import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createParser } from '@openuidev/react-lang';
import { describe, expect, it } from 'vitest';
import { aspectGuideLibrary, aspectGuideResponse, OpenUIAspectGuide } from './OpenUIAspectGuide';
import { emptyWorkspace } from './model';
import { ThemedSelect } from './ThemedSelect';

const controls = { disabled: false, onAssess: () => undefined, onQuestion: () => undefined, onResume: () => undefined, onTalk: () => undefined, onMap: () => undefined };
describe('OpenUI aspect conversation', () => {
  it('parses structured questions and renders choices without another answer form', () => {
    const response = aspectGuideResponse({ mode: 'question', name: 'Problem', title: 'Customer', question: 'Who has this problem?', aspectNumber: 1, questionNumber: 1, answered: 0, answer: 'A quoted answer <script>test</script>', status: 'in-progress', previousId: '', nextId: '' });
    const parsed = createParser(aspectGuideLibrary.toJSONSchema(), aspectGuideLibrary.root).parse(response);
    expect(parsed.meta.errors).toEqual([]);
    expect(parsed.root?.props.data).toMatchObject({ question: 'Who has this problem?' });
    const workspace = { ...emptyWorkspace(), aspectChecks: { 'customer-problem': { status: 'ready' as const, note: '<script>test</script>' } } };
    const html = renderToStaticMarkup(createElement(OpenUIAspectGuide, { ...controls, workspace, area: 'research', guide: { area: 'research', questionId: 'customer-problem' } }));
    expect(html).toContain('Guided aspect question');
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain('&lt;script&gt;test&lt;/script&gt;');
    expect(html).not.toContain('<select');
    expect(html).not.toContain('<textarea');
    expect(html).not.toContain('<script>');
  });
  it('keeps disabled and completed states within the registered OpenUI surface', () => {
    const question = renderToStaticMarkup(createElement(OpenUIAspectGuide, { ...controls, disabled: true, workspace: emptyWorkspace(), area: 'research', guide: { area: 'research', questionId: 'customer-problem' } }));
    expect(question).toContain('<fieldset class="guide-assessment" disabled=""');
    const complete = renderToStaticMarkup(createElement(OpenUIAspectGuide, { ...controls, workspace: emptyWorkspace(), area: 'verification', guide: { area: 'verification' } }));
    expect(complete).toContain('Challenge these assumptions');
  });
  it('renders shared menu controls with accessible triggers, form values and disabled semantics', () => {
    const html = renderToStaticMarkup(createElement(ThemedSelect, { label: 'Learning type', name: 'kind', defaultValue: 'correction', disabled: true, options: [{ value: 'preference', label: 'Preference' }, { value: 'correction', label: 'Correction' }] }));
    expect(html).toContain('type="hidden"');
    expect(html).toContain('name="kind"');
    expect(html).toContain('value="correction"');
    expect(html).toContain('aria-label="Learning type"');
    expect(html).toContain('aria-haspopup="menu"');
    expect(html).toContain('disabled=""');
    expect(html).not.toContain('<select');
  });
});
