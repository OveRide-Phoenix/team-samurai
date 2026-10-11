"""Validate trusted Agno context before reading or writing canonical company state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, override

from pydantic import Field, ValidationError

from samurai.contracts import (
    CompanyMismatchError,
    CompanyState,
    Contract,
    SessionMismatchError,
    StaleRevisionError,
    WorkflowRequest,
    create_company_state,
)

if TYPE_CHECKING:
    from datetime import datetime

    from agno.run import RunContext


class _TrustedWorkflowContext(Contract):
    trusted_parent_session_id: str = Field(min_length=1)
    trusted_user_id: str = Field(min_length=1)
    child_session_id: str = Field(min_length=1)


@unique
class WorkflowContextIssue(StrEnum):
    """Enumerate fail-closed workflow context boundary failures."""

    INVALID_DEPENDENCIES = "trusted workflow dependencies are missing or invalid"
    USER_MISMATCH = "trusted user does not match workflow user"
    CHILD_SESSION_MISMATCH = "child session does not match workflow session"
    SHARED_SESSION = "parent and child workflow sessions must be distinct"
    MISSING_STATE = "canonical company state is missing"
    SESSION_ALREADY_BOUND = "child session is already bound to a company"
    STATE_REWRITE = "cannot rewrite canonical company history"


@dataclass(frozen=True, slots=True)
class WorkflowContextError(Exception):
    """Report a rejected trusted-context or canonical-state boundary."""

    issue: WorkflowContextIssue

    @override
    def __str__(self) -> str:
        return self.issue.value


def _trusted_context(run_context: RunContext) -> _TrustedWorkflowContext:
    try:
        trusted = _TrustedWorkflowContext.model_validate(run_context.dependencies)
    except ValidationError as error:
        raise WorkflowContextError(WorkflowContextIssue.INVALID_DEPENDENCIES) from error
    if trusted.trusted_user_id != run_context.user_id:
        raise WorkflowContextError(WorkflowContextIssue.USER_MISMATCH)
    if trusted.child_session_id != run_context.session_id:
        raise WorkflowContextError(WorkflowContextIssue.CHILD_SESSION_MISMATCH)
    if trusted.trusted_parent_session_id == trusted.child_session_id:
        raise WorkflowContextError(WorkflowContextIssue.SHARED_SESSION)
    return trusted


def load_company_state(
    request: WorkflowRequest,
    run_context: RunContext,
    *,
    created_at: datetime,
) -> CompanyState:
    """Load one company after validating native workflow identity and session bindings."""
    trusted = _trusted_context(run_context)
    session_state = run_context.session_state
    payload = session_state.get("company") if session_state is not None else None
    if payload is None:
        if request.company_id is not None:
            raise WorkflowContextError(WorkflowContextIssue.MISSING_STATE)
        return create_company_state(trusted.trusted_parent_session_id, created_at=created_at)

    state = CompanyState.model_validate(payload)
    if request.company_id is None:
        raise WorkflowContextError(WorkflowContextIssue.SESSION_ALREADY_BOUND)
    if state.context.authenticated_session_id != trusted.trusted_parent_session_id:
        raise SessionMismatchError(
            state.context.authenticated_session_id, trusted.trusted_parent_session_id
        )
    if state.context.company_id != request.company_id:
        raise CompanyMismatchError(state.context.company_id, request.company_id)
    if state.current_revision != request.expected_revision:
        raise StaleRevisionError(state.current_revision, request.expected_revision)
    return state


def save_company_state(state: CompanyState, run_context: RunContext) -> None:
    """Save canonical state only after revalidating its trusted parent binding."""
    trusted = _trusted_context(run_context)
    if state.context.authenticated_session_id != trusted.trusted_parent_session_id:
        raise SessionMismatchError(
            state.context.authenticated_session_id, trusted.trusted_parent_session_id
        )
    session_state = run_context.session_state
    if session_state is None:
        session_state = {}
        run_context.session_state = session_state
    payload = session_state.get("company")
    if payload is not None:
        current = CompanyState.model_validate(payload)
        retained_history = state.artifacts[: len(current.artifacts)]
        if (
            state.context != current.context
            or state.current_revision < current.current_revision
            or retained_history != current.artifacts
        ):
            raise WorkflowContextError(WorkflowContextIssue.STATE_REWRITE)
    session_state["company"] = state.model_dump(mode="json")
