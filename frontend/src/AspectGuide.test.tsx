import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createParser } from '@openuidev/react-lang';
import { describe, expect, it } from 'vitest';
import { aspectGuideLibrary, aspectGuideResponse, OpenUIAspectGuide } from './OpenUIAspectGuide';
import { emptyWorkspace } from './model';
import { ThemedSelect } from './ThemedSelect';

const controls = { disabled: false, onAssess: () => undefined, onQuestion: () => undefined, onResume: () => undefined, onTalk: () => undefined, onChange: () => undefined, onSubmit: () => undefined };
describe('OpenUI aspect conversation', () => {
  it('parses structured questions and renders a real answer form separately from chat', () => {
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
    expect(html).toContain('<textarea');
    expect(html).toContain('Review answer');
    expect(html).toContain('Answer Customer &amp; problem');
    expect(html).not.toContain('<script>');
  });
  it('does not fill the answer from mentor assumptions or mark them as answered', () => {
    const workspace = { ...emptyWorkspace(), aspectChecks: { 'customer-problem': { status: 'in-progress' as const, note: 'An unreviewed hypothesis', origin: 'mentor' as const } } };
    const html = renderToStaticMarkup(createElement(OpenUIAspectGuide, { ...controls, workspace, area: 'research', guide: { area: 'research', questionId: 'customer-problem' } }));
    expect(html).toContain('0 of 18 questions answered');
    expect(html).toContain('Use this draft');
    expect(html).toMatch(/<textarea[^>]*><\/textarea>/);
    expect(html).toContain('type="submit"');
    expect(html).not.toContain('Edit in chat');
  });
  it('keeps disabled and completed states within the registered OpenUI surface', () => {
    const question = renderToStaticMarkup(createElement(OpenUIAspectGuide, { ...controls, disabled: true, workspace: emptyWorkspace(), area: 'research', guide: { area: 'research', questionId: 'customer-problem' } }));
    expect(question).toContain('<fieldset disabled=""');
    const complete = renderToStaticMarkup(createElement(OpenUIAspectGuide, { ...controls, workspace: emptyWorkspace(), area: 'verification', guide: { area: 'verification' } }));
    expect(complete).toContain('Continue walkthrough');
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
