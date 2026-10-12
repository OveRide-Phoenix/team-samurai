from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from agno.run import RunContext
from agno.run.concurrency import worker_managed_execution
from agno.session.workflow import WorkflowSession

from samurai.app import _canonical_company  # pyright: ignore[reportPrivateUsage]
from samurai.company_store_contracts import CompanyReservation
from samurai.contracts import WorkflowRequest
from samurai.parent import (
    ParentContextError,
    _child_state,  # pyright: ignore[reportPrivateUsage]
)
from samurai.schema_contracts import canonical_state_hash
from samurai.workflow_state import WorkflowContextError, load_company_state
from tests.company_store_support import bound_attempt, revision_one, store_session

if TYPE_CHECKING:
    from uuid import UUID

    from samurai.company_store import CompanyStore
    from samurai.execution_state import SamuraiPostgresDb

pytest_plugins = ("tests.company_store_support",)


def test_stale_agno_upsert_cannot_overwrite_canonical_company(
    company_store: tuple[CompanyStore, SamuraiPostgresDb, UUID],
) -> None:
    # Given canonical revision one accepted through a fenced durable attempt.
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
    store_session(database, "owner", owner)
    token = bound_attempt(database, owner, "owner", "stale-upsert")
    proposed = revision_one(owner)
    with worker_managed_execution(token.parent_run_id, token.worker_id, token.attempt):
        accepted = database.accept_company_state(proposed, token)
    accepted_hash = canonical_state_hash(accepted)

    # When a later Agno upsert carries the actor's stale revision-zero JSON.
    _ = database.upsert_session(
        WorkflowSession(
            session_id="owner-child",
            user_id="owner",
            workflow_id="company-journey",
            session_data={"session_state": {"company": owner.state.model_dump(mode="json")}},
        )
    )

    # Then both the canonical row and actor-scoped mirror retain accepted revision one.
    canonical = store.read_for_actor("owner", "owner-parent")
    mirror = database.get_session("owner-child", user_id="owner")
    assert canonical is not None
    assert canonical_state_hash(canonical.state) == accepted_hash
    assert isinstance(mirror, WorkflowSession)
    assert mirror.session_data is not None
    assert mirror.session_data["session_state"]["company"] == accepted.model_dump(mode="json")


def test_unbound_actor_cannot_read_stale_agno_company(
    company_store: tuple[CompanyStore, SamuraiPostgresDb, UUID],
) -> None:
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
    stale_payload = owner.state.model_dump(mode="json")
    _ = database.upsert_session(
        WorkflowSession(
            session_id="rogue-child",
            user_id="rogue",
            workflow_id="company-journey",
            session_data={"session_state": {"company": stale_payload}},
        )
    )
    context = RunContext(
        run_id="rogue-run",
        session_id="rogue-child",
        user_id="rogue",
        session_state={"company": stale_payload},
        dependencies={
            "trusted_user_id": "rogue",
            "trusted_parent_session_id": "rogue-parent",
            "child_session_id": "rogue-child",
        },
    )

    assert _canonical_company(
        database,
        "rogue",
        "rogue-parent",
        "rogue-child",
    ) == (None, None)
    with pytest.raises(ParentContextError, match="parent session binding is not canonical"):
        _ = _child_state(database, context)
    with pytest.raises(WorkflowContextError, match="canonical company state is missing"):
        _ = load_company_state(
            WorkflowRequest(
                company_id=owner.state.context.company_id,
                expected_revision=0,
            ),
            context,
            created_at=datetime(2026, 10, 13, tzinfo=UTC),
            db=database,
        )
