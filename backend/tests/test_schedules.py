# allow: SIZE_OK - the approved Task18 plan owns all scheduler scenarios in this one test file.

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from pydantic import JsonValue, TypeAdapter
from sqlalchemy import MetaData, Table, select, update
from sqlalchemy.schema import DropSchema

from samurai.company_store_contracts import WorkspaceRole
from samurai.execution_state import SamuraiPostgresDb
from samurai.schedule_api import schedule_router
from samurai.schedules import (
    LEASE_SECONDS,
    ScheduleCadence,
    ScheduleRun,
    ScheduleStore,
    next_occurrence,
)
from samurai.schema import FounderPlatformMigrator
from samurai.workspace_directory import WorkspaceDirectory

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator

pytest_plugins = ("tests.company_store_support",)
INT_ADAPTER = TypeAdapter(int)
BOOL_ADAPTER = TypeAdapter(bool)
JSON_ADAPTER = TypeAdapter(JsonValue)


@pytest.fixture
def schedule_database(postgres_url: str) -> Iterator[SamuraiPostgresDb]:
    schema = f"founder_t18_{uuid4().hex}"
    database = SamuraiPostgresDb(id=schema, db_url=postgres_url, db_schema=schema)
    database.ensure_work_intents_table()
    _ = FounderPlatformMigrator(database.db_engine, schema=schema).apply()
    yield database
    with database.db_engine.begin() as connection:
        _ = connection.execute(DropSchema(schema, cascade=True, if_exists=True))
    database.close()


def _persist_expired_claim(
    database: SamuraiPostgresDb,
    schedule_id: UUID,
    scheduled_for: int,
    next_run_at: int | None,
) -> None:
    runs = Table(
        "samurai_schedule_runs",
        MetaData(schema=database.db_schema),
        autoload_with=database.db_engine,
    )
    schedules = Table(
        "samurai_schedules",
        MetaData(schema=database.db_schema),
        autoload_with=database.db_engine,
    )
    with database.db_engine.begin() as connection:
        _ = connection.execute(
            runs.insert().values(
                schedule_id=schedule_id,
                scheduled_for=scheduled_for,
                status="claimed",
                claimed_at=scheduled_for - 600,
                lease_owner="old-runner",
                lease_expires_at=scheduled_for - 1,
            )
        )
        _ = connection.execute(
            update(schedules)
            .where(schedules.c.schedule_id == schedule_id)
            .values(next_run_at=next_run_at)
        )


@pytest.mark.parametrize(
    ("cadence", "expected"),
    [
        (ScheduleCadence.DAILY, "2026-03-08T09:00:00-04:00"),
        (ScheduleCadence.WEEKLY, "2026-03-14T09:00:00-04:00"),
    ],
)
def test_recurrence_keeps_local_wall_time_across_dst(
    cadence: ScheduleCadence, expected: str
) -> None:
    # Given the last 09:00 New York occurrence before daylight saving begins.
    current = datetime.fromisoformat("2026-03-07T09:00:00-05:00")

    # When the recurrence advances.
    following = next_occurrence(current, cadence, "America/New_York")

    # Then the wall clock remains 09:00 while the UTC offset changes.
    assert following.isoformat() == expected


def test_one_shot_can_be_scheduled_less_than_one_hour_ahead(
    schedule_database: SamuraiPostgresDb,
) -> None:
    # Given an authorized owner and a near-term one-shot occurrence.
    directory = WorkspaceDirectory(schedule_database)
    workspace_id = directory.create_workspace("owner", "Schedule interval").workspace_id
    company_id = directory.create_company("owner", workspace_id).company_id
    store = ScheduleStore(schedule_database.db_engine, schedule_database.db_schema)
    now = datetime(2026, 10, 14, 3, 30, tzinfo=UTC)

    # When the owner admits it for the next minute.
    schedule = store.create(
        actor_id="owner",
        workspace_id=workspace_id,
        company_id=company_id,
        cadence=ScheduleCadence.ONCE,
        timezone="Asia/Kolkata",
        first_run_at=datetime.fromtimestamp(now.timestamp() + 60, UTC),
        pinned_revision=0,
        action_kind="workspace_review",
        payload={},
        created_at=now.timestamp(),
    )

    # Then the exact one-shot occurrence is persisted without adding recurrence.
    assert schedule.next_run_at == int(now.timestamp()) + 60


