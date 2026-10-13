from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from hashlib import sha256
from pathlib import Path
from threading import Barrier, Event
from typing import TYPE_CHECKING, override
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import MetaData, Table, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import DropSchema

from samurai.company_store_contracts import WorkspaceRole
from samurai.execution_state import SamuraiPostgresDb
from samurai.file_store import FileStore
from samurai.file_store_contracts import (
    FileState,
    FileStoreError,
    FileStoreIssue,
    ObjectStore,
    StoredObject,
)
from samurai.local_object_store import LocalObjectStore
from samurai.quota import WorkspaceQuotaExceededError
from samurai.schema import FounderPlatformMigrator
from samurai.workspace_directory import WorkspaceDirectory

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

pytest_plugins = ("tests.company_store_support",)


class _QuotaUsage(BaseModel):
    file_count: int
    stored_bytes: int


@pytest.fixture
def file_database(postgres_url: str) -> Iterator[SamuraiPostgresDb]:
    schema = f"founder_t08_{uuid4().hex}"
    database = SamuraiPostgresDb(id=schema, db_url=postgres_url, db_schema=schema)
    database.ensure_work_intents_table()
    _ = FounderPlatformMigrator(database.db_engine, schema=schema).apply()
    yield database
    with database.db_engine.begin() as connection:
        _ = connection.execute(DropSchema(schema, cascade=True, if_exists=True))
    database.close()


def _quota(database: SamuraiPostgresDb, workspace_id: UUID) -> tuple[int, int]:
    quotas = Table(
        "samurai_workspace_quotas",
        MetaData(schema=database.db_schema),
        autoload_with=database.db_engine,
    )
    with database.db_engine.connect() as connection:
        row = (
            connection.execute(quotas.select().where(quotas.c.workspace_id == workspace_id))
            .mappings()
            .one()
        )
    usage = _QuotaUsage.model_validate(row)
    return usage.file_count, usage.stored_bytes


def _store(
    database: SamuraiPostgresDb, root: Path, *, objects: ObjectStore | None = None
) -> FileStore:
    return FileStore(
        database.db_engine,
        schema=database.db_schema,
        objects=objects or LocalObjectStore(root),
    )


def _workspace(database: SamuraiPostgresDb) -> UUID:
    return WorkspaceDirectory(database).create_workspace("owner", "Files").workspace_id


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def write_quarantine(self, chunks: Iterable[bytes], *, max_bytes: int) -> StoredObject:
        content = b"".join(chunks)
        if len(content) > max_bytes:
            raise FileStoreError(FileStoreIssue.FILE_TOO_LARGE)
        key = f"quarantine/{uuid4()}"
        self.objects[key] = content
        return StoredObject(key=key, byte_size=len(content), sha256=sha256(content).hexdigest())

    def promote(self, quarantine_key: str, ready_key: str) -> None:
        content = self.objects.pop(quarantine_key)
        _ = self.objects.setdefault(ready_key, content)

    def read(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        _ = self.objects.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self.objects

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.objects))

    def modified_at(self, key: str) -> int:
        if key not in self.objects:
            raise KeyError(key)
        return 0


class FailingPromoteStore(FakeObjectStore):
    @override
    def promote(self, quarantine_key: str, ready_key: str) -> None:
        _ = (quarantine_key, ready_key)
        message = "synthetic promote failure"
        raise OSError(message)


class InvalidMetadataStore(FakeObjectStore):
    @override
    def write_quarantine(self, chunks: Iterable[bytes], *, max_bytes: int) -> StoredObject:
        stored = super().write_quarantine(chunks, max_bytes=max_bytes)
        return StoredObject(key=stored.key, byte_size=stored.byte_size, sha256="invalid")


class CoordinatedObjectStore(FakeObjectStore):
    def __init__(self, inspected: Event, release: Event) -> None:
        super().__init__()
        self._inspected: Event = inspected
        self._release: Event = release

    @override
    def modified_at(self, key: str) -> int:
        self._inspected.set()
        assert self._release.wait(timeout=2)
        return super().modified_at(key)


class BlockingWriteStore(FakeObjectStore):
    def __init__(self, written: Event, release: Event) -> None:
        super().__init__()
        self._written: Event = written
        self._release: Event = release

    @override
    def write_quarantine(self, chunks: Iterable[bytes], *, max_bytes: int) -> StoredObject:
        stored = super().write_quarantine(chunks, max_bytes=max_bytes)
        self._written.set()
        assert self._release.wait(timeout=2)
        return stored


