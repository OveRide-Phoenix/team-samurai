# Setup verification — 11 October 2026

## Scope note

The entries below preserve prior foundation evidence. They do not verify the evolving `Kalyan/parent-agent` source. The parent-agent status is recorded separately so a previous workflow, API, or UI result is not presented as acceptance of the new parent Agent.

## Parent-agent increment — current status

### Implemented in the current source, pending acceptance

- With a configured Gemini model, AgentOS source registers one ordinary founder-facing agent, `samurai`; the nine internal roles are Intake, Researcher, Strategist, Product Manager, Builder, Marketer, Sales, Analyst, and Verifier.
- The parent exposes four bounded tools: `run_company_journey`, `create_launch_drafts`, `analyze_metrics`, and `read_company_state`. Parent context binds an authenticated user and parent session to a deterministic child workflow session; canonical company state and contiguous artifact revisions live in the child session.
- The core workflow is intake → brief check → research → evidence check → strategy → product plan → verification. Builder, Marketer, and Sales create reviewable drafts only. Analyst requires provenance-labelled metrics and labels founder-supplied inputs as conditional.
- Source lineage retains Gemini Search source references, excerpts, claim mappings, conflicts, assumptions, and verification findings. A retained citation is not factual verification. No parent or child tool can send, publish, spend, contact prospects, run ads, or deploy.

### Locally verified before the parent changes

- 85 combined backend tests passed before parent registration and boundary changes. This is a baseline, not evidence that the new parent API or boundary suite passes.
- Task 5's real Gemini Search smoke retained three sources. Task 6's core journey has offline confirmation.

### Focused parent checks now passing

- 14 native HTTP/JWT boundary tests and eight parent/application tests pass.
- A two-process local Uvicorn/SQLite restart retained the brief and evidence with no child workflow rerun.
- The current full suite reports 101 passing tests. Two failures remain unresolved: sandbox local-port permission and an unnamed native-workflow/global-tracing interaction.

These focused checks and the partial full-suite result do not establish a full-suite pass, full API acceptance, or AgentOS UI acceptance.

### Pending or blocked

- The approved post-fix live core journey ran and stopped at evidence verification with zero retained sources, `insufficient_evidence`, and partial artifacts. It did not satisfy journey acceptance. Skills advertising tools while Google Search disables external tools is a confirmed structural contradiction; the fix and live-journey rerun remain pending.
- The final full parent check, AgentOS UI, SSE, cancellation, and deployment acceptance remain pending. This document does not claim full API or end-to-end acceptance.
- No merge, push, deployment, external action, or Reporting change is claimed.

## Passed locally

- Backend: Ruff lint/format, basedpyright with zero diagnostics, and three pytest checks covering unauthorized discovery, authorized discovery, and rejection of an empty service key.
- Python lockfile matches the manifest (`uv lock --check`).
- Frontend: Biome, Next.js route type generation, TypeScript, and production build.
- Live backend HTTP: `/health` returned 200; `/config` returned 401 without credentials and 200 with the configured bearer key.
- Live frontend HTTP: `/api/health` returned 200 and an unsupported POST returned 405.
- Podman: isolated PostgreSQL 18.6 container healthy; authenticated TCP `SELECT 1` succeeded inside the container.
- Gemini: the configured key listed 62 models through the Google GenAI SDK. One direct `generate_content` request to `gemini-3.8-flash` returned `Samurai connection OK` (8 prompt, 4 output, 100 thinking tokens; 112 total). Credentials were not printed or committed. This verifies direct SDK access, not the AgentOS/database workflow.
- YAML and local documentation links validated; Git whitespace checks passed.
- Local environment files are ignored by Git with owner-only permissions. npm's generated lockfile omits machine-specific registry URLs; no registry credentials are committed.
- Code remains small: the application factory owns runtime configuration, and the frontend route owns liveness. No type-assertion escapes or custom orchestration abstractions were introduced.

## Limits and observations

- The initial Mac-to-Podman timeout was resolved during foundation work by restarting only Samurai's PostgreSQL container. Host queries and actual workflow persistence now pass.
- Gemini model discovery, generation, and the foundation workflow passed. Search grounding and Google Cloud deployment remain unverified.
- The frontend has no product screen yet. shadcn/ui and React visual-development tooling are documented for the next UI phase, not installed or presented as implemented UI.
- GitHub Actions and Dependabot configuration were prepared locally, not run or activated on GitHub. Setup changes are being committed on `Kalyan/project-setup`; no push or deployment was performed.
- Google GenAI emitted an upstream Python deprecation warning concerning `_UnionGenericAlias`; tests passed. Next.js noted an unrelated ancestor lockfile outside this repository and correctly ignored it.
- Editor LSP servers were unavailable; project-local type checkers and linters were run instead.
- Temporary app servers were stopped after checks. The project PostgreSQL container and its named volume remain available; existing Reporting containers and the shared Podman VM were left running.

## AgentOS foundation verification