def test_two_runners_claim_one_occurrence_and_replay_is_deduped(
    schedule_database: SamuraiPostgresDb,
) -> None:
    # Given one due daily schedule pinned to the current company revision.
    directory = WorkspaceDirectory(schedule_database)
    workspace_id = directory.create_workspace("owner", "Schedule race").workspace_id
    company_id = directory.create_company("owner", workspace_id).company_id
    store = ScheduleStore(schedule_database.db_engine, schedule_database.db_schema)
    now = datetime(2026, 10, 14, 3, 30, tzinfo=UTC)
    schedule = store.create(
        actor_id="owner",
        workspace_id=workspace_id,
        company_id=company_id,
        cadence=ScheduleCadence.DAILY,
        timezone="Asia/Kolkata",
        first_run_at=now,
        pinned_revision=0,
        action_kind="workspace_review",
        payload={},
        created_at=now.timestamp() - 3600,
    )

    # When two runner processes contend and the same instant is replayed.
    def run(runner: str) -> tuple[ScheduleRun, ...]:
        return ScheduleStore(schedule_database.db_engine, schedule_database.db_schema).run_due(
            now, runner
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(run, ("runner-a", "runner-b")))
    replay = store.run_due(now, "runner-replay")

    # Then one deterministic run exists and the next run stays at local 09:00.
    assert sum(len(items) for items in outcomes) == 1
    assert replay == ()
    runs = Table(
        "samurai_schedule_runs",
        MetaData(schema=schedule_database.db_schema),
        autoload_with=schedule_database.db_engine,
    )
    schedules = Table(
        "samurai_schedules",
        MetaData(schema=schedule_database.db_schema),
        autoload_with=schedule_database.db_engine,
    )
    with schedule_database.db_engine.connect() as connection:
        run_rows = (
            connection.execute(select(runs).where(runs.c.schedule_id == schedule.schedule_id))
            .mappings()
            .all()
        )
        next_run_at = INT_ADAPTER.validate_python(
            connection.execute(
                select(schedules.c.next_run_at).where(
                    schedules.c.schedule_id == schedule.schedule_id
                )
            ).scalar_one()
        )
    assert len(run_rows) == 1
    assert run_rows[0]["status"] == "completed"
    assert run_rows[0]["result"]["evidence_gaps"] == ["no_company_artifacts"]
    assert datetime.fromtimestamp(next_run_at, UTC).astimezone(
        ZoneInfo(schedule.timezone)
    ).isoformat() == ("2026-10-15T09:00:00+05:30")


def test_revoked_creator_is_terminal_and_downtime_coalesces_latest(
    schedule_database: SamuraiPostgresDb,
) -> None:
    # Given a schedule last due three days ago whose creator is then revoked.
    directory = WorkspaceDirectory(schedule_database)
    workspace_id = directory.create_workspace("owner", "Revoked schedule").workspace_id
    company_id = directory.create_company("owner", workspace_id).company_id
    _ = directory.put_member("owner", workspace_id, "editor", WorkspaceRole.EDITOR)
    store = ScheduleStore(schedule_database.db_engine, schedule_database.db_schema)
    first = datetime.fromisoformat("2026-10-14T09:00:00+05:30")
    schedule = store.create(
        actor_id="editor",
        workspace_id=workspace_id,
        company_id=company_id,
        cadence=ScheduleCadence.DAILY,
        timezone="Asia/Kolkata",
        first_run_at=first,
        pinned_revision=0,
        action_kind="workspace_review",
        payload={},
        created_at=first.timestamp() - 3600,
    )
    directory.delete_member("owner", workspace_id, "editor")
    advanced = datetime.fromisoformat("2026-10-17T09:00:00+05:30")

    # When two runners contend after the downtime gap.
    def run(runner: str) -> tuple[ScheduleRun, ...]:
        return ScheduleStore(schedule_database.db_engine, schedule_database.db_schema).run_due(
            advanced, runner
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(run, ("runner-a", "runner-b")))

    # Then only the latest missed occurrence is skipped and never retried.
    assert sum(len(items) for items in outcomes) == 1
    terminal = next(item for items in outcomes for item in items)
    assert terminal.scheduled_for == int(advanced.timestamp())
    assert terminal.status == "skipped"
    assert terminal.error_code == "authorization_changed"
    assert store.run_due(advanced, "runner-replay") == ()
    schedules = Table(
        "samurai_schedules",
        MetaData(schema=schedule_database.db_schema),
        autoload_with=schedule_database.db_engine,
    )
    with schedule_database.db_engine.connect() as connection:
        enabled = BOOL_ADAPTER.validate_python(
            connection.execute(
                select(schedules.c.enabled).where(schedules.c.schedule_id == schedule.schedule_id)
            ).scalar_one()
        )
    assert enabled is False