class BlockingPromoteStore(FakeObjectStore):
    def __init__(self, promoted: Event, release: Event) -> None:
        super().__init__()
        self._promoted: Event = promoted
        self._release: Event = release

    @override
    def promote(self, quarantine_key: str, ready_key: str) -> None:
        super().promote(quarantine_key, ready_key)
        self._promoted.set()
        assert self._release.wait(timeout=2)


def test_ready_upload_is_immutable_authorized_and_quota_backed(
    file_database: SamuraiPostgresDb, tmp_path: Path
) -> None:
    directory = WorkspaceDirectory(file_database)
    workspace_id = directory.create_workspace("owner", "Files").workspace_id
    store = FileStore(
        file_database.db_engine,
        schema=file_database.db_schema,
        objects=LocalObjectStore(tmp_path / "objects"),
    )

    uploaded = store.upload(
        actor_id="owner",
        workspace_id=workspace_id,
        display_name="brief.txt",
        media_type="text/plain",
        chunks=[b"bounded founder evidence\n"],
    )

    assert uploaded.state is FileState.READY
    assert store.read("owner", workspace_id, uploaded.file_id) == b"bounded founder evidence\n"
    assert _quota(file_database, workspace_id) == (1, len(b"bounded founder evidence\n"))


@pytest.mark.parametrize(
    ("display_name", "media_type", "content"),
    [
        ("brief.md", "text/markdown", b"# Brief\n"),
        ("table.csv", "text/csv", b"name,value\na,1\n"),
        ("facts.json", "application/json", b'{"fact":true}'),
        ("source.pdf", "application/pdf", b"%PDF-1.7\nopaque bytes\xff"),
    ],
)
def test_allowed_files_become_ready(
    file_database: SamuraiPostgresDb,
    tmp_path: Path,
    display_name: str,
    media_type: str,
    content: bytes,
) -> None:
    workspace_id = _workspace(file_database)
    store = _store(file_database, tmp_path / "objects")

    uploaded = store.upload(
        actor_id="owner",
        workspace_id=workspace_id,
        display_name=display_name,
        media_type=media_type,
        chunks=[content[:3], content[3:]],
    )

    assert uploaded.state is FileState.READY
    assert uploaded.content_sha256 == sha256(content).hexdigest()
    assert store.read("owner", workspace_id, uploaded.file_id) == content


@pytest.mark.parametrize(
    "case",
    [
        ("../brief.txt", "text/plain", b"text", FileStoreIssue.INVALID_NAME),
        ("brief.exe", "text/plain", b"text", FileStoreIssue.INVALID_TYPE),
        ("brief.txt", "application/json", b"text", FileStoreIssue.INVALID_TYPE),
        ("brief.txt", "text/plain", b"\xff", FileStoreIssue.INVALID_UTF8),
        ("brief.json", "application/json", b"{broken", FileStoreIssue.INVALID_JSON),
        ("brief.json", "application/json", b"NaN", FileStoreIssue.INVALID_JSON),
        ("brief.json", "application/json", b"Infinity", FileStoreIssue.INVALID_JSON),
        ("brief.pdf", "application/pdf", b"not a pdf", FileStoreIssue.INVALID_SIGNATURE),
    ],
)
def test_malformed_or_spoofed_upload_is_rejected_without_quota(
    file_database: SamuraiPostgresDb,
    tmp_path: Path,
    case: tuple[str, str, bytes, FileStoreIssue],
) -> None:
    display_name, media_type, content, issue = case
    workspace_id = _workspace(file_database)
    store = _store(file_database, tmp_path / "objects")

    with pytest.raises(FileStoreError) as caught:
        _ = store.upload(
            actor_id="owner",
            workspace_id=workspace_id,
            display_name=display_name,
            media_type=media_type,
            chunks=[content],
        )

    assert caught.value.issue is issue
    assert _quota(file_database, workspace_id) == (0, 0)
    assert not any(path.is_file() for path in (tmp_path / "objects").rglob("*"))


def test_upload_rejects_ten_mebibytes_plus_one(
    file_database: SamuraiPostgresDb, tmp_path: Path
) -> None:
    workspace_id = _workspace(file_database)
    store = _store(file_database, tmp_path / "objects")

    with pytest.raises(FileStoreError) as caught:
        _ = store.upload(
            actor_id="owner",
            workspace_id=workspace_id,
            display_name="large.txt",
            media_type="text/plain",
            chunks=[b"a" * (10 * 1024 * 1024), b"b"],
        )

    assert caught.value.issue is FileStoreIssue.FILE_TOO_LARGE
    assert _quota(file_database, workspace_id) == (0, 0)


