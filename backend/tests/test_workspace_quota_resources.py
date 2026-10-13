from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, func, select

from samurai.quota import QuotaResource, WorkspaceQuota, WorkspaceQuotaExceededError
from samurai.workspace_directory import WorkspaceDirectory

if TYPE_CHECKING:
    from collections.abc import Callable

    from samurai.execution_state import SamuraiPostgresDb

pytest_plugins = ("tests.test_workspace_quota",)


def _metadata_table(database: SamuraiPostgresDb, name: str) -> Table:
    return Table(
        name,
        MetaData(schema=database.db_schema),
        autoload_with=database.db_engine,
    )


def _commit_or_conflict(operation: Callable[[], None]) -> str:
    try:
        operation()
    except WorkspaceQuotaExceededError:
        return "conflict"
    return "committed"


def test_file_count_and_storage_bytes_share_one_atomic_boundary(
    quota_database: SamuraiPostgresDb,
) -> None:
    # Given 101 synchronized one-MiB metadata writes for one workspace.
    workspace_id = (
        WorkspaceDirectory(quota_database).create_workspace("owner", "File boundary").workspace_id
    )
    files = _metadata_table(quota_database, "samurai_files")
    quota = WorkspaceQuota(quota_database.db_schema)
    barrier = Barrier(101)

    def store_file(index: int) -> str:
        _ = barrier.wait()

        def transaction() -> None:
            with quota_database.db_engine.begin() as connection:
                quota.reserve_file(connection, workspace_id, 1024 * 1024)
                now = 1_800_000_000 + index
                _ = connection.execute(
                    files.insert().values(
                        file_id=uuid4(),
                        workspace_id=workspace_id,
                        company_id=None,
                        created_by="owner",
                        state="ready",
                        display_name=f"file-{index}",
                        media_type="text/plain",
                        byte_size=1024 * 1024,
                        content_sha256=f"{index:064x}",
                        storage_key=f"quota/{index}",
                        rejection_code=None,
                        created_at=now,
                        updated_at=now,
                        deleted_at=None,
                    )
                )

        return _commit_or_conflict(transaction)

    # When every contender crosses the same transaction-owned quota lock.
    with ThreadPoolExecutor(max_workers=101) as executor:
        outcomes = tuple(executor.map(store_file, range(101)))

    # Then storage and row counts stop together at 100 MiB and 100 files.
    assert outcomes.count("committed") == 100
    assert outcomes.count("conflict") == 1
    quotas = _metadata_table(quota_database, "samurai_workspace_quotas")
    with quota_database.db_engine.connect() as connection:
        row = (
            connection.execute(
                select(
                    quotas.c.file_count,
                    quotas.c.stored_bytes,
                    func.count(files.c.file_id).label("rows"),
                    func.coalesce(func.sum(files.c.byte_size), 0).label("bytes"),
                )
                .select_from(quotas.join(files, files.c.workspace_id == quotas.c.workspace_id))
                .where(quotas.c.workspace_id == workspace_id)
                .group_by(quotas.c.file_count, quotas.c.stored_bytes)
            )
            .mappings()
            .one()
        )
    assert dict(row) == {
        "file_count": 100,
        "stored_bytes": 100 * 1024 * 1024,
        "rows": 100,
        "bytes": 100 * 1024 * 1024,
    }


def test_failed_file_metadata_write_rolls_back_reservation(
    quota_database: SamuraiPostgresDb,
) -> None:
    # Given a valid reservation followed by a storage metadata failure.
    workspace_id = (
        WorkspaceDirectory(quota_database).create_workspace("owner", "File rollback").workspace_id
    )
    quota = WorkspaceQuota(quota_database.db_schema)

    # When the surrounding transaction aborts after quota admission.
    def fail_after_reservation() -> None:
        with quota_database.db_engine.begin() as connection:
            quota.reserve_file(connection, workspace_id, 1024)
            message = "storage write failed"
            raise RuntimeError(message)

    with pytest.raises(RuntimeError, match="storage write failed"):
        fail_after_reservation()

    # Then no reservation leaks and an oversized single file still conflicts.
    quotas = _metadata_table(quota_database, "samurai_workspace_quotas")
    with quota_database.db_engine.connect() as connection:
        counters = connection.execute(
            select(quotas.c.file_count, quotas.c.stored_bytes).where(
                quotas.c.workspace_id == workspace_id
            )
        ).one()
    assert tuple(counters) == (0, 0)
    with (
        quota_database.db_engine.begin() as connection,
        pytest.raises(WorkspaceQuotaExceededError),
    ):
        quota.reserve_file(connection, workspace_id, 10 * 1024 * 1024 + 1)


