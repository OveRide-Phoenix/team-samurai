from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import TYPE_CHECKING

from agno.db.schemas.jobs import QueuedJob
from pydantic import TypeAdapter
from sqlalchemy import MetaData, Table, func, select, text

from samurai.execution_state import (
    WORK_INTENT_METADATA_KEY,
    ApprovedStage,
    WorkIntentInput,
    WorkOperation,
)
from samurai.quota import WorkspaceQuota
from samurai.schema import FounderPlatformMigrator
from samurai.workspace_directory import WorkspaceDirectory

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from samurai.execution_state import SamuraiPostgresDb

pytest_plugins = ("tests.test_workspace_quota",)
INT_ADAPTER = TypeAdapter(int)


def _run_while_quota_locked(
    database: SamuraiPostgresDb,
    workspace_id: UUID,
    left: Callable[[], object],
    right: Callable[[], object],
) -> tuple[object, object]:
    connection = database.db_engine.connect()
    transaction = connection.begin()
    WorkspaceQuota(database.db_schema).lock(connection, workspace_id)
    barrier = Barrier(3)

    def synchronized(operation: Callable[[], object]) -> object:
        _ = barrier.wait()
        return operation()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(synchronized, left),
            executor.submit(synchronized, right),
        )
        _ = barrier.wait()
        transaction.commit()
        outcomes = (futures[0].result(timeout=10), futures[1].result(timeout=10))
    connection.close()
    return outcomes


def _shared_job(workspace_id: UUID, company_id: UUID) -> tuple[dict[str, object], WorkIntentInput]:
    intent = WorkIntentInput(
        owner_id="owner",
        parent_session_id="reconcile-parent",
        child_session_id="reconcile-child",
        workspace_id=workspace_id,
        authorization_epoch=1,
        company_id=company_id,
        operation=WorkOperation.JOURNEY,
        stage=ApprovedStage.BRIEF,
        expected_revision=0,
        approved_input={"idea": "reconciliation"},
    )
    job = QueuedJob(
        id="reconcile-job",
        component_type="agent",
        component_id="samurai",
        session_id=intent.parent_session_id,
        user_id=intent.owner_id,
        payload={
            "input": "Build my business",
            "kwargs": {"metadata": {WORK_INTENT_METADATA_KEY: intent.model_dump(mode="json")}},
        },
        max_attempts=2,
        idempotency_key="reconcile-key",
    ).to_dict()
    return job, intent


def _counts(database: SamuraiPostgresDb, workspace_id: UUID) -> tuple[int, int, int, int]:
    metadata = MetaData(schema=database.db_schema)
    quotas = Table("samurai_workspace_quotas", metadata, autoload_with=database.db_engine)
    companies = Table("samurai_companies", metadata, autoload_with=database.db_engine)
    intents = Table(
        database.work_intent_table_name,
        metadata,
        autoload_with=database.db_engine,
    )
    with database.db_engine.connect() as connection:
        quota_counts = connection.execute(
            select(quotas.c.company_count, quotas.c.active_job_count).where(
                quotas.c.workspace_id == workspace_id
            )
        ).one()
        company_rows = connection.execute(
            select(func.count())
            .select_from(companies)
            .where(companies.c.workspace_id == workspace_id)
        ).scalar_one()
        active_rows = connection.execute(
            select(func.count())
            .select_from(intents)
            .where(
                intents.c.workspace_id == workspace_id,
                intents.c.active_job_reserved,
            )
        ).scalar_one()
    return (
        INT_ADAPTER.validate_python(quota_counts[0]),
        INT_ADAPTER.validate_python(company_rows),
        INT_ADAPTER.validate_python(quota_counts[1]),
        INT_ADAPTER.validate_python(active_rows),
    )


def test_reapply_serializes_with_company_admission_without_lost_counter(
    quota_database: SamuraiPostgresDb,
) -> None:
    # Given migration reapply and live admission waiting on one workspace quota lock.
    directory = WorkspaceDirectory(quota_database)
    workspace_id = directory.create_workspace("owner", "Reconcile admission").workspace_id
    migrator = FounderPlatformMigrator(quota_database.db_engine, schema=quota_database.db_schema)

    # When both operations resume together under a bounded future timeout.
    _ = _run_while_quota_locked(
        quota_database,
        workspace_id,
        migrator.apply,
        lambda: directory.create_company("owner", workspace_id),
    )

    # Then either serialization order leaves the reconciled count equal to rows.
    assert _counts(quota_database, workspace_id) == (1, 1, 0, 0)


