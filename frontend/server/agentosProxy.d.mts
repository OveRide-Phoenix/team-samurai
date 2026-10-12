import type { IncomingMessage, ServerResponse } from 'node:http';
export function agentosProxy(root: string, fetchImpl?: typeof fetch): (req: IncomingMessage, res: ServerResponse, next: () => void) => Promise<void>;
