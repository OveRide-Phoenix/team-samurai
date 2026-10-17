"""Shared owner, company, revision and operation checks before durable admission."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from uuid import UUID  # noqa: TC003 - Pydantic resolves this field at runtime.

from agno.db.base import SessionType
from agno.session.workflow import WorkflowSession
from pydantic import Field

from samurai.company_store import CompanyStore
from samurai.company_store_contracts import WorkspaceRole
from samurai.contracts import CompanyState, Contract
from samurai.execution_state import ApprovedStage, SamuraiPostgresDb, WorkIntentInput, WorkOperation
from samurai.parent import child_session_id

if TYPE_CHECKING:
    from agno.db.base import BaseDb

    from samurai.company_store_contracts import CompanyAccess


class WorkApproval(Contract):
    """A requested work scope; the server independently checks every binding."""

    operation: WorkOperation = WorkOperation.JOURNEY
    stage: ApprovedStage = ApprovedStage.BRIEF
    expected_revision: int = Field(default=0, ge=0)
    company_id: UUID | None = None


def canonical_company(
    database: BaseDb | None, owner_id: str, parent_session_id: str, child_id: str
) -> tuple[CompanyState | None, CompanyAccess | None]:
    """Resolve canonical state from the authenticated parent's server-owned binding."""
    if database is None:
        return None, None
    if isinstance(database, SamuraiPostgresDb) and database.table_exists(
        "samurai_company_actor_bindings"
    ):
        access = CompanyStore(database.db_engine, schema=database.db_schema).read_for_actor(
            owner_id, parent_session_id
        )
        return (None, None) if access is None else (access.state, access)
    child = database.get_session(child_id, session_type=SessionType.WORKFLOW, user_id=owner_id)
    if child is None:
        return None, None
    if not isinstance(child, WorkflowSession) or child.user_id != owner_id:
        raise PermissionError
    session_data = cast("dict[str, object]", child.session_data or {})
    session_state: object = session_data.get("session_state") or {}
    if not isinstance(session_state, dict):
        raise TypeError
    payload = cast("dict[str, object]", session_state).get("company")
    return (None if payload is None else CompanyState.model_validate(payload)), None


def build_work_intent(
    database: BaseDb | None,
    owner_id: str,
    parent_session_id: str,
    message: str,
    approval: WorkApproval | None,
) -> WorkIntentInput:
    """Pin an explicit write scope or a read-only turn to current authorized state."""
    child_id = child_session_id(owner_id, parent_session_id)
    company, access = canonical_company(database, owner_id, parent_session_id, child_id)
    if (
        company is None
        and isinstance(database, SamuraiPostgresDb)
        and database.table_exists("samurai_company_actor_bindings")
    ):
        raise PermissionError
    if approval is None:
        operation = WorkOperation.READ_ONLY_STATE
        stage = ApprovedStage.BRIEF
        expected_revision = 0 if company is None else company.current_revision
        company_id = None if company is None else company.context.company_id
    else:
        operation, stage = approval.operation, approval.stage
        expected_revision, company_id = approval.expected_revision, approval.company_id
        if operation is WorkOperation.READ_ONLY_STATE:
            message = "read-only scope is server-owned"
            raise ValueError(message)
        if company is None:
            if (
                company_id is not None
                or expected_revision != 0
                or operation is not WorkOperation.JOURNEY
                or stage is not ApprovedStage.BRIEF
            ):
                raise ValueError
        else:
            if access is not None and access.role not in {
                WorkspaceRole.OWNER,
                WorkspaceRole.EDITOR,
            }:
                raise PermissionError
            if (
                company_id != company.context.company_id
                or expected_revision != company.current_revision
                or (
                    access is None and company.context.authenticated_session_id != parent_session_id
                )
            ):
                raise PermissionError
        if operation is not WorkOperation.JOURNEY and stage is not ApprovedStage.PLAN:
            message = "the approved operation and stage do not match"
            raise ValueError(message)
    return WorkIntentInput(
        owner_id=owner_id,
        parent_session_id=parent_session_id,
        child_session_id=access.child_session_id if access is not None else child_id,
        workspace_id=access.workspace_id if access is not None else None,
        authorization_epoch=access.authorization_epoch if access is not None else None,
        company_id=company_id,
        operation=operation,
        stage=stage,
        expected_revision=expected_revision,
        approved_input=message,
    )
