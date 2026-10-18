import { expect, it } from 'vitest';
import { createCopilotStart } from './copilotkit';
import { HttpAgent } from '@ag-ui/client';
import { CopilotKitCoreReact } from '@copilotkit/react-core/v2/context';

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

it.each([['SAMURAI_USAGE_LIMIT', '00:00 UTC'], ['SAMURAI_QUEUE_FULL', 'queue is full'], ['SAMURAI_RATE_LIMIT', 'Try again later']])('preserves typed admission rejection %s through the real AG-UI client', async (code, message) => {
  const core = new CopilotKitCoreReact({ runtimeUrl: 'https://samurai.example/api/copilotkit', deferInitialConnection: true });
  const agent = new HttpAgent({ agentId: 'samurai', url: 'https://samurai.example/agui', fetch: async () => new Response('data: '+JSON.stringify({ type: 'RUN_ERROR', code, message: 'PRIVATE_UPSTREAM_DETAIL' })+'\n\n', { headers: { 'content-type': 'text/event-stream' } }) });
  const response = await createCopilotStart(core, agent, 'company')('Review idea', new AbortController().signal);
  await expect(response.text()).rejects.toMatchObject({ code: 'admission', message: expect.stringContaining(message) });
});
