# Samurai deployment and CI/CD on Google Cloud

This guide records the accepted Gemini-backed AgentOS backend and the team-only frontend deployment path. The backend uses public transport with JWT-protected application routes. Frontend IAP and CI/CD implementation are separate from live acceptance; their pending checks are recorded below. Local Podman data is not migrated and in-progress work is not durable.

## Target and prerequisites

Use the confirmed project and region:

- Project: `samurai-ai-company-2026`
- Region: `asia-south1`
- Service: `samurai-backend`
- Runtime service account: `samurai-runtime@samurai-ai-company-2026.iam.gserviceaccount.com`
- Cloud SQL connection: `samurai-ai-company-2026:asia-south1:samurai-postgres`

## Previously accepted backend revision

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

## Previously accepted backend configuration

The following command records the earlier backend-only configuration, including the Agno Live verification key at version 2. It is historical evidence, not the frontend bootstrap or routine CI command: replaying `--set-secrets` would remove the new additive frontend trust setting. Routine deployment changes images only. The original private phase and key rotation are recorded above.

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
Cloud Run validation and the final public/browser checks above passed. An earlier local suite encountered an intermittent cancellation timeout, also reproduced at base commit `14d47c2a70fd29999c0ca0ccacbd182e714dbc63`. The latest PR backend run passed 147 tests. Preserve the intermittent-timeout caveat when reporting results; each deployment still requires checks for its exact commit.

## Acceptance and recovery

The earlier backend deployment acceptance is complete: native startup, a controlled Gemini call, Cloud
SQL-backed owner-scoped readback, Agno-key rotation, missing/retired/invalid-JWT rejection,
public transport checks, and authenticated Agno Live chat with reload persistence were
observed. The original business workflow still requires resolving `needs_rework` before
claiming verified business readiness. These checks do not establish durable recovery of
in-progress work. The intermittent local cancellation-test timeout and later passing run are recorded separately above.

If a revision fails, direct traffic back to the known-good revision using its actual
revision name and a currently trusted JWT key; do not restore disabled bootstrap
version 1. Investigate the failed revision's logs and configuration, and retain the
image digest and evidence. Do not retry a timed-out workflow as though it had not run.

Teardown is a separate, destructive decision: first remove callers and route traffic away,
then delete the Cloud Run service, retained image versions, secrets, and Cloud SQL data only
under an approved retention plan. Deleting the service does not erase database or Secret
Manager data automatically.

## Team-only frontend and Google identity

The production frontend is `samurai-frontend` in the same project and region. Its Node server serves the Vite assets and the narrow same-origin AgentOS proxy. Google IAP protects the Cloud Run service; the server verifies the signed assertion's issuer, signature, timestamps and exact audience before using `iap:<verified-sub>` as the application identity. It signs short-lived RS256 backend JWTs. Email headers, browser `user_id`, and browser authorization overrides are not trusted.

| Service | Runtime identity | Configuration |
| --- | --- | --- |
| Frontend | `samurai-frontend@samurai-ai-company-2026.iam.gserviceaccount.com` | `IAP_AUDIENCE=/projects/590733583260/locations/asia-south1/services/samurai-frontend`; `PUBLIC_ORIGIN` is the canonical frontend HTTPS origin; `AGENTOS_BACKEND_URL=https://samurai-backend-590733583260.asia-south1.run.app` |
| Frontend | Same identity | `AGENTOS_SIGNING_KEY=samurai-frontend-signing-key:1` from Secret Manager |
| Backend | Existing `samurai-runtime@samurai-ai-company-2026.iam.gserviceaccount.com` | Add `FRONTEND_JWT_VERIFICATION_KEY=samurai-frontend-verification-key:1`; preserve `JWT_VERIFICATION_KEY=samurai-jwt-verification-key:2` and all other runtime settings |

