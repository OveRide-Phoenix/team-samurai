"""Global maintenance for immutable workspace file storage."""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, cast, final

from sqlalchemy import text

from samurai.quota import WorkspaceQuota

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.engine import Connection, Engine
    from sqlalchemy.sql.elements import TextClause

    from samurai.file_store_contracts import ObjectStore

QUARANTINE_SECONDS = 3600
PURGE_SECONDS = 7 * 86400
RECEIPT_SECONDS = 30 * 86400


@final
class FileStoreMaintenance:
    """Run process-level cleanup under the same workspace quota locks as writes."""

    def __init__(self, engine: Engine, schema: str, objects: ObjectStore) -> None:
        """Bind one validated file-store schema and object adapter."""
        self._engine: Engine = engine
        self._schema: str = schema
        self._objects: ObjectStore = objects
        self._quota = WorkspaceQuota(schema)

    def cleanup_quarantine(self, *, now: int | None = None) -> int:
        """Reject quarantines older than one hour and release their quota."""
        timestamp = int(time.time()) if now is None else now
        with self._engine.connect() as connection:
            candidates = cast(
                "list[tuple[UUID, UUID]]",
                connection.execute(
                    self._sql(
                        """SELECT file_id, workspace_id FROM "{schema}".samurai_files
                        WHERE state = 'quarantined' AND updated_at <= :cutoff"""
                    ),
                    {"cutoff": timestamp - QUARANTINE_SECONDS},
                ).all(),
            )
        cleaned = 0
        for file_id, workspace_id in candidates:
            with self._engine.begin() as connection:
                self._quota.lock(connection, workspace_id)
                row = cast(
                    "tuple[int, str] | None",
                    connection.execute(
                        self._sql(
                            """SELECT byte_size, storage_key FROM "{schema}".samurai_files
                            WHERE file_id = :file_id AND state = 'quarantined'
                            AND updated_at <= :cutoff FOR UPDATE"""
                        ),
                        {"file_id": file_id, "cutoff": timestamp - QUARANTINE_SECONDS},
                    ).one_or_none(),
                )
                if row is None:
                    continue
                byte_size, storage_key = row
                self._quota.release_file(connection, workspace_id, byte_size)
                self._objects.delete(storage_key)
                _ = connection.execute(
                    self._sql(
                        """UPDATE "{schema}".samurai_files SET state = 'rejected',
                        rejection_code = 'quarantine_expired', updated_at = :now,
                        storage_key = 'redacted' WHERE file_id = :file_id"""
                    ),
                    {"file_id": file_id, "now": timestamp},
                )
                cleaned += 1
        return cleaned

    def purge_deleted(self, *, now: int | None = None) -> tuple[int, int]:
        """Purge unshared bytes after seven days and receipts after thirty."""
        timestamp = int(time.time()) if now is None else now
        purged = 0
        expired = 0
        with self._engine.connect() as connection:
            candidates = cast(
                "list[tuple[UUID, UUID]]",
                connection.execute(
                    self._sql(
                        """SELECT receipt_id, workspace_id
                        FROM "{schema}".samurai_file_deletion_receipts
                        WHERE purge_after <= :now"""
                    ),
                    {"now": timestamp},
                ).all(),
            )
        for receipt_id, workspace_id in candidates:
            with self._engine.begin() as connection:
                self._quota.lock(connection, workspace_id)
                receipt = cast(
                    "tuple[UUID, str, int] | None",
                    connection.execute(
                        self._sql(
                            """SELECT file_id, content_sha256, retain_until
                            FROM "{schema}".samurai_file_deletion_receipts
                            WHERE receipt_id = :receipt_id AND purge_after <= :now FOR UPDATE"""
                        ),
                        {"receipt_id": receipt_id, "now": timestamp},
                    ).one_or_none(),
                )
                if receipt is None:
                    continue
                file_id, content_sha256, retain_until = receipt
                key = self._ready_key(workspace_id, content_sha256)
                self._lock_object(connection, key)
                active = connection.execute(
                    self._sql(
                        """SELECT 1 FROM "{schema}".samurai_files
                        WHERE workspace_id = :workspace_id AND content_sha256 = :sha256
                        AND state IN ('quarantined', 'ready') LIMIT 1"""
                    ),
                    {"workspace_id": workspace_id, "sha256": content_sha256},
                ).scalar_one_or_none()
                if active is None and self._objects.exists(key):
                    self._objects.delete(key)
                    purged += 1
                if retain_until <= timestamp:
                    _ = connection.execute(
                        self._sql(
                            """DELETE FROM "{schema}".samurai_file_deletion_receipts
                            WHERE receipt_id = :receipt_id"""
                        ),
                        {"receipt_id": receipt_id},
                    )
                    _ = connection.execute(
                        self._sql(
                            """DELETE FROM "{schema}".samurai_files
                            WHERE file_id = :file_id AND state = 'deleted'"""
                        ),
                        {"file_id": file_id},
                    )
                    expired += 1
        return purged, expired

    def reconcile_orphans(self, *, now: int | None = None) -> tuple[int, int]:
        """Repair validated promotions and remove aged unreferenced quarantines."""
        timestamp = int(time.time()) if now is None else now
        repaired = 0
        with self._engine.connect() as connection:
            candidates = cast(
                "list[tuple[UUID, UUID, str]]",
                connection.execute(
                    self._sql(
                        """SELECT file_id, workspace_id, content_sha256
                        FROM "{schema}".samurai_files
                        WHERE state = 'quarantined'"""
                    )
                ).all(),
            )
        for file_id, workspace_id, content_sha256 in candidates:
            ready_key = self._ready_key(workspace_id, content_sha256)
            with self._engine.begin() as connection:
                self._lock_object(connection, ready_key)
                byte_size = cast(
                    "int | None",
                    connection.execute(
                        self._sql(
                            """SELECT byte_size FROM "{schema}".samurai_files
                            WHERE file_id = :file_id AND state = 'quarantined' FOR UPDATE"""
                        ),
                        {"file_id": file_id},
                    ).scalar_one_or_none(),
                )
                if byte_size is None:
                    continue
                if not self._objects.exists(ready_key):
                    continue
                content = self._objects.read(ready_key)
                if (
                    hashlib.sha256(content).hexdigest() != content_sha256
                    or len(content) != byte_size
                ):
                    continue
                _ = connection.execute(
                    self._sql(
                        """UPDATE "{schema}".samurai_files SET state = 'ready',
                        storage_key = :key, updated_at = :now WHERE file_id = :file_id"""
                    ),
                    {"file_id": file_id, "key": ready_key, "now": timestamp},
                )
                repaired += 1
        removed = 0
        for key in self._objects.keys():  # noqa: SIM118 - protocol exposes a tuple, not a mapping.
            if not key.startswith(("quarantine/", "ready/")):
                continue
            if key.startswith("quarantine/") and (
                self._objects.modified_at(key) > timestamp - QUARANTINE_SECONDS
            ):
                continue
            with self._engine.begin() as connection:
                self._lock_object(connection, key)
                current = connection.execute(
                    self._sql(
                        """SELECT 1 FROM "{schema}".samurai_files f
                        LEFT JOIN "{schema}".samurai_file_deletion_receipts r
                        ON r.file_id = f.file_id
                        WHERE f.storage_key = :key AND (f.state IN ('quarantined', 'ready')
                        OR (f.state = 'deleted' AND r.purge_after > :now)) LIMIT 1"""
                    ),
                    {"key": key, "now": timestamp},
                ).scalar_one_or_none()
                if current is None:
                    self._objects.delete(key)
                    removed += 1
        return repaired, removed

    @staticmethod
    def _ready_key(workspace_id: UUID, content_sha256: str) -> str:
        return f"ready/{workspace_id}/{content_sha256}"

    def _sql(self, source: str) -> TextClause:
        return text(source.format(schema=self._schema))

    @staticmethod
    def _lock_object(connection: Connection, key: str) -> None:
        _ = connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:object_key, 0))"),
            {"object_key": f"samurai-file-object:{key}"},
        )
