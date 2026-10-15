from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.schema import DropSchema

from samurai.company_store_contracts import WorkspaceRole
from samurai.execution_state import SamuraiPostgresDb
from samurai.scenario_api import scenario_actor, scenario_router
from samurai.scenario_contracts import (
    ScenarioCancelledError,
    ScenarioCreate,
    ScenarioDefinition,
    ScenarioIssue,
    ScenarioStoreError,
)
from samurai.scenario_math import ScenarioResult
from samurai.scenarios import ScenarioStore
from samurai.schema import FounderPlatformMigrator
from samurai.workspace_directory import WorkspaceDirectory

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pydantic import JsonValue
    from sqlalchemy.sql.elements import TextClause


FIXTURE = Path(__file__).parent / "fixtures/platform-evals/scenarios.json"
OWNER = "scenario-principal-a"
pytest_plugins = ("tests.company_store_support",)


def _sql(schema: str, source: str) -> TextClause:
    return text(source.format(schema=schema))


def _record_evidence(name: str, payload: JsonValue) -> None:
    configured = os.environ.get("SAMURAI_SCENARIO_EVIDENCE_DIR")
    if configured is None:
        return
    destination = Path(configured)
    destination.mkdir(parents=True, exist_ok=True)
    _ = (destination / name).write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )


@pytest.fixture
def scenario_client(
    postgres_url: str,
) -> Iterator[tuple[TestClient, SamuraiPostgresDb, UUID, UUID, str]]:
    # Given a real migrated PostgreSQL schema and one production-shaped company binding.
    schema = f"founder_t19_{uuid4().hex}"
    database = SamuraiPostgresDb(id=schema, db_url=postgres_url, db_schema=schema)
    database.ensure_work_intents_table()
    _ = FounderPlatformMigrator(database.db_engine, schema=schema).apply()
    directory = WorkspaceDirectory(database)
    workspace = directory.create_workspace(OWNER, "Scenario acceptance")
    company = directory.create_company(OWNER, workspace.workspace_id, uuid4())
    with database.db_engine.connect() as connection:
        baseline_sha256 = cast(
            "str",
            connection.execute(
                _sql(
                    schema,
                    """SELECT state_sha256 FROM "{schema}".samurai_companies
                    WHERE company_id=:company_id""",
                ),
                {"company_id": company.company_id},
            ).scalar_one(),
        )

    app = FastAPI()
    app.include_router(scenario_router(database))
    app.dependency_overrides[scenario_actor] = lambda: OWNER
    with TestClient(app) as client:
        yield client, database, workspace.workspace_id, company.company_id, baseline_sha256
    with database.db_engine.begin() as connection:
        _ = connection.execute(DropSchema(schema, cascade=True, if_exists=True))
    database.close()


def _definition_payload(baseline_sha256: str) -> dict[str, object]:
    payload = cast("dict[str, object]", json.loads(FIXTURE.read_text(encoding="utf-8")))
    return {
        **payload,
        "company_revision": 0,
        "company_state_sha256": baseline_sha256,
    }


def _canonical_baseline(database: SamuraiPostgresDb, company_id: UUID) -> tuple[int, str]:
    with database.db_engine.connect() as connection:
        row = connection.execute(
            _sql(
                database.db_schema,
                """SELECT current_revision, state_sha256
                FROM "{schema}".samurai_companies
                WHERE company_id=:company_id""",
            ),
            {"company_id": company_id},
        ).one()
    return cast("tuple[int, str]", tuple(row))


def _assert_result_provenance(
    result: ScenarioResult,
    definition: ScenarioDefinition,
    expected_inputs: ScenarioCreate,
) -> None:
    assert result.provenance == "synthetic_scenario_not_validation"
    assert result.company_revision == definition.company_revision
    assert result.company_state_sha256 == definition.company_state_sha256
    assert result.input_sha256 == definition.input_sha256
    assert result.horizon_days == expected_inputs.horizon_days
    assert result.assumptions == expected_inputs.assumptions


