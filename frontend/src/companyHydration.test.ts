import { describe, expect, it } from 'vitest';
import { companySnapshotEvents } from './agentos';
import { hydrateCompanyView } from './companyHydration';
import { emptyCompanyView, workspaceSchema } from './model';
import { messagesForArea } from './teamAreas';

const companyId = '00000000-0000-4000-8000-000000000001';
const snapshot = {
  summary: { company_id: companyId, revision: 1, artifact_count: 1, status: 'active', brief: null, sources: [], evidence_conflicts: [], verification_findings: [], next_decision: null, artifacts: [], frameworks: [] },
  artifacts: [{
    artifact_id: '00000000-0000-4000-8000-000000000002', company_id: companyId,
    artifact_type: 'research', revision: 1, input_revision: 0, producer: 'researcher',
    status: 'needs_rework', acceptance_status: 'accepted',
    payload: { artifact_type: 'research', summary: 'Research refreshed from the backend.', conflicts: [] },
    founder_statements: [], assumptions: [], measurements: [], sources: [], claims: [],
    verification_findings: [{ code: 'missing_evidence', message: 'Validate demand', severity: 'warning' }],
  }],
};
const researchEvent = companySnapshotEvents(snapshot, companyId).find(event => event.type === 'message' && event.panel?.provenance?.artifact_type === 'research');
if (researchEvent?.type !== 'message' || !researchEvent.panel) throw new Error('Missing research fixture');
const researchPanel = researchEvent.panel;

describe('shared idea snapshot hydration', () => {
  it.each(['research', 'market'] as const)('retains the original %s reply identity while refreshing its canonical panel', aspect => {
    const savedPanel = { ...researchPanel, title: 'Older panel title' };
    const current = workspaceSchema.parse({
      ...emptyCompanyView(), drafts: { research: 'Problem draft', market: 'Market draft' },
      messages: [
        { id: 'problem-question', role: 'user', text: 'Problem question', area: 'research', aspect: 'research' },
        { id: 'market-question', role: 'user', text: 'Market question', area: 'research', aspect: 'market' },
        { id: 'saved-reply', role: 'assistant', text: 'Old result', area: 'research', aspect, backendRunId: 'saved-run', panel: savedPanel },
      ], pinned: [savedPanel],
    });
    const reopened = hydrateCompanyView(current, snapshot, companyId);
    const restored = workspaceSchema.parse(JSON.parse(JSON.stringify(hydrateCompanyView(reopened, snapshot, companyId))));
    const reply = restored.messages.find(message => message.panel?.id === researchPanel.id);
    expect(reply).toMatchObject({ id: 'saved-reply', area: 'research', aspect, backendRunId: 'saved-run', panel: researchPanel });
    expect(messagesForArea(restored, aspect).map(message => message.id)).toContain('saved-reply');
    expect(messagesForArea(restored, aspect === 'market' ? 'research' : 'market').map(message => message.id)).not.toContain('saved-reply');
    expect(restored.messages.filter(message => message.panel?.id === researchPanel.id)).toHaveLength(1);
    expect(restored.pinned.find(panel => panel.id === researchPanel.id)).toEqual(researchPanel);
    expect(restored.drafts).toEqual(current.drafts);
  });

  it('loads uncached and legacy results without inventing an originating aspect', () => {
    const legacy = { ...emptyCompanyView(), messages: [{ id: 'legacy-reply', role: 'assistant' as const, text: '', panel: researchPanel, area: 'research' as const }] };
    for (const current of [emptyCompanyView(), legacy]) {
      const reopened = hydrateCompanyView(current, snapshot, companyId);
      expect(messagesForArea(reopened, 'research').some(message => message.panel?.id === researchPanel.id)).toBe(true);
      expect(messagesForArea(reopened, 'market')).toEqual([]);
    }
    expect(() => hydrateCompanyView(legacy, snapshot, '00000000-0000-4000-8000-000000000003')).toThrow('does not match');
  });
});
