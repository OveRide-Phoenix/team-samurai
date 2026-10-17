import { z } from 'zod';
import type { Panel, Workspace } from './model';

export const checkpointIdSchema = z.enum(['customer-problem', 'demand-evidence', 'riskiest-assumption', 'existing-alternatives', 'market-opportunity', 'differentiation', 'first-buyers', 'distribution', 'willingness-to-pay', 'minimum-product', 'technical-feasibility', 'data-and-security', 'build-budget', 'skills-and-team', 'running-costs', 'validation-experiment', 'implementation-roadmap', 'release-and-learning']);
export const ideaAnalysisSchema = z.strictObject({
  summary: z.string().min(1).max(800),
  starting_points: z.array(z.strictObject({ checkpoint_id: checkpointIdSchema, answer: z.string().trim().min(1).max(2000), basis: z.enum(['provided', 'inferred']) })).max(18),
}).refine(value => new Set(value.starting_points.map(point => point.checkpoint_id)).size === value.starting_points.length);
export type IdeaAnalysis = z.infer<typeof ideaAnalysisSchema>;

export function fillAspectStartingPoints(workspace: Workspace, panel?: Panel): Workspace {
  if (!panel || !('idea_analysis' in panel) || !panel.idea_analysis) return workspace;
  const aspectChecks = { ...workspace.aspectChecks };
  for (const point of panel.idea_analysis.starting_points) {
    if (aspectChecks[point.checkpoint_id]?.note.trim()) continue;
    aspectChecks[point.checkpoint_id] = { note: point.answer, status: aspectChecks[point.checkpoint_id]?.status ?? 'in-progress', origin: 'mentor', basis: point.basis };
  }
  return { ...workspace, aspectChecks };
}

export function latestIdeaAnalysis(workspace: Workspace): IdeaAnalysis | undefined {
  for (const { panel } of workspace.messages.slice().reverse()) {
    if (panel && 'idea_analysis' in panel && panel.idea_analysis) return panel.idea_analysis;
  }
  return undefined;
}
