import { useEffect, useMemo, type ReactNode } from 'react';
import { useAgent } from '@copilotkit/react-core/v2/headless';
import { CopilotKitContext, CopilotKitCoreReact, useCopilotKit } from '@copilotkit/react-core/v2/context';
import { createCopilotStart } from './copilotkit';
import type { CopilotStart } from './agentos';

type Start = CopilotStart;
type Props = { companyId: string; children: (start: Start | undefined, error?: string) => ReactNode };
const headers = { 'X-Samurai-Client': '1' };
const executingToolCallIds = new Set<string>();
function Connection({ companyId, children }: Props) {
  const { copilotkit } = useCopilotKit();
  const { agent, isReady } = useAgent({ agentId: 'samurai' });
  const start = useMemo(() => createCopilotStart(copilotkit, agent, companyId), [copilotkit, agent, companyId]);
  return children(isReady ? start : undefined, copilotkit.runtimeConnectionStatus === 'error' ? 'Proofseed could not connect. Reload to try again.' : undefined);
}
export default function CopilotCompany(props: Props) {
  // The public headless context preserves Proofseed's existing chat without loading a second chat UI.
  const copilotkit = useMemo(() => new CopilotKitCoreReact({ runtimeUrl: '/api/copilotkit', headers, credentials: 'same-origin', runtimeTransport: 'single', deferInitialConnection: true }), []);
  useEffect(() => { copilotkit.connect(); }, [copilotkit]);
  const context = useMemo(() => ({ copilotkit, executingToolCallIds, showIntelligenceIndicator: false }), [copilotkit]);
  return <CopilotKitContext.Provider value={context}><Connection {...props} /></CopilotKitContext.Provider>;
}
