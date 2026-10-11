from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agno.run import RunContext
from pydantic import ValidationError

from samurai.contracts import (
    CompanyMismatchError,
    StaleRevisionError,
    WorkflowRequest,
    WorkflowResult,
)
from samurai.workflow_state import WorkflowContextError, load_company_state, save_company_state


def _run_context(
    *,
    user_id: str = "founder-1",
    session_id: str = "child-1",
    trusted_child_session_id: str | None = None,
) -> RunContext:
    return RunContext(
        run_id="run-1",
        session_id=session_id,
        user_id=user_id,
        dependencies={
            "trusted_parent_session_id": "parent-1",
            "trusted_user_id": "founder-1",
            "child_session_id": trusted_child_session_id or session_id,
        },
        session_state={},
    )


def test_workflow_request_distinguishes_new_company_from_continuation() -> None:
    # Given the shared new-company and continuation request shapes.
    company_id = uuid4()

    # When parsed at the workflow boundary.
    new = WorkflowRequest(company_id=None, expected_revision=0)
    continuation = WorkflowRequest(company_id=company_id, expected_revision=0)

    # Then both valid states remain explicit and ambiguous new revisions fail closed.
    assert new.company_id is None
    assert continuation.company_id == company_id
    with pytest.raises(ValidationError, match="new company requests must start at revision zero"):
        _ = WorkflowRequest(company_id=None, expected_revision=1)


def test_workflow_result_requires_questions_only_for_missing_input() -> None:
    # Given a workflow result at a founder decision boundary.
    company_id = uuid4()

    # When the result needs input, then it carries at least one concise question.
    result = WorkflowResult(
        company_id=company_id,
        revision=1,
        outcome="needs_input",
        questions=("What budget can you commit?",),
    )
    assert result.questions == ("What budget can you commit?",)

    # When the result is terminal, then questions are rejected as stale UI state.
    with pytest.raises(ValidationError, match="questions are only valid for needs_input"):
        _ = WorkflowResult(
            company_id=company_id,
            revision=1,
            outcome="verified",
            questions=("This should not remain",),
        )
    with pytest.raises(ValidationError, match="at least 1 character"):
        _ = WorkflowResult(
            company_id=company_id,
            revision=1,
            outcome="needs_input",
            questions=("",),
        )


def test_context_boundary_creates_and_saves_only_canonical_child_state() -> None:
    # Given trusted native workflow context with a distinct child session.
    run_context = _run_context()
    parent_binding = {
        "company_id": None,
        "child_session_id": "child-1",
        "current_revision": 0,
    }

    # When a first request creates and saves canonical company state.
    state = load_company_state(
        WorkflowRequest(company_id=None, expected_revision=0),
        run_context,
        created_at=datetime(2026, 10, 11, tzinfo=UTC),
    )
    save_company_state(state, run_context)

    # Then canonical state belongs to the trusted parent binding without mutating it.
    assert state.context.authenticated_session_id == "parent-1"
    assert run_context.session_state == {"company": state.model_dump(mode="json")}
    assert parent_binding == {
        "company_id": None,
        "child_session_id": "child-1",
        "current_revision": 0,
    }


def test_context_boundary_rejects_identity_session_company_and_revision_mismatch() -> None:
    # Given canonical state created under trusted user, parent, and child bindings.
    run_context = _run_context()
    state = load_company_state(
        WorkflowRequest(company_id=None, expected_revision=0),
        run_context,
        created_at=datetime(2026, 10, 11, tzinfo=UTC),
    )
    save_company_state(state, run_context)

    # When any caller-controlled binding differs, then loading fails before model work.
    with pytest.raises(WorkflowContextError, match="trusted user does not match"):
        _ = load_company_state(
            WorkflowRequest(company_id=state.context.company_id, expected_revision=0),
            _run_context(user_id="attacker"),
            created_at=datetime(2026, 10, 11, tzinfo=UTC),
        )
    with pytest.raises(WorkflowContextError, match="child session does not match"):
        _ = load_company_state(
            WorkflowRequest(company_id=state.context.company_id, expected_revision=0),
            _run_context(session_id="other-child", trusted_child_session_id="child-1"),
            created_at=datetime(2026, 10, 11, tzinfo=UTC),
        )
    with pytest.raises(CompanyMismatchError):
        _ = load_company_state(
            WorkflowRequest(company_id=uuid4(), expected_revision=0),
            run_context,
            created_at=datetime(2026, 10, 11, tzinfo=UTC),
        )
    with pytest.raises(StaleRevisionError):
        _ = load_company_state(
            WorkflowRequest(company_id=state.context.company_id, expected_revision=1),
            run_context,
            created_at=datetime(2026, 10, 11, tzinfo=UTC),
        )


def test_save_rejects_canonical_history_rewrite() -> None:
    # Given canonical state already saved in the child workflow session.
    run_context = _run_context()
    first = load_company_state(
        WorkflowRequest(company_id=None, expected_revision=0),
        run_context,
        created_at=datetime(2026, 10, 11, tzinfo=UTC),
    )
    save_company_state(first, run_context)
    replacement = load_company_state(
        WorkflowRequest(company_id=None, expected_revision=0),
        _run_context(session_id="child-2"),
        created_at=datetime(2026, 10, 11, tzinfo=UTC),
    )

    # When another company state targets the same child session, then save fails closed.
    with pytest.raises(WorkflowContextError, match="cannot rewrite canonical company history"):
        save_company_state(replacement, run_context)
