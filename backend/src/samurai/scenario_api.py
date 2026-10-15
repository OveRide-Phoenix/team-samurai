"""Authenticated HTTP boundaries for deterministic synthetic scenarios."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, ClassVar, Never
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict

from samurai.scenario_contracts import (
    ScenarioCreate,
    ScenarioDefinition,
    ScenarioIssue,
    ScenarioStoreError,
)
from samurai.scenario_math import ScenarioResult
from samurai.scenarios import ScenarioStore

if TYPE_CHECKING:
    from samurai.execution_state import SamuraiPostgresDb


class EmptyScenarioRun(BaseModel):
    """Reject caller-supplied result and status claims."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


def scenario_actor(request: Request) -> str:
    """Return only identity established by production authentication middleware."""
    actor_id = getattr(request.state, "user_id", None)
    if not isinstance(actor_id, str) or not actor_id:
        raise HTTPException(status_code=401, detail="authenticated scenario actor is required")
    return actor_id


ScenarioActor = Annotated[str, Depends(scenario_actor)]
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


def _raise_http(error: ScenarioStoreError) -> Never:
    match error.issue:
        case ScenarioIssue.PERMISSION_DENIED:
            code = status.HTTP_403_FORBIDDEN
        case ScenarioIssue.NOT_FOUND:
            code = status.HTTP_404_NOT_FOUND
        case ScenarioIssue.STALE_BASELINE | ScenarioIssue.CHANGED_IDEMPOTENCY:
            code = status.HTTP_409_CONFLICT
        case ScenarioIssue.INVALID_SCHEMA | ScenarioIssue.CORRUPT_RESULT:
            code = status.HTTP_500_INTERNAL_SERVER_ERROR
    raise HTTPException(status_code=code, detail=str(error)) from error


def scenario_router(database: SamuraiPostgresDb) -> APIRouter:
    """Build scenario routes without mounting them in the Task 20 application shell."""
    store = ScenarioStore(database.db_engine, schema=database.db_schema)
    router = APIRouter(prefix="/samurai/workspaces/{workspace_id}/companies/{company_id}/scenarios")

    @router.post("", response_model=ScenarioDefinition, status_code=status.HTTP_201_CREATED)
    def create_scenario(  # noqa: PLR0913, PLR0917 - FastAPI injects each boundary value.
        workspace_id: UUID,
        company_id: UUID,
        payload: ScenarioCreate,
        actor_id: ScenarioActor,
        idempotency_key: IdempotencyKey,
        response: Response,
    ) -> ScenarioDefinition:
        try:
            definition, created = store.create(
                actor_id, workspace_id, company_id, idempotency_key, payload
            )
        except ScenarioStoreError as error:
            _raise_http(error)
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return definition

    @router.get("/{scenario_id}", response_model=ScenarioDefinition)
    def get_scenario(
        workspace_id: UUID, company_id: UUID, scenario_id: UUID, actor_id: ScenarioActor
    ) -> ScenarioDefinition:
        try:
            return store.get(actor_id, workspace_id, company_id, scenario_id)
        except ScenarioStoreError as error:
            _raise_http(error)

    @router.post(
        "/{scenario_id}/runs",
        response_model=ScenarioResult,
        status_code=status.HTTP_201_CREATED,
    )
    def run_scenario(  # noqa: PLR0913, PLR0917 - FastAPI injects each boundary value.
        workspace_id: UUID,
        company_id: UUID,
        scenario_id: UUID,
        _payload: EmptyScenarioRun,
        actor_id: ScenarioActor,
        idempotency_key: IdempotencyKey,
        response: Response,
    ) -> ScenarioResult:
        try:
            result, created = store.run(
                actor_id, workspace_id, company_id, scenario_id, idempotency_key
            )
        except ScenarioStoreError as error:
            _raise_http(error)
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return result

    @router.get("/{scenario_id}/result", response_model=ScenarioResult)
    def get_result(
        workspace_id: UUID, company_id: UUID, scenario_id: UUID, actor_id: ScenarioActor
    ) -> ScenarioResult:
        try:
            return store.get_result(actor_id, workspace_id, company_id, scenario_id)
        except ScenarioStoreError as error:
            _raise_http(error)

    return router
