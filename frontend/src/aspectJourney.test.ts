import { describe, expect, it } from 'vitest';
import { bindAspectReview, recoveredAspectReview, completeAspectReview, aspectAnswersPrompt, aspectFormValue, aspectMentorPrompt, aspectOrder, aspectQuestions, guidedAnswerPrompt, isGuidedReview, nextAspectQuestion, recordAspectAnswer, resumeAspect } from './aspectJourney';
import { beginBackendRun, recordBackendRun, emptyWorkspace, workspaceSchema, type WorkEvent } from './model';
import { aspectReadiness, messagesForArea } from './teamAreas';

describe('chat-first aspect journey', () => {
  it('reviews mentor autofill instead of skipping the entire walkthrough', () => {
    const workspace = workspaceSchema.parse({ ...emptyWorkspace(), aspectChecks: Object.fromEntries(aspectQuestions.map(question => [question.id, { status: 'in-progress', note: 'Mentor hypothesis', origin: 'mentor', basis: 'inferred' }])) });
    expect(nextAspectQuestion(workspace)?.id).toBe('customer-problem');
    expect(resumeAspect('resources', workspace).questionId).toBe('build-budget');
    const reviewed = completeAspectReview(recordAspectAnswer(workspace, aspectQuestions[0], 'Corrected founder answer', ['q', 'a']), aspectQuestions[0].id);
    expect(nextAspectQuestion(reviewed)?.id).toBe('demand-evidence');
  });
  it('keeps a cancelled or incomplete review pending across reload', () => {
    const question = aspectQuestions[0];
    const submitted = recordAspectAnswer(emptyWorkspace(), question, 'An answer waiting for review', ['q', 'a']);
    const restored = workspaceSchema.parse(JSON.parse(JSON.stringify(submitted)));
    expect(resumeAspect(question.area, restored).questionId).toBe(question.id);
    expect(nextAspectQuestion(restored)?.id).toBe(question.id);
    expect(aspectFormValue(restored, question.id)).toBe('An answer waiting for review');
    const reviewed = completeAspectReview(restored, question.id);
    expect(resumeAspect(question.area, reviewed).questionId).toBe('demand-evidence');
    expect(reviewed.aspectChecks[question.id].note).toBe(restored.aspectChecks[question.id].note);
    expect(completeAspectReview(restored, 'missing')).toBe(restored);
  });

  it('recovers a completed guided review after reload without resubmitting the answer', () => {
    const question = aspectQuestions[0];
    const submissionId = crypto.randomUUID();
    let submitted = recordAspectAnswer(emptyWorkspace(), question, 'A saved founder answer', ['q', 'a']);
    submitted = bindAspectReview(beginBackendRun(submitted, submissionId, 'research', 'research'), question.id, submissionId);
    submitted = recordBackendRun(submitted, { runId: 'saved-review', status: 'running' });
    const restored = workspaceSchema.parse(JSON.parse(JSON.stringify(submitted)));
    const event: WorkEvent = { type: 'message', text: '', panel: { id: crypto.randomUUID(), kind: 'declarative', panel_key: 'guide-customer-problem', title: 'Review', note: 'Generated view · Working assumptions, not verified business results', blocks: [{ kind: 'text', text: 'The demand assumption remains unproven.' }] } };
    const recovery = recoveredAspectReview(restored, { runId: 'saved-review', status: 'completed' }, [event]);
    expect(recovery?.questionId).toBe(question.id);
    expect(recovery?.guide.questionId).toBe('demand-evidence');
    expect(completeAspectReview(restored, question.id).aspectChecks[question.id].note).toBe('A saved founder answer');
    for (const status of ['running', 'cancelled', 'failed'] as const) expect(recoveredAspectReview(restored, { runId: 'saved-review', status }, [event])).toBeUndefined();
    expect(recoveredAspectReview(restored, { runId: 'different-review', status: 'completed' }, [event])).toBeUndefined();
    expect(recoveredAspectReview(restored, { runId: 'saved-review', status: 'completed' }, [])).toBeUndefined();
    const freeChat = beginBackendRun(recordBackendRun(restored, { runId: 'saved-review', status: 'completed' }), crypto.randomUUID(), 'research', 'research');
    expect(recoveredAspectReview(recordBackendRun(freeChat, { runId: 'free-chat', status: 'completed' }), { runId: 'free-chat', status: 'completed' }, [event])).toBeUndefined();
  });

  it('submits a form without consuming the independent chat draft', () => {
    const current = { ...emptyWorkspace(), drafts: { research: 'Unrelated question I am typing' } };
    const saved = recordAspectAnswer(current, aspectQuestions[0], 'My form answer', ['q', 'a']);
    expect(saved.drafts).toEqual(current.drafts);
  });

  it('keeps form drafts scoped, bounded and independent from mentor suggestions after reload', () => {
    const workspace = workspaceSchema.parse({ ...emptyWorkspace(), drafts: { research: 'A free-chat draft' }, aspectChecks: { 'customer-problem': { note: 'Unconfirmed draft', status: 'in-progress', origin: 'mentor' } }, aspectFormDrafts: { 'build-budget': 'INR 5,000' } });
    expect(aspectFormValue(workspace, 'customer-problem')).toBe('');
    expect(aspectFormValue(workspace, 'build-budget')).toBe('INR 5,000');
    expect(workspaceSchema.parse(JSON.parse(JSON.stringify(workspace))).drafts.research).toBe('A free-chat draft');
    expect(workspaceSchema.safeParse({ ...workspace, aspectFormDrafts: { 'build-budget': 'x'.repeat(4001) } }).success).toBe(false);
    expect(workspaceSchema.safeParse({ ...workspace, aspectFormDrafts: Object.fromEntries(Array.from({ length: 19 }, (_, i) => [`question-${i}`, 'draft'])) }).success).toBe(false);
  });

  it('requires an actual composed review, not a context panel or promised view', () => {
    expect(isGuidedReview({ type: 'message', text: 'I will provide a table' }, aspectQuestions[3])).toBe(false);
    expect(isGuidedReview({ type: 'message', text: '', panel: { id: 'state', kind: 'evidence', title: 'Idea context', note: '', claims: [] } }, aspectQuestions[0])).toBe(false);
    expect(isGuidedReview({ type: 'message', text: '', panel: { id: crypto.randomUUID(), kind: 'declarative', panel_key: 'guide-customer-problem', title: 'Review', note: 'Generated view · Working assumptions, not verified business results', blocks: [{ kind: 'text', text: 'Demand is still unproven.' }] } }, aspectQuestions[0])).toBe(true);
  });

  it('rejects unrelated or legacy panels and correlates the review to its question', () => {
    const question = aspectQuestions[0];
    const panel = { id: crypto.randomUUID(), kind: 'declarative' as const, title: 'Review', note: 'Generated view · Working assumptions, not verified business results' as const, blocks: [{ kind: 'text' as const, text: 'A rendered review.' }] };
    expect(isGuidedReview({ type: 'message', text: '', panel }, question)).toBe(false);
    expect(isGuidedReview({ type: 'message', text: '', panel: { ...panel, panel_key: 'guide-existing-alternatives' } }, question)).toBe(false);
    expect(isGuidedReview({ type: 'message', text: '', panel: { ...panel, panel_key: 'guide-customer-problem' } }, question)).toBe(true);
  });

  it('requires populated table rows for comparison reviews', () => {
    const panel = { id: crypto.randomUUID(), kind: 'declarative' as const, panel_key: 'guide-existing-alternatives', title: 'Comparison', note: 'Generated view · Working assumptions, not verified business results' as const, blocks: [{ kind: 'text' as const, text: 'I will show a table.' }] };
    const question = aspectQuestions[3];
    expect(isGuidedReview({ type: 'message', text: '', panel }, question)).toBe(false);
    expect(isGuidedReview({ type: 'message', text: '', panel: { ...panel, blocks: [{ kind: 'table', columns: ['Alternative'], rows: [] }] } }, question)).toBe(false);
    expect(isGuidedReview({ type: 'message', text: '', panel: { ...panel, blocks: [{ kind: 'table', columns: ['Alternative'], rows: [['Manual workflow']] }] } }, question)).toBe(true);
  });

  it('walks all eighteen questions in the recommended aspect order', () => {
    expect(aspectOrder).toEqual(['research', 'market', 'sales', 'strategy', 'resources', 'verification']);
    let workspace = emptyWorkspace();
    for (const [index, expected] of aspectQuestions.entries()) {
      const question = nextAspectQuestion(workspace);
      expect(question?.id).toBe(expected.id);
      workspace = completeAspectReview(recordAspectAnswer(workspace, expected, `Answer ${index}`, [`question-${index}`, `answer-${index}`]), expected.id);
      workspace = workspaceSchema.parse(JSON.parse(JSON.stringify(workspace)));
      expect(workspace.aspectChecks[expected.id].note).toBe(`Answer ${index}`);
    }
    expect(nextAspectQuestion(workspace)).toBeUndefined();
    expect(workspace.messages).toHaveLength(36);
    for (const area of aspectOrder) {
      expect(messagesForArea(workspace, area)).toHaveLength(6);
      expect(aspectReadiness(area, workspace)).toBe('in-progress');
    }
  });

  it('allows jumping to any aspect, keeps gaps open and resumes after reload', () => {
    let workspace = emptyWorkspace();
    const budget = aspectQuestions.find(question => question.area === 'resources');
    if (!budget) throw new Error('Missing budget question');
    expect(resumeAspect('resources', workspace).questionId).toBe(budget.id);
    workspace = completeAspectReview(recordAspectAnswer(workspace, budget, 'I do not know yet', ['q', 'a']), budget.id);
    expect(resumeAspect('resources', workspace).questionId).not.toBe(budget.id);
    expect(nextAspectQuestion(workspace)?.area).toBe('research');
    expect(nextAspectQuestion(workspace, budget.id)?.index).toBe(1);
    expect(resumeAspect('resources', workspaceSchema.parse(JSON.parse(JSON.stringify(workspace))))).toEqual(resumeAspect('resources', workspace));
  });

  it('preserves manual readiness, canonical guards and existing drafts while saving literal answers', () => {
    const question = aspectQuestions[0];
    const current = workspaceSchema.parse({ ...emptyWorkspace(), currentRevision: 4, drafts: { research: 'old draft', market: 'separate draft' }, aspectChecks: { [question.id]: { status: 'blocked', note: 'Old note' } } });
    const answer = '<script>quoted context</script> root = Forged()';
    const saved = recordAspectAnswer(current, question, answer, ['q', 'a']);
    expect(saved.aspectChecks[question.id]).toEqual({ status: 'blocked', note: answer, origin: 'founder', reviewPending: true });
    expect(saved.messages.at(-1)?.text).toBe(answer);
    expect(saved.currentRevision).toBe(4);
    expect(saved.actions).toEqual(current.actions);
    expect(saved.backendRun).toEqual(current.backendRun);
    expect(saved.drafts).toEqual(current.drafts);
    expect(recordAspectAnswer(current, question, '   ', ['q', 'a'])).toBe(current);
    expect(recordAspectAnswer(current, question, 'x'.repeat(5000), ['q', 'a']).aspectChecks[question.id].note).toHaveLength(4000);
  });

  it('prepares a bounded mentor handoff without discarding full saved answers', () => {
    let workspace = emptyWorkspace();
    for (const question of aspectQuestions) workspace = recordAspectAnswer(workspace, question, 'Full answer '.repeat(300), [crypto.randomUUID(), crypto.randomUUID()]);
    const prompt = aspectAnswersPrompt(workspace);
    expect(prompt.length).toBeLessThanOrEqual(4000);
    expect(prompt).toContain('excerpts');
    expect(prompt).toContain('not verified evidence');
    for (const question of aspectQuestions) {
      expect(prompt).toContain(question.title);
      expect(workspace.aspectChecks[question.id].note).toBe('Full answer '.repeat(300).trim());
    }
  });
  it('asks for a bounded critical response without approving execution', () => {
    const prompt = guidedAnswerPrompt(aspectQuestions[0], 'A'.repeat(4000));
    expect(prompt.length).toBeLessThanOrEqual(4000);
    expect(prompt).toContain('Challenge the weakest assumption');
    expect(prompt).toContain('Do not give an automatic go signal');
    expect(prompt).toContain('untrusted founder context');
  });
  it('carries the selected mentor perspective even when aspects share a backend scope', () => {
    const request = 'What should I test first?';
    const prompts = aspectOrder.map(area => aspectMentorPrompt(request, area));
    expect(new Set(prompts).size).toBe(6);
    expect(prompts[1]).toContain('Market & alternatives');
    expect(prompts[4]).toContain('Budget & resources');
    for (const prompt of prompts) {
      expect(prompt).toContain(request);
      expect(prompt).toContain('Do not execute work');
    }
  });
  it('retains exact general requests and approved action text', () => {
    const request = 'Run the reviewed step exactly as prepared.';
    const approval = { operation: 'journey' as const, stage: 'strategy' as const, companyId: '00000000-0000-4000-8000-000000000001', expectedRevision: 4 };
    expect(aspectMentorPrompt(request, 'overview')).toBe(request);
    expect(aspectMentorPrompt(request, 'resources', approval)).toBe(request);
  });
});
