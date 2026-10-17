import { describe, expect, it } from 'vitest';
import { panelSchema, latestPanels, emptyWorkspace, workspaceSchema } from './model';
import { declarativeResponse } from './DeclarativePanel';
import { knownPanelComponent, onboardingPanelCatalog } from './KnownPanel';
import { customFrameHeight, sandboxDocument } from './CustomPanel';
import { filterProspects } from './StandardPanelBody';
import { createAgentosTransport, readAgentosRun } from './agentos';
import { vi } from 'vitest';

const note = 'Generated view · Working assumptions, not verified business results' as const;
const panel = panelSchema.parse({ id: '00000000-0000-4000-8000-000000000001', kind: 'declarative', title: 'Pilot comparison', note, blocks: [{ kind: 'table', columns: ['Offer'], rows: [['Hypothesis']] }] });

describe('generative UI boundaries', () => {
  it('defines the decided onboarding panels and selects the brief separately from research', () => {
    expect(Object.keys(onboardingPanelCatalog)).toEqual(['CompanyBrief', 'ResearchEvidence', 'Offer', 'Pricing', 'DeliveryPlan', 'ProspectList']);
    const brief = panelSchema.parse({ id: 'brief', kind: 'evidence', title: 'Company brief', note: '', claims: [] });
    expect(knownPanelComponent(brief)).toBe('CompanyBrief');
    expect(knownPanelComponent({ ...brief, title: 'Research evidence' })).toBe('ResearchEvidence');
  });
  it('rejects executable catalog entries, ragged tables and verification overrides', () => {
    expect(panelSchema.safeParse({ ...panel, blocks: [{ kind: 'script', text: 'bad' }] }).success).toBe(false);
    expect(panelSchema.safeParse({ ...panel, blocks: [{ kind: 'table', columns: ['One'], rows: [['One', 'Two']] }] }).success).toBe(false);
    expect(panelSchema.safeParse({ ...panel, note: 'Verified' }).success).toBe(false);
    expect(panelSchema.safeParse({ ...panel, provenance: { artifact_type: 'strategy' } }).success).toBe(false);
  });
  it('creates an OpenUI response and retains panel updates and reload data', () => {
    if (panel.kind !== 'declarative') throw new Error('Expected composed panel');
    expect(declarativeResponse(panel)).toBe('root = Column([Table([\"Offer\"], [[\"Hypothesis\"]])])');
    const workspace = workspaceSchema.parse({ ...emptyWorkspace(), pinned: [panel], messages: [{ id: 'updated', role: 'assistant', text: '', panel: { ...panel, title: 'Updated view' } }] });
    expect(latestPanels(workspace)).toHaveLength(1);
    expect(latestPanels(workspace)[0].title).toBe('Updated view');
  });
  it('bounds custom code and contains it behind an inline-only CSP', () => {
    const custom = panelSchema.parse({ id: panel.id, kind: 'custom', title: 'Calculator', note, html: '<button>Calculate</button>', css: 'button{color:blue}', javascript: 'console.log("</ScRiPt>")' });
    if (custom.kind !== 'custom') throw new Error('Expected custom view');
    const html = sandboxDocument(custom);
    expect(html).toContain("connect-src 'none'");
    expect(html).toContain("form-action 'none'");
    expect(html).toContain("style-src-attr 'none'");
    expect(html.indexOf('@layer samurai;')).toBeLessThan(html.indexOf(custom.css));
    expect(html).toContain('<\\/script>');
    expect(panelSchema.safeParse({ ...custom, html: 'x'.repeat(60001) }).success).toBe(false);
  });
  it('presents a custom-tool result once and recovers it from the scoped native run', async () => {
    const content = 'SAMURAI_PANEL=' + JSON.stringify(panel);
    const event = (kind: string, fields = {}) => ({ event: kind, run_id: 'r', session_id: 's', agent_id: 'samurai', ...fields });
    const data = [event('RunStarted'), event('ToolCallCompleted', { tool: { result: content } }), event('RunCompleted', { content })].map(value => `data: ${JSON.stringify(value)}\n\n`).join('');
    vi.stubGlobal('fetch', vi.fn(async (_url, options) => options?.method === 'GET' ? new Response(JSON.stringify(event('RunCompleted', { status: 'COMPLETED', content }))) : new Response(data, { headers: { 'content-type': 'text/event-stream' } })));
    try {
      const output = [];
      for await (const value of createAgentosTransport('s')('Compose a panel', new AbortController().signal)) output.push(value);
      expect(output).toEqual([{ type: 'message', text: '', panel }]);
      expect((await readAgentosRun('s', 'r')).events).toEqual(output);
      expect((await readAgentosRun('s', 'r', undefined, [{ id: 'saved', role: 'assistant', text: '', panel }])).events).toEqual([]);
    } finally { vi.unstubAllGlobals(); }
  });
});


describe('interactive panel controls', () => {
  it('sizes only its own opaque custom frame and rejects action messages and oversized dimensions', () => {
    const frame = {};
    const valid = { source: frame, origin: 'null', data: { type: 'samurai:custom:size', height: 240 } };
    expect(customFrameHeight(valid, frame)).toBe(242);
    expect(customFrameHeight({ ...valid, source: {} }, frame)).toBeUndefined();
    expect(customFrameHeight({ ...valid, origin: 'https://other.example' }, frame)).toBeUndefined();
    expect(customFrameHeight({ ...valid, data: { type: 'publish', height: 240 } }, frame)).toBeUndefined();
    expect(customFrameHeight({ ...valid, data: { ...valid.data, height: 999999 } }, frame)).toBe(720);
    expect(customFrameHeight({ ...valid, data: { ...valid.data, height: NaN } }, frame)).toBeUndefined();
    expect(customFrameHeight({ ...valid, data: { ...valid.data, user: 'forged' } }, frame)).toBeUndefined();
  });
  it('filters prospects by fit and the current company shortlist', () => {
    const rows = [
      { id: 'a', name: 'Maple Clinic', area: 'Bengaluru', reason: 'Evening demand', fit: 'High' as const },
      { id: 'b', name: 'Oak Clinic', area: 'Pune', reason: 'Small team', fit: 'Medium' as const },
    ];
    expect(filterProspects(rows, 'All', ['a'])).toEqual(rows);
    expect(filterProspects(rows, 'Shortlisted', ['a', 'foreign'])).toEqual([rows[0]]);
    expect(filterProspects(rows, 'High fit', [])).toEqual([rows[0]]);
  });
});
