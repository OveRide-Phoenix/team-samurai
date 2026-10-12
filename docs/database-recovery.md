# Database recovery verification

`backend/scripts/verify_database_recovery.py` performs a provider-free PostgreSQL 18
backup and restore into a separate disposable database. It never creates, drops, or
overwrites a database. The operator must create an empty target whose name starts with
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

`--mode cloud` is intentionally inert before task 11 cost and mutation approval. Without
`--dry-run` it exits with code 2 after writing `status: blocked`,
`cloud_mutation_attempted: false`, and `completion_proof: false`. It does not invoke `gcloud`
or any provider API.

The standalone local drill validates runner mechanics against a PostgreSQL 18 fixture. The
final baseline/candidate schema compatibility matrix remains pending until task 4's additive
queue/state schema is integrated. Do not describe the fixture drill as migration, Cloud SQL,
PITR, or production recovery proof.

After a drill, inventory the exact disposable container, volume, source database, target
database, and bound port. Remove only the uniquely named `samurai-readiness-restore-*`
resources created for the drill, recheck that the port is free, and retain a sanitized cleanup
receipt. Never remove the normal Samurai PostgreSQL volume or any Reporting resource.
