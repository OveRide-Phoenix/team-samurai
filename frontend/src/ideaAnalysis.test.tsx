import { renderToStaticMarkup } from 'react-dom/server';
import { createParser } from '@openuidev/react-lang';
import { describe, expect, it } from 'vitest';
import { fillAspectStartingPoints, ideaAnalysisSchema } from './ideaAnalysis';
import { applyBackendEvent, emptyWorkspace, initialCompanyPrompt, panelSchema, workspaceSchema } from './model';
import { nextAspectQuestion, recordAspectAnswer, aspectQuestions } from './aspectJourney';
import { ideaAnalysisLibrary, OpenUIIdeaAnalysis } from './OpenUIIdeaAnalysis';
import { aspectReadiness } from './teamAreas';

const analysis = ideaAnalysisSchema.parse({ summary: 'A useful hypothesis, with demand still untested.', starting_points: [{ checkpoint_id: 'customer-problem', answer: 'Tutors lose time scheduling lessons.', basis: 'inferred' }, { checkpoint_id: 'minimum-product', answer: 'Test one booking journey.', basis: 'inferred' }] });
const panel = panelSchema.parse({ id: 'intake', kind: 'evidence', title: 'Company brief', note: '', claims: [], idea_analysis: analysis });
describe('mentor starting points', () => {
  it('fills drafts on a backend result, preserves edits and readiness, and resumes at a genuine gap', () => {
    let workspace = applyBackendEvent(emptyWorkspace(), 'r', { type: 'message', text: '', panel });
    expect(workspace.aspectChecks['customer-problem']).toMatchObject({ origin: 'mentor', basis: 'inferred', status: 'in-progress' });
    expect(nextAspectQuestion(workspace)?.id).toBe('demand-evidence');
    expect(aspectReadiness('research', workspace)).toBe('in-progress');
    workspace = recordAspectAnswer(workspace, aspectQuestions[0], 'A corrected founder answer', ['q', 'a']);
    const restored = workspaceSchema.parse(JSON.parse(JSON.stringify(fillAspectStartingPoints(workspace, panel))));
    expect(restored.aspectChecks['customer-problem']).toMatchObject({ note: 'A corrected founder answer', origin: 'founder' });
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
    expect(welcome).toContain('I’m Samurai');
    const html = renderToStaticMarkup(<OpenUIIdeaAnalysis analysis={analysis} pending={false} onAspect={() => undefined} />);
    expect(html.match(/<details>/g)).toHaveLength(6);
    expect(html).toContain('Mentor assumption');
    expect(html).toContain('Needs your input');
    expect(html).toContain('not verified research');
  });
});
