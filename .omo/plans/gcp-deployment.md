# Samurai GCP deployment

Target: the existing Samurai/Gemini backend, preserving `/agentos`, parent/internal workflows, PostgreSQL persistence, JWT isolation, and local Podman behavior. The sibling `agent-platform` checkout is a deployment reference only; do not replace the product with its OpenAI platform.

## Acceptance and tasks

- [x] Inspect the actual backend and reference deployment layer; verify current official GCP contracts.
- [x] Prepare the smallest backend container and production configuration that refuses startup without JWT, keeps secrets outside images, and supports Cloud SQL.
- [x] Provide explicit-project/region deployment instructions, secure secret delivery, bounded Cloud Run execution settings, and rollback/teardown guidance.
- [x] Verify offline checks and record actual container/runtime results and limitations (below).
- [x] Obtain the intended GCP project/region, authenticated CLI, and billing linkage.
- [x] Provision scoped resources and secrets, deploy privately, and prove authenticated live behavior (private API acceptance only).
- [x] Connect the cloud endpoint to Agno Live with its production verification key and record browser acceptance.

## Boundaries

Cloud project `samurai-ai-company-2026` was created under the Team Samurai account; existing billing linkage was verified in Dia. The user selected Mumbai (`asia-south1`). No GCP resources may be created by guessing either value. Google Cloud CLI 588.0.0 is installed in the parent workspace `.tools/google-cloud-sdk`; CLI sign-in as the Team Samurai account, project ACTIVE state, and enabled billing were verified before provisioning. Cloud deployment incurs charges. No frontend deployment or migration of existing local database contents is implied. Preserve Reporting containers and all private local configuration. Keep this branch local pending publication authorization.

Reference checkout: `agno-agi/agentos-gcp`, commit `3176288c1c91df8ffd95438b276f5733a93f26ed`.

## Discovery result

No existing backend image or deployment manifest. The reference has incompatible OpenAI-specific environment and entrypoint, so use a Samurai-specific image. Preserve one worker and initially one Cloud Run instance because cancellation state is process-local. Settings require a production JWT guard. `/agentos/health` proves liveness only; DB writes and authenticated founder runs need independent acceptance. Cloud Run timeout does not guarantee cancellation or resumability. Official references: https://docs.cloud.google.com/run/docs/configuring/request-timeout and https://docs.cloud.google.com/sql/docs/postgres/connect-run.

## Deployment configuration

Container and production validation are delegated separately from scoped GCP infrastructure provisioning. The initial deployment uses a single worker and instance, with enough request concurrency to process cancellation while a stream is open. No queue-backed resumability is claimed.

Artifact Registry `samurai` and the dedicated runtime service account exist. Cloud SQL `samurai-postgres` is RUNNABLE in Mumbai: PostgreSQL 18, Enterprise `db-g1-small`, zonal, 10 GB SSD with a 20 GB auto-resize cap, backups/PITR and deletion protection enabled, connector enforcement required, no public authorized networks. Database/user `samurai` and four scoped secrets exist. This is infrastructure readiness, not an application deployment or database-write acceptance claim.

## Local validation and release boundary

Runtime/container changes are committed locally as `dad101b`. Ruff, formatting, basedpyright, and five focused configuration/JWT tests passed. The full suite returned 144 passed and one streaming-cancellation timeout; the same focused failure was reproduced on unchanged base `14d47c2a70fd29999c0ca0ccacbd182e714dbc63`. No cancellation code was changed, and cloud cancellation acceptance remains unverified.

An initial AMD64 image returned health 200 and unauthenticated config 401 locally. The final image `04267aa8f9ab84fe0aeb0494c68d2f0b0f94b3933f00fe3ca1708803670b2597` built successfully but did not become HTTP-ready under local ARM emulation before cleanup. Native AMD64 private Cloud Run startup subsequently passed; the earlier image's local HTTP result is not claimed for the final image. Temporary test containers were removed; Reporting services were preserved.

## Private cloud acceptance

The initial private revision was `samurai-backend-00001-9mx` at `https://samurai-backend-590733583260.asia-south1.run.app`, using registry digest `sha256:ea7ad0802e3f33a2ece0312b7258f055175aef926f208bb2b9abd63e0e2d8ba8`. Native startup passed. Root directly observed anonymous health 403, IAM-authenticated health 200, IAM-only config 401, and valid IAM plus bootstrap application JWT config 200. The subsequent Agno Live release is recorded below.

The approved fictional parent run `998bfc51-9399-4410-afab-7ff63dbdd5a9` completed using `gemini-3.5-flash-lite`. Root independently read its `COMPLETED` status and Google/model metadata through the owner-scoped persisted-run API. The release lane found five accepted artifacts, with verification and the overall workflow outcome `needs_rework`. This verifies runtime execution and Cloud SQL-backed persistence, not verified business readiness or cancellation.

## Agno Live continuation

The user completed sign-in and explicitly approved the 30-day Live trial and JWT setup. `Samurai GCP` was registered with the cloud `/agentos` endpoint in Dia. Revision `samurai-backend-00002-p4s` serves the same immutable image with `samurai-jwt-verification-key:2`, containing Agno's public verification key. Public HTTP transport is enabled; application routes remain JWT-protected. Root independently verified public health 200 and unauthenticated config 401. The release lane also verified invalid/old bootstrap JWT rejection, disabled secret version 1, and removed the bootstrap private key and temporary credentials.

Root observed `Samurai GCP Active` in Dia, ran one small authenticated chat without workflows or business-artifact generation, and reloaded the page. The answer remained in session `60b7222c-3af9-4834-b0e6-36cac09f4f6e`. Screenshot evidence remains local and ignored. The task-created Dia tab was closed after browser acceptance; existing tabs and Reporting services were preserved.

The trial requires no credit card; Agno states Pro features stop after 30 days unless payment details are added. No payment details were added. Cloud SQL remains billable. Frontend deployment, cloud cancellation, durable resumability, and resolution of business verification `needs_rework` remain outside this completed deployment acceptance. Branch changes remain local and unpushed.
