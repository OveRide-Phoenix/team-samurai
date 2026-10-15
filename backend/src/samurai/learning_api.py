"""Authenticated HTTP actions for explicit founder learning."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, ClassVar, NoReturn, assert_never
from uuid import UUID  # noqa: TC003 - FastAPI resolves route annotations at runtime.

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator
from pydantic_core import PydanticCustomError
from starlette.concurrency import run_in_threadpool

from samurai.learning import (
    LearningContext,
    LearningCreate,
    LearningIssue,
    LearningKind,
    LearningRecord,
    LearningStore,
    LearningStoreError,
    LearningSupersede,
)

if TYPE_CHECKING:
    from typing import Self

    from samurai.execution_state import SamuraiPostgresDb

FounderText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]


class CreateLearningRequest(BaseModel):
    """One explicit founder preference or correction."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    company_id: UUID
    kind: LearningKind
    source_revision: int
    founder_text: FounderText
    shared: bool = False

    @model_validator(mode="after")
    def validate_sharing(self) -> Self:
        """Reject preference sharing before the persistence boundary."""
        if self.shared and self.kind is not LearningKind.CORRECTION:
            code = "learning_shared_kind"
            message = "only corrections may be shared"
            raise PydanticCustomError(code, message)
        return self


class SupersedeLearningRequest(BaseModel):
    """Replacement text pinned to a current company revision."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    company_id: UUID
    source_revision: int
    founder_text: FounderText
    shared: bool | None = None


def authenticated_actor(request: Request) -> str:
    """Return the identity populated by the production JWT boundary."""
    actor_id = getattr(request.state, "user_id", None)
    if not isinstance(actor_id, str) or not actor_id:
        raise HTTPException(status_code=401, detail="authenticated workspace actor is required")
    return actor_id


def _raise_learning_error(error: LearningStoreError) -> NoReturn:
    match error.issue:
        case LearningIssue.RECORD_NOT_FOUND | LearningIssue.COMPANY_NOT_FOUND:
            code = status.HTTP_404_NOT_FOUND
        case LearningIssue.SHARED_ROLE_REQUIRED:
            code = status.HTTP_403_FORBIDDEN
        case LearningIssue.STALE_REVISION | LearningIssue.RECORD_SUPERSEDED:
            code = status.HTTP_409_CONFLICT
        case (
            LearningIssue.INVALID_SCHEMA
            | LearningIssue.SHARED_CORRECTION_REQUIRED
            | LearningIssue.SHARING_MISMATCH
            | LearningIssue.AUDIT_MISMATCH
        ):
            code = status.HTTP_422_UNPROCESSABLE_CONTENT
        case _:
            assert_never(error.issue)
    raise HTTPException(status_code=code, detail=str(error)) from error


def learning_router(database: SamuraiPostgresDb) -> APIRouter:
    """Build explicit create, list, and supersede routes."""
    store = LearningStore(database.db_engine, schema=database.db_schema)
    router = APIRouter(prefix="/samurai/workspaces/{workspace_id}/learning")

    @router.post("", response_model=LearningRecord, status_code=status.HTTP_201_CREATED)
    async def create(
        workspace_id: UUID,
        body: CreateLearningRequest,
        actor_id: Annotated[str, Depends(authenticated_actor)],
    ) -> LearningRecord:
        try:
            return await run_in_threadpool(
                store.create,
                LearningCreate(
                    actor_id=actor_id,
                    workspace_id=workspace_id,
                    company_id=body.company_id,
                    kind=body.kind,
                    source_revision=body.source_revision,
                    founder_text=body.founder_text,
                    shared=body.shared,
                ),
            )
        except LearningStoreError as error:
            _raise_learning_error(error)

    @router.get("", response_model=LearningContext)
    async def list_records(
        workspace_id: UUID,
        company_id: Annotated[UUID, Query()],
        actor_id: Annotated[str, Depends(authenticated_actor)],
        *,
        include_history: bool = False,
    ) -> LearningContext:
        try:
            return await run_in_threadpool(
                store.list,
                actor_id,
                workspace_id,
                company_id,
                include_history=include_history,
            )
        except LearningStoreError as error:
            _raise_learning_error(error)

    @router.post(
        "/{learning_id}/supersede",
        response_model=LearningRecord,
        status_code=status.HTTP_201_CREATED,
    )
    async def supersede(
        workspace_id: UUID,
        learning_id: UUID,
        body: SupersedeLearningRequest,
        actor_id: Annotated[str, Depends(authenticated_actor)],
    ) -> LearningRecord:
        try:
            return await run_in_threadpool(
                store.supersede,
                LearningSupersede(
                    actor_id=actor_id,
                    workspace_id=workspace_id,
                    company_id=body.company_id,
                    learning_id=learning_id,
                    source_revision=body.source_revision,
                    founder_text=body.founder_text,
                    shared=body.shared,
                ),
            )
        except LearningStoreError as error:
            _raise_learning_error(error)

    return router