The signer and public-key secrets and scoped runtime access were provisioned during bootstrap and verified in the deployed frontend. Only the frontend runtime may read its private signer. The backend receives the public key; CI needs no secret payload access. Never put keys or tokens in image layers, committed files, browser storage, `VITE_` variables, workflow output, or command history. Current configuration accepts one Agno public key and one frontend public key; it does not support overlapping old/new frontend keys. Coordinate frontend signer and backend verification-key rotation during maintenance, or first extend and test frontend trust to allow an overlap before switching the signer. Preserve the Agno verification key throughout. Never restore disabled bootstrap key version 1.

Bootstrap requires IAP enabled on the frontend, no anonymous Cloud Run invoker grant, and `roles/run.invoker` on that service for `service-590733583260@gcp-sa-iap.iam.gserviceaccount.com`. Configure the HTTP startup probe at `/healthz` and a request timeout compatible with backend streaming. Keep IAP off the backend so Agno Live continues to work with its application JWT.

The initial authorized Google account is `teamsamurai.sksk@gmail.com`. Team membership is an explicit IAP IAM allowlist: grant approved users or a Google group `roles/iap.httpsResourceAccessor` on the frontend IAP resource. To onboard another member, obtain the approved Google account/group, add that principal, then verify sign-in and a separate user's data isolation. Do not grant `allUsers` IAP access. The OAuth brand has been created and approved. The custom IAP OAuth client is enabled; this account completed Google sign-in and a bounded live brief run on 12 October 2026. Signing in to Agno Live and signing in through IAP produce different application identities and do not automatically transfer existing sessions.

## Main and manual CI/CD

[deploy.yml](../.github/workflows/deploy.yml) runs on pushes to `main` and `workflow_dispatch`. Manual runs must select `main`; both the workflow and Google federation reject other refs. In GitHub Actions choose **Deploy production → Run workflow → main** for an authorized manual deployment. Production runs are serialized with `cancel-in-progress: false`.

The workflow calls [checks.yml](../.github/workflows/checks.yml) for the same commit: locked dependency installs, backend Ruff/format/basedpyright/pytest, frontend check/build/Sites/server tests, and deployment-script checks. It builds both Linux/amd64 images before cloud authentication, pushes commit-tagged images, resolves immutable digests, and invokes [deploy-cloud-run.sh](../scripts/deploy-cloud-run.sh).

The Google OIDC federation provider is `projects/590733583260/locations/global/workloadIdentityPools/github/providers/github-main`. It accepts the immutable repository ID `1413923270`, owner ID `24836702`, main ref, and intended `deploy.yml` push/manual claims. It impersonates `samurai-deployer@samurai-ai-company-2026.iam.gserviceaccount.com`. No service-account JSON key is used. WIF and the deployer account have been bootstrapped; successful GitHub credential exchange and rollout remain acceptance checks.

Routine deployer permissions are Cloud Run Developer on the two existing services, Artifact Registry Writer on the `samurai` repository, and Service Account User on the two runtime accounts. The repository federation principal receives Workload Identity User on the deployer. Bootstrap IAM, secrets, IAP, runtime configuration and initial service creation are separate from the image-update workflow.

Both services must exist before routine deployment. The script requires a single ready revision serving 100% for each service and records both previous revisions/digests in the Actions summary before updating either. It updates only the backend image, then only the frontend image, preserving runtime accounts, secrets, Cloud SQL, IAP and probes. It checks readiness, deployed digests and traffic, backend liveness, and anonymous frontend protection. These checks do not prove authenticated founder or Agno Live behavior.

## Rollback and rollout limits

Two service updates are not atomic. If frontend deployment fails after backend succeeds, the backend may already be serving the new image. The workflow stops; it does not automatically retry a run POST or roll back services. Avoid active long runs during rollout because cancellation remains process-local and revision replacement cannot resume in-flight work. Health GET retries are separate from business execution.

Use the Actions summary to identify the previous revision for each affected service, then route traffic explicitly after reviewing compatibility:

