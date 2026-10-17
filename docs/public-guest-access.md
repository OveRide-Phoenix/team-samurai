# Public judge access

Approved access model: anyone with the frontend URL can use a private guest session,
without Google sign-in. Implementation is staged on `Kalyan/public-guest-access`;
production activation has not been performed.

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
Cancellation, stream reconnection and reads remain available after exhaustion.
These are request counts, not a financial ceiling: tools and the existing bounded
retry can cause multiple Gemini calls per admitted submission. Read traffic and
hosting costs are not capped by these counters.

Guest membership changes are denied. Existing backend membership checks still
control every workspace, company and file access. Missing usage tables or database
failures reject guest writes. Shared counters do not replace workspace storage,
company and active-job quotas.

## Activation dependency

Read-only inspection on 17 October 2026 found `samurai-backend-00011-4sz` configured
with `SAMURAI_ENVIRONMENT=production`, no `QUEUE_ENABLED`, and no `REDIS_URL`.
The default queue setting is false. Production native company runs return 503 in
that configuration. This is a separate dependency from Google sign-in.

The earlier deferral was superseded on 17 October: the user approved seven days
of 1 GiB Basic Redis and one always-on 1 vCPU / 2 GiB backend in Mumbai, accepting
temporary Redis outages. IAP removal still depends on runtime verification.

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

Before activation:

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
6. Test two fresh browser sessions, reload, cross-guest rejection, daily exhaustion,
   and a complete bounded fictional company flow. Confirm existing IAP data remains
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
