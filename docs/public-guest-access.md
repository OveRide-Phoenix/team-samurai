# Public judge access

Approved access model: anyone with the frontend URL can use a private guest session,
without Google sign-in. Activated on 17 October 2026 at
https://samurai-frontend-590733583260.asia-south1.run.app/ for the approved seven-day
window. Backend JWT authorization remains enabled.

## Identity and limits

The Node BFF issues an RSA-signed, Secure, HttpOnly, SameSite=Lax host-only cookie
on the initial page visit. It expires after seven days. Keep the same browser and
cookies to retain access; clearing cookies or expiration creates a new guest and
does not recover the previous guest's workspace. Guest identities use a separate
`guest:` namespace, while existing team identities retain their `iap:` namespace.
The browser never receives the backend signing key or a backend JWT.

Each verified guest has up to 10 AI submissions and 60 write requests per UTC day.
All guests combined have up to 50 AI submissions and 300 write requests per UTC
day. AI submissions also count as writes. PostgreSQL reserves both counters in one
transaction under a shared lock, so changing cookies or adding Cloud Run instances
does not reset the global allowance. Failed submissions consume their reservation.
Non-AI writes use their separate write budget even if a lower AI limit is below
the retained AI counter. Cancellation, stream reconnection and reads remain
available after exhaustion.
These are request counts, not a financial ceiling: tools and the existing bounded
retry can cause multiple Gemini calls per admitted submission. Read traffic and
hosting costs are not capped by these counters.

Guest membership changes are denied. Existing backend membership checks still
control every workspace, company and file access. Missing usage tables or database
failures reject guest writes. Shared counters do not replace workspace storage,
company and active-job quotas.

## Hosting decision and expiry

Read-only inspection on 17 October 2026 found `samurai-backend-00011-4sz` configured
with `SAMURAI_ENVIRONMENT=production`, no `QUEUE_ENABLED`, and no `REDIS_URL`.
The default queue setting is false. Production native company runs return 503 in
that configuration. This is a separate dependency from Google sign-in.

The earlier deferral was superseded on 17 October: the user approved seven days
of 1 GiB Basic Redis and one always-on 1 vCPU / 2 GiB backend in Mumbai, accepting
temporary Redis outages. Queue readiness and guest boundaries passed before
frontend IAP was removed.

Temporary resources: `samurai-judge-network`, `samurai-judge-subnet`
(`10.48.0.0/26`, Mumbai), and `samurai-judge-redis` (Basic, AUTH enabled, private
direct peering). Redis creation began at 2026-10-17 16:51:39 UTC; the approved
window ends **2026-10-24 16:51:39 UTC / 22:21:39 IST**. The Codex heartbeat
`end-samurai-seven-day-judge-window` checks hourly and performs the rollback after
expiry unless explicitly extended. It depends on Codex availability and is not a
provider-enforced expiry or hard spending cap.

At expiry, block new guest admission, drain outstanding work, restore team-only
IAP and request-based backend billing with minimum zero and queue disabled, then
delete the temporary Redis once unused. Preserve Cloud SQL and all user data.
Do not leave revision-level minimums at one when scaling back. Remove unused
task-created network/secret resources only after confirming no dependencies.

Activation/rollback checklist for future deployments:

1. Complete the approved durable queue deployment and verify the worker, Redis,
   native run, reconnection and cancellation paths.
2. Apply the additive `0005_guest_usage` migration through the existing founder
   migrator after its inventory/backup checks. Do not modify earlier migrations.
3. Deploy backend code with `GUEST_ACCESS_ENABLED=true`; production configuration
   rejects that setting unless `QUEUE_ENABLED=true` and Redis is configured.
4. Deploy the BFF with `FRONTEND_AUTH_MODE=guest`, preserving the signing secret and
   backend verification key. Update deployment checks to explicitly support this
   mode before pushing a main-branch deployment.