```sh
gcloud run services update-traffic samurai-frontend \
  --project=samurai-ai-company-2026 --region=asia-south1 \
  --to-revisions=PREVIOUS_FRONTEND_REVISION=100
gcloud run services update-traffic samurai-backend \
  --project=samurai-ai-company-2026 --region=asia-south1 \
  --to-revisions=PREVIOUS_BACKEND_REVISION=100
```

Rollback frontend before removing backend trust it requires. The original `00002` backend revision lacks frontend JWT trust; restoring it can keep Agno Live working while breaking the IAP frontend. Keep a known-good additive-trust revision once accepted. If secret/configuration changes are involved, check the selected revision's pinned versions and access before restoring traffic. After traffic rollback the latest-ready revision may differ from the serving revision; the routine script intentionally refuses that state. Reconcile by deploying the known-good image with the intended current configuration and verify it before the next automatic rollout. Never retry an interrupted business run without checking its persisted status.

## Frontend and CI acceptance record

As verified on 12 October 2026, the approved Google account signed in through IAP, loaded backend intake questions, completed a fictional dental-receptionist brief, and retained the rendered brief after a full browser reload. Research was not started. Anonymous frontend requests redirect to Google sign-in (302); backend liveness returns 200 and unauthenticated configuration returns 401.

Bootstrap source `65bff23ecedafa62c32d67f9b56a7c520d2580f8` was built natively in Cloud Build `4c4a8d10-edc8-4b61-ba2f-98f6145e3a7b`:

| Service | Bootstrap revision | Immutable image digest |
| --- | --- | --- |
| Backend | `samurai-backend-00003-wpr` | `backend@sha256:74bead66c7bb97f95590c0a644d6d83bc9fa119d4c32b73ef5d80b46d86f5c5b` |
| Frontend | `samurai-frontend-00001-6rw` | `frontend@sha256:cb9e87e5d5e739f78ffafb1fa302c06d5ae585dae106f2f07e6920ea8a2f041e` |

Both images are in `asia-south1-docker.pkg.dev/samurai-ai-company-2026/samurai`. The frontend URL is https://samurai-frontend-590733583260.asia-south1.run.app. The one-time native build used `samurai-builder`, repository-scoped Artifact Registry Writer, Logs Writer, and object read access on the private source bucket `samurai-ai-company-2026-build-source`. Routine GitHub deployment builds images on its runner and does not use this builder.

Integrated [GitHub checks](https://github.com/OveRide-Phoenix/team-samurai/actions/runs/38261179631) passed for `51b9d4022b0f14b6b732b751553add8ed02b48c1`, including 157 backend tests and frontend checks. Local frontend verification passed 79 Vitest, 33 server, and four Sites tests plus type checking/build. Local backend verification passed 156 tests with one pre-existing intermittent cancellation timeout. The new JWT isolation test cleans its cancellation state.

- [x] Production auth/proxy tests, additive JWT trust, both native containers, and deployment script checks.
- [x] Scoped production security review for source `65bff23ecedafa62c32d67f9b56a7c520d2580f8`.
- [x] Frontend IAP, startup probe, pinned secrets, scoped runtime identity and approved-account sign-in.
- [x] Live brief creation and browser reload, with research deliberately paused.
- [x] Automated owner-isolation and missing/forged/expired/wrong-audience assertion rejection tests.
- [ ] A second approved Google account has not been supplied; two-account live acceptance is unverified. Browser namespaces do not prevent manual access to localStorage in a shared browser profile.
- [ ] Existing Agno Live regression after additive JWT trust.
- [ ] Main automatic and manual GitHub deployment acceptance; WIF is provisioned, but successful credential exchange and rollout must still be observed.


## References

- [Cloud Run request timeout](https://docs.cloud.google.com/run/docs/configuring/request-timeout)
- [Cloud Run and Cloud SQL for PostgreSQL](https://docs.cloud.google.com/sql/docs/postgres/connect-run)
- [Cloud Run Secret Manager configuration](https://docs.cloud.google.com/run/docs/configuring/services/secrets)