def test_authenticated_router_harness_dental_clinic_idempotency(
    scenario_client: tuple[TestClient, SamuraiPostgresDb, UUID, UUID, str],
) -> None:
    # Given an authenticated founder's explicit 90-day dental-clinic inputs.
    client, database, workspace_id, company_id, baseline_sha256 = scenario_client
    definition_key = str(uuid4())
    run_key = str(uuid4())
    path = f"/samurai/workspaces/{workspace_id}/companies/{company_id}/scenarios"

    # When the same normalized definition and run are submitted twice.
    created = client.post(
        path,
        headers={"Idempotency-Key": definition_key},
        json=_definition_payload(baseline_sha256),
    )
    replayed = client.post(
        path,
        headers={"Idempotency-Key": definition_key},
        json=_definition_payload(baseline_sha256),
    )
    assert created.status_code == 201, created.text
    assert replayed.status_code == 200, replayed.text
    definition = ScenarioDefinition.model_validate(cast("object", created.json()))
    scenario_id = definition.scenario_id
    run_path = f"{path}/{scenario_id}/runs"
    store = ScenarioStore(database.db_engine, schema=database.db_schema)
    barrier = Barrier(2)

    def replay_definition() -> None:
        _ = barrier.wait()
        _ = store.create(
            OWNER,
            workspace_id,
            company_id,
            UUID(definition_key),
            ScenarioCreate.model_validate(_definition_payload(baseline_sha256)),
        )

    def run_definition() -> None:
        _ = barrier.wait()
        _ = store.run(
            OWNER,
            workspace_id,
            company_id,
            scenario_id,
            UUID(run_key),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        replay_future = pool.submit(replay_definition)
        run_future = pool.submit(run_definition)
        replay_future.result(timeout=10)
        run_future.result(timeout=10)

    first_run = client.get(f"{path}/{scenario_id}/result")
    second_run = client.post(run_path, headers={"Idempotency-Key": run_key}, json={})
    fetched = client.get(f"{path}/{scenario_id}/result")
    duplicate_definition = client.post(
        path,
        headers={"Idempotency-Key": str(uuid4())},
        json=_definition_payload(baseline_sha256),
    )
    duplicate_scenario_id = ScenarioDefinition.model_validate(
        cast("object", duplicate_definition.json())
    ).scenario_id
    duplicate_run = client.post(
        f"{path}/{duplicate_scenario_id}/runs",
        headers={"Idempotency-Key": str(uuid4())},
        json={},
    )

    # Then one byte-stable synthetic result exposes formulas, sensitivity, and constraints.
    assert first_run.status_code == 200, first_run.text
    assert second_run.status_code == 200, second_run.text
    assert first_run.content == second_run.content == fetched.content
    assert duplicate_run.content == first_run.content
    result = ScenarioResult.model_validate(cast("object", first_run.json()))
    second_result = ScenarioResult.model_validate(cast("object", second_run.json()))
    _assert_result_provenance(
        result,
        definition,
        ScenarioCreate.model_validate(_definition_payload(baseline_sha256)),
    )
    assert result.result_sha256 == second_result.result_sha256
    assert [item.label for item in result.trajectories] == [
        "low",
        "base",
        "high",
    ]
    assert len(result.formulas) == 4
    assert [item.assumption for item in result.sensitivity] == [
        "lead_growth",
        "conversion_change",
        "price_change",
    ]
    assert {item.constraint for item in result.constraint_findings} == {"founder_budget_ceiling"}
    assert all(item.violated for item in result.constraint_findings)
    serialized = first_run.text
    for forbidden in ("connected_measurement", '"supported"', '"verified"'):
        assert forbidden not in serialized
    canonical_revision, canonical_sha256 = _canonical_baseline(database, company_id)
    assert canonical_revision == 0
    assert canonical_sha256 == baseline_sha256
    _record_evidence(
        "task-19-scenario.json",
        {
            "canonical_revision": canonical_revision,
            "canonical_state_sha256": canonical_sha256,
            "create_status": created.status_code,
            "replay_status": replayed.status_code,
            "run_status": second_run.status_code,
            "result": result.model_dump(mode="json"),
        },
    )


def test_changed_inputs_overclaim_and_stale_baseline_are_rejected(
    scenario_client: tuple[TestClient, SamuraiPostgresDb, UUID, UUID, str],
) -> None:
    # Given one immutable definition pinned to revision zero.
    client, database, workspace_id, company_id, baseline_sha256 = scenario_client
    key = str(uuid4())
    path = f"/samurai/workspaces/{workspace_id}/companies/{company_id}/scenarios"
    payload = _definition_payload(baseline_sha256)
    created = client.post(path, headers={"Idempotency-Key": key}, json=payload)
    assert created.status_code == 201, created.text
    scenario_id = ScenarioDefinition.model_validate(cast("object", created.json())).scenario_id

    # When the key changes meaning, a client overclaims status, or the company advances.
    changed = {**payload, "horizon_days": 91}
    conflict = client.post(path, headers={"Idempotency-Key": key}, json=changed)
    overclaim = client.post(
        f"{path}/{scenario_id}/runs",
        headers={"Idempotency-Key": str(uuid4())},
        json={"status": "verified demand"},
    )
    blank = client.post(
        path,
        headers={"Idempotency-Key": str(uuid4())},
        json={**payload, "title": "   "},
    )
    unbounded = _definition_payload(baseline_sha256)
    baseline_metrics = cast("list[dict[str, object]]", unbounded["baseline_metrics"])
    baseline_metrics[0]["value"] = "1e99999"
    huge = client.post(
        path,
        headers={"Idempotency-Key": str(uuid4())},
        json=unbounded,
    )
    with database.db_engine.begin() as connection:
        _ = connection.execute(
            _sql(
                database.db_schema,
                """UPDATE "{schema}".samurai_companies
                SET current_revision=1 WHERE company_id=:company_id""",
            ),
            {"company_id": company_id},
        )
    stale = client.post(
        f"{path}/{scenario_id}/runs",
        headers={"Idempotency-Key": str(uuid4())},
        json={},
    )

    # Then all failures are explicit and no completed scenario rows exist.
    assert conflict.status_code == 409
    assert overclaim.status_code == 422
    assert blank.status_code == 422
    assert huge.status_code == 422
    assert stale.status_code == 409
    with database.db_engine.connect() as connection:
        run_count = cast(
            "int",
            connection.execute(
                _sql(
                    database.db_schema,
                    """SELECT count(*) FROM "{schema}".samurai_scenario_runs
                    WHERE scenario_id=:scenario_id""",
                ),
                {"scenario_id": scenario_id},
            ).scalar_one(),
        )
    assert run_count == 0
    _record_evidence(
        "task-19-scenario-error.json",
        {
            "changed_idempotency_status": conflict.status_code,
            "overclaim_status": overclaim.status_code,
            "blank_status": blank.status_code,
            "huge_decimal_status": huge.status_code,
            "stale_status": stale.status_code,
            "persisted_result_rows": run_count,
        },
    )


def test_revoked_actor_and_cancelled_transaction_persist_no_partial_result(
    scenario_client: tuple[TestClient, SamuraiPostgresDb, UUID, UUID, str],
) -> None:
    # Given one current scenario and its authenticated creator.
    client, database, workspace_id, company_id, baseline_sha256 = scenario_client
    path = f"/samurai/workspaces/{workspace_id}/companies/{company_id}/scenarios"
    created = client.post(
        path,
        headers={"Idempotency-Key": str(uuid4())},
        json=_definition_payload(baseline_sha256),
    )
    scenario_id = ScenarioDefinition.model_validate(cast("object", created.json())).scenario_id
    store = ScenarioStore(database.db_engine, schema=database.db_schema)

    # When cancellation interrupts the single result transaction before commit.
    with pytest.raises(ScenarioCancelledError):
        _ = store.run(
            OWNER,
            workspace_id,
            company_id,
            scenario_id,
            uuid4(),
            cancelled=lambda label: label == "base",
        )
    with database.db_engine.begin() as connection:
        _ = connection.execute(
            _sql(
                database.db_schema,
                """UPDATE "{schema}".samurai_workspace_memberships
                SET active=false, authorization_epoch=authorization_epoch+1
                WHERE workspace_id=:workspace_id AND user_id=:actor_id""",
            ),
            {"workspace_id": workspace_id, "actor_id": OWNER},
        )
    revoked = client.post(
        f"{path}/{scenario_id}/runs",
        headers={"Idempotency-Key": str(uuid4())},
        json={},
    )

    # Then rollback leaves zero low/base/high rows and revocation is enforced on replay.
    assert revoked.status_code == 403
    with database.db_engine.connect() as connection:
        counts = cast(
            "int",
            connection.execute(
                _sql(
                    database.db_schema,
                    """SELECT count(*) FROM "{schema}".samurai_scenario_runs
                    WHERE scenario_id=:scenario_id""",
                ),
                {"scenario_id": scenario_id},
            ).scalar_one(),
        )
        current_revision = cast(
            "int",
            connection.execute(
                _sql(
                    database.db_schema,
                    """SELECT current_revision FROM "{schema}".samurai_companies
                    WHERE company_id=:company_id""",
                ),
                {"company_id": company_id},
            ).scalar_one(),
        )
    assert counts == 0
    assert current_revision == 0
    _record_evidence(
        "task-19-scenario-cancellation.json",
        {
            "revoked_status": revoked.status_code,
            "persisted_result_rows": counts,
            "canonical_revision": current_revision,
        },
    )


def test_idempotency_is_actor_scoped_and_replay_reauthorizes(
    scenario_client: tuple[TestClient, SamuraiPostgresDb, UUID, UUID, str],
) -> None:
    # Given two current writers using the same idempotency key and normalized inputs.
    _, database, workspace_id, company_id, baseline_sha256 = scenario_client
    editor = "scenario-principal-b"
    _ = WorkspaceDirectory(database).put_member(OWNER, workspace_id, editor, WorkspaceRole.OWNER)
    store = ScenarioStore(database.db_engine, schema=database.db_schema)
    inputs = ScenarioCreate.model_validate(_definition_payload(baseline_sha256))
    definition_key = uuid4()
    run_key = uuid4()
    owner_definition, _ = store.create(OWNER, workspace_id, company_id, definition_key, inputs)
    editor_definition, _ = store.create(editor, workspace_id, company_id, definition_key, inputs)
    _, _ = store.run(OWNER, workspace_id, company_id, owner_definition.scenario_id, run_key)

    # When the owner membership is revoked before replaying the completed run.
    WorkspaceDirectory(database).delete_member(OWNER, workspace_id, OWNER)

    # Then actor identity scopes definition keys and replay checks current authority.
    assert owner_definition.scenario_id != editor_definition.scenario_id
    with pytest.raises(ScenarioStoreError) as caught:
        _ = store.run(OWNER, workspace_id, company_id, owner_definition.scenario_id, run_key)
    assert caught.value.issue is ScenarioIssue.PERMISSION_DENIED
    with database.db_engine.connect() as connection:
        result_rows = cast(
            "int",
            connection.execute(
                _sql(
                    database.db_schema,
                    """SELECT count(*) FROM "{schema}".samurai_scenario_runs
                    WHERE scenario_id=:scenario_id""",
                ),
                {"scenario_id": owner_definition.scenario_id},
            ).scalar_one(),
        )
    assert result_rows == 3
    _record_evidence(
        "task-19-scenario-authorization.json",
        {
            "actor_scoped_definition_ids": True,
            "revoked_replay_issue": caught.value.issue.value,
            "persisted_complete_result_rows": result_rows,
        },
    )
