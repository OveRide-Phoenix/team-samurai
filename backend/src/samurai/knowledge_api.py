"""Authenticated HTTP boundary for explicitly indexed workspace knowledge."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, NoReturn, Self, assert_never
from uuid import UUID  # noqa: TC003 - FastAPI resolves route annotations at runtime.

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError
from starlette.concurrency import run_in_threadpool

from samurai.contracts import KnowledgeReference
from samurai.knowledge import (
    KnowledgeChunk,
    KnowledgeIssue,
    KnowledgeStore,
    KnowledgeStoreError,
)
from samurai.local_object_store import LocalObjectStore

if TYPE_CHECKING:
    from pathlib import Path

    from samurai.execution_state import SamuraiPostgresDb


class IndexKnowledgeRequest(BaseModel):
    """One explicit file or accepted-artifact indexing request."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    company_id: UUID
    file_id: UUID | None = None
    artifact_id: UUID | None = None

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        """Require a single typed source identity."""
        if (self.file_id is None) == (self.artifact_id is None):
            code = "knowledge_source"
            raise PydanticCustomError(code, "exactly one file_id or artifact_id is required")
        return self


class SearchKnowledgeRequest(BaseModel):
    """Bounded company-scoped lexical search request."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    company_id: UUID
    query: str = Field(min_length=1, max_length=200)


class KnowledgeSearchView(BaseModel):
    """Untrusted excerpt paired with exact internal provenance."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    reference: KnowledgeReference
    excerpt: str = Field(min_length=1, max_length=2000)
    score: int = Field(ge=1)


def _actor(request: Request) -> str:
    actor_id = getattr(request.state, "user_id", None)
    if not isinstance(actor_id, str) or not actor_id:
        raise HTTPException(status_code=401, detail="authenticated workspace actor is required")
    return actor_id


def _reference(chunk: KnowledgeChunk) -> KnowledgeReference:
    return KnowledgeReference(
        chunk_id=chunk.chunk_id,
        file_id=chunk.file_id,
        artifact_id=chunk.artifact_id,
        indexed_revision=chunk.indexed_revision,
        ordinal=chunk.ordinal,
        content_sha256=chunk.content_sha256,
        trust_class="uploaded_file" if chunk.file_id is not None else "accepted_artifact",
    )


def _raise_knowledge_error(error: KnowledgeStoreError) -> NoReturn:
    match error.issue:
        case KnowledgeIssue.PERMISSION_DENIED:
            code = status.HTTP_403_FORBIDDEN
        case KnowledgeIssue.SOURCE_NOT_FOUND:
            code = status.HTTP_404_NOT_FOUND
        case (
            KnowledgeIssue.SOURCE_INELIGIBLE
            | KnowledgeIssue.CONTENT_CHANGED
            | KnowledgeIssue.WORKSPACE_QUOTA
        ):
            code = status.HTTP_409_CONFLICT
        case (
            KnowledgeIssue.INVALID_SCHEMA
            | KnowledgeIssue.INVALID_QUERY
            | KnowledgeIssue.INVALID_SCOPE
            | KnowledgeIssue.SENSITIVE_CONTENT
        ):
            code = status.HTTP_422_UNPROCESSABLE_CONTENT
        case _:
            assert_never(error.issue)
    raise HTTPException(status_code=code, detail=str(error)) from error


def knowledge_router(database: SamuraiPostgresDb, storage_root: Path) -> APIRouter:
    """Build private explicit-index and scoped-search routes."""
    store = KnowledgeStore(
        database.db_engine,
        schema=database.db_schema,
        objects=LocalObjectStore(storage_root),
    )
    router = APIRouter(prefix="/samurai/workspaces/{workspace_id}/knowledge")

    @router.post("/index", response_model=list[KnowledgeReference])
    async def index(
        request: Request, workspace_id: UUID, body: IndexKnowledgeRequest
    ) -> list[KnowledgeReference]:
        try:
            scope = await run_in_threadpool(
                store.current_scope, _actor(request), workspace_id, body.company_id
            )
            if body.file_id is not None:
                chunks = await run_in_threadpool(store.index_file, scope, body.file_id)
            elif body.artifact_id is not None:
                chunks = await run_in_threadpool(store.index_artifact, scope, body.artifact_id)
            else:
                raise AssertionError
        except KnowledgeStoreError as error:
            _raise_knowledge_error(error)
        return [_reference(chunk) for chunk in chunks]

    @router.post("/search", response_model=list[KnowledgeSearchView])
    async def search(
        request: Request, workspace_id: UUID, body: SearchKnowledgeRequest
    ) -> list[KnowledgeSearchView]:
        try:
            scope = await run_in_threadpool(
                store.current_scope, _actor(request), workspace_id, body.company_id
            )
            results = await run_in_threadpool(store.retrieve, scope, body.query)
        except KnowledgeStoreError as error:
            _raise_knowledge_error(error)
        return [
            KnowledgeSearchView(
                reference=_reference(result), excerpt=result.excerpt, score=result.score
            )
            for result in results
        ]

    return router
