import { renderToStaticMarkup } from 'react-dom/server';
import { createParser } from '@openuidev/react-lang';
import { describe, expect, it } from 'vitest';
import { fillAspectStartingPoints, ideaAnalysisSchema } from './ideaAnalysis';
import { applyBackendEvent, emptyWorkspace, initialCompanyPrompt, panelSchema, workspaceSchema } from './model';
import { completeAspectReview, nextAspectQuestion, recordAspectAnswer, aspectQuestions, aspectOrder } from './aspectJourney';
import { ideaAnalysisLibrary, OpenUIIdeaAnalysis } from './OpenUIIdeaAnalysis';
import { aspectReadiness } from './teamAreas';
import { aspectCatalog } from './ideaAspectCatalog';

const analysis = ideaAnalysisSchema.parse({ summary: 'A useful hypothesis, with demand still untested.', starting_points: [{ checkpoint_id: 'customer-problem', answer: 'Tutors lose time scheduling lessons.', basis: 'inferred' }, { checkpoint_id: 'minimum-product', answer: 'Test one booking journey.', basis: 'inferred' }] });
const panel = panelSchema.parse({ id: 'intake', kind: 'evidence', title: 'Company brief', note: '', claims: [], idea_analysis: analysis });
describe('mentor starting points', () => {
  it('fills drafts on a backend result, preserves edits and readiness, and asks the founder to review inferred drafts', () => {
    let workspace = applyBackendEvent(emptyWorkspace(), 'r', { type: 'message', text: '', panel });
    expect(workspace.aspectChecks['customer-problem']).toMatchObject({ origin: 'mentor', basis: 'inferred', status: 'in-progress' });
    expect(nextAspectQuestion(workspace)?.id).toBe('customer-problem');
    expect(aspectReadiness('research', workspace)).toBe('in-progress');
    workspace = completeAspectReview(recordAspectAnswer(workspace, aspectQuestions[0], 'A corrected founder answer', ['q', 'a']), aspectQuestions[0].id);
    const restored = workspaceSchema.parse(JSON.parse(JSON.stringify(fillAspectStartingPoints(workspace, panel))));
    expect(restored.aspectChecks['customer-problem']).toMatchObject({ note: 'A corrected founder answer', origin: 'founder' });
    expect(nextAspectQuestion(restored)?.id).toBe('demand-evidence');
    expect(restored.actions).toEqual([]);
    expect(restored.currentRevision).toBeUndefined();
  });
  it('rejects duplicate, unknown, oversized and falsely verified answers', () => {
    const point = analysis.starting_points[0];
    for (const starting_points of [[point, point], [{ ...point, checkpoint_id: 'invented' }], [{ ...point, answer: 'x'.repeat(2001) }], [{ ...point, basis: 'verified' }]]) expect(ideaAnalysisSchema.safeParse({ ...analysis, starting_points }).success).toBe(false);
    const prompt = initialCompanyPrompt({ idea: 'A booking app for tutors', customer: '', location: '', budget: '', goal: '' });
    expect(prompt).toContain('"budget":null');
    expect(prompt).toContain('Do not run research');
  });
  it('renders the greeting and all six expandable OpenUI aspects with honest labels', () => {
    const parsed = createParser(ideaAnalysisLibrary.toJSONSchema(), ideaAnalysisLibrary.root).parse('root = IdeaFirstPass({"pending":true})');
    expect(parsed.meta.errors).toEqual([]);
    const welcome = renderToStaticMarkup(<OpenUIIdeaAnalysis pending onAspect={() => undefined} />);
    expect(welcome).toContain('I’m Proofseed');
    const html = renderToStaticMarkup(<OpenUIIdeaAnalysis analysis={analysis} pending={false} onAspect={() => undefined} />);
    expect(html.match(/<details>/g)).toHaveLength(6);
    expect(html).toContain('Mentor assumption');
    expect(html).toContain('Needs your input');
    expect(html).toContain('not verified research');
  });
  it('explains each prefilled aspect before any disclosure is opened', () => {
    // Given an intake with every aspect drafted, in a different order from the journey.
    const starting_points = aspectOrder.flatMap(area => aspectCatalog[area].checkpoints.map((check, index) => ({ checkpoint_id: check.id, answer: `Draft for ${check.id}`, basis: index === 0 ? 'provided' : 'inferred' }))).reverse();
    const complete = ideaAnalysisSchema.parse({ ...analysis, starting_points });
    // When the first mentor reply renders.
    const html = renderToStaticMarkup(<OpenUIIdeaAnalysis analysis={complete} pending={false} onAspect={() => undefined} />);
    const recaps = [...html.matchAll(/<section class="analysis-aspect"[^>]*>([\s\S]*?)<\/section>/g)];
    // Then all six recaps explain their actual draft outside the closed details.
    expect(recaps).toHaveLength(6);
    aspectOrder.forEach((area, index) => {
      const visible = recaps[index]?.[1]?.split('<details>')[0] ?? '';
      expect(visible).toContain(`Draft for ${aspectCatalog[area].checkpoints[0]?.id}`);
      expect(visible).toContain('data-basis="provided"');
      expect(visible).toContain('3 / 3 drafted');
    });
  });
  it('explains partial drafts and leaves empty aspects visibly open for input', () => {
    // Given an intake with a later checkpoint only, including untrusted answer text.
    const partial = ideaAnalysisSchema.parse({ ...analysis, starting_points: [{ checkpoint_id: 'demand-evidence', answer: '<script>unverified</script>', basis: 'inferred' }] });
    // When the first mentor reply renders.
    const html = renderToStaticMarkup(<OpenUIIdeaAnalysis analysis={partial} pending={false} onAspect={() => undefined} />);
    const recaps = [...html.matchAll(/<section class="analysis-aspect"[^>]*>([\s\S]*?)<\/section>/g)];
    // Then its draft is visible and escaped; the other five aspects have questions, not invented answers.
    const visible = recaps.map(recap => recap[1]?.split('<details>')[0] ?? '');
    expect(visible[0]).toContain('&lt;script&gt;unverified&lt;/script&gt;');
    expect(visible[0]).toContain('data-basis="inferred"');
    expect(visible.filter(recap => recap.includes('data-basis="unknown"'))).toHaveLength(5);
    expect(visible.filter(recap => recap.includes('0 / 3 drafted'))).toHaveLength(5);
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('<details open');
  });
});
