# AgentOS foundation and next steps

OMo planning selected one user-facing `WorkflowAgent`, not seven exposed agents.
Agno restricts its WorkflowAgent to orchestration and history, so native runtime
skills belong to the internal brief agent. This follows the official
[conversational workflow example](https://docs.agno.com/examples/agent-os/serving-workflows/with-workflow-agent)
and [skills example](https://docs.agno.com/examples/agent-os/skills/basic).

## Current foundation

1. **Done:** `company-foundation` accepts a new idea or revision through the main
   agent, drafts a typed `CompanyBrief`, and runs deterministic structural checks.
2. **Done:** instruction-only intake/evidence skills, separate prompt assets, three
   starter prompts, ordered step events, PostgreSQL sessions, and history follow-ups.
3. **Done:** local bearer access, optional RS256 JWT scope enforcement with user
   isolation, restricted CORS, offline checks, and live API verification.
4. **Done:** Samurai Local was created in a
   separate Chrome window at `localhost:8000/agentos`. Its public key is configured
   locally; JWT discovery, starter prompts and workflow WebSocket access succeed.
   Request-scoped workflow construction prevents provider-model reuse across runs.
   Three consecutive starter runs completed 2/2, and registered cancellation settled
   visibly and as `CANCELLED` in PostgreSQL with tracing still enabled. An independent
   JWT SSE request also completed both ordered steps and persisted `COMPLETED`.
5. **Partial:** native tracing is enabled and HTTP traces persist. Workflow/session
   correlation is not observed with the installed instrumentation; use stored run
   events for step/skill evidence. This is not a claim of complete trace coverage.

## Next implementation sequence

1. Add typed research evidence and Gemini Search grounding. Store source URLs,
   timestamps, supported claims, conflicting evidence, and explicit uncertainty.
2. Add strategy and product-plan steps consuming that evidence, followed by a
   verifier that checks source support and asks for unresolved decisions.
3. Add marketing/sales launch-kit drafts and the founder workspace. Keep sending,
   publishing, spending, and deploying behind explicit action authorization.
4. Add company-scoped access, Cloud SQL/Storage, and a verified Cloud Run deployment.
   Decide on durable execution only when background jobs require restart recovery.

Keep configuration exact and locked; verify official APIs before upgrades. OMo and
Ponytail remain contributor skills, not runtime agent instructions. All foundation
work belongs to `Kalyan/agentos-foundation`; commit locally and push only on request.
