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

The bootstrap exposes AgentOS health and authenticated runtime APIs. A `researcher` agent is registered only when `GOOGLE_API_KEY` is non-empty. It has no research tools yet and does not claim grounded research. The company workflow, verifier, business schemas, Cloud Storage integration, and end-user/company authorization are planned.

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

`GET /health` is liveness only. `GET /config` requires `Authorization: Bearer <OS_SECURITY_KEY>`. Use AgentOS's OpenAPI docs at `/docs` to inspect the actual locked API. Model calls may incur costs; the setup checks do not make them.

The runtime disables automatic database provisioning on startup so liveness/configuration checks work without a database. AgentOS creates required tables on its normal database write paths. Starting the process alone does not prove persistence. Use Cloud SQL and controlled schema management for deployment; do not expose this shared-key bootstrap publicly.

Stop only this project's database with `uv tool run --from podman-compose podman-compose stop` from the root. Do not use `down -v` unless deleting this project's local database is intended.

### Current Mac verification limit

On 11 October 2026, PostgreSQL 18.6 was healthy in Podman 6.0.2/libkrun and accepted authenticated TCP queries inside its container. Connections from this Mac through `127.0.0.1:54329` timed out, so host-to-database persistence is **not verified**. The mapping remains localhost-only, and no shared VM or unrelated containers were restarted. Resolve the local forwarding issue before running database-backed agent work. Process health and authentication checks remain usable independently.

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
