"""Typed contracts for immutable workspace file storage."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, ClassVar, Protocol, override, runtime_checkable
from uuid import UUID  # noqa: TC003 - Pydantic resolves UUID fields at runtime.

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


@unique
class FileState(StrEnum):
    """Durable file lifecycle states."""

    QUARANTINED = "quarantined"
    READY = "ready"
    REJECTED = "rejected"
    DELETED = "deleted"


class FileStoreIssue(StrEnum):
    """Stable file boundary failures."""

    INVALID_NAME = "invalid file name"
    INVALID_TYPE = "file extension and media type are not allowed"
    INVALID_UTF8 = "text file must be valid UTF-8"
    INVALID_JSON = "JSON file must contain one valid JSON value"
    INVALID_SIGNATURE = "PDF signature is invalid"
    FILE_TOO_LARGE = "file exceeds the 10 MiB limit"
    EMPTY_CHUNK = "file chunks must contain bytes"
    PERMISSION_DENIED = "file is not available"
    NOT_READY = "file is not ready"
    PROMOTION_FAILED = "file promotion failed"
    STORAGE_KEY = "unsafe storage key"
    STORAGE_ROOT = "storage root cannot be a symlink"
    HASH_MISMATCH = "stored content hash mismatch"
    STORAGE_MISSING = "stored content is missing"
    NOT_FOUND = "file not found"


@dataclass(slots=True)
class FileStoreError(Exception):
    """Expose one stable boundary failure without leaking paths."""

    issue: FileStoreIssue

    @override
    def __str__(self) -> str:
        """Return the stable boundary message."""
        if self.issue is FileStoreIssue.NOT_READY:
            return FileStoreIssue.PERMISSION_DENIED.value
        return self.issue.value


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Server-generated quarantine object description."""

    key: str
    byte_size: int
    sha256: str


class FileRecord(BaseModel):
    """Internal lifecycle metadata for one logical workspace file."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    file_id: UUID
    workspace_id: UUID
    company_id: UUID | None
    state: FileState
    display_name: str
    media_type: str
    byte_size: int
    content_sha256: str
    storage_key: str
    created_at: int
    updated_at: int


class FileContentReference(BaseModel):
    """Checked byte accounting and content identity from file metadata."""

    byte_size: int
    content_sha256: str


@runtime_checkable
class ObjectStore(Protocol):
    """Minimum object semantics required by local and future cloud adapters."""

    def write_quarantine(self, chunks: Iterable[bytes], *, max_bytes: int) -> StoredObject:
        """Stream bounded bytes to a generated quarantine key."""
        ...

    def promote(self, quarantine_key: str, ready_key: str) -> None:
        """Atomically make quarantined bytes available at a generated ready key."""
        ...

    def read(self, key: str) -> bytes:
        """Read bytes for one internal key."""
        ...

    def chunks(self, key: str, *, chunk_size: int) -> Iterator[bytes]:
        """Stream one internal key in bounded chunks."""
        ...

    def delete(self, key: str) -> None:
        """Delete one internal key idempotently."""
        ...

    def exists(self, key: str) -> bool:
        """Report whether one internal key exists."""
        ...

    def keys(self) -> tuple[str, ...]:
        """List internal keys for maintenance reconciliation."""
        ...

    def modified_at(self, key: str) -> int:
        """Return integer modification time for retention decisions."""
        ...
