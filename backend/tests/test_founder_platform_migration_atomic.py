from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

import pytest
from agno.db.postgres import PostgresDb
from agno.session.workflow import WorkflowSession
from pydantic import TypeAdapter
from sqlalchemy import MetaData, Table, create_engine, inspect, select
from sqlalchemy.schema import DropSchema

from samurai.contracts import CompanyState, create_company_state
from samurai.schema import FounderPlatformMigrator
from samurai.schema_contracts import LegacyMigrationError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

JSON_OBJECT = TypeAdapter(dict[str, object])


@pytest.fixture
def postgres_url() -> str:
    value = os.environ.get("SAMURAI_TEST_DATABASE_URL")
    if value is None:
        pytest.skip("SAMURAI_TEST_DATABASE_URL is required for migration tests")
    return value


@pytest.fixture
def migration_database(postgres_url: str) -> Iterator[tuple[Engine, str]]:
    schema = f"founder_t04_atomic_{uuid4().hex}"
    engine = create_engine(postgres_url)
    yield engine, schema
    with engine.begin() as connection:
        _ = connection.execute(DropSchema(schema, cascade=True, if_exists=True))
    engine.dispose()


def _state(parent_session_id: str, revision: int = 0) -> CompanyState:
    state = create_company_state(
        parent_session_id,
        created_at=datetime(2026, 10, 13, 6, 30, tzinfo=UTC),
    )
    return state.model_copy(update={"current_revision": revision})


def _seed(
    postgres_url: str,
    schema: str,
    *,
    owner_id: str | None,
    parent_session_id: str,
    state: CompanyState,
) -> None:
    database = PostgresDb(db_url=postgres_url, db_schema=schema)
    _ = database.upsert_session(
        WorkflowSession(
            session_id=f"child-{parent_session_id}",
            user_id=owner_id,
            workflow_id="company-journey",
            session_data={"session_state": {"company": state.model_dump(mode="json")}},
            created_at=1_760_336_200,
            updated_at=1_760_336_260,
        )
    )
    database.close()


def _table_names(engine: Engine, schema: str) -> set[str]:
    return set(inspect(engine).get_table_names(schema=schema))


@pytest.mark.parametrize("case", ["missing_owner", "invalid_lineage"])
def test_invalid_legacy_state_rolls_back_schema_and_data(
    migration_database: tuple[Engine, str],
    postgres_url: str,
    case: Literal["missing_owner", "invalid_lineage"],
) -> None:
    # Given a missing owner or a company whose declared revision has no artifacts.
    engine, schema = migration_database
    invalid = _state("broken-parent", revision=1 if case == "invalid_lineage" else 0)
    _seed(
        postgres_url,
        schema,
        owner_id=None if case == "missing_owner" else "owner-a",
        parent_session_id="broken-parent",
        state=invalid,
    )
    before_tables = _table_names(engine, schema)
    with engine.connect() as connection:
        sessions = Table("agno_sessions", MetaData(schema=schema), autoload_with=engine)
        before_state = JSON_OBJECT.validate_python(
            connection.execute(
                select(sessions.c.session_data).where(
                    sessions.c.session_id == "child-broken-parent"
                )
            ).scalar_one()
        )

    # When the migration validates the legacy boundary.
    with pytest.raises(LegacyMigrationError):
        _ = FounderPlatformMigrator(engine, schema=schema).apply()

    # Then transactional DDL/backfill is absent and source JSON is untouched.
    assert _table_names(engine, schema) == before_tables
    with engine.connect() as connection:
        after_state = JSON_OBJECT.validate_python(
            connection.execute(
                select(sessions.c.session_data).where(
                    sessions.c.session_id == "child-broken-parent"
                )
            ).scalar_one()
        )
    assert after_state == before_state


def test_duplicate_company_uuid_is_ambiguous_and_atomic(
    migration_database: tuple[Engine, str], postgres_url: str
) -> None:
    # Given two legacy sessions claiming the same canonical company UUID.
    engine, schema = migration_database
    duplicated = _state("parent-a")
    _seed(
        postgres_url,
        schema,
        owner_id="owner-a",
        parent_session_id="parent-a",
        state=duplicated,
    )
    _seed(
        postgres_url,
        schema,
        owner_id="owner-b",
        parent_session_id="parent-b",
        state=duplicated,
    )
    before_tables = _table_names(engine, schema)

    # When the migration inventories the ambiguous owner/history mapping.
    with pytest.raises(LegacyMigrationError, match="ambiguous duplicate legacy company UUID"):
        _ = FounderPlatformMigrator(engine, schema=schema).apply()

    # Then no founder-platform schema or source rewrite commits.
    assert _table_names(engine, schema) == before_tables
