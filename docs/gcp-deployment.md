# Samurai backend deployment on Google Cloud

This is the deployment guide for the existing Gemini-backed Samurai AgentOS backend. A
private Cloud Run revision is now deployed; the frontend, local Podman data, and durable
background work are outside this deployment.

## Target and prerequisites

Use the confirmed project and region:

- Project: `samurai-ai-company-2026`
- Region: `asia-south1`
- Service: `samurai-backend`
- Runtime service account: `samurai-runtime@samurai-ai-company-2026.iam.gserviceaccount.com`
- Cloud SQL connection: `samurai-ai-company-2026:asia-south1:samurai-postgres`

## Current private revision

The following native Linux/amd64 Cloud Run revision is deployed with private transport:

- Revision: `samurai-backend-00001-9mx`
- Service URL: `https://samurai-backend-590733583260.asia-south1.run.app`
- Image: `asia-south1-docker.pkg.dev/samurai-ai-company-2026/samurai/samurai-backend@sha256:ea7ad0802e3f33a2ece0312b7258f055175aef926f208bb2b9abd63e0e2d8ba8`
- Source commit: `dad101bb1b0e59c993802ca1c0338b4ef6b146cb`

The private revision proved the native startup path that the local ARM-emulated final-image
probe could not. Anonymous health access returned HTTP 403, an authorized IAM request to
`/agentos/health` returned success, and an IAM-only request to `/agentos/config` returned
HTTP 401. The same request with IAM authentication plus the temporary bootstrap application
JWT returned HTTP 200. No credential value is recorded here.

An approved parent POST completed run `998bfc51-9399-4410-afab-7ff63dbdd5a9` with
`gemini-3.5-flash-lite`, 1,885 parent tokens, and a 15.78-second duration. The bounded
`run_company_journey` tool was the only tool invoked in this test. An owner-scoped GET
readback returned HTTP 200 with `COMPLETED`, proving the Cloud SQL-backed record and Gemini
call for this controlled run. This does not confirm that the whole business workflow
produced its expected artifacts.

Agno sign-in and Cloud Run connection registration are pending, followed by production-key
rotation and private JWT/no-JWT validation. Public transport remains disabled until those
private checks complete; browser acceptance follows the public transition.

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

## Initial private Cloud Run revision

Start with private Cloud Run transport. This keeps the technical routes behind Cloud Run
IAM while Agno sign-in, browser acceptance, and production-key rotation remain incomplete.
The command below uses the deployed immutable image digest and does not make the service
public.

The following is the reviewed initial-revision template. Replace only the pinned secret
versions before use:

```sh
gcloud run deploy samurai-backend \
  --project=samurai-ai-company-2026 \
  --region=asia-south1 \
  --image=asia-south1-docker.pkg.dev/samurai-ai-company-2026/samurai/samurai-backend@sha256:ea7ad0802e3f33a2ece0312b7258f055175aef926f208bb2b9abd63e0e2d8ba8 \
  --service-account=samurai-runtime@samurai-ai-company-2026.iam.gserviceaccount.com \
  --add-cloudsql-instances=samurai-ai-company-2026:asia-south1:samurai-postgres \
  --set-env-vars=SAMURAI_ENVIRONMENT=production,GEMINI_MODEL=gemini-3.5-flash-lite \
  --set-secrets=DATABASE_URL=REPLACE_WITH_DATABASE_URL_SECRET:REPLACE_WITH_VERSION,OS_SECURITY_KEY=REPLACE_WITH_OS_SECURITY_KEY_SECRET:REPLACE_WITH_VERSION,GOOGLE_API_KEY=REPLACE_WITH_GOOGLE_API_KEY_SECRET:REPLACE_WITH_VERSION,JWT_VERIFICATION_KEY=REPLACE_WITH_JWT_PUBLIC_KEY_SECRET:REPLACE_WITH_VERSION \
  --port=8080 \
  --cpu=1 \
  --memory=2Gi \
  --max-instances=1 \
  --min-instances=0 \
  --concurrency=8 \
  --timeout=3600s \
  --no-allow-unauthenticated
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

First sign in to Agno, register the Cloud Run connection, and obtain its final public
verification key. Rotate the JWT configuration, then use an authorized IAM client against
the private service to confirm a valid production JWT and rejection without one. Only then
make a separate, controlled transition to `--allow-unauthenticated` for the existing AgentOS
Live console and complete browser acceptance. The console has a Samurai RS256 JWT but no
Google Cloud Run invoker identity. Public transport must not make the AgentOS application
unauthenticated: protected routes must still reject requests without a valid production
Samurai JWT. Repeat public health and unauthenticated-config checks during that transition.
Do not use the temporary bootstrap application JWT as the production browser credential.

`/agentos/health` is a liveness route only. It does not prove a Cloud SQL write, Gemini
response, agent workflow, or durable recovery.

## Local verification boundary

The focused production-guard and Cloud SQL socket-parser checks, static checks, and final
Linux/amd64 image build passed locally. An earlier equivalent image returned health 200 and
unauthenticated configuration access returned 401. The final-source image did not accept a
local ARM-emulated loopback probe before its temporary container was removed, so private
Cloud Run validation is required before this image is exposed publicly. The full local suite
also has a cancellation timeout reproduced unchanged at base commit
`14d47c2a70fd29999c0ca0ccacbd182e714dbc63`; do not represent that suite as green.

## Acceptance and recovery

The private-revision observations include a controlled Gemini call and Cloud SQL-backed
owner-scoped readback. Before public transport, record the configured service account,
Cloud SQL attachment, pinned secret versions, and exact invocation identity, then complete
the following pending checks:

1. Sign in to Agno, register the Cloud Run connection, and obtain the final public
   verification key.
2. Rotate the temporary key and use IAM access against the private service to verify both
   a valid production JWT and a no-JWT HTTP 401 response.
3. After the controlled public transition, a public request to `/agentos/health` returns
   success, `/agentos/config` without a Samurai JWT returns HTTP 401, and browser
   acceptance completes through the AgentOS Live console.
4. The intended business workflow produces and verifies its expected artifacts without
   exposing keys, tokens, founder data, or database URLs. The completed bounded parent run
   above is not evidence for this broader acceptance.

If a revision fails, direct traffic back to the known-good revision using its actual
revision name, investigate the failed revision's logs and configuration, and retain the
image digest and evidence. Do not retry a timed-out workflow as though it had not run.

Teardown is a separate, destructive decision: first remove callers and route traffic away,
then delete the Cloud Run service, retained image versions, secrets, and Cloud SQL data only
under an approved retention plan. Deleting the service does not erase database or Secret
Manager data automatically.

## References

- [Cloud Run request timeout](https://docs.cloud.google.com/run/docs/configuring/request-timeout)
- [Cloud Run and Cloud SQL for PostgreSQL](https://docs.cloud.google.com/sql/docs/postgres/connect-run)
- [Cloud Run Secret Manager configuration](https://docs.cloud.google.com/run/docs/configuring/services/secrets)
