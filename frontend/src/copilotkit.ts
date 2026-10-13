import type { AbstractAgent } from '@ag-ui/client';
import type { CopilotKitCoreReact } from '@copilotkit/react-core/v2/context';

// Feed CopilotKit's authenticated AG-UI events into the retained workspace/recovery adapter.
export function createCopilotStart(core: CopilotKitCoreReact, agent: AbstractAgent, sessionId: string) {
  return async (input: string, signal: AbortSignal): Promise<Response> => {
    agent.threadId = sessionId;
    agent.setState({});
    agent.setMessages([{ id: crypto.randomUUID(), role: 'user', content: input }]);
    let unsubscribe: (() => void) | undefined;
    const stream = new ReadableStream<Uint8Array>({ start(controller) {
      let closed = false;
      let terminal: unknown;
      const abort = () => agent.abortRun();
      signal.addEventListener('abort', abort, { once: true });
      const subscription = agent.subscribe({
        onCustomEvent({ event }) {
          if (event.name !== 'samurai' || closed) return;
          const value = event.value as { event?: string };
          if (value.event === 'RunCompleted' || value.event === 'RunCancelled') terminal = event.value;
          else controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event.value)}\n\n`));
        },
        onRunErrorEvent() { if (!closed) { closed = true; controller.error(new Error('Samurai could not complete this run.')); } },
      });
      unsubscribe = () => subscription.unsubscribe();
      void core.runAgent({ agent, runId: crypto.randomUUID() }).then(() => {
        if (!closed) {
          if (terminal) controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(terminal)}\n\n`));
          closed = true; controller.close();
        }
      }).catch(() => {
        if (!closed) { closed = true; controller.error(new Error('Samurai could not complete this run.')); }
      }).finally(() => { signal.removeEventListener('abort', abort); unsubscribe?.(); });
    }, cancel() { unsubscribe?.(); agent.abortRun(); } });
    return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } });
  };
}
