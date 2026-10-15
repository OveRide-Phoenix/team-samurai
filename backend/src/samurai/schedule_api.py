"""Authenticated HTTP boundary for bounded workspace schedules."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, ClassVar, Final, Literal, NoReturn
from uuid import UUID  # noqa: TC003 - FastAPI resolves route UUIDs at runtime.

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from samurai.quota import WorkspaceQuotaExceededError
from samurai.schedules import (
    ScenarioRecomputePayload,
    ScheduleCadence,
    ScheduleError,
    ScheduleIssue,
    ScheduleRecord,
    ScheduleRun,
    ScheduleStore,
    WorkspaceReviewPayload,
)

if TYPE_CHECKING:
    from samurai.execution_state import SamuraiPostgresDb

TimezoneName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class _ScheduleCreate(BaseModel):
    """Fields shared by each allowlisted scheduled operation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    cadence: ScheduleCadence
    timezone: TimezoneName
    first_run_at: AwareDatetime
    pinned_revision: int = Field(ge=0)


class WorkspaceReviewScheduleCreate(_ScheduleCreate):
    """Schedule the bounded canonical-state evidence review."""

    action_kind: Literal["workspace_review"]
    payload: WorkspaceReviewPayload = Field(default_factory=WorkspaceReviewPayload)


class ScenarioRecomputeScheduleCreate(_ScheduleCreate):
    """Schedule one deterministic persisted scenario recomputation."""

    action_kind: Literal["scenario_recompute"]
    payload: ScenarioRecomputePayload


ScheduleCreate = Annotated[
    WorkspaceReviewScheduleCreate | ScenarioRecomputeScheduleCreate,
    Field(discriminator="action_kind"),
]


ERROR_STATUS: Final = {
    ScheduleIssue.EDITOR_REQUIRED: status.HTTP_403_FORBIDDEN,
    ScheduleIssue.MEMBER_REQUIRED: status.HTTP_403_FORBIDDEN,
    ScheduleIssue.COMPANY_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ScheduleIssue.SCHEDULE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ScheduleIssue.REVISION_CHANGED: status.HTTP_409_CONFLICT,
    ScheduleIssue.INVALID_TIMEZONE: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ScheduleIssue.NO_RECURRENCE: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ScheduleIssue.INVALID_SCHEMA: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ScheduleIssue.OFFSET_REQUIRED: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _actor(request: Request) -> str:
    actor_id = getattr(request.state, "user_id", None)
    if not isinstance(actor_id, str) or not actor_id:
        raise HTTPException(status_code=401, detail="authenticated workspace actor is required")
    return actor_id


def _raise_schedule_error(error: ScheduleError) -> NoReturn:
    raise HTTPException(status_code=ERROR_STATUS[error.issue], detail=str(error)) from error


def schedule_router(database: SamuraiPostgresDb) -> APIRouter:
    """Build task-owned schedule routes for the authenticated API harness."""
    store = ScheduleStore(database.db_engine, database.db_schema)
    router = APIRouter(prefix="/samurai/workspaces/{workspace_id}")

    @router.post(
        "/companies/{company_id}/schedules",
        response_model=ScheduleRecord,
        status_code=status.HTTP_201_CREATED,
    )
    def create_schedule(
        request: Request, workspace_id: UUID, company_id: UUID, payload: ScheduleCreate
    ) -> ScheduleRecord:
        try:
            return store.create(
                actor_id=_actor(request),
                workspace_id=workspace_id,
                company_id=company_id,
                cadence=payload.cadence,
                timezone=payload.timezone,
                first_run_at=payload.first_run_at,
                pinned_revision=payload.pinned_revision,
                action_kind=payload.action_kind,
                payload=payload.payload.model_dump(mode="json"),
                created_at=datetime.now(UTC).timestamp(),
            )
        except WorkspaceQuotaExceededError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ScheduleError as error:
            _raise_schedule_error(error)

    @router.get("/schedules", response_model=list[ScheduleRecord])
    def list_schedules(request: Request, workspace_id: UUID) -> list[ScheduleRecord]:
        try:
            return list(store.list(_actor(request), workspace_id))
        except ScheduleError as error:
            _raise_schedule_error(error)

    @router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
    def disable_schedule(request: Request, workspace_id: UUID, schedule_id: UUID) -> Response:
        try:
            store.disable(_actor(request), workspace_id, schedule_id)
        except ScheduleError as error:
            _raise_schedule_error(error)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/schedules/{schedule_id}/runs", response_model=list[ScheduleRun])
    def list_schedule_runs(
        request: Request, workspace_id: UUID, schedule_id: UUID
    ) -> list[ScheduleRun]:
        try:
            return list(store.list_runs(_actor(request), workspace_id, schedule_id))
        except ScheduleError as error:
            _raise_schedule_error(error)

    return router
