import { z } from 'zod';

export const teamAreaSchema = z.enum(['overview', 'research', 'strategy', 'verification', 'sales']);
export const workflowAreaSchema = z.enum(['research', 'market', 'sales', 'strategy', 'resources', 'verification']);
export const ideaAreaSchema = workflowAreaSchema.or(z.literal('overview'));
export type IdeaAspect = z.infer<typeof workflowAreaSchema>;
export type IdeaArea = IdeaAspect | 'overview';
export const checkpointStatusSchema = z.enum(['in-progress', 'ready', 'blocked']);
export type CheckpointStatus = z.infer<typeof checkpointStatusSchema>;
export const readinessLabels = { ready: 'Ready', 'in-progress': 'In progress', blocked: 'Blocked' } as const;
export const aspectChecksSchema = z.record(z.string().min(1).max(80), z.strictObject({
  status: checkpointStatusSchema,
  note: z.string().max(4000),
  origin: z.enum(['mentor', 'founder']).optional(),
  reviewPending: z.boolean().optional(),
  reviewSubmissionId: z.string().uuid().optional(),
  basis: z.enum(['provided', 'inferred']).optional(),
})).refine(checks => Object.keys(checks).length <= 18, 'At most eighteen checkpoints can be saved').default({});

export const aspectFormDraftsSchema = z.record(z.string().min(1).max(80), z.string().max(4000))
  .refine(drafts => Object.keys(drafts).length <= 18, 'At most eighteen form drafts can be saved').optional();
