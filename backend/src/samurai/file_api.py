"""Authenticated HTTP boundary for private workspace files."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, NoReturn
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException

from samurai.config import WORKSPACE_QUOTA_LIMITS
from samurai.file_store import FileStore
from samurai.file_store_contracts import FileState, FileStoreError, FileStoreIssue
from samurai.local_object_store import LocalObjectStore
from samurai.quota import WorkspaceQuotaExceededError

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from starlette.types import Message, Receive

    from samurai.execution_state import SamuraiPostgresDb

MULTIPART_OVERHEAD_BYTES: Final = 64 * 1024


class FileView(BaseModel):
    """Public file metadata without an internal storage location."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)

    file_id: UUID
    workspace_id: UUID
    company_id: UUID | None
    state: FileState
    display_name: str
    media_type: str
    byte_size: int
    content_sha256: str
    created_at: int
    updated_at: int


class CleanupView(BaseModel):
    """Workspace-scoped maintenance counts."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    quarantines_rejected: int
    objects_purged: int
    receipts_expired: int
    promotions_repaired: int
    orphans_removed: int


class _HttpRequestMessage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    type: str
    body: bytes = b""


def _actor(request: Request) -> str:
    actor_id = getattr(request.state, "user_id", None)
    if not isinstance(actor_id, str) or not actor_id:
        raise HTTPException(status_code=401, detail="authenticated workspace actor is required")
    return actor_id


def _raise_file_error(error: FileStoreError) -> NoReturn:
    match error.issue:
        case FileStoreIssue.FILE_TOO_LARGE:
            code = status.HTTP_413_CONTENT_TOO_LARGE
        case FileStoreIssue.PERMISSION_DENIED:
            code = status.HTTP_403_FORBIDDEN
        case FileStoreIssue.NOT_FOUND:
            code = status.HTTP_404_NOT_FOUND
        case (
            FileStoreIssue.NOT_READY
            | FileStoreIssue.HASH_MISMATCH
            | FileStoreIssue.STORAGE_MISSING
            | FileStoreIssue.PROMOTION_FAILED
        ):
            code = status.HTTP_409_CONFLICT
        case _:
            code = status.HTTP_422_UNPROCESSABLE_CONTENT
    raise HTTPException(status_code=code, detail=str(error)) from error


def _file_chunks(upload: UploadFile) -> Iterable[bytes]:
    while chunk := upload.file.read(64 * 1024):
        yield chunk


def _bounded_request(request: Request) -> Request:
    received = 0

    async def receive() -> Message:
        nonlocal received
        message = await request.receive()
        if message["type"] == "http.request":
            received += len(_HttpRequestMessage.model_validate(message).body)
            if received > WORKSPACE_QUOTA_LIMITS.per_file_bytes + MULTIPART_OVERHEAD_BYTES:
                raise HTTPException(status_code=413, detail=FileStoreIssue.FILE_TOO_LARGE.value)
        return message

    bounded_receive: Receive = receive
    return Request(request.scope, bounded_receive)


async def _upload_parts(request: Request) -> tuple[FormData, UploadFile, UUID | None]:
    content_type = request.headers.get("content-type", "")
    content_length = request.headers.get("content-length")
    if not content_type.casefold().startswith("multipart/form-data;"):
        raise HTTPException(status_code=415, detail="multipart form data required")
    if content_length is not None:
        try:
            request_size = int(content_length)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="invalid content length") from error
        if request_size > WORKSPACE_QUOTA_LIMITS.per_file_bytes + MULTIPART_OVERHEAD_BYTES:
            raise HTTPException(status_code=413, detail=FileStoreIssue.FILE_TOO_LARGE.value)
    try:
        form = await _bounded_request(request).form(
            max_files=1,
            max_fields=1,
            max_part_size=WORKSPACE_QUOTA_LIMITS.per_file_bytes,
        )
    except MultiPartException as error:
        raise HTTPException(status_code=400, detail="invalid file upload fields") from error
    keys = tuple(form.keys())
    if set(keys) - {"file", "company_id"}:
        await form.close()
        raise HTTPException(status_code=400, detail="invalid file upload fields")
    files = form.getlist("file")
    companies = form.getlist("company_id")
    if len(files) != 1 or len(companies) > 1 or not isinstance(files[0], UploadFile):
        await form.close()
        raise HTTPException(status_code=400, detail="invalid file upload fields")
    company_value = companies[0] if companies else None
    if company_value is not None and not isinstance(company_value, str):
        await form.close()
        raise HTTPException(status_code=400, detail="invalid company binding")
    try:
        company_id = None if company_value is None else UUID(company_value)
    except ValueError as error:
        await form.close()
        raise HTTPException(status_code=422, detail="invalid company binding") from error
    return form, files[0], company_id


def file_router(  # noqa: C901 - nested handlers are the complete bounded file surface.
    database: SamuraiPostgresDb, storage_root: Path
) -> APIRouter:
    """Build private file routes over the app-owned database and local storage."""
    store = FileStore(
        database.db_engine,
        schema=database.db_schema,
        objects=LocalObjectStore(storage_root),
    )
    router = APIRouter(prefix="/samurai/workspaces/{workspace_id}/files")

    @router.post("", response_model=FileView, status_code=status.HTTP_201_CREATED)
    async def upload_file(request: Request, workspace_id: UUID) -> FileView:
        form, upload, company_id = await _upload_parts(request)
        try:
            try:
                record = await run_in_threadpool(
                    store.upload,
                    _actor(request),
                    workspace_id,
                    upload.filename or "",
                    upload.content_type or "",
                    _file_chunks(upload),
                    company_id=company_id,
                )
            except WorkspaceQuotaExceededError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
            except FileStoreError as error:
                _raise_file_error(error)
        finally:
            await form.close()
        return FileView.model_validate(record)

    @router.get("", response_model=list[FileView])
    async def list_files(
        request: Request, workspace_id: UUID, company_id: UUID | None = None
    ) -> list[FileView]:
        try:
            records = await run_in_threadpool(
                store.list, _actor(request), workspace_id, company_id=company_id
            )
        except FileStoreError as error:
            _raise_file_error(error)
        return [FileView.model_validate(record) for record in records]

    @router.post("/cleanup", response_model=CleanupView)
    async def cleanup_files(request: Request, workspace_id: UUID) -> CleanupView:
        content_length = request.headers.get("content-length", "0")
        if not content_length.isdecimal():
            raise HTTPException(status_code=400, detail="invalid content length")
        if request.url.query or request.headers.get("transfer-encoding") or int(content_length):
            raise HTTPException(status_code=400, detail="cleanup request must be empty")
        try:
            counts = await run_in_threadpool(store.cleanup_workspace, _actor(request), workspace_id)
        except FileStoreError as error:
            _raise_file_error(error)
        return CleanupView(
            quarantines_rejected=counts[0],
            objects_purged=counts[1],
            receipts_expired=counts[2],
            promotions_repaired=counts[3],
            orphans_removed=counts[4],
        )

    @router.get("/{file_id}", response_model=FileView)
    async def file_metadata(request: Request, workspace_id: UUID, file_id: UUID) -> FileView:
        try:
            record = await run_in_threadpool(store.metadata, _actor(request), workspace_id, file_id)
        except FileStoreError as error:
            _raise_file_error(error)
        return FileView.model_validate(record)

    @router.get("/{file_id}/download")
    async def download_file(
        request: Request, workspace_id: UUID, file_id: UUID
    ) -> StreamingResponse:
        try:
            record, chunks = await run_in_threadpool(
                store.stream, _actor(request), workspace_id, file_id
            )
        except FileStoreError as error:
            _raise_file_error(error)
        encoded_name = quote(record.display_name, safe="")
        return StreamingResponse(
            chunks,
            media_type=record.media_type,
            headers={
                "Content-Disposition": (
                    f"attachment; filename=\"download\"; filename*=UTF-8''{encoded_name}"
                ),
                "Content-Length": str(record.byte_size),
                "X-Content-SHA256": record.content_sha256,
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_file(request: Request, workspace_id: UUID, file_id: UUID) -> Response:
        try:
            await run_in_threadpool(store.delete, _actor(request), workspace_id, file_id)
        except FileStoreError as error:
            _raise_file_error(error)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
