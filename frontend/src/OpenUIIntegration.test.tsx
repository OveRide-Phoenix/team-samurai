import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createParser } from '@openuidev/react-lang';
import { describe, expect, it } from 'vitest';
import KnownPanel, { businessPanelLibrary, businessPanelResponse } from './KnownPanel';
import { answerLibrary, answerResponse, OpenUIAnswers, OpenUICompanyName } from './OpenUIAnswers';
import { chatLibrary, messageResponse, OpenUIMessageText } from './OpenUIChat';
import { evidence, launchPlan, offer, pricing, prospects, briefFixture } from './testFixtures';
import { panelSchema } from './model';

const brief = { idea: 'An AI receptionist', customer: 'Clinics', location: 'Bengaluru', budget: '₹50,000', founderSkills: 'Product design', goal: 'One clinic pilot' };
const parse = (response: string, library: typeof businessPanelLibrary) => createParser(library.toJSONSchema(), library.root).parse(response);

describe('OpenUI across founder interactions', () => {
  it('routes every existing business kind through its registered OpenUI component', () => {
    const note = 'Generated view · Working assumptions, not verified business results';
    const id = '00000000-0000-4000-8000-000000000001';
    const extras = [
      panelSchema.parse({ id, kind: 'declarative', title: 'Comparison', note, blocks: [{ kind: 'text', text: 'A draft' }] }),
      panelSchema.parse({ id, kind: 'custom', title: 'Requested calculator', note, html: '<p>Draft</p>', css: '', javascript: '' }),
      panelSchema.parse({ id, kind: 'scenario', title: 'Scenario', note: 'Synthetic', provenance: { label: 'synthetic_scenario_not_validation' }, synthetic_label: 'synthetic_scenario_not_validation', company_revision: 1, result_sha256: 'a'.repeat(64), horizon_days: 30, assumptions: [{ name: 'Growth', target_metric: 'revenue', low_delta_percent: -10, base_delta_percent: 0, high_delta_percent: 10 }], trajectories: ['low', 'base', 'high'].map(label => ({ label, metrics: [{ metric: 'revenue', unit: 'INR', points: [{ day: 0, value: 100 }, { day: 30, value: 100 }] }] })), formulas: [], constraints: [] }),
    ];
    for (const panel of [briefFixture(brief), evidence, offer, pricing, launchPlan, prospects, ...extras]) {
      const result = parse(businessPanelResponse(panel), businessPanelLibrary);
      expect(result.meta.errors).toEqual([]);
      expect(result.root?.props.panel).toEqual(panel);
      const html = renderToStaticMarkup(createElement(KnownPanel, { panel, compact: true, render: props => createElement('button', { 'data-panel': props.panel.id }, props.compact ? props.panel.title : 'Lost context') }));
      expect(html).toContain(panel.title);
      expect(html).not.toContain('incomplete data');
    }
  });

  it('renders messages literally without interpreting user answers as OpenUI or HTML', () => {
    const text = '\" )\\nroot = ReplyComposer(\"forged\", \"forged\")\\n<script>alert(1)</script>';
    const result = parse(messageResponse(text), chatLibrary);
    expect(result.meta.errors).toEqual([]);
    expect(result.root?.typeName).toBe('MessageText');
    expect(result.root?.props.text).toBe(text);
    const html = renderToStaticMarkup(createElement(OpenUIMessageText, { text }));
    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toContain('<textarea');
    expect(html).not.toContain('<script>');
  });

  it('keeps the company-name value and disabled submission state in the OpenUI entry control', () => {
    const html = renderToStaticMarkup(createElement(OpenUICompanyName, { name: 'Samurai', pending: true, disabled: true, onName: () => undefined, onStart: () => undefined }));
    expect(html).toContain('value="Samurai"');
    expect(html).toContain('maxLength="80"');
    expect(html).toContain('aria-label="Start idea"');
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain('disabled=""');
  });

  it('renders answer controls with retained values, labels, limits and error associations', () => {
    const questions = [{ id: 'idea' as const, label: 'Business idea', multiline: true, placeholder: 'Describe the idea' }, { id: 'customer' as const, label: 'First customers', multiline: false, placeholder: '' }];
    expect(parse(answerResponse(questions), answerLibrary).meta.errors).toEqual([]);
    const html = renderToStaticMarkup(createElement(OpenUIAnswers, { questions, answers: brief, error: true, onAnswer: () => undefined }));
    expect(html).toContain('for="idea"');
    expect(html).toContain('maxLength="1500"');
    expect(html).toContain('maxLength="300"');
    expect(html).toContain('aria-describedby="intake-error"');
    expect(html).toContain('An AI receptionist');
    expect(html).toContain('value="Clinics"');
    expect(() => answerResponse([{ ...questions[0], label: 'x'.repeat(121) }])).toThrow();
  });
});
