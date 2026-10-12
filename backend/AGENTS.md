# Backend contributor guide

Read [../AGENTS.md](../AGENTS.md) and [README.md](README.md). Use `agno:agno`, `omo:programming`, and Ponytail; use `omo:debugging` for runtime issues. Consult current Agno documentation through Context7 and verify the installed API before copying examples.

- Python 3.14, uv, Agno AgentOS, Gemini, and PostgreSQL are the selected stack. Register only the ordinary `Samurai` parent Agent for founders; use explicit internal Agno Workflows for the company journey, drafts, and metrics analysis.
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

Current readiness integration has not accepted durable queue, reconnect, or cloud recovery behavior. Do not describe those active workstreams as complete from local setup, compatibility, or prior deployment evidence.

Founder-paced journey: native `run_company_journey` defaults to `stage="brief"`. Explicit research, strategy, and plan stages stop at their respective boundaries; incomplete context and source gates remain enforced. The UI offers one next-stage action and suppresses repeated artifacts by retained ID/revision. Tests use deterministic models; no additional paid provider run was made for this refinement.
