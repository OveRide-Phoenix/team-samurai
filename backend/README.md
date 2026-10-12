# Backend

Owns the server-side behavior for **AI Idea → Company**. Read the root [AGENTS.md](../AGENTS.md) and [logical architecture](../README.md#logical-architecture) first.

## Responsibilities

- Authenticate requests and enforce company access and authorization for consequential actions.
- Coordinate research, strategy, product work, building, marketing, sales, analysis, and verification around shared company state.
- Integrate Gemini and approved tools; retain evidence, decisions, artifact lineage, and explicit uncertainties.
- Persist work status, approvals, results, and business measurements, and expose structured data to the frontend.
- Execute authorized integrations and jobs with observable success and failure outcomes.

## Selected stack and status

Python 3.14, Agno AgentOS, Gemini, Pydantic, and PostgreSQL. See [the architecture decision](../docs/architecture.md) and [backend contributor instructions](AGENTS.md). Exact versions are pinned in `pyproject.toml` and `uv.lock`.

When a Gemini model is configured, the current source registers one ordinary AgentOS agent, `samurai`, named **Samurai**. It is the only founder-facing agent; specialist agents are internal workflow executors. Its four bounded tools are `run_company_journey`, `create_launch_drafts`, `analyze_metrics`, and `read_company_state`. The model does not choose arbitrary role or workflow IDs, and trusted `RunContext` supplies user, parent session, child-session binding, company, and revision.

`run_company_journey` invokes the explicit intake → brief check → research → evidence check → strategy → product plan → verification workflow. `create_launch_drafts` runs Builder, Marketer, and Sales only after verified strategy and product inputs, and creates drafts only. `analyze_metrics` accepts eligible provenance-labelled metrics; founder-supplied metrics remain conditional and unverified. `read_company_state` returns a summary of canonical state for the current parent session. None of these tools sends, publishes, spends, contacts prospects, runs ads, or deploys.

The parent session stores only `child_session_id`, `company_id`, and `current_revision`. The deterministic child workflow session owns canonical `CompanyState`: a backend-generated company ID and a contiguous, accepted artifact history. Every artifact records its input revision, producer, status, founder statements, assumptions, sources, claims, measurements where applicable, and verification findings. Stale or mismatched context is rejected before state changes.

Intake, Strategist, Product Manager, and Verifier preload the validated `evidence-discipline` and `action-boundaries` skill text and expose no runtime function tools. Researcher uses native Gemini Search only. Builder, Marketer, Sales, and Analyst have only the local read-only `get_skill_instructions`, `get_skill_reference`, and `get_skill_script` functions. The parent loads the same validated local skills but bounds inspection to instructions and references. None of these skill surfaces adds external execution authority. Prompts live in `src/samurai/prompts/`; these runtime skills are separate from contributor OMo/Ponytail skills.

Each child workflow has a deadline of `GEMINI_TIMEOUT_SECONDS * 7` (420 seconds at the default 60-second timeout). On timeout, the parent cancels and drains child runs. Parent and child model calls are capped at `AGENT_TOOL_CALL_LIMIT + 1` (five at the default limit of four), and child failures are surfaced as sanitized typed errors rather than provider detail.

Local onboarding validation at `d6d05fb` passed `task check`: 141 backend tests, Ruff, formatting, and basedpyright, plus the frontend check, type generation, and build. Separately, authenticated parent API checks cover parent registration, run reads, restart/recall, owner isolation, input rejection, sanitized errors, the five-artifact core journey, and conditional metrics analysis. The API primary retained three unique grounded sources and nine propagated references; claims remained unverified and verification returned `needs_rework`. The metrics child completed revision 6 with all seven fields, founder-supplied provenance, no connector receipt, and `based_on_founder_supplied_metrics`.

The final real TCP cancellation regression observed streamed child progress, returned cancellation in about 20 ms, persisted both parent and child as `CANCELLED`, emptied the active registry, and prevented a late artifact. Chrome independently completed the fictional five-artifact primary, state recall, and reload persistence. These are local acceptance results. No live launch-draft generation, push, deployment, or external action is claimed. See [setup verification](../docs/setup-verification.md) for the detailed evidence boundary and [the parent-agent plan](../.omo/plans/samurai-parent-agents.md) for the acceptance scenarios.

## Local setup

From the repository root, run:

```sh
task setup
task backend:dev
```

`task setup` installs locked Python dependencies, creates only missing root and backend `.env` files at owner-only permissions, and validates that their database credentials match. It never prints or replaces secrets. `task backend:dev` checks port 8000, starts only Samurai's PostgreSQL service, and runs Uvicorn in the foreground. `task health` checks PostgreSQL and `GET /agentos/health` without a model call. In shared-key mode, `GET /agentos/config` accepts `Authorization: Bearer <OS_SECURITY_KEY>`; when `JWT_VERIFICATION_KEY` is configured, use a valid user JWT instead. Use `/agentos/docs` for the installed API schema.

Set `GOOGLE_API_KEY` only when ready to call Gemini. The tracked default remains `gemini-3.8-flash`; a lower-cost local experiment may set `GEMINI_MODEL=gemini-3.5-flash-lite` in ignored `backend/.env`. Never commit that file. See [local development](../docs/local-development.md) for the full command reference and JWT test surface.

## Cloud Run preparation

The [GCP deployment guide](../docs/gcp-deployment.md) records the reviewed container,
production JWT guard, Cloud SQL socket contract, and required Cloud Run inputs. The
configuration, focused local tests, static checks, and final Linux/amd64 image build are
verified. The equivalent initial image returned health 200 and rejected unauthenticated
configuration access; the final-source image did not accept a local ARM-emulated loopback
probe before cleanup. Private native Cloud Run revision `samurai-backend-00001-9mx` then
proved IAM health access, IAM-only configuration rejection, and configuration access with
the temporary bootstrap application JWT. An approved bounded `run_company_journey` parent
run completed with `gemini-3.5-flash-lite`; an owner-scoped `COMPLETED` readback proved its
Cloud SQL-backed record. That run does not prove expected business artifacts for the full
workflow. Agno sign-in/connection registration, production-key rotation, and private JWT
validation remain pending; public transport is disabled and browser acceptance follows its
controlled transition.
The full local suite also has a cancellation timeout reproduced unchanged at base commit
`14d47c2a70fd29999c0ca0ccacbd182e714dbc63`; it is not treated as a deployment-change pass.

The runtime disables automatic database provisioning on startup so liveness/configuration checks work without a database. AgentOS creates required tables on its normal database write paths. Starting the process alone does not prove persistence. Use Cloud SQL and controlled schema management for deployment; do not expose this shared-key bootstrap publicly.

Use `task db:status`, `task db:logs`, and `task db:stop` from the root for Samurai-only database lifecycle actions. `db:stop` preserves the volume; do not use `down -v` unless deleting this project's local database is intended.

### Podman connection verification

On 11 October 2026, the initial Mac connection timeout was resolved by restarting only `team-samurai_postgres_1`. Host queries, persisted workflow sessions, and a history-aware follow-up after an application restart passed. The shared Podman VM and unrelated containers were not changed. If the same forwarding issue recurs, inspect the named project container before changing shared infrastructure.

## AgentOS control plane

Use the in-built browser or a separate Chrome window for Samurai testing; preserve the Reporting test window. Add a separate **Samurai Local** connection at `https://os.agno.com` using `http://localhost:8000/agentos`. Do not edit another project's connection.

The control-plane connection uses JWT authorization. Enable it for the new connection and put its **public** verification key in a quoted multiline `JWT_VERIFICATION_KEY` value in `backend/.env`, then restart the backend. The server uses RS256 verification, native Agno scope checks, and user isolation. JWT configuration replaces shared-key authentication; `OS_SECURITY_KEY` is not accepted as a JWT. Never paste the Google key into AgentOS. JWT unit checks use temporary test keys; the real Samurai control-plane public key is now installed in the ignored local environment.

Earlier browser attempts failed with `ERR_BLOCKED_BY_CLIENT` and a hosted connection-creation 403. A later Chrome retry using `localhost:8000/agentos` succeeded: Agno created Samurai Local, issued its public key, and authenticated discovery displayed the workflow and all three starter prompts. The earlier failure's precise cause was not established. No unauthenticated fallback or public tunnel was needed.

## Frontend boundary

Agree request/result shapes, identity and company scope, work status, evidence and artifact references, errors, and approval transitions before integration. Keep backend secrets server-side and enforce permissions even when the frontend has already checked them. Treat model and tool outputs as untrusted inputs to validation.

## Development and verification

```sh
uv run ruff check src tests
uv run ruff format --check src tests
uv run basedpyright
uv run pytest
```

Tests isolate configuration and verify AgentOS authentication without a Google key or running database. Report real PostgreSQL and Gemini checks separately. Settings read `.env` relative to the working directory, so run commands from `backend/`. Never commit credentials or use the service key as browser authentication.

## Route isolation and Reporting reference

AgentOS is mounted at `/agentos` in a parent FastAPI application. Its authentication,
CORS, discovery, agent/session endpoints and API docs stay inside that mount.
The parent explicitly runs the child lifespan so startup and shutdown are preserved.
Root-level `/config`, `/workflows`, and `/health` are not AgentOS endpoints.
This uses FastAPI's [sub-application pattern](https://fastapi.tiangolo.com/advanced/sub-applications/).

The active Reporting reference uses `/agentos` on port 8311, explicit child lifespan,
custom bearer/JWT handling, private-network CORS, and domain-specific APIs. Samurai
keeps port 8000 and native Agno authentication. Its JWT mode intentionally rejects
the shared key. Reporting's custom authentication, queues, AG-UI integration and
business routes are not prerequisites for this foundation and were not copied.
The path change does not prove that Agno's hosted connection-creation 403 is fixed.
