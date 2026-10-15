"""Deterministic workspace knowledge over accepted artifacts and ready text files."""

# allow: SIZE_OK — one transaction boundary owns authorization, provenance, quota, and retrieval.

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, ClassVar, Final, Literal, cast, final, override
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text

from samurai.company_store_contracts import WorkspaceRole
from samurai.company_store_queries import valid_schema
from samurai.contracts import ArtifactEnvelope, CompanyState, KnowledgeReference
from samurai.file_store_contracts import FileStoreError, ObjectStore
from samurai.quota import QuotaResource, WorkspaceQuota, WorkspaceQuotaExceededError

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine
    from sqlalchemy.orm import Session as SqlAlchemySession
    from sqlalchemy.sql.elements import TextClause

CHUNK_CHARACTERS: Final = 2000
CHUNKS_PER_SOURCE: Final = 50
MAX_QUERY_CHARACTERS: Final = 200
MAX_RESULTS: Final = 5
TEXT_MEDIA_TYPES: Final = {"text/plain", "text/markdown", "text/csv", "application/json"}
TOKEN_PATTERN: Final = re.compile(r"\w+")
WHITESPACE_PATTERN: Final = re.compile(r"\s+")
SECRET_PATTERN: Final = re.compile(
    r"(?i:-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:api[_-]?key|password|secret|token)[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{8,}|[a-z][a-z0-9+.-]*://[^\s:/]+:[^\s@]+@)"
)


