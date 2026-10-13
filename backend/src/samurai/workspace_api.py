"""Strict authenticated HTTP contracts for shared workspaces."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, ClassVar
from uuid import UUID  # noqa: TC003 - Pydantic resolves route and response UUIDs at runtime.

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, StringConstraints

from samurai.company_store_contracts import WorkspaceRole  # noqa: TC001 - Pydantic runtime field.
from samurai.workspace_directory import WorkspaceDirectory
from samurai.workspace_directory_contracts import CompanySnapshot  # noqa: TC001 - Pydantic runtime field.

if TYPE_CHECKING:
    from samurai.execution_state import SamuraiPostgresDb

DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class WorkspaceCreate(BaseModel):
    """Accepted workspace creation fields."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    display_name: DisplayName


class MemberUpdate(BaseModel):
    """Accepted membership update fields."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    role: WorkspaceRole


class EmptyRequest(BaseModel):
    """Reject identity and all other caller-supplied fields."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class WorkspaceView(BaseModel):
    """One workspace visible to the authenticated actor."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)

    workspace_id: UUID
    display_name: str
    role: WorkspaceRole
    authorization_epoch: int


class MemberView(BaseModel):
    """Current persisted membership state."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)

    workspace_id: UUID
    user_id: str
    role: WorkspaceRole
    authorization_epoch: int


class CompanyView(BaseModel):
    """Shared company metadata with only the actor's session binding."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)

    workspace_id: UUID
    company_id: UUID
    current_revision: int
    created_at: int
    parent_session_id: str | None
    child_session_id: str | None
    snapshot: CompanySnapshot | None = None


def _actor(request: Request) -> str:
    actor_id = getattr(request.state, "user_id", None)
    if not isinstance(actor_id, str) or not actor_id:
        raise HTTPException(status_code=401, detail="authenticated workspace actor is required")
    return actor_id


def workspace_router(database: SamuraiPostgresDb) -> APIRouter:
    """Build routes backed by the app-owned canonical database."""
    directory = WorkspaceDirectory(database)
    router = APIRouter(prefix="/samurai")

    @router.post("/workspaces", response_model=WorkspaceView, status_code=status.HTTP_201_CREATED)
    def create_workspace(request: Request, payload: WorkspaceCreate) -> WorkspaceView:
        record = directory.create_workspace(_actor(request), payload.display_name)
        return WorkspaceView.model_validate(record)

    @router.get("/workspaces", response_model=list[WorkspaceView])
    def list_workspaces(request: Request) -> list[WorkspaceView]:
        return [
            WorkspaceView.model_validate(item)
            for item in directory.list_workspaces(_actor(request))
        ]

    @router.put("/workspaces/{workspace_id}/members/{user_id}", response_model=MemberView)
    def put_member(
        request: Request, workspace_id: UUID, user_id: str, payload: MemberUpdate
    ) -> MemberView:
        if not user_id:
            raise HTTPException(status_code=422, detail="member subject is required")
        record = directory.put_member(_actor(request), workspace_id, user_id, payload.role)
        return MemberView.model_validate(record)

    @router.delete(
        "/workspaces/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
    )
    def delete_member(request: Request, workspace_id: UUID, user_id: str) -> Response:
        directory.delete_member(_actor(request), workspace_id, user_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/workspaces/{workspace_id}/companies",
        response_model=CompanyView,
        status_code=status.HTTP_201_CREATED,
    )
    def create_company(request: Request, workspace_id: UUID, _payload: EmptyRequest) -> CompanyView:
        return CompanyView.model_validate(directory.create_company(_actor(request), workspace_id))

    @router.get("/workspaces/{workspace_id}/companies", response_model=list[CompanyView])
    def list_companies(request: Request, workspace_id: UUID) -> list[CompanyView]:
        records = directory.list_companies(_actor(request), workspace_id)
        return [CompanyView.model_validate(item) for item in records]

    @router.post(
        "/workspaces/{workspace_id}/companies/{company_id}/open", response_model=CompanyView
    )
    def open_company(
        request: Request, workspace_id: UUID, company_id: UUID, _payload: EmptyRequest
    ) -> CompanyView:
        record = directory.open_company(_actor(request), workspace_id, company_id)
        return CompanyView.model_validate(record)

    return router