def test_reapply_serializes_with_terminal_release_without_deadlock_or_leak(
    quota_database: SamuraiPostgresDb,
) -> None:
    # Given one active shared job and reapply/cancellation waiting on its quota lock.
    directory = WorkspaceDirectory(quota_database)
    workspace_id = directory.create_workspace("owner", "Reconcile terminal").workspace_id
    company_id = directory.create_company("owner", workspace_id).company_id
    job, intent = _shared_job(workspace_id, company_id)
    assert quota_database.enqueue_work_job(job, intent)["accepted"] is True
    migrator = FounderPlatformMigrator(quota_database.db_engine, schema=quota_database.db_schema)

    # When reconciliation and terminal release resume together with a ten-second bound.
    outcomes = _run_while_quota_locked(
        quota_database,
        workspace_id,
        migrator.apply,
        lambda: quota_database.cancel_job("reconcile-job"),
    )

    # Then both finish, cancellation commits, and the counter equals live reservations.
    assert True in outcomes
    assert _counts(quota_database, workspace_id) == (1, 1, 0, 0)


def test_intent_upgrade_serializes_with_terminal_release_without_deadlock(
    quota_database: SamuraiPostgresDb,
) -> None:
    # Given an active shared job and intent upgrade/cancellation waiting on its quota lock.
    directory = WorkspaceDirectory(quota_database)
    workspace_id = directory.create_workspace("owner", "Upgrade terminal").workspace_id
    company_id = directory.create_company("owner", workspace_id).company_id
    job, intent = _shared_job(workspace_id, company_id)
    assert quota_database.enqueue_work_job(job, intent)["accepted"] is True

    # When upgrade and terminal release resume together with a ten-second bound.
    outcomes = _run_while_quota_locked(
        quota_database,
        workspace_id,
        quota_database.ensure_work_intents_table,
        lambda: quota_database.cancel_job("reconcile-job"),
    )

    # Then both finish, cancellation commits, and the counter equals live reservations.
    assert True in outcomes
    assert _counts(quota_database, workspace_id) == (1, 1, 0, 0)


def test_upgrade_backfills_live_job_before_creating_missing_quota_row(
    quota_database: SamuraiPostgresDb,
) -> None:
    # Given a pre-Task7 shared workspace, queued job, and no quota row/reservation column.
    directory = WorkspaceDirectory(quota_database)
    workspace_id = directory.create_workspace("owner", "Legacy live job").workspace_id
    company_id = directory.create_company("owner", workspace_id).company_id
    job, intent = _shared_job(workspace_id, company_id)
    assert quota_database.enqueue_work_job(job, intent)["accepted"] is True
    quotas = Table(
        "samurai_workspace_quotas",
        MetaData(schema=quota_database.db_schema),
        autoload_with=quota_database.db_engine,
    )
    intent_table_name = f'"{quota_database.db_schema}".samurai_work_intents'
    with quota_database.db_engine.begin() as connection:
        _ = connection.execute(
            text(f'DROP INDEX "{quota_database.db_schema}".uq_samurai_reserved_company_work')
        )
        _ = connection.execute(
            text(f"ALTER TABLE {intent_table_name} DROP COLUMN active_job_reserved")
        )
        _ = connection.execute(quotas.delete().where(quotas.c.workspace_id == workspace_id))

    # When intent upgrade runs before migration creates and reconciles the missing row.
    quota_database.ensure_work_intents_table()
    migrator = FounderPlatformMigrator(quota_database.db_engine, schema=quota_database.db_schema)
    _ = migrator.apply()
    quota_database.ensure_work_intents_table()
    _ = migrator.apply()

    # Then one live intent owns one active slot after repeated upgrade and reconciliation.
    assert _counts(quota_database, workspace_id) == (1, 1, 1, 1)