def test_upload_accepts_exact_ten_mebibyte_stream(
    file_database: SamuraiPostgresDb, tmp_path: Path
) -> None:
    workspace_id = _workspace(file_database)
    store = _store(file_database, tmp_path / "objects")

    uploaded = store.upload(
        actor_id="owner",
        workspace_id=workspace_id,
        display_name="limit.txt",
        media_type="text/plain",
        chunks=(b"a" * (1024 * 1024) for _ in range(10)),
    )

    assert uploaded.byte_size == 10 * 1024 * 1024
    assert _quota(file_database, workspace_id) == (1, 10 * 1024 * 1024)


def test_concurrent_uploads_serialize_at_workspace_byte_quota(
    file_database: SamuraiPostgresDb, tmp_path: Path
) -> None:
    workspace_id = _workspace(file_database)
    store = _store(file_database, tmp_path / "objects")
    quotas = Table(
        "samurai_workspace_quotas",
        MetaData(schema=file_database.db_schema),
        autoload_with=file_database.db_engine,
    )
    files = Table(
        "samurai_files",
        MetaData(schema=file_database.db_schema),
        autoload_with=file_database.db_engine,
    )
    with file_database.db_engine.begin() as connection:
        _ = connection.execute(
            quotas.update()
            .where(quotas.c.workspace_id == workspace_id)
            .values(file_count=10, stored_bytes=100 * 1024 * 1024 - 1)
        )
        _ = connection.execute(
            files.insert(),
            [
                {
                    "file_id": uuid4(),
                    "workspace_id": workspace_id,
                    "created_by": "owner",
                    "state": "quarantined",
                    "display_name": f"existing-{index}.txt",
                    "media_type": "text/plain",
                    "byte_size": 10 * 1024 * 1024 - (1 if index == 9 else 0),
                    "content_sha256": f"{index:064x}",
                    "storage_key": f"quarantine/synthetic-{index}",
                    "created_at": 1,
                    "updated_at": 1,
                }
                for index in range(10)
            ],
        )
    barrier = Barrier(2)

    def upload(display_name: str) -> bool:
        def chunks() -> Iterator[bytes]:
            _ = barrier.wait(timeout=2)
            yield b"x"

        try:
            _ = store.upload("owner", workspace_id, display_name, "text/plain", chunks())
        except WorkspaceQuotaExceededError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(upload, ("one.txt", "two.txt")))

    assert sorted(results) == [False, True]
    assert _quota(file_database, workspace_id) == (11, 100 * 1024 * 1024)
    assert (
        len(tuple(path for path in (tmp_path / "objects" / "ready").rglob("*") if path.is_file()))
        == 1
    )


def test_membership_revocation_after_quarantine_rolls_back_bytes(
    file_database: SamuraiPostgresDb,
) -> None:
    directory = WorkspaceDirectory(file_database)
    workspace_id = directory.create_workspace("owner", "Files").workspace_id
    _ = directory.put_member("owner", workspace_id, "editor", WorkspaceRole.EDITOR)
    written = Event()
    release = Event()
    objects = BlockingWriteStore(written, release)
    store = _store(file_database, Path("unused"), objects=objects)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            store.upload, "editor", workspace_id, "brief.txt", "text/plain", [b"revoked"]
        )
        assert written.wait(timeout=2)
        directory.delete_member("owner", workspace_id, "editor")
        release.set()
        with pytest.raises(HTTPException) as caught:
            _ = future.result(timeout=2)

    assert caught.value.status_code == 403
    assert _quota(file_database, workspace_id) == (0, 0)
    assert objects.objects == {}


def test_metadata_insert_failure_rolls_back_quota_and_quarantine(
    file_database: SamuraiPostgresDb,
) -> None:
    workspace_id = _workspace(file_database)
    objects = InvalidMetadataStore()
    store = _store(file_database, Path("unused"), objects=objects)

    with pytest.raises(IntegrityError):
        _ = store.upload("owner", workspace_id, "brief.txt", "text/plain", [b"rollback"])

    assert _quota(file_database, workspace_id) == (0, 0)
    assert objects.objects == {}


