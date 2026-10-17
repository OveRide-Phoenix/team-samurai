# Production readiness cost baseline

**Status: seven-day Basic queue approved on 17 October 2026.** The approval covers
one always-on backend (1 vCPU / 2 GiB) and 1 GiB Basic Redis in Mumbai.
Temporary Redis outages are accepted; a separate restore target is not approved. This is an estimate, not a bill or a
spend cap. No numeric budget was supplied, so free tier, credits, committed-use
discounts, and billing alerts are deliberately excluded from the arithmetic.

## Refreshed judge-access estimate — 17 October 2026

The user approved the Basic option for seven days. This section supersedes the older price arithmetic
below: that estimate incorrectly used Iowa's Redis price for Mumbai.

Smallest managed deployment compatible with the current queue: keep the existing
Cloud SQL database, run the existing backend continuously at 1 vCPU / 2 GiB with
instance-based billing and minimum 1 instance, and add 1 GiB Memorystore for Redis.
Use Direct VPC egress, avoiding a separate connector VM charge. For the lowest-cost
judge deployment uses maximum 1 backend instance; the tested rollout script
sets both service and revision minimum/maximum to 1.
This is not a hard spending cap; revision overlap and variable charges can add cost.

| Component / option | USD per 730-hour month | USD for seven days |
| --- | ---: | ---: |
| One always-on backend, 1 vCPU / 2 GiB | 57.82 | 13.31 |
| Redis Basic, 1 GiB, Mumbai at $0.063/GiB-hour | 45.99 | 10.58 |
| Backend + Basic Redis | **103.81** | **23.89** |
| Backend + Standard Redis (automatic failover), $0.11/GiB-hour | **138.12** | **31.79** |