- The initial setup was fast-forward merged into local `main`; foundation work is on `Kalyan/agentos-foundation`. No push occurred.
- Seven offline tests pass, covering bearer authentication, invalid configuration, workflow discovery/starter prompts/CORS, invalid brief rejection, unverified evidence retention, and JWT mode rejecting the shared key while accepting a signed test identity. Ruff and strict basedpyright pass.
- A live non-streaming Gemini-backed AgentOS request completed both ordered steps. Stored executor data shows both native skill instruction calls succeeded.
- After an application restart, the same session recalled the supplied INR 50,000 budget and 30-day goal with zero steps rerun.
- A live SSE run with separate model instances completed `WorkflowAgentStarted → WorkflowStarted → StepStarted/StepCompleted → WorkflowCompleted → WorkflowAgentCompleted`. The partial brief identified missing budget, skills, and goal and retained `evidence_status=unverified`.
- A final streaming run with tracing enabled also completed both steps and persisted run `5ea062e9-292e-4777-a4a0-3d16c591eaa9`. Earlier shared-model streaming attempts stalled and were cancelled; independent model instances are retained for the nested agents.
- Native tracing stores HTTP trace records, but no session-linked workflow traces were observed. Stored run events and executor outputs provide the verified workflow evidence; complete trace correlation remains unverified.
- In-built browser sign-in succeeded. Automated direct navigation initially reported `ERR_BLOCKED_BY_CLIENT`; the user subsequently opened `http://127.0.0.1:8000/health` manually and obtained status `ok`. A later automated CONNECT attempt still returned to the form without saving or reaching Samurai. The user then supplied DevTools evidence: `POST https://os-api.agno.com/api/v1/operating-systems/` returned **403 Forbidden**, with an HTML response and `Server: awselb/2.0`. This identifies the hosted connection-creation request as the failure; headers alone do not establish the account or infrastructure cause. The JWT public key was not obtained and UI acceptance remains blocked. JWT enablement is approved. Chrome and existing Reporting settings were untouched.
- Live workflow error paths returned 401 without authentication and 422 for a missing message. The lockfile check passed.
- JWT checks use temporary generated test keys, not a claim of real Agno account authorization. No long-term memory, search grounding, durable queue, or production tenant security was introduced.

## AgentOS namespace verification

- Read the active `Plan Fusion skills agent flow` and `Reporting — single-report workflow` sessions and inspected their referenced Reporting implementation without modifying it. Reporting mounts `/agentos` and explicitly enters the child runtime lifespan; Samurai now follows that pattern.
- Samurai connection URL: `http://localhost:8000/agentos`. Reporting remains `http://localhost:8311/agentos`.
- Eight tests, Ruff and basedpyright passed. Tests cover mounted bearer/JWT access, CORS, OpenAPI's `/agentos` server URL, and a parent-owned route remaining outside AgentOS authentication.
- Real HTTP checks: `/agentos/health` 200; `/agentos/config` 401 without credentials and 200 with credentials; mounted workflow discovery 200; missing workflow message 422. Root `/config`, `/health`, and `/workflows` returned 404. Startup and shutdown completed cleanly.
- Updated the frontend backend-base template and ignored local configuration. No credentials were staged. The temporary Samurai server was stopped; Reporting was unchanged.
- The installed Agno OpenAPI generator emits a duplicate `get_config` operation-ID warning; the schema request succeeds. Google GenAI's existing Python deprecation warning also remains.
- This increment did not rerun paid model generation or resolve the hosted Agno 403. The real control-plane JWT key and UI acceptance are still pending. Reporting also explicitly enables private-network CORS; that is a separate browser-access consideration, not evidence explaining the hosted 403.


## Real JWT connection acceptance

- A later retry at `http://localhost:8000/agentos` in a separate Chrome window successfully created **Samurai Local** with JWT enabled. The prior hosted 403 did not recur; its exact original cause remains unknown.
- Installed the issued public verification key only in ignored `backend/.env` (mode 600). JWT remains RS256 with native user isolation; the Google key and database password were not entered into Agno.
- The UI showed **Samurai Local Active**, the main workflow and all three starter prompts. Server logs confirmed authenticated config/workflow discovery returned 200 and the workflow WebSocket was accepted.
- The initial dental-clinic starter run remained at 0/2 with a static registered workflow whose request copies shared Gemini model objects. Agno's documented `WorkflowFactory` now constructs the workflow and model per request; no authentication or tracing setting was weakened.
- Three consecutive JWT UI starter runs visibly reached **2 out of 2 steps done** and persisted `COMPLETED` with both step results. A fourth run cancelled after registration settled within two seconds to “Run … was cancelled” / “Cancelled during execution” and persisted `CANCELLED`.
- An independent JWT HTTP/SSE request returned 200, emitted both ordered `StepCompleted` events and `WorkflowCompleted`, and persisted `COMPLETED` with two step results and non-zero Gemini usage.
- Direct isolation reproduced one success followed by a provider-response timeout when reusing a model client, while two fresh-model runs completed. This supports request-scoped model/client construction as the mechanism boundary; it does not claim that the correlated OpenTelemetry attribute-cap warnings caused the stall.
- Nine backend tests, Ruff lint/format, strict basedpyright, and the lockfile check pass on the fix commit. The dependency lock is unchanged.
- Non-JWT fallback was unnecessary because JWT authentication succeeded. No backend authentication was disabled. Reporting's connection and runtime were not changed.
- The task-created Chrome tab and temporary Samurai process were closed after testing. The saved Agno connection remains available; the copied worktree `.env` was removed, while the source checkout `.env` remained untouched and mode 600.