def _artifact_json(artifact: ArtifactEnvelope) -> str:
    return json.dumps(
        artifact.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


@unique
class KnowledgeTrustClass(StrEnum):
    """Authority-derived source class returned with every chunk."""

    ACCEPTED_ARTIFACT = "accepted_artifact"
    UPLOADED_FILE = "uploaded_file"


@unique
class KnowledgeIssue(StrEnum):
    """Stable failures safe to expose at the later API boundary."""

    INVALID_SCHEMA = "invalid knowledge schema"
    INVALID_QUERY = "knowledge query must contain 1 to 200 characters"
    INVALID_SCOPE = "company scope is required"
    PERMISSION_DENIED = "active workspace membership and epoch are required"
    SOURCE_NOT_FOUND = "knowledge source was not found"
    SOURCE_INELIGIBLE = "knowledge source is not eligible"
    CONTENT_CHANGED = "knowledge source content changed during indexing"
    SENSITIVE_CONTENT = "knowledge source contains credential material"
    WORKSPACE_QUOTA = "workspace knowledge quota exceeded"


@dataclass(slots=True)
class KnowledgeStoreError(Exception):
    """Reject one unsafe operation without leaking storage details."""

    issue: KnowledgeIssue

    @override
    def __str__(self) -> str:
        return self.issue.value


@dataclass(frozen=True, slots=True)
class KnowledgeScope:
    """Server-derived actor and workspace authorization fence."""

    actor_id: str
    workspace_id: UUID
    authorization_epoch: int
    company_id: UUID | None = None


class KnowledgeChunk(BaseModel):
    """Immutable indexed excerpt with exact source provenance."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    chunk_id: UUID
    workspace_id: UUID
    company_id: UUID | None
    file_id: UUID | None
    artifact_id: UUID | None
    indexed_revision: int
    ordinal: int
    excerpt: str
    content_sha256: str
    trust_class: KnowledgeTrustClass
    evidence_status: Literal["untrusted_context"] = "untrusted_context"


class KnowledgeResult(KnowledgeChunk):
    """One deterministic lexical match, never evidence support."""

    score: int


class _MembershipRow(BaseModel):
    role: WorkspaceRole
    authorization_epoch: int


class _FileRow(BaseModel):
    file_id: UUID
    company_id: UUID | None
    state: str
    media_type: str
    byte_size: int
    content_sha256: str
    storage_key: str
    updated_at: int


class _CandidateRow(BaseModel):
    chunk_id: UUID
    workspace_id: UUID
    company_id: UUID | None
    file_id: UUID | None
    artifact_id: UUID | None
    source_revision: int
    ordinal: int
    content: str
    content_sha256: str
    file_sha256: str | None
    canonical_state: dict[str, JsonValue] | None


class _ReferenceRow(BaseModel):
    chunk_id: UUID
    company_id: UUID | None
    file_id: UUID | None
    artifact_id: UUID | None
    source_revision: int
    ordinal: int
    content_sha256: str
    file_state: str | None
    file_sha256: str | None


@dataclass(frozen=True, slots=True)
class _Source:
    source_id: UUID
    company_id: UUID | None
    trust_class: KnowledgeTrustClass
    revision: int
    content_sha256: str
    excerpts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeAcceptance:
    """Canonical scope and new references checked in one acceptance transaction."""

    workspace_id: UUID
    company_id: UUID
    canonical_state: CompanyState
    references: tuple[KnowledgeReference, ...]


@final
class KnowledgeReferenceGuard:
    """Reject changed or inaccessible knowledge before canonical acceptance."""

    def __init__(self, schema: str) -> None:
        """Bind validation to one migrated founder-platform schema."""
        if not valid_schema(schema):
            raise KnowledgeStoreError(KnowledgeIssue.INVALID_SCHEMA)
        self._schema = schema

    def validate(
        self, connection: Connection | SqlAlchemySession, acceptance: KnowledgeAcceptance
    ) -> None:
        """Validate each new reference using the caller's locked transaction."""
        for reference in acceptance.references:
            raw = (
                connection.execute(
                    self._sql(
                        """SELECT k.chunk_id, k.company_id, k.file_id, k.artifact_id,
                        k.source_revision, k.ordinal, k.content_sha256,
                        f.state AS file_state, f.content_sha256 AS file_sha256
                        FROM "{schema}".samurai_knowledge_chunks k
                        LEFT JOIN "{schema}".samurai_files f ON f.file_id=k.file_id
                        WHERE k.workspace_id=:workspace_id AND k.chunk_id=:chunk_id
                        AND (k.company_id IS NULL OR k.company_id=:company_id)"""
                    ),
                    {
                        "workspace_id": acceptance.workspace_id,
                        "company_id": acceptance.company_id,
                        "chunk_id": reference.chunk_id,
                    },
                )
                .mappings()
                .one_or_none()
            )
            if raw is None or not self._matches(
                _ReferenceRow.model_validate(raw), reference, acceptance.canonical_state
            ):
                raise KnowledgeStoreError(KnowledgeIssue.CONTENT_CHANGED)

    @staticmethod
    def _matches(row: _ReferenceRow, reference: KnowledgeReference, state: CompanyState) -> bool:
        shared = (
            row.chunk_id == reference.chunk_id
            and row.source_revision == reference.indexed_revision
            and row.ordinal == reference.ordinal
            and row.content_sha256 == reference.content_sha256
            and row.file_id == reference.file_id
            and row.artifact_id == reference.artifact_id
        )
        if not shared:
            return False
        if reference.file_id is not None:
            return row.file_state == "ready" and row.file_sha256 == reference.content_sha256
        artifact = next(
            (
                item
                for item in state.artifacts
                if item.artifact_id == reference.artifact_id
                and item.revision == reference.indexed_revision
            ),
            None,
        )
        return (
            artifact is not None
            and hashlib.sha256(_artifact_json(artifact).encode()).hexdigest()
            == reference.content_sha256
        )

    def _sql(self, source: str) -> TextClause:
        return text(source.format(schema=self._schema))


@final
class KnowledgeStore:
    """Index and retrieve bounded knowledge under current workspace authority."""

    def __init__(self, engine: Engine, *, schema: str, objects: ObjectStore) -> None:
        """Bind one migrated schema and immutable object adapter."""
        if not valid_schema(schema):
            raise KnowledgeStoreError(KnowledgeIssue.INVALID_SCHEMA)
        self._engine = engine
        self._schema = schema
        self._objects = objects
        self._quota = WorkspaceQuota(schema)

    def index_artifact(
        self, scope: KnowledgeScope, artifact_id: UUID
    ) -> tuple[KnowledgeChunk, ...]:
        """Index one immutable artifact read from canonical company state."""
        if scope.company_id is None:
            raise KnowledgeStoreError(KnowledgeIssue.INVALID_SCOPE)
        with self._engine.begin() as connection:
            self._admit(connection, scope, writable=True)
            state = self._company_state(connection, scope, lock=True)
            artifact = next(
                (
                    candidate
                    for candidate in state.artifacts
                    if candidate.artifact_id == artifact_id
                ),
                None,
            )
            if artifact is None or artifact.acceptance_status != "accepted":
                raise KnowledgeStoreError(KnowledgeIssue.SOURCE_NOT_FOUND)
            self._reject_secret_values(cast("JsonValue", artifact.model_dump(mode="json")))
            canonical = self._artifact_json(artifact)
            self._reject_secrets(canonical)
            return self._replace(
                connection,
                scope,
                _Source(
                    source_id=artifact_id,
                    company_id=scope.company_id,
                    trust_class=KnowledgeTrustClass.ACCEPTED_ARTIFACT,
                    revision=artifact.revision,
                    content_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
                    excerpts=self._chunk(canonical),
                ),
            )

    def current_scope(
        self, actor_id: str, workspace_id: UUID, company_id: UUID | None
    ) -> KnowledgeScope:
        """Resolve the current server-owned membership epoch for one request."""
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    self._sql(
                        """SELECT role, authorization_epoch
                        FROM "{schema}".samurai_workspace_memberships
                        WHERE workspace_id=:workspace_id AND user_id=:actor_id AND active"""
                    ),
                    {"workspace_id": workspace_id, "actor_id": actor_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise KnowledgeStoreError(KnowledgeIssue.PERMISSION_DENIED)
            membership = _MembershipRow.model_validate(row)
            scope = KnowledgeScope(
                actor_id=actor_id,
                workspace_id=workspace_id,
                authorization_epoch=membership.authorization_epoch,
                company_id=company_id,
            )
            self._admit(connection, scope, writable=False)
            return scope

    def index_file(self, scope: KnowledgeScope, file_id: UUID) -> tuple[KnowledgeChunk, ...]:
        """Index one ready UTF-8 file after an atomic state and hash recheck."""
        with self._engine.begin() as connection:
            self._admit(connection, scope, writable=True)
            row = self._file(connection, scope, file_id, lock=False)
            if row is None:
                raise KnowledgeStoreError(KnowledgeIssue.SOURCE_NOT_FOUND)
            if not self._eligible_file(row):
                self._purge(connection, scope.workspace_id, file_id=file_id)
                issue = KnowledgeIssue.SOURCE_INELIGIBLE
            else:
                issue = None
        if issue is not None:
            raise KnowledgeStoreError(issue)
        decoded = self._read_file_content(row)
        with self._engine.begin() as connection:
            self._admit(connection, scope, writable=True)
            current = self._file(connection, scope, file_id, lock=True)
            if current is None:
                raise KnowledgeStoreError(KnowledgeIssue.SOURCE_NOT_FOUND)
            if not self._eligible_file(current):
                self._purge(connection, scope.workspace_id, file_id=file_id)
                issue = KnowledgeIssue.SOURCE_INELIGIBLE
                result = ()
            elif (
                current.content_sha256 != row.content_sha256
                or current.storage_key != row.storage_key
            ):
                issue = KnowledgeIssue.CONTENT_CHANGED
                result = ()
            else:
                issue = None
                result = self._replace(
                    connection,
                    scope,
                    _Source(
                        source_id=file_id,
                        company_id=current.company_id,
                        trust_class=KnowledgeTrustClass.UPLOADED_FILE,
                        revision=current.updated_at,
                        content_sha256=current.content_sha256,
                        excerpts=self._chunk(decoded),
                    ),
                )
        if issue is not None:
            raise KnowledgeStoreError(issue)
        return result

    def retrieve(self, scope: KnowledgeScope, query: str) -> tuple[KnowledgeResult, ...]:
        """Return at most five stable lexical matches in the authorized scope."""
        normalized_query = self._normalize(query)
        if not normalized_query or len(query) > MAX_QUERY_CHARACTERS:
            raise KnowledgeStoreError(KnowledgeIssue.INVALID_QUERY)
        query_tokens = self._tokens(normalized_query)
        with self._engine.begin() as connection:
            self._admit(connection, scope, writable=False)
            self._purge_inaccessible_files(connection, scope.workspace_id)
            rows = connection.execute(
                self._sql(
                    """SELECT k.chunk_id, k.workspace_id, k.company_id, k.file_id,
                    k.artifact_id, k.source_revision, k.ordinal, k.content, k.content_sha256,
                    f.content_sha256 AS file_sha256, c.canonical_state
                    FROM "{schema}".samurai_knowledge_chunks k
                    LEFT JOIN "{schema}".samurai_files f ON f.file_id = k.file_id
                    LEFT JOIN "{schema}".samurai_companies c ON c.company_id = k.company_id
                    WHERE k.workspace_id = :workspace_id AND
                    ((CAST(:company_id AS uuid) IS NULL AND k.company_id IS NULL) OR
                    (CAST(:company_id AS uuid) IS NOT NULL AND
                    (k.company_id IS NULL OR k.company_id = CAST(:company_id AS uuid))))
                    ORDER BY k.content_sha256, k.ordinal, k.chunk_id"""
                ),
                {"workspace_id": scope.workspace_id, "company_id": scope.company_id},
            ).mappings()
            candidates = tuple(_CandidateRow.model_validate(row) for row in rows)
        ranked = [
            result
            for candidate in candidates
            if (result := self._result(candidate, query_tokens)) is not None
        ]
        ranked.sort(
            key=lambda item: (-item.score, item.content_sha256, item.ordinal, item.chunk_id)
        )
        return tuple(ranked[:MAX_RESULTS])

    def _admit(self, connection: Connection, scope: KnowledgeScope, *, writable: bool) -> None:
        self._quota.lock(connection, scope.workspace_id)
        row = (
            connection.execute(
                self._sql(
                    """SELECT role, authorization_epoch
                    FROM "{schema}".samurai_workspace_memberships
                    WHERE workspace_id=:workspace_id AND user_id=:actor_id AND active"""
                ),
                {"workspace_id": scope.workspace_id, "actor_id": scope.actor_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise KnowledgeStoreError(KnowledgeIssue.PERMISSION_DENIED)
        membership = _MembershipRow.model_validate(row)
        if membership.authorization_epoch != scope.authorization_epoch or (
            writable and membership.role is WorkspaceRole.VIEWER
        ):
            raise KnowledgeStoreError(KnowledgeIssue.PERMISSION_DENIED)
        if scope.company_id is not None:
            _ = self._company_state(connection, scope, lock=False)

    def _company_state(
        self, connection: Connection, scope: KnowledgeScope, *, lock: bool
    ) -> CompanyState:
        query = """SELECT canonical_state FROM "{schema}".samurai_companies
        WHERE workspace_id=:workspace_id AND company_id=:company_id"""
        if lock:
            query += " FOR UPDATE"
        row = connection.execute(
            self._sql(query),
            {"workspace_id": scope.workspace_id, "company_id": scope.company_id},
        ).scalar_one_or_none()
        if row is None:
            raise KnowledgeStoreError(KnowledgeIssue.SOURCE_NOT_FOUND)
        return CompanyState.model_validate(row)

    def _file(
        self, connection: Connection, scope: KnowledgeScope, file_id: UUID, *, lock: bool
    ) -> _FileRow | None:
        query = """SELECT file_id, company_id, state, media_type, byte_size, content_sha256,
        storage_key, updated_at FROM "{schema}".samurai_files
        WHERE workspace_id=:workspace_id AND file_id=:file_id"""
        if lock:
            query += " FOR UPDATE"
        row = (
            connection.execute(
                self._sql(query), {"workspace_id": scope.workspace_id, "file_id": file_id}
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        parsed = _FileRow.model_validate(row)
        if scope.company_id is not None and parsed.company_id not in {None, scope.company_id}:
            raise KnowledgeStoreError(KnowledgeIssue.SOURCE_NOT_FOUND)
        return parsed

    def _replace(
        self,
        connection: Connection,
        scope: KnowledgeScope,
        source: _Source,
    ) -> tuple[KnowledgeChunk, ...]:
        column = (
            "file_id" if source.trust_class is KnowledgeTrustClass.UPLOADED_FILE else "artifact_id"
        )
        existing = tuple(
            connection.execute(
                self._sql(
                    f"""SELECT content_sha256, source_revision, ordinal, content
                    FROM "{{schema}}".samurai_knowledge_chunks
                    WHERE workspace_id=:workspace_id AND {column}=:source_id
                    ORDER BY ordinal FOR UPDATE"""  # noqa: S608 - enum-selected column.
                ),
                {"workspace_id": scope.workspace_id, "source_id": source.source_id},
            ).mappings()
        )
        expected = tuple(
            (source.content_sha256, source.revision, ordinal, excerpt)
            for ordinal, excerpt in enumerate(source.excerpts)
        )
        actual = tuple(
            (row["content_sha256"], row["source_revision"], row["ordinal"], row["content"])
            for row in existing
        )
        chunks = self._models(scope, source)
        if actual == expected:
            return chunks
        delta = len(chunks) - len(existing)
        try:
            if delta > 0:
                self._quota.reserve(
                    connection, scope.workspace_id, QuotaResource.KNOWLEDGE_CHUNK, amount=delta
                )
            elif delta < 0:
                self._quota.release(
                    connection, scope.workspace_id, QuotaResource.KNOWLEDGE_CHUNK, amount=-delta
                )
        except WorkspaceQuotaExceededError as error:
            raise KnowledgeStoreError(KnowledgeIssue.WORKSPACE_QUOTA) from error
        delete_query = " ".join(
            (
                'DELETE FROM "{schema}".samurai_knowledge_chunks',
                f"WHERE workspace_id=:workspace_id AND {column}=:source_id",
            )
        )
        _ = connection.execute(
            self._sql(delete_query),
            {"workspace_id": scope.workspace_id, "source_id": source.source_id},
        )
        for chunk in chunks:
            _ = connection.execute(
                self._sql(
                    """INSERT INTO "{schema}".samurai_knowledge_chunks
                    (chunk_id,workspace_id,company_id,file_id,artifact_id,source_revision,
                    ordinal,content,content_sha256,created_at) VALUES
                    (:chunk_id,:workspace_id,:company_id,:file_id,:artifact_id,:source_revision,
                    :ordinal,:content,:content_sha256,:created_at)"""
                ),
                {
                    "chunk_id": chunk.chunk_id,
                    "workspace_id": chunk.workspace_id,
                    "company_id": chunk.company_id,
                    "file_id": chunk.file_id,
                    "artifact_id": chunk.artifact_id,
                    "source_revision": chunk.indexed_revision,
                    "ordinal": chunk.ordinal,
                    "content": chunk.excerpt,
                    "content_sha256": chunk.content_sha256,
                    "created_at": int(time.time()),
                },
            )
        return chunks

    def _models(
        self,
        scope: KnowledgeScope,
        source: _Source,
    ) -> tuple[KnowledgeChunk, ...]:
        is_file = source.trust_class is KnowledgeTrustClass.UPLOADED_FILE
        return tuple(
            KnowledgeChunk(
                chunk_id=uuid5(
                    NAMESPACE_URL,
                    ":".join(
                        (
                            "samurai-knowledge",
                            str(scope.workspace_id),
                            source.trust_class,
                            str(source.source_id),
                            source.content_sha256,
                            str(ordinal),
                        )
                    ),
                ),
                workspace_id=scope.workspace_id,
                company_id=source.company_id,
                file_id=source.source_id if is_file else None,
                artifact_id=None if is_file else source.source_id,
                indexed_revision=source.revision,
                ordinal=ordinal,
                excerpt=excerpt,
                content_sha256=source.content_sha256,
                trust_class=source.trust_class,
            )
            for ordinal, excerpt in enumerate(source.excerpts)
        )

    def _purge(self, connection: Connection, workspace_id: UUID, *, file_id: UUID) -> None:
        removed = connection.execute(
            self._sql(
                """DELETE FROM "{schema}".samurai_knowledge_chunks
                WHERE workspace_id=:workspace_id AND file_id=:file_id RETURNING chunk_id"""
            ),
            {"workspace_id": workspace_id, "file_id": file_id},
        ).rowcount
        if removed:
            self._quota.release(
                connection, workspace_id, QuotaResource.KNOWLEDGE_CHUNK, amount=removed
            )

    def _purge_inaccessible_files(self, connection: Connection, workspace_id: UUID) -> None:
        removed = connection.execute(
            self._sql(
                """DELETE FROM "{schema}".samurai_knowledge_chunks k
                WHERE k.workspace_id=:workspace_id AND k.file_id IS NOT NULL AND NOT EXISTS
                (SELECT 1 FROM "{schema}".samurai_files f WHERE f.file_id=k.file_id
                AND f.workspace_id=k.workspace_id AND f.state='ready'
                AND f.media_type IN ('text/plain','text/markdown','text/csv','application/json')
                AND f.company_id IS NOT DISTINCT FROM k.company_id
                AND f.content_sha256=k.content_sha256) RETURNING k.chunk_id"""
            ),
            {"workspace_id": workspace_id},
        ).rowcount
        if removed:
            self._quota.release(
                connection, workspace_id, QuotaResource.KNOWLEDGE_CHUNK, amount=removed
            )

    def _result(self, row: _CandidateRow, query_tokens: frozenset[str]) -> KnowledgeResult | None:
        if row.file_id is not None:
            if (
                row.artifact_id is not None
                or row.file_sha256 is None
                or row.file_sha256 != row.content_sha256
            ):
                return None
            trust_class = KnowledgeTrustClass.UPLOADED_FILE
            source_hash = row.file_sha256
        else:
            if row.artifact_id is None or row.canonical_state is None:
                return None
            state = CompanyState.model_validate(row.canonical_state)
            artifact = next(
                (item for item in state.artifacts if item.artifact_id == row.artifact_id), None
            )
            if artifact is None or artifact.revision != row.source_revision:
                return None
            trust_class = KnowledgeTrustClass.ACCEPTED_ARTIFACT
            source_hash = hashlib.sha256(self._artifact_json(artifact).encode()).hexdigest()
            if source_hash != row.content_sha256:
                return None
        score = len(query_tokens & self._tokens(row.content))
        if score == 0:
            return None
        return KnowledgeResult(
            chunk_id=row.chunk_id,
            workspace_id=row.workspace_id,
            company_id=row.company_id,
            file_id=row.file_id,
            artifact_id=row.artifact_id,
            indexed_revision=row.source_revision,
            ordinal=row.ordinal,
            excerpt=row.content,
            content_sha256=source_hash,
            trust_class=trust_class,
            score=score,
        )

    @staticmethod
    def _eligible_file(row: _FileRow) -> bool:
        return row.state == "ready" and row.media_type in TEXT_MEDIA_TYPES

    @staticmethod
    def _artifact_json(artifact: ArtifactEnvelope) -> str:
        return _artifact_json(artifact)

    @staticmethod
    def _normalize(value: str) -> str:
        return WHITESPACE_PATTERN.sub(" ", unicodedata.normalize("NFKC", value)).strip()

    @classmethod
    def _chunk(cls, value: str) -> tuple[str, ...]:
        normalized = cls._normalize(value)[: CHUNK_CHARACTERS * CHUNKS_PER_SOURCE]
        return tuple(
            normalized[offset : offset + CHUNK_CHARACTERS]
            for offset in range(0, len(normalized), CHUNK_CHARACTERS)
        )

    @staticmethod
    def _tokens(value: str) -> frozenset[str]:
        return frozenset(TOKEN_PATTERN.findall(value.casefold()))

    @staticmethod
    def _reject_secrets(value: str) -> None:
        if SECRET_PATTERN.search(value) is not None:
            raise KnowledgeStoreError(KnowledgeIssue.SENSITIVE_CONTENT)

    @classmethod
    def _reject_secret_values(cls, value: JsonValue) -> None:
        if isinstance(value, str):
            cls._reject_secrets(value)
        elif isinstance(value, list):
            for item in value:
                cls._reject_secret_values(item)
        elif isinstance(value, dict):
            for item in value.values():
                cls._reject_secret_values(item)

    def _read_file_content(self, row: _FileRow) -> str:
        try:
            content = self._objects.read(row.storage_key)
        except (FileStoreError, KeyError, OSError) as error:
            raise KnowledgeStoreError(KnowledgeIssue.CONTENT_CHANGED) from error
        if (
            len(content) != row.byte_size
            or hashlib.sha256(content).hexdigest() != row.content_sha256
        ):
            raise KnowledgeStoreError(KnowledgeIssue.CONTENT_CHANGED)
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise KnowledgeStoreError(KnowledgeIssue.CONTENT_CHANGED) from error
        self._reject_secrets(decoded)
        return decoded

    def _sql(self, source: str) -> TextClause:
        return text(source.format(schema=self._schema))
