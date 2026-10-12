from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from agno.run.concurrency import worker_managed_execution
from agno.session.workflow import WorkflowSession
from pydantic import TypeAdapter
from sqlalchemy import text

from samurai.company_store_contracts import (
    ActorBinding,
    CompanyReservation,
    CompanyStoreError,
    CompanyStoreIssue,
    WorkspaceRole,
)
from samurai.contracts import CompanyContext
from samurai.execution_state import (
    ApprovedStage,
    NormalizedWorkInput,
    SamuraiPostgresDb,
    WorkIntentError,
    WorkIntentInput,
    WorkIntentIssue,
    WorkOperation,
)
from tests.company_store_support import ClaimedJob, intent, job, revision_one

if TYPE_CHECKING:
    from samurai.company_store import CompanyStore

pytest_plugins = ("tests.company_store_support",)


def test_company_context_retains_optional_workspace_identity() -> None:
    # Given a server-reserved workspace and company identity.
    workspace_id = uuid4()

    # When the company context crosses the canonical-state boundary.
    context = CompanyContext(
        workspace_id=workspace_id,
        company_id=uuid4(),
        authenticated_session_id="owner-session",
        created_at=datetime(2026, 10, 13, tzinfo=UTC),
    )

    # Then the app-owned workspace identity survives exact serialization.
    assert context.model_dump(mode="json")["workspace_id"] == str(workspace_id)


def test_reserved_company_is_shared_through_actor_specific_bindings(
    company_store: tuple[CompanyStore, SamuraiPostgresDb, UUID],
) -> None:
    # Given one reserved company owned through an actor-specific parent session.
    store, _database, workspace_id = company_store
    owner = store.reserve(
        CompanyReservation(
            workspace_id=workspace_id,
            actor_id="owner",
            parent_session_id="owner-parent",
            child_session_id="owner-child",
            created_at=datetime(2026, 10, 13, tzinfo=UTC),
        )
    )

    # When a second authorized editor binds its own native parent and child sessions.
    editor = store.bind_actor(
        ActorBinding(
            company_id=owner.state.context.company_id,
            actor_id="editor",
            parent_session_id="editor-parent",
            child_session_id="editor-child",
        )
    )

    # Then both actor-scoped bindings read one app-owned canonical company.
    assert owner.role is WorkspaceRole.OWNER
    assert editor.role is WorkspaceRole.EDITOR
    assert editor.state == owner.state
    assert editor.parent_session_id == "editor-parent"
    assert editor.child_session_id == "editor-child"
    assert store.read_for_actor("owner", "owner-parent") == owner
    assert store.read_for_actor("editor", "editor-parent") == editor


def test_duplicate_legacy_binding_reports_domain_conflict(
    company_store: tuple[CompanyStore, SamuraiPostgresDb, UUID],
) -> None:
    store, _database, workspace_id = company_store
    reservation = CompanyReservation(
        workspace_id=workspace_id,
        actor_id="owner",
        parent_session_id="owner-parent",
        child_session_id="owner-child",
        created_at=datetime(2026, 10, 13, tzinfo=UTC),
    )
    _ = store.reserve(reservation)

    with pytest.raises(CompanyStoreError) as rejected:
        _ = store.reserve(reservation)

    assert rejected.value.issue is CompanyStoreIssue.BINDING_CONFLICT


def test_work_intent_pins_server_derived_workspace_authorization() -> None:
    # Given server-derived workspace scope for an authenticated editor.
    workspace_id = uuid4()

    # When durable work approval is created for its reserved company.
    intent = WorkIntentInput(
        owner_id="editor",
        parent_session_id="editor-parent",
        child_session_id="editor-child",
        workspace_id=workspace_id,
        authorization_epoch=7,
        company_id=uuid4(),
        operation=WorkOperation.JOURNEY,
        stage=ApprovedStage.BRIEF,
        expected_revision=1,
        approved_input={"idea": "Clinic assistant"},
    )

    # Then acceptance can recheck exactly the authorization admitted by the server.
    assert intent.workspace_id == workspace_id
    assert intent.authorization_epoch == 7