def test_same_workspace_deduplicates_bytes_but_keeps_file_ids(
    file_database: SamuraiPostgresDb, tmp_path: Path
) -> None:
    workspace_id = _workspace(file_database)
    store = _store(file_database, tmp_path / "objects")

    first = store.upload("owner", workspace_id, "one.txt", "text/plain", [b"same"])
    second = store.upload("owner", workspace_id, "two.txt", "text/plain", [b"same"])

    assert first.file_id != second.file_id
    assert first.storage_key == second.storage_key
    assert _quota(file_database, workspace_id) == (2, 8)
    assert [path for path in (tmp_path / "objects" / "ready").rglob("*") if path.is_file()] == [
        tmp_path / "objects" / first.storage_key
    ]


def test_ready_read_rechecks_membership_and_file_identity(
    file_database: SamuraiPostgresDb, tmp_path: Path
) -> None:
    workspace_id = _workspace(file_database)
    other_workspace = (
        WorkspaceDirectory(file_database).create_workspace("other", "Other").workspace_id
    )
    store = _store(file_database, tmp_path / "objects")
    uploaded = store.upload("owner", workspace_id, "brief.txt", "text/plain", [b"private"])

    with pytest.raises(FileStoreError, match="file is not available"):
        _ = store.read("other", workspace_id, uploaded.file_id)
    with pytest.raises(FileStoreError, match="file is not available"):
        _ = store.read("owner", other_workspace, uploaded.file_id)


def test_delete_tombstone_denies_reads_and_retains_shared_blob(
    file_database: SamuraiPostgresDb, tmp_path: Path
) -> None:
    workspace_id = _workspace(file_database)
    store = _store(file_database, tmp_path / "objects")
    first = store.upload("owner", workspace_id, "one.txt", "text/plain", [b"same"])
    second = store.upload("owner", workspace_id, "two.txt", "text/plain", [b"same"])

    store.delete("owner", workspace_id, first.file_id, now=100)

    with pytest.raises(FileStoreError, match="file is not available"):
        _ = store.read("owner", workspace_id, first.file_id)
    assert store.read("owner", workspace_id, second.file_id) == b"same"
    assert _quota(file_database, workspace_id) == (1, 4)
    assert (tmp_path / "objects" / first.storage_key).is_file()


def test_promote_failure_stays_quarantined_until_cleanup(
    file_database: SamuraiPostgresDb,
) -> None:
    workspace_id = _workspace(file_database)
    objects = FailingPromoteStore()
    store = _store(file_database, Path("unused"), objects=objects)

    with pytest.raises(FileStoreError) as caught:
        _ = store.upload("owner", workspace_id, "brief.txt", "text/plain", [b"pending"])

    assert caught.value.issue is FileStoreIssue.PROMOTION_FAILED
    assert _quota(file_database, workspace_id) == (1, 7)
    assert store.cleanup_quarantine(now=2**62) == 1
    assert store.cleanup_quarantine(now=2**62) == 0
    assert _quota(file_database, workspace_id) == (0, 0)
    assert objects.objects == {}


def test_quarantine_cleanup_serializes_with_inflight_promotion(
    file_database: SamuraiPostgresDb,
) -> None:
    workspace_id = _workspace(file_database)
    promoted = Event()
    release = Event()
    objects = BlockingPromoteStore(promoted, release)
    store = _store(file_database, Path("unused"), objects=objects)

    with ThreadPoolExecutor(max_workers=2) as executor:
        upload_future = executor.submit(
            store.upload, "owner", workspace_id, "brief.txt", "text/plain", [b"promoted"]
        )
        assert promoted.wait(timeout=2)
        cleanup_future = executor.submit(store.cleanup_quarantine, now=2**62)
        with pytest.raises(FutureTimeoutError):
            _ = cleanup_future.result(timeout=0.1)
        release.set()
        uploaded = upload_future.result(timeout=2)
        assert cleanup_future.result(timeout=2) == 0

    assert uploaded.state is FileState.READY
    assert store.read("owner", workspace_id, uploaded.file_id) == b"promoted"
    assert _quota(file_database, workspace_id) == (1, 8)


def test_deleted_blob_purge_and_receipt_retention_are_idempotent(
    file_database: SamuraiPostgresDb, tmp_path: Path
) -> None:
    workspace_id = _workspace(file_database)
    store = _store(file_database, tmp_path / "objects")
    uploaded = store.upload("owner", workspace_id, "brief.txt", "text/plain", [b"old"])
    store.delete("owner", workspace_id, uploaded.file_id, now=10)

    assert store.purge_deleted(now=10 + 7 * 86400 - 1) == (0, 0)
    assert store.purge_deleted(now=10 + 7 * 86400) == (1, 0)
    assert store.purge_deleted(now=10 + 7 * 86400) == (0, 0)
    assert not (tmp_path / "objects" / uploaded.storage_key).exists()
    assert store.purge_deleted(now=10 + 30 * 86400) == (0, 1)
    assert store.purge_deleted(now=10 + 30 * 86400) == (0, 0)


