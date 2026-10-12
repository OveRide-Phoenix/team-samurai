from __future__ import annotations

import os
from datetime import UTC, datetime
from multiprocessing import get_context
from typing import TYPE_CHECKING

import pytest
from agno.run.concurrency import worker_managed_execution
from agno.session.workflow import WorkflowSession
from pydantic import TypeAdapter
from sqlalchemy import MetaData, Table

from samurai.company_store_contracts import ActorBinding, CompanyReservation
from samurai.contracts import CompanyState
from samurai.execution_state import (
    AcceptanceToken,
    SamuraiPostgresDb,
    WorkIntentError,
    WorkIntentIssue,
)
from samurai.schema_contracts import canonical_state_hash
from tests.company_store_support import bound_attempt, revision_one, store_session

if TYPE_CHECKING:
    from multiprocessing.queues import Queue
    from multiprocessing.synchronize import Barrier
    from uuid import UUID

    from samurai.company_store import CompanyStore

STATE_ADAPTER = TypeAdapter(CompanyState)
TOKEN_ADAPTER = TypeAdapter(AcceptanceToken)
pytest_plugins = ("tests.company_store_support",)


def _accept_at_barrier(
    payload: tuple[str, str, str, str],
    barrier: Barrier,
    results: Queue[str],
) -> None:
    database_url, schema, state_json, token_json = payload
    database = SamuraiPostgresDb(
        id=f"race-{os.getpid()}",
        db_url=database_url,
        db_schema=schema,
        create_schema=False,
    )
    state = STATE_ADAPTER.validate_json(state_json)
    token = TOKEN_ADAPTER.validate_json(token_json)
    with worker_managed_execution(token.parent_run_id, token.worker_id, token.attempt):
        _ = barrier.wait()
        try:
            accepted = database.accept_company_state(state, token)
        except WorkIntentError as error:
            results.put(error.issue.value)
        else:
            results.put(f"accepted:{accepted.current_revision}")
    database.close()


@pytest.mark.parametrize("actor_id", ["viewer", "editor"])
def test_acceptance_rechecks_workspace_authorization_before_writes(
    company_store: tuple[CompanyStore, SamuraiPostgresDb, UUID],
    actor_id: str,
) -> None:
    # Given admitted work whose viewer role or editor epoch is no longer writable.
    store, database, workspace_id = company_store
    owner = store.reserve(
        CompanyReservation(
            workspace_id=workspace_id,
            actor_id="owner",
            parent_session_id="owner-parent",
            child_session_id="owner-child",
            created_at=datetime(2026, 10, 13, tzinfo=UTC),
        )
    )
    actor = store.bind_actor(
        ActorBinding(
            company_id=owner.state.context.company_id,
            actor_id=actor_id,
            parent_session_id=f"{actor_id}-parent",
            child_session_id=f"{actor_id}-child",
        )
    )
    store_session(database, "owner", owner)
    store_session(database, actor_id, actor)
    token = bound_attempt(database, actor, actor_id, f"{actor_id}-authorization")
    before = canonical_state_hash(owner.state)
    if actor_id == "editor":
        memberships = Table(
            "samurai_workspace_memberships",
            MetaData(schema=database.db_schema),
            autoload_with=database.db_engine,
        )
        with database.db_engine.begin() as connection:
            _ = connection.execute(
                memberships.update()
                .where(
                    memberships.c.workspace_id == workspace_id,
                    memberships.c.user_id == actor_id,
                )
                .values(active=False, authorization_epoch=2)
            )

    # When the claimed attempt tries to accept after the authorization boundary changed.
    with (
        worker_managed_execution(token.parent_run_id, token.worker_id, token.attempt),
        pytest.raises(WorkIntentError) as rejected,
    ):
        _ = database.accept_company_state(revision_one(owner), token)

    # Then authorization is rejected before canonical or legacy mirror writes.
    canonical = store.read_for_actor("owner", "owner-parent")
    mirror = database.get_session("owner-child", user_id="owner")
    assert rejected.value.issue is WorkIntentIssue.AUTHORIZATION_CHANGED
    assert canonical is not None
    assert canonical_state_hash(canonical.state) == before
    assert isinstance(mirror, WorkflowSession)
    assert mirror.session_data is not None
    assert (
        canonical_state_hash(
            CompanyState.model_validate(mirror.session_data["session_state"]["company"])
        )
        == before
    )


def test_two_editor_acceptance_race_commits_one_revision(
    company_store: tuple[CompanyStore, SamuraiPostgresDb, UUID],
    postgres_url: str,
) -> None:
    # Given two pre-index in-flight editor attempts pinned to revision zero.
    store, database, workspace_id = company_store
    owner = store.reserve(
        CompanyReservation(
            workspace_id=workspace_id,
            actor_id="owner",
            parent_session_id="owner-parent",
            child_session_id="owner-child",
            created_at=datetime(2026, 10, 13, tzinfo=UTC),
        )
    )
    memberships = Table(
        "samurai_workspace_memberships",
        MetaData(schema=database.db_schema),
        autoload_with=database.db_engine,
    )
    with database.db_engine.begin() as connection:
        _ = connection.execute(
            memberships.insert().values(
                workspace_id=workspace_id,
                user_id="editor-2",
                role="editor",
                authorization_epoch=1,
                active=True,
                created_at=1,
                updated_at=1,
            )
        )
    editors = tuple(
        store.bind_actor(
            ActorBinding(
                company_id=owner.state.context.company_id,
                actor_id=actor_id,
                parent_session_id=f"{actor_id}-parent",
                child_session_id=f"{actor_id}-child",
            )
        )
        for actor_id in ("editor", "editor-2")
    )
    store_session(database, "owner", owner)
    for actor_id, access in zip(("editor", "editor-2"), editors, strict=True):
        store_session(database, actor_id, access)
    tokens: list[AcceptanceToken] = []
    intents = Table(
        database.work_intent_table_name,
        MetaData(schema=database.db_schema),
        autoload_with=database.db_engine,
    )
    for actor_id, access in zip(("editor", "editor-2"), editors, strict=True):
        token = bound_attempt(database, access, actor_id, f"race-{actor_id}")
        tokens.append(token)
        with database.db_engine.begin() as connection:
            _ = connection.execute(
                intents.update()
                .where(intents.c.parent_run_id == token.parent_run_id)
                .values(state="legacy_active")
            )

    # When both processes cross a barrier and accept the same proposed revision.
    context = get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    proposed_json = revision_one(owner).model_dump_json()
    processes = [
        context.Process(
            target=_accept_at_barrier,
            args=(
                (
                    postgres_url,
                    database.db_schema,
                    proposed_json,
                    token.model_dump_json(),
                ),
                barrier,
                results,
            ),
        )
        for token in tokens
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)

    # Then the row lock accepts one revision and rejects the other as stale.
    outcomes = sorted(results.get(timeout=2) for _ in processes)
    canonical = store.read_for_actor("owner", "owner-parent")
    mirror = database.get_session("owner-child", user_id="owner")
    assert all(process.exitcode == 0 for process in processes)
    assert outcomes == ["accepted:1", WorkIntentIssue.STALE_REVISION.value]
    assert canonical is not None
    assert canonical.state.current_revision == 1
    assert isinstance(mirror, WorkflowSession)
    assert mirror.session_data is not None
    assert canonical_state_hash(canonical.state) == canonical_state_hash(
        CompanyState.model_validate(mirror.session_data["session_state"]["company"])
    )
