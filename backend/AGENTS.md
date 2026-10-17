# Backend contributor guide

Read [../AGENTS.md](../AGENTS.md) and [README.md](README.md). Use `agno:agno`, `omo:programming`, and Ponytail; use `omo:debugging` for runtime issues. Consult current Agno documentation through Context7 and verify the installed API before copying examples.

- Python 3.14, uv, Agno AgentOS, Gemini, and PostgreSQL are the selected stack. Register only the ordinary `Samurai` parent Agent for founders; use the existing internal Agno Workflows for the software-idea journey, drafts, and metrics analysis. The product is a mentor and validator for apps, websites and software enhancements; do not expand it into general company execution.
- Keep typed configuration at the boundary, secrets server-side, and structured agent outputs validated with Pydantic.
- Keep the parent session limited to the child-session/company/revision binding. The child workflow session owns canonical state and artifact lineage; do not pre-create a service per role or widen the four bounded parent tools.
- Keep Intake, Strategist, Product Manager, and Verifier on preloaded validated skill text with no runtime function tools; keep native Gemini Search limited to Researcher under the bounded Flash-Lite policy. Builder, Marketer, Sales, Analyst, and the parent may use bounded local read-only skill inspection, never external action tools.
- Preserve the child deadline at seven configured model timeouts, cancellation-and-drain behavior, model cap at tool-call budget plus one, and sanitized typed workflow errors. Do not claim queue-backed resumability from persisted sessions.
- Maintain the accepted local boundaries: parent/core journeys preserve unverified claims and `needs_rework`, founder metrics remain conditional, cancellation must stop and drain both runs without late artifacts, and launch drafts remain untested live and draft-only.
- Run Ruff, basedpyright, pytest, and a real HTTP smoke check. Database and Gemini proof must be reported separately.
- Start local backend work from the repository root with `task backend:dev`; use `task health` and the Samurai-only `task db:*` commands for checks and lifecycle. Preserve existing `.env` files, volumes, and Reporting services.
- Shared bearer access is for local development. Add identity, company isolation, and action authorization before public access.
- Keep `.env` ignored; document configuration in `.env.example`. Never include key values or database URLs with passwords in logs or handoffs.

### Superseded model configuration — 12 October 2026
The temporary `gemini-3.8-flash` restoration is historical context only. The paid-account Flash-Lite policy below supersedes it; do not restore 3.8 from this record.

### Paid-account Flash-Lite testing — 12 October 2026
The user funded the API account and now requests `gemini-3.5-flash-lite` with native Google Search. This supersedes the preceding 3.8 restoration and temporary no-call instruction. Keep all roles on Flash-Lite and enable Search only for Researcher. Initial live verification is one bounded research call; do not launch bulk/full-journey tests without discussing measured cost. Billing allowance and tax are estimates until confirmed in the account. Keep the local backend stopped outside explicitly requested testing to avoid accidental charges.

The native queue implementation (`201f0f7`, formatted at `aa07b46`) and Task 8's independently reviewed local PostgreSQL/Redis restore scenario establish bounded local durable recovery. Task 7 terminal UI evidence (`1a4c6a9`), Task 10's provider-free readiness runner (`76c9884`), and Task 9's provider-free local acceptance (`1f841e7`) are also locally accepted. Task 9's combined check has 233 backend tests passed with 26 PostgreSQL tests intentionally skipped and separately covered, not an authorized GitHub Actions run. Do not describe those local results as Cloud Run deployment, Cloud SQL recovery, or a provider-backed business run: `a84c718` and `571a378` prepare those external steps only. The user deferred the paid cloud queue upgrade; Task 11 remains deferred and unverified while local founder work continues.

Founder-paced journey: native `run_company_journey` defaults to `stage="brief"`. Explicit research, strategy, and plan stages stop at their respective boundaries; incomplete context and source gates remain enforced. The UI offers one next-stage action and suppresses repeated artifacts by retained ID/revision. Tests use deterministic models; no additional paid provider run was made for this refinement.

### CopilotKit presentation boundary — 13 October 2026
Expose the existing Samurai parent through the authenticated scoped AG-UI route `/agentos/agents/samurai/agui`. Its permission remains `agents:samurai:run`, with owner checks before streaming and a fresh model per request. Only one text user turn is accepted; reject client-supplied tools, state, dependencies, identity and resumptions. Saved runs and cancellation continue through native AgentOS routes. PostgreSQL turns must enter the existing native durable queue before forwarding acceptance; preserve worker ownership, immutable work approval, cancellation, receipt recovery and the real PostgreSQL/Redis HTTP regressions. The inline path remains read-only for lightweight non-PostgreSQL fixtures; reject explicit work approval with HTTP 503 rather than running approved work without a durable worker.

The four business tools remain; `compose_panel` and `create_custom_panel` add bounded presentation only. Validate compositions and custom source with Pydantic, use owner/session-scoped stable panel IDs, and persist their results in the parent run. They do not update canonical company artifacts or evidence. In Agno 3.1.2, nested Pydantic tool annotations are mistaken for injected parameters: expose the explicit compose schema, accept plain block input and validate it at the presentation boundary. Keep the real Agno tool-execution regression. All generated views remain drafts, regardless of attached sources.


### Software-idea mentoring aspects — 17 October 2026

The six UI aspects reuse the existing five `team_area` wire values: Idea maps to `overview`; Problem & demand and Market & alternatives map to `research`; Product & technology and Budget & resources map to `strategy`; Sales & distribution maps to `sales`; Validation & delivery maps to `verification`. Preserve these IDs, API contracts, saved data and backend journey. They are conversation scopes, not separate agent chats or new services.

Every aspect is independently discussable. Missing research, technical choices, budget or another aspect must not block read-only mentoring. Show assumptions and evidence gaps as soft links; `suggest_team_area` is an optional suggestion and never switches areas or executes work. Ordinary chat can read owned state and compose draft views without completing upstream stages. Do not claim those views verify demand, costs or delivery.

The only other allowed forwarded property is bounded `work_approval` (operation, stage, expected_revision and company_id); validate it independently against authenticated canonical state before native queue admission. Reject every other forwarded property. Turns without explicit work approval are read-only. This never supplies identity, dependencies, canonical state or expanded JWT permissions. Keep the owned parent/child company binding, native cancellation and originating area in run metadata.

Preserve all existing execution guards: strategy requires complete supported research; delivery planning requires strategy; sales drafts require verified inputs. The verification-only stage reads existing state and never runs upstream stages; missing execution prerequisites return `needs_input`. These are saved-work gates, not mentoring gates. Read-only state includes the latest artifact of each type. Scoped `read_company_state` continues within the existing call cap; workflow and optional handoff tools stop the run.
