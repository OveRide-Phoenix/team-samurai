"""Bounded local implementation of the workspace object-store contract."""

from __future__ import annotations

import hashlib
import os
import stat
from contextlib import contextmanager, suppress
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, final
from uuid import uuid4

from samurai.file_store_contracts import FileStoreError, FileStoreIssue, StoredObject

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable


@final
class LocalObjectStore:
    """Store server-generated keys through directory-relative no-follow operations."""

    def __init__(self, root: Path) -> None:
        """Create and pin a non-symlink storage root."""
        if root.is_symlink():
            raise FileStoreError(FileStoreIssue.STORAGE_ROOT)
        root.mkdir(parents=True, exist_ok=True)
        self._root: Path = root.resolve()

    def write_quarantine(self, chunks: Iterable[bytes], *, max_bytes: int) -> StoredObject:
        """Stream bounded bytes to one server-generated quarantine object."""
        key = f"quarantine/{uuid4()}"
        digest = hashlib.sha256()
        size = 0
        with self._parent(key, create=True) as (parent, leaf):
            descriptor = os.open(
                leaf,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    for chunk in chunks:
                        size += len(chunk)
                        self._check_size(size, max_bytes)
                        _ = stream.write(chunk)
                        digest.update(chunk)
            except BaseException:
                os.unlink(leaf, dir_fd=parent)
                raise
        return StoredObject(key=key, byte_size=size, sha256=digest.hexdigest())

    def promote(self, quarantine_key: str, ready_key: str) -> None:
        """Link valid bytes into content-addressed storage without overwriting."""
        expected = PurePosixPath(ready_key).name
        if self._hash(quarantine_key) != expected:
            raise FileStoreError(FileStoreIssue.HASH_MISMATCH)
        with (
            self._parent(quarantine_key) as (source_parent, source_leaf),
            self._parent(ready_key, create=True) as (target_parent, target_leaf),
        ):
            try:
                os.link(
                    source_leaf,
                    target_leaf,
                    src_dir_fd=source_parent,
                    dst_dir_fd=target_parent,
                    follow_symlinks=False,
                )
            except FileExistsError:
                if self._hash(ready_key) != expected:
                    raise FileStoreError(FileStoreIssue.HASH_MISMATCH) from None
            os.unlink(source_leaf, dir_fd=source_parent)

    def read(self, key: str) -> bytes:
        """Read one internal key without following a final symlink."""
        with self._parent(key) as (parent, leaf):
            try:
                descriptor = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            except FileNotFoundError as error:
                raise FileStoreError(FileStoreIssue.STORAGE_MISSING) from error
        with os.fdopen(descriptor, "rb") as stream:
            return stream.read()

    def delete(self, key: str) -> None:
        """Delete one internal key idempotently."""
        try:
            with self._parent(key) as (parent, leaf):
                try:
                    os.unlink(leaf, dir_fd=parent)
                except FileNotFoundError:
                    return
        except FileStoreError as error:
            if error.issue is not FileStoreIssue.STORAGE_MISSING:
                raise

    def exists(self, key: str) -> bool:
        """Check one internal key without following symlinks."""
        try:
            with self._parent(key) as (parent, leaf):
                try:
                    mode = os.stat(leaf, dir_fd=parent, follow_symlinks=False).st_mode
                except FileNotFoundError:
                    return False
        except FileStoreError as error:
            if error.issue is FileStoreIssue.STORAGE_MISSING:
                return False
            raise
        return stat.S_ISREG(mode)

    def keys(self) -> tuple[str, ...]:
        """List regular objects without traversing symlink directories."""
        return tuple(
            sorted(
                path.relative_to(self._root).as_posix()
                for path in self._root.rglob("*")
                if path.is_file() and not path.is_symlink()
            )
        )

    def modified_at(self, key: str) -> int:
        """Return an object's integer modification time."""
        with self._parent(key) as (parent, leaf):
            return int(os.stat(leaf, dir_fd=parent, follow_symlinks=False).st_mtime)

    @contextmanager
    def _parent(self, key: str, *, create: bool = False) -> Generator[tuple[int, str]]:
        parts = PurePosixPath(key).parts
        if (
            PurePosixPath(key).is_absolute()
            or not parts
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise FileStoreError(FileStoreIssue.STORAGE_KEY)
        descriptor = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                try:
                    child = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=descriptor,
                    )
                except FileNotFoundError:
                    if not create:
                        raise FileStoreError(FileStoreIssue.STORAGE_MISSING) from None
                    with suppress(FileExistsError):
                        os.mkdir(part, mode=0o700, dir_fd=descriptor)
                    child = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=descriptor,
                    )
                os.close(descriptor)
                descriptor = child
        except OSError as error:
            os.close(descriptor)
            raise FileStoreError(FileStoreIssue.STORAGE_KEY) from error
        try:
            yield descriptor, parts[-1]
        finally:
            os.close(descriptor)

    def _hash(self, key: str) -> str:
        digest = hashlib.sha256()
        with self._parent(key) as (parent, leaf):
            try:
                descriptor = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            except FileNotFoundError as error:
                raise FileStoreError(FileStoreIssue.STORAGE_MISSING) from error
        with os.fdopen(descriptor, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _check_size(size: int, max_bytes: int) -> None:
        if size > max_bytes:
            raise FileStoreError(FileStoreIssue.FILE_TOO_LARGE)
