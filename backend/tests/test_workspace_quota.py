from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import MetaData, Table, func, select
from sqlalchemy.schema import DropSchema

from samurai.company_store_contracts import WorkspaceRole
from samurai.execution_state import SamuraiPostgresDb
from samurai.schema import FounderPlatformMigrator
from samurai.workspace_directory import WorkspaceDirectory

pytest_plugins = ("tests.company_store_support",)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


class _QuotaRow(BaseModel):
    company_limit: int
    member_limit: int
    file_limit: int
    stored_bytes_limit: int
    per_file_bytes_limit: int
    active_job_limit: int
    schedule_limit: int
    knowledge_chunk_limit: int
    company_count: int
    member_count: int
    file_count: int
    stored_bytes: int
    active_job_count: int
    schedule_count: int
    knowledge_chunk_count: int


@pytest.fixture
def quota_database(postgres_url: str) -> Iterator[SamuraiPostgresDb]:
    schema = f"founder_t07_{uuid4().hex}"
    database = SamuraiPostgresDb(id=schema, db_url=postgres_url, db_schema=schema)
    database.ensure_work_intents_table()
    _ = FounderPlatformMigrator(database.db_engine, schema=schema).apply()
    yield database
    with database.db_engine.begin() as connection:
        _ = connection.execute(DropSchema(schema, cascade=True, if_exists=True))
    database.close()


def _status(operation: Callable[[], object]) -> int:
    try:
        _ = operation()
    except HTTPException as error:
        return error.status_code
    return 201


def _quota_row(database: SamuraiPostgresDb, workspace_id: UUID) -> _QuotaRow:
    quotas = Table(
        "samurai_workspace_quotas",
        MetaData(schema=database.db_schema),
        autoload_with=database.db_engine,
    )
    with database.db_engine.connect() as connection:
        row = (
            connection.execute(select(quotas).where(quotas.c.workspace_id == workspace_id))
            .mappings()
            .one()
        )
    return _QuotaRow.model_validate(row)


def test_workspace_creation_owns_fixed_server_quota_defaults(
    quota_database: SamuraiPostgresDb,
) -> None:
    # Given the real workspace directory over the migrated schema.
    directory = WorkspaceDirectory(quota_database)

    # When a founder creates a workspace.
    workspace = directory.create_workspace("owner", "Quota defaults")

    # Then the transaction creates its immutable server-owned quota row.
    quota = _quota_row(quota_database, workspace.workspace_id)
    assert quota.model_dump() == {
        "company_limit": 10,
        "member_limit": 10,
        "file_limit": 100,
        "stored_bytes_limit": 100 * 1024 * 1024,
        "per_file_bytes_limit": 10 * 1024 * 1024,
        "active_job_limit": 3,
        "schedule_limit": 20,
        "knowledge_chunk_limit": 1000,
        "company_count": 0,
        "member_count": 1,
        "file_count": 0,
        "stored_bytes": 0,
        "active_job_count": 0,
        "schedule_count": 0,
        "knowledge_chunk_count": 0,
    }


def test_concurrent_company_reservations_stop_at_workspace_limit(
    quota_database: SamuraiPostgresDb,
) -> None:
    # Given eleven company reservations synchronized for one workspace.
    directory = WorkspaceDirectory(quota_database)
    workspace_id = directory.create_workspace("owner", "Company boundary").workspace_id
    barrier = Barrier(11)

    def reserve() -> int:
        _ = barrier.wait()
        return _status(lambda: directory.create_company("owner", workspace_id))

    # When all contenders race the durable admission transaction.
    with ThreadPoolExecutor(max_workers=11) as executor:
        futures = tuple(executor.submit(reserve) for _index in range(11))
        statuses = tuple(future.result() for future in futures)

    # Then ten rows commit, one request conflicts, and the counter matches rows.
    assert statuses.count(201) == 10
    assert statuses.count(409) == 1
    companies = Table(
        "samurai_companies",
        MetaData(schema=quota_database.db_schema),
        autoload_with=quota_database.db_engine,
    )
    with quota_database.db_engine.connect() as connection:
        committed = connection.execute(
            select(func.count())
            .select_from(companies)
            .where(companies.c.workspace_id == workspace_id)
        ).scalar_one()
    assert committed == 10
    assert _quota_row(quota_database, workspace_id).company_count == committed


def test_concurrent_member_reactivation_and_creation_stop_at_workspace_limit(
    quota_database: SamuraiPostgresDb,
) -> None:
    # Given eleven distinct additions racing for nine remaining active-member slots.
    directory = WorkspaceDirectory(quota_database)
    workspace_id = directory.create_workspace("owner", "Member boundary").workspace_id
    barrier = Barrier(11)

    def add(index: int) -> int:
        _ = barrier.wait()
        return _status(
            lambda: directory.put_member(
                "owner", workspace_id, f"member-{index}", WorkspaceRole.VIEWER
            )
        )

    # When the owner submits all membership writes concurrently.
    with ThreadPoolExecutor(max_workers=11) as executor:
        statuses = tuple(executor.map(add, range(11)))

    # Then only nine additions commit and the counter equals active membership rows.
    assert statuses.count(201) == 9
    assert statuses.count(409) == 2
    memberships = Table(
        "samurai_workspace_memberships",
        MetaData(schema=quota_database.db_schema),
        autoload_with=quota_database.db_engine,
    )
    with quota_database.db_engine.connect() as connection:
        committed = connection.execute(
            select(func.count())
            .select_from(memberships)
            .where(memberships.c.workspace_id == workspace_id, memberships.c.active)
        ).scalar_one()
    assert committed == 10
    assert _quota_row(quota_database, workspace_id).member_count == committed
