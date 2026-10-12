# Samurai backend deployment on Google Cloud

This is the deployment guide for the existing Gemini-backed Samurai AgentOS backend. The
Cloud Run backend is deployed with public transport and JWT-protected application routes; the frontend, local Podman data, and durable
background work are outside this deployment.

## Target and prerequisites

Use the confirmed project and region:

- Project: `samurai-ai-company-2026`
- Region: `asia-south1`
- Service: `samurai-backend`
- Runtime service account: `samurai-runtime@samurai-ai-company-2026.iam.gserviceaccount.com`
- Cloud SQL connection: `samurai-ai-company-2026:asia-south1:samurai-postgres`

## Current revision

As verified on 12 October 2026, the native Linux/amd64 revision serves 100% of traffic
with public transport for Agno Live and RS256 JWT protection on application routes:

- Revision: `samurai-backend-00002-p4s`
- Service URL: `https://samurai-backend-590733583260.asia-south1.run.app`
- Image: `asia-south1-docker.pkg.dev/samurai-ai-company-2026/samurai/samurai-backend@sha256:ea7ad0802e3f33a2ece0312b7258f055175aef926f208bb2b9abd63e0e2d8ba8`
- Source commit: `dad101bb1b0e59c993802ca1c0338b4ef6b146cb`

## Earlier private-phase validation

The initial revision `samurai-backend-00001-9mx` used private transport and proved the native startup path that the local ARM-emulated final-image
probe could not. Anonymous health access returned HTTP 403, an authorized IAM request to
`/agentos/health` returned success, and an IAM-only request to `/agentos/config` returned
HTTP 401. The same request with IAM authentication plus the temporary bootstrap application
JWT returned HTTP 200. No credential value is recorded here.

An approved parent POST completed run `998bfc51-9399-4410-afab-7ff63dbdd5a9` with
`gemini-3.5-flash-lite`, 1,885 parent tokens, and a 15.78-second duration. The bounded
`run_company_journey` tool was the only tool invoked in this test. An owner-scoped GET
readback returned HTTP 200 with `COMPLETED`, proving the Cloud SQL-backed record and Gemini
call for this controlled run. Five artifacts were accepted, but overall verification
remained `needs_rework`, so this is not verified business readiness.

## Final JWT and browser acceptance

Agno sign-in and registration of **Samurai GCP** are complete. Its Agno-issued public
verification key is pinned as `samurai-jwt-verification-key:2` in revision
`samurai-backend-00002-p4s`. The image digest, runtime account, Cloud SQL attachment, and
runtime settings were preserved. Before opening transport, IAM health returned 200,
IAM-only configuration returned 401, and the retired bootstrap JWT returned 401.
After enabling `allUsers` Cloud Run invoker access, anonymous `/agentos/health` returned
200; anonymous and invalid-JWT `/agentos/config` requests returned 401. Bootstrap secret
version 1 is disabled, and the local bootstrap private signing key was removed.

In the Agno Live browser console, **Samurai GCP** displayed **Active**. The Samurai agent
answered a one-sentence chat request in about two seconds without invoking workflows or
creating artifacts. A full browser reload retained session
`60b7222c-3af9-4834-b0e6-36cac09f4f6e`, proving the final connection's authenticated chat
and session persistence. This browser check is separate from the earlier five-artifact
business run and does not resolve its `needs_rework` outcome.

The user-authorized Agno Live 30-day trial was activated. Its UI stated that no credit
card was required and trial features would stop without payment details. No payment
details were added.

## Provisioning prerequisites

Before creating a revision, create the `samurai` Artifact Registry repository in `asia-south1`, a
Cloud SQL for PostgreSQL database and application user, the runtime service account,
and the following Secret Manager secrets. Keep their values out of the image, source
tree, shell history, and Cloud Run non-secret environment variables.

| Runtime variable | Secret Manager content |
| --- | --- |
| `DATABASE_URL` | The complete application PostgreSQL URL |
| `OS_SECURITY_KEY` | A fresh random AgentOS security key of at least 32 characters |
| `GOOGLE_API_KEY` | The Gemini API key |
| `JWT_VERIFICATION_KEY` | The public RS256 verification key issued for Samurai's production client |

Use a versioned secret reference for environment variables. Cloud Run resolves
environment-variable secrets when an instance starts, so a pinned version makes each
revision reproducible. The runtime account needs only `roles/secretmanager.secretAccessor`
on those four secrets and `roles/cloudsql.client` for the selected Cloud SQL instance.
Do not grant it Editor, Owner, Secret Manager Admin, or a Google Cloud API role that is
not required by a deployed integration. Grant Cloud Storage access only when the planned
artifact-storage integration exists and scope it to its bucket.

The deployer is distinct from the runtime account. It needs Cloud Run deployment
permission, permission to act as the runtime account, and permission to read the chosen
image. It must not reuse the runtime account.

## Container

Build from the backend directory so `backend/.dockerignore` keeps local environments,
test caches, Git metadata, and Python bytecode out of the build context:

```sh
podman build --platform linux/amd64 --tag samurai-backend:local backend
```

The image pins Python `3.14.5-slim-bookworm` and uv `0.9.21`, synchronizes the committed
`uv.lock` with `--locked --no-dev`, copies only `src/`, and runs as UID 10001. It defaults
`SAMURAI_ENVIRONMENT=production`; startup therefore fails unless the JWT public key and
Gemini key are supplied. Cloud Run provides `PORT`; the container listens on it, with 8080
only as the local fallback.

