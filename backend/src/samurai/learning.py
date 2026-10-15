"""Explicit learning transaction boundary kept intact. # noqa: SIZE_OK."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, ClassVar, Final, Literal, cast, final
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from samurai.company_store_contracts import WorkspaceRole
from samurai.company_store_queries import valid_schema
from samurai.quota import WorkspaceQuota

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine
    from sqlalchemy.sql.elements import TextClause

MAX_LEARNING_RECORDS: Final = 20
NANOSECONDS_PER_MILLISECOND: Final = 1_000_000
JAVASCRIPT_MAX_SAFE_INTEGER: Final = 9_007_199_254_740_991
UNTRUSTED_CONTEXT: Final = "untrusted_preference_context"


@unique
class LearningKind(StrEnum):
    """Explicit learning kinds accepted at the API boundary."""

    PREFERENCE = "preference"
    CORRECTION = "correction"


@unique
class LearningIssue(StrEnum):
    """Stable learning failures safe to expose over HTTP."""

    INVALID_SCHEMA = "invalid learning schema"
    COMPANY_NOT_FOUND = "company not found in workspace"
    STALE_REVISION = "source company revision is stale"
    SHARED_ROLE_REQUIRED = "shared corrections require workspace owner or editor role"
    SHARED_CORRECTION_REQUIRED = "only corrections may be shared"
    RECORD_NOT_FOUND = "learning record not found"
    RECORD_SUPERSEDED = "learning record is already superseded"
    SHARING_MISMATCH = "supersession must preserve explicit sharing scope"
    AUDIT_MISMATCH = "learning record audit hash does not match"


class LearningStoreError(Exception):
    """Reject an unsafe learning operation without leaking another actor's record."""

    issue: LearningIssue

    def __init__(self, issue: LearningIssue) -> None:
        """Preserve a stable issue while retaining normal exception traceback behavior."""
        super().__init__(issue.value)
        self.issue = issue


class LearningRecord(BaseModel):
    """One immutable founder statement and its supersession status."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    learning_id: UUID
    workspace_id: UUID
    user_id: str
    company_id: UUID
    kind: LearningKind
    source_revision: int
    founder_text: str
    created_by: str
    audit_sha256: str
    shared: bool
    superseded_by: UUID | None
    active: bool
    created_at: int = Field(ge=0, le=JAVASCRIPT_MAX_SAFE_INTEGER)
    evidence_status: Literal["untrusted_preference_context"] = UNTRUSTED_CONTEXT


class LearningContext(BaseModel):
    """Bounded records explicitly marked as untrusted preference context."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    context_boundary: Literal["untrusted_preference_context"] = UNTRUSTED_CONTEXT
    records: tuple[LearningRecord, ...]


class _LearningRow(BaseModel):
    learning_id: UUID
    workspace_id: UUID
    user_id: str
    company_id: UUID
    kind: LearningKind
    source_revision: int
    founder_text: str
    created_by: str
    audit_sha256: str
    shared: bool
    superseded_by: UUID | None
    active: bool
    created_at: int


@dataclass(frozen=True, slots=True)
class LearningCreate:
    """Server-owned identity plus validated explicit founder input."""

    actor_id: str
    workspace_id: UUID
    company_id: UUID
    kind: LearningKind
    source_revision: int
    founder_text: str
    shared: bool


@dataclass(frozen=True, slots=True)
class LearningSupersede:
    """Server-owned identity plus an explicit replacement statement."""

    actor_id: str
    workspace_id: UUID
    company_id: UUID
    learning_id: UUID
    source_revision: int
    founder_text: str
    shared: bool | None