def test_purge_race_with_same_hash_upload_preserves_ready_bytes(
    file_database: SamuraiPostgresDb, tmp_path: Path
) -> None:
    workspace_id = _workspace(file_database)
    store = _store(file_database, tmp_path / "objects")
    deleted = store.upload("owner", workspace_id, "old.txt", "text/plain", [b"same"])
    store.delete("owner", workspace_id, deleted.file_id, now=10)
    barrier = Barrier(2)

    def chunks() -> Iterator[bytes]:
        _ = barrier.wait(timeout=2)
        yield b"same"

    def purge() -> tuple[int, int]:
        _ = barrier.wait(timeout=2)
        return store.purge_deleted(now=10 + 7 * 86400)

    with ThreadPoolExecutor(max_workers=2) as executor:
        purge_future = executor.submit(purge)
        upload_future = executor.submit(
            store.upload, "owner", workspace_id, "new.txt", "text/plain", chunks()
        )
        purged = purge_future.result(timeout=2)
        uploaded = upload_future.result(timeout=2)

    assert purged in {(0, 0), (1, 0)}
    assert store.read("owner", workspace_id, uploaded.file_id) == b"same"
    assert (tmp_path / "objects" / uploaded.storage_key).is_file()
    assert _quota(file_database, workspace_id) == (1, 4)


def test_local_object_store_rejects_traversal_symlink_and_hash_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "objects"
    store = LocalObjectStore(root)
    stored = store.write_quarantine([b"safe"], max_bytes=10)

    with pytest.raises(FileStoreError, match="unsafe storage key"):
        _ = store.read("../outside")
    with pytest.raises(FileStoreError, match="stored content hash mismatch"):
        store.promote(stored.key, f"ready/{uuid4()}/{'0' * 64}")
    symlink_root = tmp_path / "link"
    symlink_root.symlink_to(root, target_is_directory=True)
    with pytest.raises(FileStoreError, match="storage root cannot be a symlink"):
        _ = LocalObjectStore(symlink_root)


def test_local_object_store_missing_parent_and_symlink_have_no_outside_effect(
    tmp_path: Path,
) -> None:
    root = tmp_path / "objects"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    store = LocalObjectStore(root)

    assert not store.exists(f"ready/{uuid4()}/{'0' * 64}")
    store.delete(f"ready/{uuid4()}/{'0' * 64}")
    (root / "quarantine").symlink_to(outside, target_is_directory=True)
    with pytest.raises(FileStoreError, match="unsafe storage key"):
        _ = store.write_quarantine([b"blocked"], max_bytes=10)
    assert tuple(outside.iterdir()) == ()