At an illustrative planning conversion of **INR 100/USD** (not a live FX quote or
Google's INR SKU tariff), these are about **INR 10,400/month or INR 2,400/week** for
Basic, and **INR 13,800/month or INR 3,200/week** for Standard. Taxes are additional.
A sustained second backend adds $57.82/month; with Basic the two-instance total
is $161.62/month. Free-tier discounts, credits and commitments are excluded.

These are gross post-change backend-plus-Redis prices, not the entire application
bill and not an exact incremental amount. Redis is new; the always-on backend
replaces current backend billing. Existing Cloud SQL, frontend, Gemini usage,
network traffic, storage growth, logging/builds and any recovery drill are excluded.
No live billing usage or account-specific INR prices were retrieved.

Basic is the minimum-cost competition option but has **no automatic Redis failover**:
a Redis outage pauses admission, streaming/cancellation and coordination until it
recovers. Durable job records stay in PostgreSQL; actual cloud recovery still needs
verification. Standard is preferable if uninterrupted judge access matters. Neither
choice makes the existing zonal Cloud SQL deployment highly available.

Decision: seven-day Basic is approved with the availability tradeoff accepted.
Standard and an extension beyond seven days require a new decision.
Seven-day arithmetic does not automatically stop billing: approved teardown or a
return to the previous configuration is required at the end. Do not purchase a
long-term commitment for this experiment.

Current authoritative sources:

- [Cloud Run pricing](https://cloud.google.com/run/pricing): Mumbai is Tier 1;
  instance CPU $0.000018/vCPU-second and RAM $0.000002/GiB-second.
  Monthly backend arithmetic: 730 * 3600 * (0.000018 + 2 * 0.000002).
- [Memorystore pricing](https://cloud.google.com/memorystore/docs/redis/pricing):
  the page's published regional table data was read for `Mumbai (asia-south1)`;
  Basic M1 is $0.063/GiB-hour and Standard M1 is $0.11/GiB-hour. The default visible
  Iowa table ($0.049 Basic) must not be used for Mumbai.
- [Redis tiers](https://docs.cloud.google.com/memorystore/docs/redis/redis-tiers):
  Basic is standalone; Standard provides cross-zone replication and failover.
- [Cloud Run billing](https://docs.cloud.google.com/run/docs/configuring/billing-settings):
  continuously available background CPU requires instance-based billing with a
  minimum instance; instances can still be terminated and must recover durably.
- [Direct VPC comparison](https://docs.cloud.google.com/run/docs/configuring/connecting-vpc):
  Direct VPC avoids the additional VMs charged for a connector; traffic remains
  subject to applicable network pricing.

## 12 October 2026 baseline (historical; pricing superseded above)

| Surface | Verified current state | Cost treatment |
| --- | --- | --- |
| Backend Cloud Run | `samurai-backend-00007-6wc`, 100% traffic; template reports `maxScale=1`, service metadata reports `maxScale=3`, and concurrency is 8. The differing scopes make the live maximum ambiguous. | Existing traffic and billing cost are not available from this read-only inventory. Do not call them zero. |
| Frontend Cloud Run | `samurai-frontend-00005-g7c`, 100% traffic; no change proposed. | Existing, unchanged. |
| Cloud SQL | `samurai-postgres`: PostgreSQL 18, zonal `db-g1-small`, 10 GiB PD-SSD, backups and PITR enabled, seven-day log retention. | Existing, unchanged except for one later temporary restore drill. |
| Managed Redis / Cloud Tasks | The `redis.googleapis.com` and `cloudtasks.googleapis.com` APIs are disabled. This proves neither inventory nor absence of resources. | Treat the proposed Redis instance as an incremental cost; do not enable either API in this task. |
| Redis network path | The backend template has no Direct VPC or connector annotation. The Compute Engine API is disabled, so VPC/subnet inventory could not be read without an API activation. | Direct VPC egress is selected, but the exact VPC/subnet/firewall prerequisite is BLOCKED. Do not call its traffic cost zero. |

The selected field-only command output is retained in
`.omo/evidence/readiness/task-1/baseline.md`. It contains no secret values.

## Proposed operating design (not deployed)

The durable queue is intentionally not a process-local substitute. The planned
AgentOS settings are:

| Setting | Planned value | Reason |
| --- | --- | --- |
| durable queue / source of truth | `durable=True`, existing Cloud SQL/PostgreSQL | Accepted work survives a replica restart. |
| Redis coordination | managed shared Redis, prefix `samurai:production:v1`; Cloud Run Direct VPC egress with `private-ranges-only`, no Serverless VPC Access connector | Cross-replica live events and cancellation; Redis is coordination, not queue truth. Direct VPC is the provider-recommended Cloud Run path and avoids managed connector instances. |
| deployment affinity | `deployment_id="samurai-production-v1"` | Preserve the identifier across compatible revisions; drain/migrate before changing it. |
| admission and concurrency | one active job per company; `max_concurrency=2` per replica; `max_queue_depth=10` fleet-wide | A Cloud Run replica limit is not a durable global admission control. |
| attempts | `max_attempts=2`, `retry_delay_seconds=30` | Native jittered exponential delay; a retry can repeat provider charges and side effects until later idempotency work is complete. |
| run timeout | `480` seconds | Seven configured 60-second model timeouts plus 60 seconds for parent/database cleanup. |
| shutdown/claiming | `stop_timeout_seconds=5`, `lock_grace_seconds=60`, `poll_interval=1` | Graceful stop remains strictly below the lock grace. |
| retention | `retention_seconds=86400` | Keep terminal queue evidence for one day. |

These values match the currently pinned `agno==3.1.2` queue contract: durable
queues support per-replica concurrency, fleet queue depth, attempts, native
jittered retry delay, timeout, deployment affinity, lock grace, poll interval,
retention, and a shutdown window. At the 12 October design snapshot, queue and
Redis configuration had not been implemented. The current local implementation
now defines `create_queue_config` in `backend/src/samurai/config.py`, including
`durable=True`, and has [local acceptance evidence](local-acceptance.md). This
cost design still does not establish a deployed queue or current cloud settings.

For costing only, the target backend shape is one vCPU and 2 GiB memory. The
deployment guide records that as the intended initial allocation, but the
selected live `gcloud` projection did not return explicit CPU/memory limits.
The deployment task must set the values explicitly and re-read them; this
estimate must not be used to infer the current allocation.

## Proposed gross cost and known incremental cost (USD)

Cloud Run Mumbai is Tier 1. Its published instance-based default rates are
$0.000018/vCPU-second and $0.000002/GiB-second. Instance-based CPU is charged
for an instance's whole lifecycle, including idle time, so the minimum instance
has a real recurring floor. The monthly calculations use 730 hours = 2,628,000
seconds and deliberately apply no free tier or discount.

| Item | Formula | One-month estimate | Cost treatment and boundary |
| --- | --- | ---: | --- |
| One continuously allocated backend instance | `2,628,000 × (1 × 0.000018 + 2 × 0.000002)` | $57.82 | Gross proposed floor for `min-instances=1`; it replaces an existing backend allocation, so it is not by itself an incremental cost. Excludes requests and egress. |
| Second backend instance if continuously active | same formula | $57.82 additional | Gross sustained two-instance capacity; a `max-instances=2` limit is not a hard bill cap. |
| Managed Redis coordination | 1 GiB Basic M1 × `$0.049/GiB-hour` × 730 hours | $35.77 | Known new recurring cost. Basic M1 is sufficient only because PostgreSQL remains queue truth. It is not an HA Redis design. |
| Direct VPC egress | no Serverless VPC Access connector | no separate connector-instance baseline | Direct VPC has no managed connector instance and its network cost scales with the service. This is not a zero-traffic-cost claim; the VPC/subnet, placement, and traffic rate remain blocked. |
| Post-change gross recurring floor | one backend floor + Redis | **$93.59/month** | Before unknown variable charges. |
| Post-change sustained two-instance gross | two backends + Redis | **$151.40/month** | Capacity scenario, not a cap or forecast. |
| One temporary Cloud SQL restore drill | `1 hour × $0.035` (`db-g1-small`) + `10 GiB × $0.000232877/GiB-hour` = `$0.03732877` | **$0.04 minimum** | The source is zonal PD-SSD, so this uses the ordinary Storage rate, not the HA Storage rate. A single target is created later, observed for at most 60 minutes, then deleted. Actual elapsed time and any backup/log/network charge are recorded separately. |

The Redis figure uses the smallest documented provisioned capacity tier. Google
charges Redis from creation whether it is used or not. The restore estimate
uses the observed source tier and disk size; PITR creates a new target and the
target inherits source settings. It is a bounded drill estimate only, not an
authorization to restore.

## Current versus incremental and unresolved charges

The current backend request traffic, existing Cloud SQL compute/storage,
frontend, backups, Artifact Registry, and Gemini usage are **existing costs**;
this task did not retrieve billing-account usage and does not estimate them as
zero. Redis is the only fully identified new recurring resource at $35.77/month.
The backend's actual incremental cost is not computable from this inventory:
the proposed instance-based allocation replaces existing backend usage, so it
is `proposed billed instance time − current billed backend usage`. The figures
above are gross post-change capacity costs, not that difference. The restore
drill is a one-time incremental item after approval.

The following have no safe total yet and must remain visible in any approval:

- Gemini input/output token price and actual tokens: bounded by the 60-second
  model timeout, seven-timeout child deadline, configured tool limit, and at
  most two queue attempts, but token volume and provider price were not
  retrieved. No provider call was made.
- Redis network path: **Direct VPC egress** with `private-ranges-only` is the
  selected design. Its exact same-region VPC/subnet, `/26` capacity, firewall,
  and data-transfer rate cannot be read because `compute.googleapis.com` is
  disabled. Do not provision Redis or call the traffic charge zero until that
  prerequisite is approved and inspected. A Serverless VPC Access connector is
  excluded because it introduces managed connector instances and fixed cost.
- Cloud Run request count, cross-region egress, Cloud SQL backup/log/storage
  growth, and actual restore duration. Same-region Google-resource transfer can
  be free only when the final network path and regions satisfy the provider's
  pricing conditions.

## Approval and cleanup gate

Before any paid configuration or provider run, present the $93.59 gross
post-change floor, $151.40 sustained two-instance scenario, $35.77 known new
Redis charge, the $0.04-or-more restore drill, and the unresolved variables for
explicit approval. An approval must name the resource configuration and test
duration; it cannot be inferred from this document or from a billing alert.

The Redis implementation is additionally blocked until an approved read-only
network inventory identifies an `asia-south1` VPC/subnet with `/26` or larger
capacity and the required firewall path. The deployment must then set Direct
VPC egress to `private-ranges-only` and read it back. No Serverless VPC Access
connector is part of this design.

After an approved restore drill, delete only the discovered temporary target
whose name begins with `samurai-recovery-drill-`, then retain a sanitized
inventory and measured duration/cost receipt. Do not delete the source
`samurai-postgres`, its backups, or unrelated resources.

## Authoritative sources consulted 12 October 2026

- [Cloud Run pricing](https://cloud.google.com/run/pricing) — Mumbai is Tier 1;
  the **Services (Instance-based billing)** table gives the $0.000018
  vCPU-second and $0.000002 GiB-second rates used above.
- [Cloud Run billing settings](https://cloud.google.com/run/docs/configuring/billing-settings)
  — instance-based CPU exists for the instance lifecycle and minimum instances
  keep CPU available outside requests.
- [Memorystore for Redis pricing](https://cloud.google.com/memorystore/docs/redis/pricing)
  — the Basic M1 (1–4 GiB) table rate is $0.049/GiB-hour and the service bills
  provisioned capacity from creation.
- [Cloud SQL pricing](https://cloud.google.com/sql/pricing) — the shared-core
  `db-g1-small` table rate is $0.035/hour; the non-HA **Storage** table rate is
  $0.000232877/GiB-hour. The $0.000465753/GiB-hour **HA Storage** rate is not
  applicable to the observed zonal source.
- [Cloud SQL restore overview](https://cloud.google.com/sql/docs/postgres/backup-recovery/restore)
  — PITR creates a new target that inherits source settings.
- [Cloud Run Direct VPC egress](https://cloud.google.com/run/docs/configuring/vpc-direct-vpc)
  and [Cloud Run to Memorystore Redis](https://cloud.google.com/memorystore/docs/redis/connect-redis-instance-cloud-run)
  — Direct VPC egress avoids a connector; the recommended Redis connection
  route requires access to the authorized VPC network.
- [Agno durable queue documentation](https://docs.agno.com/agent-os/background-execution/durable-queue)
  and [multi-replica guidance](https://docs.agno.com/agent-os/background-execution/multi-replica)
  — durable PostgreSQL queue with Redis coordination and timing controls.