def test_workspace_index_enforces_company_wide_admission_across_actors(
    company_store: tuple[CompanyStore, SamuraiPostgresDb, UUID],
) -> None:
    # Given two isolated actors bound to one server-reserved company.
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
    editor = store.bind_actor(
        ActorBinding(
            company_id=owner.state.context.company_id,
            actor_id="editor",
            parent_session_id="editor-parent",
            child_session_id="editor-child",
        )
    )

    # When each actor tries to admit active work for the shared company.
    first = intent(owner, "owner", "owner-parent", "owner-child")
    second = intent(editor, "editor", "editor-parent", "editor-child")
    assert database.enqueue_work_job(job("owner-work", first), first)["accepted"] is True
    with pytest.raises(WorkIntentError) as rejected:
        _ = database.enqueue_work_job(job("editor-work", second), second)

    # Then the actual UUID column and attached unique index fence the second actor.
    with database.db_engine.connect() as connection:
        data_type = TypeAdapter(str).validate_python(
            connection.execute(
                text(
                    """SELECT data_type FROM information_schema.columns
                WHERE table_schema=:schema AND table_name='samurai_work_intents'
                AND column_name='workspace_id'"""
                ),
                {"schema": database.db_schema},
            ).scalar_one()
        )
        index_definition = TypeAdapter(str).validate_python(
            connection.execute(
                text(
                    """SELECT indexdef FROM pg_indexes WHERE schemaname=:schema
                AND indexname='uq_samurai_active_company_work_v2'"""
                ),
                {"schema": database.db_schema},
            ).scalar_one()
        )
    assert rejected.value.issue is WorkIntentIssue.ACTIVE_WORK
    assert data_type == "uuid"
    assert "UNIQUE INDEX" in index_definition
    assert "COALESCE" in index_definition


def test_acceptance_updates_canonical_row_and_legacy_owner_mirror(
    company_store: tuple[CompanyStore, SamuraiPostgresDb, UUID],
) -> None:
    # Given an editor-authorized durable attempt for a reserved company revision.
    store, database, workspace_id = company_store
    access = store.reserve(
        CompanyReservation(
            workspace_id=workspace_id,
            actor_id="owner",
            parent_session_id="owner-parent",
            child_session_id="owner-child",
            created_at=datetime(2026, 10, 13, tzinfo=UTC),
        )
    )
    _ = database.upsert_session(
        WorkflowSession(
            session_id="owner-child",
            user_id="owner",
            workflow_id="company-journey",
            session_data={"session_state": {"company": access.state.model_dump(mode="json")}},
        )
    )
    approval = intent(access, "owner", "owner-parent", "owner-child")
    run_id = "canonical-acceptance"
    result = database.enqueue_work_job(job(run_id, approval), approval)
    assert result["accepted"] is True
    claimed = ClaimedJob.model_validate(database.claim_job("worker-a", 30))
    proposed = revision_one(access)

    # When the claimed attempt accepts revision one.
    with worker_managed_execution(run_id, "worker-a", claimed.attempt):
        bound = database.bind_work_intent(
            run_id,
            NormalizedWorkInput(
                operation=approval.operation,
                stage=approval.stage,
                expected_revision=0,
                arguments={"idea": "Clinic assistant"},
            ),
        )
        accepted = database.accept_company_state(proposed, bound.token)

    # Then the company row and exact legacy owner session mirror agree.
    canonical = store.read_for_actor("owner", "owner-parent")
    mirror = database.get_session("owner-child", user_id="owner")
    assert canonical is not None
    assert canonical.state == accepted
    assert isinstance(mirror, WorkflowSession)
    assert mirror.session_data is not None
    assert mirror.session_data["session_state"]["company"] == accepted.model_dump(mode="json")
