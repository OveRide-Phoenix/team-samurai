import { expect, it } from 'vitest';
import { createCopilotStart } from './copilotkit';

it('carries one stable submission and bounded approval through CopilotKit', async () => {
  const approval = { operation: 'journey', stage: 'brief', expectedRevision: 0, companyId: '00000000-0000-4000-8000-000000000003' } as const;
  let emit: ((value: { event: { name: string; value: object } }) => void) | undefined;
  const agent = { setState() {}, setMessages() {}, abortRun() {},
    subscribe(callbacks: { onCustomEvent: typeof emit }) { emit = callbacks.onCustomEvent; return { unsubscribe() {} }; },
  } as unknown as Parameters<typeof createCopilotStart>[1];
  const core = { async runAgent(options: { runId: string; forwardedProps: object }) {
    expect(options.runId).toBe('00000000-0000-4000-8000-000000000004');
    expect(options.forwardedProps).toEqual({ team_area: 'research', work_approval: { operation: 'journey', stage: 'brief', expected_revision: 0, company_id: approval.companyId } });
    emit?.({ event: { name: 'samurai', value: { event: 'RunCompleted' } } });
  } } as unknown as Parameters<typeof createCopilotStart>[0];
  const response = await createCopilotStart(core, agent, 'company')('Build my company', new AbortController().signal, 'research', approval, '00000000-0000-4000-8000-000000000004');
  expect(await response.text()).toContain('RunCompleted');
});
