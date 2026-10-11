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
4. **Blocked on hosted connection creation:** sign-in and manual local health
   succeed, but Agno's hosted `POST /api/v1/operating-systems/` returns 403, as
   shown by the user's DevTools capture. No JWT public key has been installed.
   Resolve the hosted access failure, then complete local JWT and UI acceptance.
5. **Partial:** native tracing is enabled and HTTP traces persist. Workflow/session
   correlation is not observed with the installed instrumentation; use stored run
   events for step/skill evidence. This is not a claim of complete trace coverage.

## Next implementation sequence

1. Finish the local browser connection once localhost access is available. Install
   Samurai's own public verification key, verify starter prompts, run a new idea,
   reload its session, and ask a follow-up. Preserve the existing Reporting connection.
2. Add typed research evidence and Gemini Search grounding. Store source URLs,
   timestamps, supported claims, conflicting evidence, and explicit uncertainty.
3. Add strategy and product-plan steps consuming that evidence, followed by a
   verifier that checks source support and asks for unresolved decisions.
4. Add marketing/sales launch-kit drafts and the founder workspace. Keep sending,
   publishing, spending, and deploying behind explicit action authorization.
5. Add company-scoped access, Cloud SQL/Storage, and a verified Cloud Run deployment.
   Decide on durable execution only when background jobs require restart recovery.

Keep configuration exact and locked; verify official APIs before upgrades. OMo and
Ponytail remain contributor skills, not runtime agent instructions. All foundation
work belongs to `Kalyan/agentos-foundation`; commit locally and push only on request.
