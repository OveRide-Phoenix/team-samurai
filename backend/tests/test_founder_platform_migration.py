from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from agno.db.postgres import PostgresDb
from agno.session.workflow import WorkflowSession
from pydantic import BaseModel
from sqlalchemy import MetaData, Table, create_engine, func, inspect, select
from sqlalchemy.schema import DropSchema

from samurai.contracts import CompanyState, create_company_state
from samurai.schema import FounderPlatformMigrator
from samurai.schema_contracts import (
    LegacySessionData,
    canonical_state_hash,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

SCRIPT = Path(__file__).parents[1] / "scripts" / "migrate_founder_platform.py"


class _Receipt(BaseModel):
    status: str
    owners: int
    companies: int
    revisions: int
    state_sha256: list[str]


class _MigratedCompany(BaseModel):
    company_id: UUID
    canonical_state: CompanyState
    state_sha256: str
    legacy_session_id: str


class _LegacySnapshot(BaseModel):
    session_id: str
    session_data: dict[str, object]


@pytest.fixture
def postgres_url() -> str:
    value = os.environ.get("SAMURAI_TEST_DATABASE_URL")
    if value is None:
        pytest.skip("SAMURAI_TEST_DATABASE_URL is required for migration tests")
    return value


@pytest.fixture
def migration_database(postgres_url: str) -> Iterator[tuple[Engine, str]]:
    schema = f"founder_t04_{uuid4().hex}"
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
            session_data={
                "legacy_note": "preserve",
                "session_state": {
                    "company": state.model_dump(mode="json"),
                    "unrelated": "preserve",
                },
            },
            created_at=1_760_336_200,
            updated_at=1_760_336_260,
        )
    )
    database.close()


def _table_names(engine: Engine, schema: str) -> set[str]:
    return set(inspect(engine).get_table_names(schema=schema))


def test_dry_run_is_read_only_and_reports_exact_inventory(
    migration_database: tuple[Engine, str], postgres_url: str, tmp_path: Path
) -> None:
    # Given two legacy owners with three valid companies.
    engine, schema = migration_database
    _seed(
        postgres_url,
        schema,
        owner_id="owner-a",
        parent_session_id="parent-a1",
        state=_state("parent-a1"),
    )
    _seed(
        postgres_url,
        schema,
        owner_id="owner-a",
        parent_session_id="parent-a2",
        state=_state("parent-a2"),
    )
    _seed(
        postgres_url,
        schema,
        owner_id="owner-b",
        parent_session_id="parent-b1",
        state=_state("parent-b1"),
    )
    before = _table_names(engine, schema)
    receipt = tmp_path / "dry-run.json"

    # When the real CLI inventories in dry-run mode.
    result = subprocess.run(  # noqa: S603 - fixed interpreter and repository-owned script.
        [
            sys.executable,
            str(SCRIPT),
            "--dry-run",
            "--database-url-env",
            "SAMURAI_MIGRATION_TEST_URL",
            "--schema",
            schema,
            "--receipt",
            str(receipt),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "SAMURAI_MIGRATION_TEST_URL": postgres_url},
    )

    # Then no database object changed and the receipt is an exact inventory.
    assert result.returncode == 0
    assert _table_names(engine, schema) == before
    payload = _Receipt.model_validate_json(receipt.read_bytes())
    assert payload.status == "planned"
    assert payload.owners == 2
    assert payload.companies == 3
    assert payload.revisions == 0
    assert len(payload.state_sha256) == 3


def test_apply_reapply_and_legacy_mirror_are_idempotent(
    migration_database: tuple[Engine, str], postgres_url: str
) -> None:
    # Given the provider-free fixture's two owners and three legacy companies.
    engine, schema = migration_database
    seeded: list[CompanyState] = []
    for owner, parent in (("owner-a", "a-1"), ("owner-a", "a-2"), ("owner-b", "b-1")):
        state = _state(parent)
        seeded.append(state)
        _seed(postgres_url, schema, owner_id=owner, parent_session_id=parent, state=state)
    with engine.connect() as connection:
        sessions = Table("agno_sessions", MetaData(schema=schema), autoload_with=engine)
        legacy_before = {
            row.session_id: row.session_data
            for row in map(
                _LegacySnapshot.model_validate,
                connection.execute(
                    select(sessions.c.session_id, sessions.c.session_data).order_by(
                        sessions.c.session_id
                    )
                ).mappings(),
            )
        }
    migrator = FounderPlatformMigrator(engine, schema=schema)

    # When the ordered migration is applied twice.
    first = migrator.apply()
    second = migrator.apply()
    with engine.connect() as connection:
        tables = tuple(
            Table(name, MetaData(schema=schema), autoload_with=engine)
            for name in (
                "samurai_workspaces",
                "samurai_workspace_memberships",
                "samurai_companies",
                "samurai_schema_migrations",
            )
        )
        counts = tuple(
            connection.execute(select(func.count()).select_from(table)).scalar_one()
            for table in tables
        )
        company_table = tables[2]
        migrated = tuple(
            _MigratedCompany.model_validate(row)
            for row in connection.execute(select(company_table)).mappings()
        )
        legacy_after = {
            row.session_id: row.session_data
            for row in map(
                _LegacySnapshot.model_validate,
                connection.execute(
                    select(sessions.c.session_id, sessions.c.session_data).order_by(
                        sessions.c.session_id
                    )
                ).mappings(),
            )
        }

    # Then the idempotent backfill is byte-equivalent and leaves legacy JSON intact.
    expected = {str(state.context.company_id): canonical_state_hash(state) for state in seeded}
    assert first == second
    assert counts == (2, 2, 3, 1)
    assert {str(row.company_id): row.state_sha256 for row in migrated} == expected
    assert all(row.canonical_state.context.company_id == row.company_id for row in migrated)
    assert legacy_after == legacy_before

    # When canonical state later advances.
    mirrored_state = seeded[0].model_copy(
        update={
            "context": seeded[0].context.model_copy(
                update={"created_at": datetime(2026, 10, 13, 7, 30, tzinfo=UTC)}
            )
        }
    )
    with engine.begin() as connection:
        _ = connection.execute(
            company_table.update()
            .where(company_table.c.company_id == mirrored_state.context.company_id)
            .values(
                canonical_state=mirrored_state.model_dump(mode="json"),
                state_sha256=canonical_state_hash(mirrored_state),
                updated_at=1_760_336_300,
            )
        )
        mirrored_company = _MigratedCompany.model_validate(
            connection.execute(
                select(company_table).where(
                    company_table.c.company_id == mirrored_state.context.company_id
                )
            )
            .mappings()
            .one()
        )
        mirrored_legacy = LegacySessionData.model_validate(
            connection.execute(
                select(sessions.c.session_data).where(sessions.c.session_id == "child-a-1")
            ).scalar_one()
        )

    # Then the trigger mirrors exact state and preserves unrelated legacy JSON.
    assert mirrored_company.state_sha256 == canonical_state_hash(mirrored_state)
    assert mirrored_legacy.model_extra == {"legacy_note": "preserve"}
    assert mirrored_legacy.session_state.model_extra == {"unrelated": "preserve"}
    assert mirrored_legacy.session_state.company == mirrored_state
