import { describe, expect, it } from 'vitest';
import { aspectAnswersPrompt, aspectMentorPrompt, aspectOrder, aspectQuestions, guidedAnswerPrompt, nextAspectQuestion, recordAspectAnswer, resumeAspect } from './aspectJourney';
import { emptyWorkspace, workspaceSchema } from './model';
import { aspectReadiness, messagesForArea } from './teamAreas';

describe('chat-first aspect journey', () => {
  it('walks all eighteen questions in the recommended aspect order', () => {
    expect(aspectOrder).toEqual(['research', 'market', 'sales', 'strategy', 'resources', 'verification']);
    let workspace = emptyWorkspace();
    for (const [index, expected] of aspectQuestions.entries()) {
      const question = nextAspectQuestion(workspace);
      expect(question?.id).toBe(expected.id);
      workspace = recordAspectAnswer(workspace, expected, `Answer ${index}`, [`question-${index}`, `answer-${index}`]);
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
    workspace = recordAspectAnswer(workspace, budget, 'I do not know yet', ['q', 'a']);
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
    expect(saved.aspectChecks[question.id]).toEqual({ status: 'blocked', note: answer, origin: 'founder' });
    expect(saved.messages.at(-1)?.text).toBe(answer);
    expect(saved.currentRevision).toBe(4);
    expect(saved.actions).toEqual(current.actions);
    expect(saved.backendRun).toEqual(current.backendRun);
    expect(saved.drafts).toMatchObject({ research: '', market: 'separate draft' });
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