@pytest.mark.parametrize("cadence", [ScheduleCadence.ONCE, ScheduleCadence.DAILY])
def test_expired_lease_reclaims_exact_occurrence_and_fences_old_runner(
    schedule_database: SamuraiPostgresDb, cadence: ScheduleCadence
) -> None:
    # Given a runner claims an occurrence and crashes before handler execution.
    directory = WorkspaceDirectory(schedule_database)
    workspace_id = directory.create_workspace("owner", f"Lease {cadence}").workspace_id
    company_id = directory.create_company("owner", workspace_id).company_id
    store = ScheduleStore(schedule_database.db_engine, schedule_database.db_schema)
    due = datetime(2026, 10, 14, 3, 30, tzinfo=UTC)
    schedule = store.create(
        actor_id="owner",
        workspace_id=workspace_id,
        company_id=company_id,
        cadence=cadence,
        timezone="Asia/Kolkata",
        first_run_at=due,
        pinned_revision=0,
        action_kind="workspace_review",
        payload={},
        created_at=due.timestamp() - 3600,
    )
    runs = Table(
        "samurai_schedule_runs",
        MetaData(schema=schedule_database.db_schema),
        autoload_with=schedule_database.db_engine,
    )
    companies = Table(
        "samurai_companies",
        MetaData(schema=schedule_database.db_schema),
        autoload_with=schedule_database.db_engine,
    )
    with schedule_database.db_engine.connect() as connection:
        state_before = JSON_ADAPTER.validate_python(
            connection.execute(
                select(companies.c.canonical_state).where(companies.c.company_id == company_id)
            ).scalar_one()
        )
    scheduled_for = int(due.timestamp())
    original_claim = store._claim(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        scheduled_for, "old-runner"
    )
    assert original_claim is not None

    # When the original claimant resumes at and after expiry before replacement.
    at_expiry = store._execute(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        original_claim, scheduled_for + LEASE_SECONDS, "old-runner"
    )
    after_expiry = store._execute(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        original_claim, scheduled_for + LEASE_SECONDS + 1, "old-runner"
    )
    with schedule_database.db_engine.connect() as connection:
        expired_run = (
            connection.execute(select(runs).where(runs.c.schedule_id == schedule.schedule_id))
            .mappings()
            .one()
        )
        state_after_expiry = JSON_ADAPTER.validate_python(
            connection.execute(
                select(companies.c.canonical_state).where(companies.c.company_id == company_id)
            ).scalar_one()
        )
    recovered_at = scheduled_for + LEASE_SECONDS + 1
    recovered = store.run_due(datetime.fromtimestamp(recovered_at, UTC), "new-runner")
    fenced = store._execute(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        original_claim, recovered_at, "old-runner"
    )

    # Then expiry fences the original claim and replacement executes exactly once.
    assert at_expiry is None
    assert after_expiry is None
    assert (expired_run["status"], expired_run["result"], expired_run["completed_at"]) == (
        "claimed",
        None,
        None,
    )
    assert state_after_expiry == state_before
    assert len(recovered) == 1
    assert recovered[0].scheduled_for == scheduled_for
    assert fenced is None
    schedules = Table(
        "samurai_schedules",
        MetaData(schema=schedule_database.db_schema),
        autoload_with=schedule_database.db_engine,
    )
    quotas = Table(
        "samurai_workspace_quotas",
        MetaData(schema=schedule_database.db_schema),
        autoload_with=schedule_database.db_engine,
    )
    with schedule_database.db_engine.connect() as connection:
        next_run_at = connection.execute(
            select(schedules.c.next_run_at).where(schedules.c.schedule_id == schedule.schedule_id)
        ).scalar_one_or_none()
        schedule_count = INT_ADAPTER.validate_python(
            connection.execute(
                select(quotas.c.schedule_count).where(quotas.c.workspace_id == workspace_id)
            ).scalar_one()
        )
    assert (next_run_at, schedule_count) == (
        (None, 0)
        if cadence is ScheduleCadence.ONCE
        else (int(datetime(2026, 10, 15, 3, 30, tzinfo=UTC).timestamp()), 1)
    )


