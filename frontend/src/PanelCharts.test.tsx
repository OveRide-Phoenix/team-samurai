import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ComparisonBars, numericComparison, ScenarioLines, ShareRing } from './PanelCharts';

const render = renderToStaticMarkup;
describe('data-driven panel charts', () => {
  it('charts only compatible numeric columns and retains exact displayed units', () => {
    expect(numericComparison(['Pilot', 'Monthly'], [['Basic', '₹4,999'], ['Plus', '₹6,999']])).toEqual([{ label: 'Basic', display: '₹4,999', value: 4999 }, { label: 'Plus', display: '₹6,999', value: 6999 }]);
    for (const rows of [[['A', '₹4,999'], ['B', '$99']], [['A', '₹4999 /mo'], ['B', '₹6999']], [['A', '1,2'], ['B', '3']], [['A', '-10'], ['B', '20']], [['A', 'About 5k'], ['B', '10k']], [['A', '9'.repeat(400)], ['B', '1']]]) expect(numericComparison(['Name', 'Value'], rows)).toBeNull();
    expect(numericComparison(['Name'], [['A'], ['B']])).toBeNull();
    expect(numericComparison(['Name', 'Value'], [['A', '1']])).toBeNull();
    expect(numericComparison(['Name', 'Value'], [['A'], ['B', '2']])).toBeNull();
  });
  it('represents zero evidence honestly rather than inventing progress', () => {
    const html = render(createElement(ShareRing, { segments: [{ label: 'Supported', value: 0 }, { label: 'Hypotheses', value: 3 }], value: '0/3', label: 'supported' }));
    expect(html).toContain('Supported: 0, Hypotheses: 3');
    expect(html).toContain('0/3');
    const empty = render(createElement(ShareRing, { segments: [{ label: 'Findings', value: 0 }], value: '0', label: 'findings' }));
    expect(empty).not.toMatch(/NaN|Infinity/);
  });
  it('renders zero-value bars and escapes chart labels', () => {
    const html = render(createElement(ComparisonBars, { items: [{ label: '<script>', value: 0, display: '0' }], label: 'Values' }));
    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toMatch(/NaN|Infinity/);
  });
  it('uses only supplied scenario endpoints, including negative and large values', () => {
    for (const values of [[0, 0], [-100, 200], [-1e308, 1e308]]) {
      const html = render(createElement(ScenarioLines, { trajectories: [{ label: 'low', points: [{ day: 0, value: values[0] }, { day: 30, value: values[1] }] }], horizon: 30 }));
      expect(html).not.toMatch(/NaN|Infinity/);
      expect(html.match(/<circle/g)).toHaveLength(2);
      expect(html).toContain('endpoints only');
    }
  });
});
