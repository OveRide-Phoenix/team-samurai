import hashlib
import json
from uuid import uuid4

from agno.db.postgres import PostgresDb
from agno.session.workflow import WorkflowSession
from pydantic import JsonValue, TypeAdapter
from sqlalchemy import MetaData, Table, select
from sqlalchemy.schema import DropSchema

from samurai.company_store import CompanyStore
from samurai.contracts import CompanyState
from samurai.execution_state import SamuraiPostgresDb
from samurai.schema import FounderPlatformMigrator
from samurai.schema_contracts import canonical_state_hash

pytest_plugins = ("tests.company_store_support",)


def test_legacy_context_upgrade_preserves_json_and_hash(postgres_url: str) -> None:
    # Given actual pre-Task5 company JSON with no workspace_id field.
    schema = f"founder_t05_upgrade_{uuid4().hex}"
    company_id = uuid4()
    legacy_company: dict[str, JsonValue] = {
        "context": {
            "company_id": str(company_id),
            "authenticated_session_id": "legacy-parent",
            "created_at": "2026-10-12T00:00:00Z",
        },
        "current_revision": 0,
        "artifacts": [],
    }
    encoded = json.dumps(
        legacy_company,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    legacy_hash = hashlib.sha256(encoded.encode()).hexdigest()
    legacy_db = PostgresDb(id=schema, db_url=postgres_url, db_schema=schema)
    _ = legacy_db.upsert_session(
        WorkflowSession(
            session_id="legacy-child",
            user_id="legacy-owner",
            workflow_id="company-journey",
            session_data={"session_state": {"company": legacy_company}},
        )
    )
    legacy_db.close()
    database = SamuraiPostgresDb(
        id=schema,
        db_url=postgres_url,
        db_schema=schema,
        create_schema=False,
    )
    database.ensure_work_intents_table()

    try:
        # When Task5 parses, migrates, reads, upserts, and reruns the Task4 migration.
        parsed = CompanyState.model_validate(legacy_company)
        assert parsed.model_dump(mode="json") == legacy_company
        assert canonical_state_hash(parsed) == legacy_hash
        first = FounderPlatformMigrator(database.db_engine, schema=schema).apply()
        store = CompanyStore(database.db_engine, schema=schema)
        access = store.read_for_actor("legacy-owner", "legacy-parent")
        assert access is not None
        _ = database.upsert_session(
            WorkflowSession(
                session_id="legacy-child",
                user_id="legacy-owner",
                workflow_id="company-journey",
                session_data={"session_state": {"company": parsed.model_dump(mode="json")}},
            )
        )
        second = FounderPlatformMigrator(database.db_engine, schema=schema).apply()

        # Then legacy canonical bytes and the pre-Task5 hash remain unchanged.
        companies = Table(
            "samurai_companies",
            MetaData(schema=schema),
            autoload_with=database.db_engine,
        )
        with database.db_engine.connect() as connection:
            row = (
                connection.execute(
                    select(companies.c.canonical_state, companies.c.state_sha256).where(
                        companies.c.company_id == company_id
                    )
                )
                .mappings()
                .one()
            )
        canonical = TypeAdapter(dict[str, JsonValue]).validate_python(row["canonical_state"])
        stored_hash = TypeAdapter(str).validate_python(row["state_sha256"])
        mirror = database.get_session("legacy-child", user_id="legacy-owner")
        assert canonical == legacy_company
        assert stored_hash == legacy_hash
        assert first.state_sha256 == second.state_sha256 == (legacy_hash,)
        assert isinstance(mirror, WorkflowSession)
        assert mirror.session_data is not None
        assert mirror.session_data["session_state"]["company"] == legacy_company
    finally:
        with database.db_engine.begin() as connection:
            _ = connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        database.close()