5. Remove frontend IAP and permit public invocation only for the frontend after
   guest admission and backend JWT checks pass. Backend application JWT checks
   remain required.
6. Test independent guest sessions, reload, cross-guest rejection and daily
   exhaustion. Run a bounded fictional intake; record any broader journey tests separately. Confirm existing IAP data remains
   inaccessible. Show judges the cookie lifetime and usage-limit notice before launch.

Rollback: restore frontend IAP/access policy and `FRONTEND_AUTH_MODE=iap`; disable
backend guests. Retain the additive table and existing user data. No deployment,
cloud migration, IAP change, or paid Gemini run is implied by local test results.

## Local verification

Provider-free PostgreSQL checks cover concurrent per-guest admission, global caps
across fresh identities, UTC rollover, cross-guest workspace denial, membership
change denial, database failure, and disabled-mode rejection. Server HTTP tests
cover signed-cookie retention, separate guest namespaces, tampering/duplication,
expiration, backend-token separation and unchanged IAP/CSRF protections.

The built production frontend was opened in Codex's internal browser against a
local provider-free backend and disposable PostgreSQL database: anonymous entry,
company reservation, opening intake and reload readback worked. This proves the
guest access boundary and database plumbing, not Gemini execution or cloud recovery.
The temporary tab, servers and database are cleaned up after verification.

## Production acceptance — 17 October 2026

Source `066ad775cf09313f15aebc42a20b0d6aeb613dc9` passed
[branch checks](https://github.com/OveRide-Phoenix/team-samurai/actions/runs/39051637537)
and [main deployment](https://github.com/OveRide-Phoenix/team-samurai/actions/runs/39051820305).
The activation snapshot is backend `samurai-backend-00015-vzq` and frontend
`samurai-frontend-00011-cxs`. Subsequent main pushes also deploy; consult their
Actions summaries for newer revision/digest pairs.

- Backend: one always-on 1 vCPU / 2 GiB instance, service and revision min/max 1,
  concurrency 8, HTTP startup probe `/agentos/health`, private VPC egress and queue
  enabled. Redis AUTH URL is pinned to `samurai-judge-redis-url:1`.
- Fresh Cloud SQL backup `1792256634492` succeeded. Additive migration
  `0005_guest_usage` preserved all three existing companies, two owners, eleven
  revisions and their state hashes. The temporary `samurai-guest-migration` job
  was deleted after verification; Cloud SQL remains unchanged apart from the
  additive migration and test records.
- Queue readiness reported healthy with worker and coordination available.
  Anonymous protected backend access remained HTTP 401; frontend entry was 200.
- Two independent HTTP cookie jars proved distinct guest identities, saved
  workspace readback, cross-guest denial and wrong-origin write rejection.
  Cookies retained Secure, HttpOnly and SameSite=Lax protections.
- In Codex's internal browser, the approved fictional dental-clinic idea produced
  a saved brief and retained it after reload. PostgreSQL confirmed the native
  job completed on attempt 1, accepted revision 1, and a completed Agno run.
  Recorded run metrics were 3,114 input and 149 output tokens, not a billing receipt.
- Landing-page captures passed visual review at 375, 768 and 1280 pixels in both
  themes. The task browser tab and viewport override were cleaned up.
- Local verification passed 437 backend tests (156 environment-gated skips),
  46 focused real-PostgreSQL checks without skips, 213 frontend tests, 64 server
  tests, type checking/build and deployment-script checks. Main CI also passed
  its PostgreSQL recovery/migration tests.

Live quota exhaustion was not induced; concurrent limits, UTC rollover, database
failure and cookie tampering are covered by provider-free tests. This acceptance
covers intake and persistence, not a complete research-to-launch journey or an
injected Redis outage/recovery drill. Basic Redis has no failover. The user accepted
temporary outages; durable PostgreSQL state does not make every outage invisible.
The expiry heartbeat is a cleanup follow-up, not a guaranteed billing cutoff.
