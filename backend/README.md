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

The runtime exposes one conversational workflow, `company-foundation`, named **Samurai — Build My Business**, when `GOOGLE_API_KEY` is configured. Its native Agno `WorkflowAgent` routes new ideas and revisions through two ordered steps: draft a typed company brief, then deterministically check its structure and missing context. Follow-ups can use stored workflow history without rerunning the steps.

The internal brief agent loads the instruction-only `company-intake` and `evidence-discipline` skills from `src/samurai/skills/`. Prompts live in `src/samurai/prompts/`; AgentOS exposes three starter prompts. These runtime skills are separate from contributor OMo/Ponytail skills. The main agent and brief agent have independent model instances for nested streaming.

The result always reports `evidence_status=unverified`: schema validation is not research or market validation. Grounded research, strategy, launch kits, business record schemas, Cloud Storage, and production company authorization remain later phases. See [the foundation plan](../docs/agentos-foundation-plan.md).

## Local setup

1. In the repository root, copy `.env.example` to `.env` if it does not exist. Generate a local `POSTGRES_PASSWORD` with `openssl rand -hex 24`.
2. With the Podman machine running, run `uv tool run --from podman-compose podman-compose up -d` from the root. The native provider avoids dependence on a Docker compatibility socket. The database listens only on `127.0.0.1:54329`; its named volume preserves data across container restarts. The image comes from the Docker Official Images ECR mirror.
3. In `backend/`, copy `.env.example` to `.env` if it does not exist. Set `DATABASE_URL` using the root password and generate `OS_SECURITY_KEY` with `openssl rand -hex 32`. Local files already generated for this checkout must not be overwritten.
4. Set `GOOGLE_API_KEY` when ready to call Gemini. Leave it blank for setup-only checks. `GEMINI_MODEL` can be changed explicitly; its default is `gemini-3.8-flash`.
5. Run:

```sh
uv sync --locked
uv run uvicorn samurai.app:create_app --factory --app-dir src --host 127.0.0.1 --port 8000
```

`GET /agentos/health` is liveness only. `GET /agentos/config` requires `Authorization: Bearer <OS_SECURITY_KEY>`. Use AgentOS's OpenAPI docs at `/agentos/docs` to inspect the actual locked API. Model calls may incur costs; the setup checks do not make them.

The runtime disables automatic database provisioning on startup so liveness/configuration checks work without a database. AgentOS creates required tables on its normal database write paths. Starting the process alone does not prove persistence. Use Cloud SQL and controlled schema management for deployment; do not expose this shared-key bootstrap publicly.

Stop only this project's database with `uv tool run --from podman-compose podman-compose stop` from the root. Do not use `down -v` unless deleting this project's local database is intended.

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
CORS, discovery, workflow/session endpoints and API docs stay inside that mount.
The parent explicitly runs the child lifespan so startup and shutdown are preserved.
Root-level `/config`, `/workflows`, and `/health` are no longer AgentOS endpoints.
This uses FastAPI's [sub-application pattern](https://fastapi.tiangolo.com/advanced/sub-applications/).

The active Reporting reference uses `/agentos` on port 8311, explicit child lifespan,
custom bearer/JWT handling, private-network CORS, and domain-specific APIs. Samurai
keeps port 8000 and native Agno authentication. Its JWT mode intentionally rejects
the shared key. Reporting's custom authentication, queues, AG-UI integration and
business routes are not prerequisites for this foundation and were not copied.
The path change does not prove that Agno's hosted connection-creation 403 is fixed.
