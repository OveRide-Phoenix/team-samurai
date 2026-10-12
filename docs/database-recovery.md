# Database recovery verification

`backend/scripts/verify_database_recovery.py` performs a PostgreSQL 18 backup and restore
into a separate disposable database. Local mode never creates, drops, or overwrites a
database. The operator must create an empty target whose name starts with
`samurai_recovery_` and remove it after reviewing the evidence.

The local runner requires PostgreSQL 18 `pg_dump` and `pg_restore` on `PATH`. Put database
URLs in environment variables so credentials do not appear in command arguments or output:

```bash
export SAMURAI_RECOVERY_SOURCE_URL='postgresql://USER:PASSWORD@HOST:PORT/SOURCE_DB'
export SAMURAI_RECOVERY_TARGET_URL='postgresql://USER:PASSWORD@HOST:PORT/samurai_recovery_TARGET'
uv run --directory backend python scripts/verify_database_recovery.py \
  --mode local \
  --source-env SAMURAI_RECOVERY_SOURCE_URL \
  --target-env SAMURAI_RECOVERY_TARGET_URL \
  --evidence-dir ../.omo/evidence/readiness/task-8
```

The runner refuses identical source and target identities, targets outside the
`samurai_recovery_` namespace, non-empty targets, missing assertion tables, and PostgreSQL
client versions other than 18. `pg_dump` and `pg_restore` receive connection secrets only
through their process environment. Their raw output is not copied into evidence.

Successful `restore.json` evidence has `status: completed` and `completion_proof: true` only
after all of these checks pass:

- every public table has the same source and restored row count;
- each accepted `samurai_work_intents` row resolves to an `agno_sessions` row with the same
  owner;
- at least one accepted intent exists; its child session retains history through the accepted
  revision; and `accepted_artifact_ids` exactly matches the canonical artifact slice from the
  intent's expected revision through its accepted revision. Later child progress does not
  invalidate an earlier accepted window.

`--dry-run` validates identities and writes a sanitized `status: planned` record with
`completion_proof: false`. It does not connect to either database and cannot be cited as a
restore result.

Cloud mode is preparation for a separately authorized Task 11 drill. Its boundary is fixed to
project `samurai-ai-company-2026`, region `asia-south1`, and target prefix
`samurai-recovery-drill-`. The source and target instance names must be explicit and different.
The runner uses `gcloud sql instances list` to prove the exact target is absent before any
create command. It refuses every other project, region, prefix, existing target, or missing
execution gate.

A cloud `--dry-run` performs read-only `gcloud` discovery of the source and target. It chooses
PITR when the source reports PITR enabled and requires an RFC3339 `--point-in-time`; otherwise
it selects the latest successful backup. The receipt remains `status: planned` with
`completion_proof: false`.

```bash
uv run --directory backend python scripts/verify_database_recovery.py \
  --mode cloud \
  --project samurai-ai-company-2026 \
  --region asia-south1 \
  --source-instance samurai-postgres \
  --target-prefix samurai-recovery-drill- \
  --target-instance samurai-recovery-drill-UNIQUE \
  --point-in-time 2026-10-12T00:00:00Z \
  --evidence-dir ../.omo/evidence/readiness/task-11 \
  --dry-run
```

Without `--dry-run` or `--execute-cloud-restore`, cloud mode exits with code 2 after writing a
blocked receipt and does not invoke `gcloud`. The execution gate enables a clone or backup
restore only inside the fixed boundary. After target observation, and after any post-create
failure, the runner inventories the exact target and deletes only that target. Its receipt
records whether cleanup succeeded. Raw provider output is omitted from receipts and errors.

The create, observation, failure, and cleanup paths are covered with a fake `gcloud`
executable. No real Cloud SQL mutation or provider call was made during implementation. These
tests prove CLI preparation only; they do not satisfy the authorized live drill, retention
check, measured recovery time, restored application checks, or independent Cloud SQL evidence
required by Task 11.

The local baseline/candidate schema matrix is recorded in
`.omo/evidence/readiness/task-8/migration-compatibility-matrix.md`. It proves c84 reads on the
expanded schema, candidate reads of old/new sessions, transactional DDL rollback and retry,
and restored binding recovery. The separate Task 6 pending/running worker-restart row must pass
before the full matrix is complete. Do not describe the local drills as Cloud SQL, PITR, or
production recovery proof.

After a drill, inventory the exact disposable container, volume, source database, target
database, and bound port. Remove only the uniquely named `samurai-readiness-restore-*`
resources created for the drill, recheck that the port is free, and retain a sanitized cleanup
receipt. Never remove the normal Samurai PostgreSQL volume or any Reporting resource.