@final
class LearningStore:
    """Persist and retrieve learning only under current workspace authority."""

    def __init__(self, engine: Engine, *, schema: str) -> None:
        """Bind learning persistence to one validated application schema."""
        if not valid_schema(schema):
            raise LearningStoreError(LearningIssue.INVALID_SCHEMA)
        self._engine = engine
        self._schema = schema
        self._quota = WorkspaceQuota(schema)

    def create(self, request: LearningCreate) -> LearningRecord:
        """Persist one explicit statement under current actor authority."""
        with self._engine.begin() as connection:
            role = self._admit(connection, request)
            self._require_sharing(request.kind, shared=request.shared, role=role)
            return self._insert(connection, request)

    def supersede(self, request: LearningSupersede) -> LearningRecord:
        """Replace one active visible record without rewriting its history."""
        with self._engine.begin() as connection:
            role = self._admit_scope(
                connection,
                request.actor_id,
                request.workspace_id,
                request.company_id,
                request.source_revision,
            )
            raw = (
                connection.execute(
                    self._sql(
                        """SELECT learning_id,workspace_id,user_id,company_id,kind,
                        source_revision,founder_text,created_by,audit_sha256,shared,
                        superseded_by,active,created_at
                        FROM "{schema}".samurai_learning_records
                        WHERE learning_id=:learning_id AND workspace_id=:workspace_id
                        AND company_id=:company_id FOR UPDATE"""
                    ),
                    {
                        "learning_id": request.learning_id,
                        "workspace_id": request.workspace_id,
                        "company_id": request.company_id,
                    },
                )
                .mappings()
                .one_or_none()
            )
            if raw is None:
                raise LearningStoreError(LearningIssue.RECORD_NOT_FOUND)
            prior = self._record(_LearningRow.model_validate(raw))
            if not prior.shared and prior.user_id != request.actor_id:
                raise LearningStoreError(LearningIssue.RECORD_NOT_FOUND)
            if not prior.active:
                raise LearningStoreError(LearningIssue.RECORD_SUPERSEDED)
            replacement_shared = False if request.shared is None else request.shared
            if replacement_shared != prior.shared or (prior.shared and request.shared is not True):
                raise LearningStoreError(LearningIssue.SHARING_MISMATCH)
            self._require_sharing(prior.kind, shared=replacement_shared, role=role)
            replacement = self._insert(
                connection,
                LearningCreate(
                    actor_id=request.actor_id,
                    workspace_id=request.workspace_id,
                    company_id=request.company_id,
                    kind=prior.kind,
                    source_revision=request.source_revision,
                    founder_text=request.founder_text,
                    shared=replacement_shared,
                ),
            )
            _ = connection.execute(
                self._sql(
                    """UPDATE "{schema}".samurai_learning_records
                    SET active=false,superseded_by=:replacement_id
                    WHERE learning_id=:learning_id"""
                ),
                {
                    "replacement_id": replacement.learning_id,
                    "learning_id": request.learning_id,
                },
            )
            return replacement

    def list(
        self,
        actor_id: str,
        workspace_id: UUID,
        company_id: UUID,
        *,
        include_history: bool = False,
    ) -> LearningContext:
        """Return at most twenty actor-visible records under an untrusted boundary."""
        with self._engine.begin() as connection:
            _ = self._admit_scope(connection, actor_id, workspace_id, company_id)
            rows = connection.execute(
                self._sql(
                    """SELECT learning_id,workspace_id,user_id,company_id,kind,
                    source_revision,founder_text,created_by,audit_sha256,shared,
                    superseded_by,active,created_at
                    FROM "{schema}".samurai_learning_records
                    WHERE workspace_id=:workspace_id AND company_id=:company_id
                    AND (user_id=:actor_id OR shared)
                    AND (:include_history OR active)
                    ORDER BY created_at DESC,learning_id DESC LIMIT :limit"""
                ),
                {
                    "workspace_id": workspace_id,
                    "company_id": company_id,
                    "actor_id": actor_id,
                    "include_history": include_history,
                    "limit": MAX_LEARNING_RECORDS,
                },
            ).mappings()
            return LearningContext(
                records=tuple(self._record(_LearningRow.model_validate(row)) for row in rows)
            )

    def _admit(self, connection: Connection, request: LearningCreate) -> WorkspaceRole:
        return self._admit_scope(
            connection,
            request.actor_id,
            request.workspace_id,
            request.company_id,
            request.source_revision,
        )

    def _admit_scope(
        self,
        connection: Connection,
        actor_id: str,
        workspace_id: UUID,
        company_id: UUID,
        source_revision: int | None = None,
    ) -> WorkspaceRole:
        self._quota.lock(connection, workspace_id)
        role = connection.execute(
            self._sql(
                """SELECT role FROM "{schema}".samurai_workspace_memberships
                WHERE workspace_id=:workspace_id AND user_id=:actor_id AND active FOR SHARE"""
            ),
            {"workspace_id": workspace_id, "actor_id": actor_id},
        ).scalar_one_or_none()
        if role is None:
            raise HTTPException(status_code=403, detail="active workspace membership required")
        self._require_company(
            connection,
            workspace_id,
            company_id,
            source_revision,
        )
        return WorkspaceRole(cast("str", role))

    def _require_company(
        self,
        connection: Connection,
        workspace_id: UUID,
        company_id: UUID,
        source_revision: int | None = None,
    ) -> None:
        revision = cast(
            "int | None",
            connection.execute(
                self._sql(
                    """SELECT current_revision FROM "{schema}".samurai_companies
                    WHERE workspace_id=:workspace_id AND company_id=:company_id FOR SHARE"""
                ),
                {"workspace_id": workspace_id, "company_id": company_id},
            ).scalar_one_or_none(),
        )
        if revision is None:
            raise LearningStoreError(LearningIssue.COMPANY_NOT_FOUND)
        if source_revision is not None and revision != source_revision:
            raise LearningStoreError(LearningIssue.STALE_REVISION)

    @staticmethod
    def _require_sharing(kind: LearningKind, *, shared: bool, role: WorkspaceRole) -> None:
        if shared and kind is not LearningKind.CORRECTION:
            raise LearningStoreError(LearningIssue.SHARED_CORRECTION_REQUIRED)
        if shared and role not in {WorkspaceRole.OWNER, WorkspaceRole.EDITOR}:
            raise LearningStoreError(LearningIssue.SHARED_ROLE_REQUIRED)

    def _insert(self, connection: Connection, request: LearningCreate) -> LearningRecord:
        learning_id = uuid4()
        created_at = time.time_ns()
        parameters = {
            "learning_id": learning_id,
            "workspace_id": request.workspace_id,
            "user_id": request.actor_id,
            "company_id": request.company_id,
            "kind": request.kind.value,
            "source_revision": request.source_revision,
            "founder_text": request.founder_text,
            "created_by": request.actor_id,
            "shared": request.shared,
            "created_at": created_at,
        }
        parameters["audit_sha256"] = self._audit(parameters)
        _ = connection.execute(
            self._sql(
                """INSERT INTO "{schema}".samurai_learning_records
                (learning_id,workspace_id,user_id,company_id,kind,source_revision,
                founder_text,created_by,audit_sha256,shared,created_at)
                VALUES (:learning_id,:workspace_id,:user_id,:company_id,:kind,
                :source_revision,:founder_text,:created_by,:audit_sha256,:shared,:created_at)"""
            ),
            parameters,
        )
        return self._record(
            _LearningRow.model_validate({**parameters, "superseded_by": None, "active": True})
        )

    def _record(self, row: _LearningRow) -> LearningRecord:
        values = row.model_dump(mode="python")
        audit_fields = row.model_dump(
            mode="python", exclude={"active", "superseded_by", "audit_sha256"}
        )
        if self._audit(audit_fields) != row.audit_sha256:
            raise LearningStoreError(LearningIssue.AUDIT_MISMATCH)
        return LearningRecord.model_validate(
            {**values, "created_at": row.created_at // NANOSECONDS_PER_MILLISECOND}
        )

    @staticmethod
    def _audit(fields: dict[str, str | int | bool | UUID]) -> str:
        canonical = json.dumps(fields, default=str, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _sql(self, source: str) -> TextClause:
        return text(source.format(schema=self._schema))