def test_interrupted_stream_removes_partial_quarantine(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")

    def interrupted() -> Iterator[bytes]:
        yield b"partial"
        message = "synthetic interrupted stream"
        raise OSError(message)

    with pytest.raises(OSError, match="synthetic interrupted stream"):
        _ = store.write_quarantine(interrupted(), max_bytes=10)
    assert store.keys() == ()


def test_revoked_membership_denies_ready_read(
    file_database: SamuraiPostgresDb, tmp_path: Path
) -> None:
    directory = WorkspaceDirectory(file_database)
    workspace_id = directory.create_workspace("owner", "Files").workspace_id
    _ = directory.put_member("owner", workspace_id, "editor", WorkspaceRole.EDITOR)
    store = _store(file_database, tmp_path / "objects")
    uploaded = store.upload("editor", workspace_id, "brief.txt", "text/plain", [b"private"])

    directory.delete_member("owner", workspace_id, "editor")

    with pytest.raises(FileStoreError, match="file is not available"):
        _ = store.read("editor", workspace_id, uploaded.file_id)


def test_reconcile_repairs_valid_promotion_and_rejects_corrupt_candidate(
    file_database: SamuraiPostgresDb,
) -> None:
    workspace_id = _workspace(file_database)
    objects = FailingPromoteStore()
    store = _store(file_database, Path("unused"), objects=objects)
    with pytest.raises(FileStoreError, match="file promotion failed"):
        _ = store.upload("owner", workspace_id, "brief.txt", "text/plain", [b"pending"])
    quarantine_key = objects.keys()[0]
    digest = sha256(b"pending").hexdigest()
    ready_key = f"ready/{workspace_id}/{digest}"
    FakeObjectStore.promote(objects, quarantine_key, ready_key)

    objects.objects[ready_key] = b"corrupt"
    assert store.reconcile_orphans(now=2**62) == (0, 1)
    objects.objects[ready_key] = b"pending"
    assert store.reconcile_orphans(now=2**62) == (1, 0)


def test_reconcile_removes_only_aged_unreferenced_quarantine(
    file_database: SamuraiPostgresDb,
) -> None:
    objects = FakeObjectStore()
    store = _store(file_database, Path("unused"), objects=objects)
    orphan = objects.write_quarantine([b"orphan"], max_bytes=10)

    assert store.reconcile_orphans(now=3599) == (0, 0)
    assert objects.exists(orphan.key)
    assert store.reconcile_orphans(now=3600) == (0, 1)
    assert not objects.exists(orphan.key)


def test_reconcile_removes_promoted_orphan_after_quarantine_cleanup(
    file_database: SamuraiPostgresDb,
) -> None:
    workspace_id = _workspace(file_database)
    objects = FailingPromoteStore()
    store = _store(file_database, Path("unused"), objects=objects)
    with pytest.raises(FileStoreError, match="file promotion failed"):
        _ = store.upload("owner", workspace_id, "brief.txt", "text/plain", [b"pending"])
    quarantine_key = objects.keys()[0]
    ready_key = f"ready/{workspace_id}/{sha256(b'pending').hexdigest()}"
    FakeObjectStore.promote(objects, quarantine_key, ready_key)

    assert store.cleanup_quarantine(now=2**62) == 1
    assert objects.exists(ready_key)
    assert store.reconcile_orphans(now=2**62) == (0, 1)
    assert not objects.exists(ready_key)


def test_reconcile_retains_deleted_blob_until_purge_window(
    file_database: SamuraiPostgresDb,
) -> None:
    workspace_id = _workspace(file_database)
    objects = FakeObjectStore()
    store = _store(file_database, Path("unused"), objects=objects)
    uploaded = store.upload("owner", workspace_id, "brief.txt", "text/plain", [b"retained"])
    store.delete("owner", workspace_id, uploaded.file_id, now=10)

    assert store.reconcile_orphans(now=11) == (0, 0)
    assert objects.exists(uploaded.storage_key)


def test_orphan_reconcile_serializes_with_metadata_admission(
    file_database: SamuraiPostgresDb,
) -> None:
    workspace_id = _workspace(file_database)
    inspected = Event()
    release = Event()
    objects = CoordinatedObjectStore(inspected, release)
    store = _store(file_database, Path("unused"), objects=objects)
    orphan = objects.write_quarantine([b"race"], max_bytes=10)
    file_id = uuid4()

    with file_database.db_engine.connect() as connection:
        transaction = connection.begin()
        _ = connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:object_key, 0))"),
            {"object_key": f"samurai-file-object:{orphan.key}"},
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(store.reconcile_orphans, now=3600)
            assert inspected.wait(timeout=2)
            _ = connection.execute(
                Table(
                    "samurai_files",
                    MetaData(schema=file_database.db_schema),
                    autoload_with=file_database.db_engine,
                ).insert(),
                {
                    "file_id": file_id,
                    "workspace_id": workspace_id,
                    "created_by": "owner",
                    "state": "quarantined",
                    "display_name": "race.txt",
                    "media_type": "text/plain",
                    "byte_size": 4,
                    "content_sha256": orphan.sha256,
                    "storage_key": orphan.key,
                    "created_at": 1,
                    "updated_at": 1,
                },
            )
            release.set()
            with pytest.raises(FutureTimeoutError):
                _ = future.result(timeout=0.1)
            transaction.commit()
            assert future.result(timeout=2) == (0, 0)
    assert objects.exists(orphan.key)


def test_object_store_conformance(tmp_path: Path) -> None:
    stores: tuple[ObjectStore, ...] = (LocalObjectStore(tmp_path / "objects"), FakeObjectStore())
    for store in stores:
        stored = store.write_quarantine([b"con", b"tent"], max_bytes=7)
        ready_key = f"ready/{uuid4()}/{stored.sha256}"

        store.promote(stored.key, ready_key)

        assert store.read(ready_key) == b"content"
        assert store.exists(ready_key)
        assert store.keys() == (ready_key,)
        store.delete(ready_key)
        assert not store.exists(ready_key)
