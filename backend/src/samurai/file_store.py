"""Immutable workspace files over a bounded object-store contract."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, final
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text

from samurai import file_store_maintenance as maintenance
from samurai.company_store_contracts import WorkspaceRole
from samurai.company_store_queries import valid_schema
from samurai.config import WORKSPACE_QUOTA_LIMITS
from samurai.file_store_contracts import (
    FileContentReference,
    FileRecord,
    FileState,
    FileStoreError,
    FileStoreIssue,
    ObjectStore,
)
from samurai.quota import WorkspaceQuota
from samurai.workspace_membership import WorkspaceMembership

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from sqlalchemy.engine import Connection, Engine
    from sqlalchemy.sql.elements import TextClause

ALLOWED_TYPES: Final = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".pdf": "application/pdf",
}
INVALID_SCHEMA: Final = "invalid file store schema"


@final
class FileStore:
    """Coordinate membership, logical quota, metadata, and immutable bytes."""

    def __init__(self, engine: Engine, *, schema: str, objects: ObjectStore) -> None:
        """Bind one schema and object adapter."""
        if not valid_schema(schema):
            raise ValueError(INVALID_SCHEMA)
        self._engine: Engine = engine
        self._schema: str = schema
        self._objects: ObjectStore = objects
        self._membership: WorkspaceMembership = WorkspaceMembership(engine, schema)
        self._quota: WorkspaceQuota = WorkspaceQuota(schema)
        self._maintenance = maintenance.FileStoreMaintenance(engine, schema, objects)

    def upload(  # noqa: PLR0913 - public storage operation requires all scoped file facts.
        self,
        actor_id: str,
        workspace_id: UUID,
        display_name: str,
        media_type: str,
        chunks: Iterable[bytes],
        *,
        company_id: UUID | None = None,
    ) -> FileRecord:
        """Validate and promote one immutable logical file."""
        timestamp = int(time.time())
        self._require_writable(actor_id, workspace_id)
        quarantined = self._objects.write_quarantine(
            chunks, max_bytes=WORKSPACE_QUOTA_LIMITS.per_file_bytes
        )
        try:
            self._validate(display_name, media_type, self._objects.read(quarantined.key))
        except BaseException:
            self._objects.delete(quarantined.key)
            raise
        file_id = uuid4()
        try:
            with self._engine.begin() as connection:
                self._quota.lock(connection, workspace_id)
                self._lock_object(connection, quarantined.key)
                self._require_writable(actor_id, workspace_id, connection)
                if company_id is not None:
                    self._require_company(connection, workspace_id, company_id)
                self._quota.reserve_file(connection, workspace_id, quarantined.byte_size)
                _ = connection.execute(
                    self._sql(
                        """INSERT INTO "{schema}".samurai_files
                        (file_id, workspace_id, company_id, created_by, state, display_name,
                        media_type,
                        byte_size, content_sha256, storage_key, created_at, updated_at)
                        VALUES (:file_id, :workspace_id, :company_id, :actor_id,
                        'quarantined', :display_name,
                        :media_type, :byte_size, :sha256, :storage_key, :now, :now)"""
                    ),
                    {
                        "file_id": file_id,
                        "workspace_id": workspace_id,
                        "company_id": company_id,
                        "actor_id": actor_id,
                        "display_name": display_name,
                        "media_type": media_type,
                        "byte_size": quarantined.byte_size,
                        "sha256": quarantined.sha256,
                        "storage_key": quarantined.key,
                        "now": timestamp,
                    },
                )
        except BaseException:
            self._objects.delete(quarantined.key)
            raise
        ready_key = f"ready/{workspace_id}/{quarantined.sha256}"
        with self._engine.begin() as connection:
            self._lock_object(connection, ready_key)
            try:
                self._objects.promote(quarantined.key, ready_key)
            except (FileStoreError, OSError) as error:
                raise FileStoreError(FileStoreIssue.PROMOTION_FAILED) from error
            promoted = connection.execute(
                self._sql(
                    """UPDATE "{schema}".samurai_files SET state = 'ready',
                        storage_key = :storage_key, updated_at = :now
                        WHERE file_id = :file_id AND state = 'quarantined'"""
                ),
                {"file_id": file_id, "storage_key": ready_key, "now": timestamp},
            )
            if promoted.rowcount != 1:
                raise FileStoreError(FileStoreIssue.PROMOTION_FAILED)
        return self._record(actor_id, workspace_id, file_id)

    def read(self, actor_id: str, workspace_id: UUID, file_id: UUID) -> bytes:
        """Read one ready file through current workspace membership."""
        try:
            _record, chunks = self.stream(actor_id, workspace_id, file_id)
        except FileStoreError as error:
            if error.issue is FileStoreIssue.NOT_FOUND:
                raise FileStoreError(FileStoreIssue.NOT_READY) from error
            raise
        return b"".join(chunks)

    def list(
        self, actor_id: str, workspace_id: UUID, *, company_id: UUID | None = None
    ) -> list[FileRecord]:
        """List visible non-deleted files through current workspace membership."""
        with self._engine.connect() as connection:
            role = self._membership.require_member(connection, workspace_id, actor_id)
            if company_id is not None:
                self._require_company(connection, workspace_id, company_id)
            rows = connection.execute(
                self._sql(
                    """SELECT file_id, workspace_id, company_id, state, display_name, media_type,
                    byte_size, content_sha256, storage_key, created_at, updated_at
                    FROM "{schema}".samurai_files
                    WHERE workspace_id = :workspace_id AND state != 'deleted'
                    AND (CAST(:company_id AS uuid) IS NULL
                    OR company_id = CAST(:company_id AS uuid))
                    AND (CAST(:ready_only AS boolean) = false OR state = 'ready')
                    ORDER BY created_at, file_id"""
                ),
                {
                    "workspace_id": workspace_id,
                    "company_id": company_id,
                    "ready_only": role is WorkspaceRole.VIEWER,
                },
            ).mappings()
            return [FileRecord.model_validate(row) for row in rows]

    def metadata(self, actor_id: str, workspace_id: UUID, file_id: UUID) -> FileRecord:
        """Return visible file metadata without exposing its storage key."""
        record, role = self._record_with_role(actor_id, workspace_id, file_id)
        if record.state is FileState.DELETED:
            raise FileStoreError(FileStoreIssue.NOT_FOUND)
        if role is WorkspaceRole.VIEWER and record.state is not FileState.READY:
            raise FileStoreError(FileStoreIssue.NOT_FOUND)
        return record

    def stream(
        self, actor_id: str, workspace_id: UUID, file_id: UUID
    ) -> tuple[FileRecord, Iterator[bytes]]:
        """Verify and return a fresh bounded stream for one ready file."""
        record = self.metadata(actor_id, workspace_id, file_id)
        if record.state is not FileState.READY:
            raise FileStoreError(FileStoreIssue.NOT_READY)
        digest = hashlib.sha256()
        size = 0
        for chunk in self._objects.chunks(record.storage_key, chunk_size=1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
        if digest.hexdigest() != record.content_sha256 or size != record.byte_size:
            raise FileStoreError(FileStoreIssue.HASH_MISMATCH)
        return record, self._objects.chunks(record.storage_key, chunk_size=64 * 1024)

    def delete(
        self,
        actor_id: str,
        workspace_id: UUID,
        file_id: UUID,
        *,
        now: int | None = None,
    ) -> None:
        """Tombstone one file and immediately release its logical quota."""
        timestamp = int(time.time()) if now is None else now
        with self._engine.begin() as connection:
            self._quota.lock(connection, workspace_id)
            self._require_writable(actor_id, workspace_id, connection)
            raw_row = (
                connection.execute(
                    self._sql(
                        """SELECT byte_size, content_sha256 FROM "{schema}".samurai_files
                    WHERE file_id = :file_id AND workspace_id = :workspace_id
                    AND state IN ('quarantined', 'ready') FOR UPDATE"""
                    ),
                    {"file_id": file_id, "workspace_id": workspace_id},
                )
                .mappings()
                .one_or_none()
            )
            if raw_row is None:
                raise FileStoreError(FileStoreIssue.NOT_READY)
            row = FileContentReference.model_validate(raw_row)
            self._quota.release_file(connection, workspace_id, row.byte_size)
            _ = connection.execute(
                self._sql(
                    """UPDATE "{schema}".samurai_files SET state = 'deleted', deleted_at = :now,
                    updated_at = :now WHERE file_id = :file_id"""
                ),
                {"file_id": file_id, "now": timestamp},
            )
            _ = connection.execute(
                self._sql(
                    """INSERT INTO "{schema}".samurai_file_deletion_receipts
                    (receipt_id, file_id, workspace_id, content_sha256, deleted_by,
                    deleted_at, purge_after, retain_until)
                    VALUES (:receipt_id, :file_id, :workspace_id, :sha256, :actor_id,
                    :now, :purge_after, :retain_until)"""
                ),
                {
                    "receipt_id": uuid4(),
                    "file_id": file_id,
                    "workspace_id": workspace_id,
                    "sha256": row.content_sha256,
                    "actor_id": actor_id,
                    "now": timestamp,
                    "purge_after": timestamp + maintenance.PURGE_SECONDS,
                    "retain_until": timestamp + maintenance.RECEIPT_SECONDS,
                },
            )

    def cleanup_quarantine(self, *, now: int | None = None) -> int:
        """Reject quarantines older than one hour and release their quota."""
        return self._maintenance.cleanup_quarantine(now=now)

    def purge_deleted(self, *, now: int | None = None) -> tuple[int, int]:
        """Purge unshared bytes after seven days and receipts after thirty."""
        return self._maintenance.purge_deleted(now=now)

    def reconcile_orphans(self, *, now: int | None = None) -> tuple[int, int]:
        """Repair validated promotions and remove aged unreferenced quarantines."""
        return self._maintenance.reconcile_orphans(now=now)

    def cleanup_workspace(
        self, actor_id: str, workspace_id: UUID, *, now: int | None = None
    ) -> tuple[int, int, int, int, int]:
        """Run owner-only maintenance that cannot cross the selected workspace."""
        with self._engine.begin() as connection:
            self._membership.require_owner(connection, workspace_id, actor_id)
        rejected = self._maintenance.cleanup_quarantine(
            workspace_id=workspace_id, actor_id=actor_id, now=now
        )
        purged, expired = self._maintenance.purge_deleted(
            workspace_id=workspace_id, actor_id=actor_id, now=now
        )
        repaired, removed = self._maintenance.reconcile_orphans(
            workspace_id=workspace_id, actor_id=actor_id, now=now
        )
        return rejected, purged, expired, repaired, removed

    def _record(self, actor_id: str, workspace_id: UUID, file_id: UUID) -> FileRecord:
        record, _role = self._record_with_role(actor_id, workspace_id, file_id)
        return record

    def _record_with_role(
        self, actor_id: str, workspace_id: UUID, file_id: UUID
    ) -> tuple[FileRecord, WorkspaceRole]:
        with self._engine.connect() as connection:
            try:
                role = self._membership.require_member(connection, workspace_id, actor_id)
            except HTTPException as error:
                raise FileStoreError(FileStoreIssue.PERMISSION_DENIED) from error
            row = (
                connection.execute(
                    self._sql(
                        """SELECT f.file_id, f.workspace_id, f.company_id, f.state,
                    f.display_name, f.media_type,
                    f.byte_size, f.content_sha256, f.storage_key, f.created_at, f.updated_at
                    FROM "{schema}".samurai_files f
                    WHERE f.file_id = :file_id AND f.workspace_id = :workspace_id"""
                    ),
                    {"file_id": file_id, "workspace_id": workspace_id},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise FileStoreError(FileStoreIssue.NOT_FOUND)
        return FileRecord.model_validate(row), role

    def _require_writable(
        self, actor_id: str, workspace_id: UUID, connection: Connection | None = None
    ) -> None:
        if connection is None:
            with self._engine.connect() as fresh:
                role = self._membership.require_member(fresh, workspace_id, actor_id)
        else:
            role = self._membership.require_member(connection, workspace_id, actor_id)
        if role is WorkspaceRole.VIEWER:
            raise FileStoreError(FileStoreIssue.PERMISSION_DENIED)

    def _require_company(
        self, connection: Connection, workspace_id: UUID, company_id: UUID
    ) -> None:
        found = connection.execute(
            self._sql(
                """SELECT 1 FROM "{schema}".samurai_companies
                WHERE company_id = :company_id AND workspace_id = :workspace_id"""
            ),
            {"company_id": company_id, "workspace_id": workspace_id},
        ).scalar_one_or_none()
        if found is None:
            raise FileStoreError(FileStoreIssue.NOT_FOUND)

    @staticmethod
    def _validate(display_name: str, media_type: str, content: bytes) -> None:
        path = PurePosixPath(display_name)
        if path.name != display_name or display_name in {"", ".", ".."}:
            raise FileStoreError(FileStoreIssue.INVALID_NAME)
        expected = ALLOWED_TYPES.get(path.suffix.casefold())
        if expected != media_type:
            raise FileStoreError(FileStoreIssue.INVALID_TYPE)
        if media_type == "application/pdf":
            if not content.startswith(b"%PDF-"):
                raise FileStoreError(FileStoreIssue.INVALID_SIGNATURE)
            return
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise FileStoreError(FileStoreIssue.INVALID_UTF8) from error
        if media_type == "application/json":
            try:
                json.loads(decoded, parse_constant=_reject_json_constant)
            except (json.JSONDecodeError, ValueError) as error:
                raise FileStoreError(FileStoreIssue.INVALID_JSON) from error

    def _sql(self, source: str) -> TextClause:
        return text(source.format(schema=self._schema))

    @staticmethod
    def _lock_object(connection: Connection, key: str) -> None:
        _ = connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:object_key, 0))"),
            {"object_key": f"samurai-file-object:{key}"},
        )


def _reject_json_constant(value: str) -> None:
    message = f"invalid JSON constant: {value}"
    raise ValueError(message)