@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_code"),
    [
        ("disabled", "skipped", "schedule_disabled"),
        ("revision", "skipped", "revision_changed"),
        ("quota", "skipped", "workspace_quota"),
        ("unregistered", "failed", "unregistered_action"),
    ],
)
def test_dispatch_validation_failure_is_terminal_without_company_mutation(
    schedule_database: SamuraiPostgresDb,
    failure: str,
    expected_status: str,
    expected_code: str,
) -> None:
    # Given a claimed run whose dispatch authority changes before execution.
    directory = WorkspaceDirectory(schedule_database)
    workspace_id = directory.create_workspace("owner", f"Failure {failure}").workspace_id
    company_id = directory.create_company("owner", workspace_id).company_id
    store = ScheduleStore(schedule_database.db_engine, schedule_database.db_schema)
    due = datetime(2026, 10, 14, 3, 30, tzinfo=UTC)
    schedule = store.create(
        actor_id="owner",
        workspace_id=workspace_id,
        company_id=company_id,
        cadence=ScheduleCadence.DAILY,
        timezone="Asia/Kolkata",
        first_run_at=due,
        pinned_revision=0,
        action_kind="workspace_review",
        payload={},
        created_at=due.timestamp() - 3600,
    )
    scheduled_for = int(due.timestamp())
    _persist_expired_claim(
        schedule_database, schedule.schedule_id, scheduled_for, scheduled_for + 86_400
    )
    schedules = Table(
        "samurai_schedules",
        MetaData(schema=schedule_database.db_schema),
        autoload_with=schedule_database.db_engine,
    )
    companies = Table(
        "samurai_companies",
        MetaData(schema=schedule_database.db_schema),
        autoload_with=schedule_database.db_engine,
    )
    quotas = Table(
        "samurai_workspace_quotas",
        MetaData(schema=schedule_database.db_schema),
        autoload_with=schedule_database.db_engine,
    )
    with schedule_database.db_engine.begin() as connection:
        state_before = JSON_ADAPTER.validate_python(
            connection.execute(
                select(companies.c.canonical_state).where(companies.c.company_id == company_id)
            ).scalar_one()
        )
        if failure == "disabled":
            _ = connection.execute(
                update(schedules)
                .where(schedules.c.schedule_id == schedule.schedule_id)
                .values(enabled=False)
            )
        elif failure == "revision":
            _ = connection.execute(
                update(companies)
                .where(companies.c.company_id == company_id)
                .values(current_revision=1)
            )
        elif failure == "quota":
            _ = connection.execute(
                update(quotas)
                .where(quotas.c.workspace_id == workspace_id)
                .values(schedule_count=21)
            )
        else:
            _ = connection.execute(
                update(schedules)
                .where(schedules.c.schedule_id == schedule.schedule_id)
                .values(action_kind="not_registered")
            )

    # When the claimed run crosses the final locked validation boundary.
    receipts = store.run_due(due, "runner")

    # Then it terminalizes without invoking the handler or mutating company state.
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.status == expected_status
    assert receipt.error_code == expected_code
    assert receipt.result is None
    assert store.run_due(due, "retry") == ()
    with schedule_database.db_engine.connect() as connection:
        state_after = JSON_ADAPTER.validate_python(
            connection.execute(
                select(companies.c.canonical_state).where(companies.c.company_id == company_id)
            ).scalar_one()
        )
    assert state_after == state_before


def test_authenticated_router_harness_enforces_validation_and_schedule_limit(
    schedule_database: SamuraiPostgresDb,
) -> None:
    # Given the task-owned router mounted behind a synthetic identity boundary.
    directory = WorkspaceDirectory(schedule_database)
    workspace_id = directory.create_workspace("owner", "Schedule API").workspace_id
    company_id = directory.create_company("owner", workspace_id).company_id
    app = FastAPI()

    @app.middleware("http")
    async def identity(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.user_id = request.headers.get("X-Test-Subject")
        return await call_next(request)

    app.include_router(schedule_router(schedule_database))
    endpoint = f"/samurai/workspaces/{workspace_id}/companies/{company_id}/schedules"
    payload: dict[str, JsonValue] = {
        "cadence": "daily",
        "timezone": "Asia/Kolkata",
        "first_run_at": "2027-10-14T09:00:00+05:30",
        "pinned_revision": 0,
        "action_kind": "workspace_review",
        "payload": {},
    }

    # When unauthenticated, invalid-zone, sub-hour cadence, and valid requests cross HTTP.
    with TestClient(app) as client:
        unauthenticated = client.post(endpoint, json=payload)
        invalid_zone = client.post(
            endpoint,
            headers={"X-Test-Subject": "owner"},
            json={**payload, "timezone": "Not/AZone"},
        )
        sub_hour_cadence = client.post(
            endpoint,
            headers={"X-Test-Subject": "owner"},
            json={**payload, "cadence": "hourly"},
        )
        created = tuple(
            client.post(endpoint, headers={"X-Test-Subject": "owner"}, json=payload)
            for _index in range(21)
        )

    # Then identity, IANA parsing, and the durable quota fail closed distinctly.
    assert unauthenticated.status_code == 401
    assert invalid_zone.status_code == 422
    assert sub_hour_cadence.status_code == 422
    assert [response.status_code for response in created].count(201) == 20
    assert [response.status_code for response in created].count(409) == 1
