# Local development

This guide starts only Samurai's local services. It preserves existing private configuration, PostgreSQL data, Reporting on port 8311, and unrelated Podman workloads. It does not deploy, push, or make external business actions.

## Prerequisites

Install [Task](https://taskfile.dev/), `uv`, and Podman with a running machine. Node.js and npm are required only for the frontend UI. Run commands from the repository root.

`Taskfile.yml` pins `podman-compose` 1.6.0 through `uv tool run`; no system-wide compose installation is required.

## Start and check the backend

```sh
task setup
task backend:dev
```

`task setup` installs locked backend dependencies, creates missing root `.env` and `backend/.env` files with owner-only permissions, and validates that they share the same database password. Existing files are preserved and secret values are never printed.

`task backend:dev` checks that port 8000 is free, starts only the Samurai PostgreSQL and Redis coordination services without recreating them, and runs Uvicorn in the foreground on `127.0.0.1:8000`. Redis binds only to `127.0.0.1:16379`; if another local process has that port, startup stops with a named error before it starts a Samurai Redis container. Stop the server with Ctrl-C. In another terminal:

```sh
task health
task db:status
```

The verified local health path is `http://127.0.0.1:8000/agentos/health`. It proves the local PostgreSQL and Redis services and backend process are reachable without a Gemini call; it does not prove a provider response or a product workflow.

If settings do not match the private files you just validated, stale shell exports can override dotenv values. Unset the relevant inherited `POSTGRES_PASSWORD`, `DATABASE_URL`, authentication, or model variable in that terminal, then rerun the Task command. Do not print the environment while troubleshooting.

## Database lifecycle

```sh
task db:up
task db:status
task db:logs
task db:stop
```

These commands operate only on Samurai's PostgreSQL service. `db:up` waits for health and uses `--no-recreate`; repeating it keeps the existing container and volume. `db:stop` preserves data. Do not use `down -v` unless intentionally deleting Samurai's database, and do not use these commands for Reporting.

## Redis coordination lifecycle

```sh
task redis:up
task redis:status
task redis:logs
task redis:stop
```

These commands operate only on Samurai's Redis coordination service and its
`redis-data` volume. They do not stop or recreate Reporting or other Podman
services. The pinned image is the official Redis 8.8.0 Alpine multi-architecture
digest through the public ECR Docker mirror. Redis is started for local health
checks, but `QUEUE_ENABLED=false` remains the default.

Setting `QUEUE_ENABLED=true` requires a nonblank `REDIS_URL`; local setup and
runtime validation fail clearly when it is absent. They never replace that
missing coordination with a process-local queue. The default local URL is
`redis://127.0.0.1:16379/0` and should remain private to this checkout.

To isolate Redis coordination for another Samurai checkout, add a free
`REDIS_PORT` value to that checkout's ignored root `.env` before its first
`task setup`. Compose binds that port and first-time setup writes the matching
private `REDIS_URL` into its new `backend/.env`. Existing environment files are
preserved; change their Redis URL deliberately rather than expecting setup to
overwrite it. Set `SAMURAI_COMPOSE_PROJECT` to a unique value for that Redis
Compose project. PostgreSQL remains on its documented `54329` host port and
is not concurrently isolated by this Redis override.

## Provider-free recovery checks

GitHub Actions runs recovery tests against disposable PostgreSQL 18 and Redis
services over service DNS, with no Gemini or other provider credentials. To run
the same focused suite locally, point `SAMURAI_TEST_DATABASE_URL` at an isolated
disposable PostgreSQL database and set `REDIS_URL` to Samurai's isolated Redis
service, then run:

```sh
task recovery:check
```

Do not point this command at a shared, Reporting, or production database. It
does not create, overwrite, or delete environment files or existing volumes.

## Workspace files

Authenticated workspace members use the private routes under
`/agentos/samurai/workspaces/{workspace_id}/files`. Owners and editors can
upload and delete; viewers can list and download ready files. Uploads accept
one file plus an optional same-workspace `company_id`, with a 10 MiB limit and
the allowlisted text, Markdown, CSV, JSON, and PDF types. Responses expose
metadata and hashes without storage paths or public URLs.

Local objects live below `STORAGE_ROOT` (default `.samurai-storage`). Deleting a
file releases its logical workspace quota immediately, while unshared physical
bytes remain for the seven-day retention window. Size local disk for that
retention headroom. Owner cleanup is workspace-scoped; it does not expose the
global maintenance functions or accept a client-supplied clock.

For a provider-free loopback check, start the migrated backend with a temporary
RS256 verification key, then run `backend/scripts/smoke_founder_platform.py`
with the matching private signing key. The script creates synthetic owner,
editor, viewer, and cross-workspace principals and verifies upload, list,
download headers and bytes, denied mutation, oversized rejection, deletion,
and empty scoped cleanup. Use only a disposable PostgreSQL schema and remove
the temporary key, storage directory, schema, and server after the check.

## Frontend UI preview

```sh
task frontend:setup
task frontend:dev
```

The founder UI runs at `http://127.0.0.1:4173/` from `frontend/`. It includes onboarding, chat, panels, and the company dashboard with labelled preview data. Frontend setup only needs Node/npm and does not start the backend or database. The former Next.js `/api/health` scaffold is removed. New companies use authenticated native AgentOS through the local Vite proxy; existing/sample companies remain Preview. Prerequisites come from the backend, and Team shows actual workflow step history. Live Gemini intake/research and saved-result recovery were exercised locally, with research stopping at missing source evidence. Production IAP authentication and the Node proxy were verified against recorded deployed revisions; that historical result does not show that the current local source is deployed. Source-supported live strategy and launch drafts remain pending.

## Frontend-to-AgentOS contract

The implemented frontend integration uses the installed AgentOS OpenAPI reference at `http://127.0.0.1:8000/agentos/docs` as its route source of truth and keeps the backend as the authorization boundary. Its server-side route sends `POST /agentos/agents/samurai/runs` as form data with `message`, `session_id`, and `stream`, with the verified user JWT in `Authorization: Bearer <token>`. Reuse the same `session_id` for a company rather than treating browser state as company state.

For streaming journeys, consume the SSE lifecycle and use the returned run identifier with the authenticated run-read and cancel routes under `/agentos/agents/samurai/runs/{run_id}`. Handle terminal completion, errors, and cancellation before rendering a final result; do not infer completion from a connection closing. The backend enforces user isolation and validates the request body, so the frontend must not send framework-owned context or bypass the backend with a direct model call.

`BACKEND_URL` is reserved and is not consumed by the current UI preview. Do not put `OS_SECURITY_KEY`, `GOOGLE_API_KEY`, JWT verification configuration, or user bearer tokens in `VITE_` or other browser-exposed variables.

## Checks

```sh
task check
```

This runs the backend formatter, lint, type check, and tests, then the frontend checks and build. It performs locked dependency setup first and may take longer than `task health`. Local onboarding validation at `d6d05fb` completed this command successfully: 141 backend tests, Ruff, formatting, basedpyright, and the frontend check, type generation, and build passed.

## Gemini and JWT AgentOS connection

Setup and health checks do not need Gemini. For an approved local Gemini run, put `GOOGLE_API_KEY` only in ignored `backend/.env`; never put it in a browser, screenshot, log, or committed file. The model is locked to `gemini-3.5-flash-lite`; no automatic fallback is configured.

To connect a new technical-console session:

1. Start `task backend:dev` and open `https://os.agno.com` in a separate Samurai task window.
2. Add a local operating-system connection at `http://localhost:8000/agentos` and enable JWT authorization.
3. Copy only the issued **public** verification key into the quoted `JWT_VERIFICATION_KEY` value in ignored `backend/.env`, then restart `task backend:dev`.
4. Return to the connection and confirm that **Samurai** and its starter prompts are visible before running a test prompt.

Use a quoted multiline PEM value, with no private key or token:

```dotenv
JWT_VERIFICATION_KEY="-----BEGIN PUBLIC KEY-----
REPLACE_WITH_THE_ISSUED_PUBLIC_KEY
-----END PUBLIC KEY-----"
```

JWT configuration takes precedence over shared-key authentication: when it is configured, `OS_SECURITY_KEY` is not accepted as a bearer credential. Keep both values private in ignored local files. Never expose a Google key to AgentOS or treat the connection as a public deployment.

## AgentOS technical-console check

The local AgentOS endpoint is `http://localhost:8000/agentos`. The verified technical-console path showed one Samurai agent and three starter prompts, a saved five-artifact journey, and retained-state recall. The console currently presents raw structured JSON. It is test evidence, not the planned custom founder UI.

Use this approved fictional brief once the JWT connection and Gemini key are ready:

> Build my business: an AI receptionist for independent Indian dental clinics in India. Budget INR 50000; founder skills Python and Next.js; goal validate demand in 30 days.

The honest expected result is a revisioned journey with retained sources and visible verification findings. Claims can remain unverified and verification can return `needs_rework`; neither outcome is a failure to hide. Follow with: “What customer, budget, founder skills, evidence conflicts, and next decision did we retain?” A retained answer should read saved company state rather than rerun the journey.

Use an approved test brief only. Keep keys, account details, and private founder data out of screenshots. The three baseline screenshots are untracked local evidence; they are deliberately not linked or embedded in repository documentation.

## Status and plans

[The plan index](../.omo/plans/README.md) distinguishes portable completed work from the current local onboarding plan. New runtime boulders, ledgers, screenshots, and evidence remain local-only; already tracked historical records are retained.

### Local UI integration — 11 October 2026

New companies use native AgentOS SSE through the Vite server proxy. Configure `AGENTOS_USER_TOKEN` in ignored `frontend/.env.local` and the matching `JWT_VERIFICATION_KEY` in ignored `backend/.env`; restart the backend after changing its configuration. `GEMINI_MODEL` is locked to `gemini-3.5-flash-lite`, with no fallback. The original 2.5 Flash-Lite request returned HTTP 404 for this new account. The user then authorized 3.5 Flash-Lite on 12 October; verify its access separately. Existing and dental-demo companies retain Preview mode. Never call fixture tests proof of successful Gemini research. The static production build contains no proxy; live use requires the existing production proxy/auth integration and an authorized deployment.

Google Search grounding is disabled in this free-tier 3.5 Flash-Lite runtime. Research without citations remains insufficient evidence; no paid search or billing was enabled.