def test_schedule_and_knowledge_metadata_reservations_match_committed_rows(
    quota_database: SamuraiPostgresDb,
) -> None:
    # Given 21 schedule contenders and 999 existing knowledge chunks.
    directory = WorkspaceDirectory(quota_database)
    workspace_id = directory.create_workspace("owner", "Metadata boundaries").workspace_id
    company_id = directory.create_company("owner", workspace_id).company_id
    schedules = _metadata_table(quota_database, "samurai_schedules")
    chunks = _metadata_table(quota_database, "samurai_knowledge_chunks")
    quota = WorkspaceQuota(quota_database.db_schema)
    schedule_barrier = Barrier(21)

    def add_schedule(index: int) -> str:
        _ = schedule_barrier.wait()

        def transaction() -> None:
            with quota_database.db_engine.begin() as connection:
                quota.reserve(connection, workspace_id, QuotaResource.SCHEDULE)
                _ = connection.execute(
                    schedules.insert().values(
                        schedule_id=uuid4(),
                        workspace_id=workspace_id,
                        company_id=company_id,
                        created_by="owner",
                        creator_authorization_epoch=1,
                        cadence="daily",
                        timezone="UTC",
                        action_kind="task",
                        payload={},
                        pinned_revision=0,
                        enabled=True,
                        next_run_at=1_800_000_000 + index,
                        last_run_at=None,
                        created_at=1_800_000_000,
                        updated_at=1_800_000_000,
                    )
                )

        return _commit_or_conflict(transaction)

    # When schedule admission races and two chunks contend for the last slot.
    with ThreadPoolExecutor(max_workers=21) as executor:
        schedule_outcomes = tuple(executor.map(add_schedule, range(21)))
    with quota_database.db_engine.begin() as connection:
        quota.reserve(connection, workspace_id, QuotaResource.KNOWLEDGE_CHUNK, amount=999)
        _ = connection.execute(
            chunks.insert(),
            [
                {
                    "chunk_id": uuid4(),
                    "workspace_id": workspace_id,
                    "company_id": company_id,
                    "file_id": None,
                    "artifact_id": None,
                    "source_revision": 0,
                    "ordinal": index,
                    "content": f"chunk-{index}",
                    "content_sha256": f"{index:064x}",
                    "created_at": 1_800_000_000,
                }
                for index in range(999)
            ],
        )
    chunk_barrier = Barrier(2)

    def add_chunk(index: int) -> str:
        _ = chunk_barrier.wait()

        def transaction() -> None:
            with quota_database.db_engine.begin() as connection:
                quota.reserve(connection, workspace_id, QuotaResource.KNOWLEDGE_CHUNK)
                _ = connection.execute(
                    chunks.insert().values(
                        chunk_id=uuid4(),
                        workspace_id=workspace_id,
                        company_id=company_id,
                        file_id=None,
                        artifact_id=None,
                        source_revision=0,
                        ordinal=999 + index,
                        content=f"final-{index}",
                        content_sha256=f"{1000 + index:064x}",
                        created_at=1_800_000_000,
                    )
                )

        return _commit_or_conflict(transaction)

    with ThreadPoolExecutor(max_workers=2) as executor:
        chunk_outcomes = tuple(executor.map(add_chunk, range(2)))

    # Then both counters equal their committed metadata rows at fixed limits.
    assert schedule_outcomes.count("committed") == 20
    assert schedule_outcomes.count("conflict") == 1
    assert chunk_outcomes.count("committed") == 1
    assert chunk_outcomes.count("conflict") == 1
    quotas = _metadata_table(quota_database, "samurai_workspace_quotas")
    with quota_database.db_engine.connect() as connection:
        counters = connection.execute(
            select(quotas.c.schedule_count, quotas.c.knowledge_chunk_count).where(
                quotas.c.workspace_id == workspace_id
            )
        ).one()
        schedule_rows = connection.execute(
            select(func.count())
            .select_from(schedules)
            .where(schedules.c.workspace_id == workspace_id, schedules.c.enabled)
        ).scalar_one()
        chunk_rows = connection.execute(
            select(func.count()).select_from(chunks).where(chunks.c.workspace_id == workspace_id)
        ).scalar_one()
    assert tuple(counters) == (schedule_rows, chunk_rows) == (20, 1000)