## Cloud SQL

Attach the selected Cloud SQL connection to Cloud Run. That creates the socket directory
at `/cloudsql/PROJECT:REGION:INSTANCE`. The existing `PostgresDsn` configuration works
with psycopg's `host` query parameter; no connector package or application code change is
required:

```dotenv
DATABASE_URL=postgresql+psycopg://samurai:URL_ENCODED_PASSWORD@localhost/samurai?host=/cloudsql/samurai-ai-company-2026:asia-south1:samurai-postgres
```

The `localhost` authority satisfies the settings URL parser. The psycopg dialect receives
the query value as its Unix-socket `host`. The database password remains part of the
single `DATABASE_URL` Secret Manager value. Keep the Cloud SQL instance in `asia-south1`
and do not add public authorized networks for this service path.

## Current Cloud Run configuration

The following command records the final deployed configuration, including the Agno Live
verification key at version 2. It is for an authorized redeployment of this service, not
bootstrap setup. The original private phase and key rotation are recorded above.

```sh
gcloud run deploy samurai-backend \
  --project=samurai-ai-company-2026 \
  --region=asia-south1 \
  --image=asia-south1-docker.pkg.dev/samurai-ai-company-2026/samurai/samurai-backend@sha256:ea7ad0802e3f33a2ece0312b7258f055175aef926f208bb2b9abd63e0e2d8ba8 \
  --service-account=samurai-runtime@samurai-ai-company-2026.iam.gserviceaccount.com \
  --add-cloudsql-instances=samurai-ai-company-2026:asia-south1:samurai-postgres \
  --set-env-vars=SAMURAI_ENVIRONMENT=production,GEMINI_MODEL=gemini-3.5-flash-lite \
  --set-secrets=DATABASE_URL=samurai-database-url:1,OS_SECURITY_KEY=samurai-os-security-key:1,GOOGLE_API_KEY=samurai-google-api-key:1,JWT_VERIFICATION_KEY=samurai-jwt-verification-key:2 \
  --port=8080 \
  --cpu=1 \
  --memory=2Gi \
  --max-instances=1 \
  --min-instances=0 \
  --concurrency=8 \
  --timeout=3600s \
  --allow-unauthenticated
```

`max-instances=1` is an initial-pilot mitigation for the process-local cancellation registry,
not a process-affinity guarantee: replacement and revision overlap can still create more
than one process. Do not split traffic or begin active long runs during a rollout.
`concurrency=8` leaves capacity for cancellation and run-read requests while a streamed run
is active. `min-instances=0` avoids an always-on instance because there is no scheduler or
background queue in this application. The explicit 1 CPU and 2 GiB memory are the initial
runtime allocation, subject to measured revision sizing. The 3600-second request timeout
accommodates up to four bounded child workflows, each with the existing 420-second deadline.
It does not make work resumable: when Cloud Run reaches a request timeout it can return 504
while the instance continues processing, and a reconnect can land on another instance. Do
not add automatic client retries or claim recovery until work execution, cancellation, and
idempotency are durable across instances.

Agno Live authenticates application requests with its Samurai RS256 JWT and does not
supply a Google Cloud Run invoker identity. Public transport is therefore enabled, while
protected application routes require a valid JWT. Keep the Agno-issued version 2 public
key pinned; do not restore the retired bootstrap credential. Repeat public health,
missing/invalid-JWT rejection, authenticated chat, and reload checks after future changes.

`/agentos/health` is a liveness route only. It does not prove a Cloud SQL write, Gemini
response, agent workflow, or durable recovery.

## Local verification boundary

The focused production-guard and Cloud SQL socket-parser checks, static checks, and final
Linux/amd64 image build passed locally. An earlier equivalent image returned health 200 and
unauthenticated configuration access returned 401. The final-source image did not accept a
local ARM-emulated loopback probe before its temporary container was removed, but subsequent native
Cloud Run validation and the final public/browser checks above passed. The full local suite
also has a cancellation timeout reproduced unchanged at base commit
`14d47c2a70fd29999c0ca0ccacbd182e714dbc63`; do not represent that suite as green.

## Acceptance and recovery

Deployment acceptance is complete: native startup, a controlled Gemini call, Cloud
SQL-backed owner-scoped readback, Agno-key rotation, missing/retired/invalid-JWT rejection,
public transport checks, and authenticated Agno Live chat with reload persistence were
observed. The original business workflow still requires resolving `needs_rework` before
claiming verified business readiness. These checks do not establish durable recovery of
in-progress work or a passing full local cancellation suite.

If a revision fails, direct traffic back to the known-good revision using its actual
revision name and a currently trusted JWT key; do not restore disabled bootstrap
version 1. Investigate the failed revision's logs and configuration, and retain the
image digest and evidence. Do not retry a timed-out workflow as though it had not run.

Teardown is a separate, destructive decision: first remove callers and route traffic away,
then delete the Cloud Run service, retained image versions, secrets, and Cloud SQL data only
under an approved retention plan. Deleting the service does not erase database or Secret
Manager data automatically.

## References

- [Cloud Run request timeout](https://docs.cloud.google.com/run/docs/configuring/request-timeout)
- [Cloud Run and Cloud SQL for PostgreSQL](https://docs.cloud.google.com/sql/docs/postgres/connect-run)
- [Cloud Run Secret Manager configuration](https://docs.cloud.google.com/run/docs/configuring/services/secrets)
