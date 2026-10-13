"""Atomic workspace quota counters for durable resource transactions."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, Final, override

from pydantic import BaseModel
from sqlalchemy import text

from samurai.company_store_queries import valid_schema
from samurai.config import WORKSPACE_QUOTA_LIMITS

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.engine import Connection
    from sqlalchemy.orm import Session as SqlAlchemySession
    from sqlalchemy.sql.elements import TextClause


@unique
class QuotaResource(StrEnum):
    """Single-counter resources governed by one workspace row."""

    COMPANY = "company"
    MEMBER = "member"
    FILE = "file"
    ACTIVE_JOB = "active_job"
    SCHEDULE = "schedule"
    KNOWLEDGE_CHUNK = "knowledge_chunk"


@dataclass(frozen=True, slots=True)
class _QuotaColumns:
    count: str
    limit: str


RESOURCE_COLUMNS: Final = {
    QuotaResource.COMPANY: _QuotaColumns("company_count", "company_limit"),
    QuotaResource.MEMBER: _QuotaColumns("member_count", "member_limit"),
    QuotaResource.ACTIVE_JOB: _QuotaColumns("active_job_count", "active_job_limit"),
    QuotaResource.SCHEDULE: _QuotaColumns("schedule_count", "schedule_limit"),
    QuotaResource.KNOWLEDGE_CHUNK: _QuotaColumns("knowledge_chunk_count", "knowledge_chunk_limit"),
}


class _QuotaRow(BaseModel):
    file_limit: int
    stored_bytes_limit: int
    per_file_bytes_limit: int
    file_count: int
    stored_bytes: int


@dataclass(slots=True)
class WorkspaceQuotaExceededError(Exception):
    """Reject a resource reservation beyond a fixed workspace limit."""

    resource: QuotaResource

    @override
    def __str__(self) -> str:
        return "workspace quota exceeded"


@unique
class QuotaStateIssue(StrEnum):
    """Stable internal quota consistency failures."""

    INVALID_SCHEMA = "invalid workspace quota schema"
    INVALID_RESERVATION = "quota reservation amount must be positive"
    INVALID_RELEASE = "quota release amount must be positive"
    COUNTER_UNDERFLOW = "workspace quota counter underflow"
    INVALID_FILE_SIZE = "file byte size cannot be negative"
    FILE_COUNTER_UNDERFLOW = "workspace file quota counter underflow"
    MISSING_ROW = "workspace quota row is missing"


@dataclass(slots=True)
class WorkspaceQuotaStateError(Exception):
    """Report missing or inconsistent durable quota state."""

    issue: QuotaStateIssue

    @override
    def __str__(self) -> str:
        return self.issue.value


class WorkspaceQuota:
    """Lock and mutate one workspace counter inside a caller-owned transaction."""

    def __init__(self, schema: str) -> None:
        """Bind quota operations to one validated app schema."""
        if not valid_schema(schema):
            raise WorkspaceQuotaStateError(QuotaStateIssue.INVALID_SCHEMA)
        self._schema: str = schema

    def create(self, connection: Connection, workspace_id: UUID, timestamp: int) -> None:
        """Create the quota authority in the workspace creation transaction."""
        _ = connection.execute(
            self._sql(
                """INSERT INTO "{schema}".samurai_workspace_quotas
                (workspace_id, company_limit, member_limit, file_limit,
                stored_bytes_limit, per_file_bytes_limit, active_job_limit,
                schedule_limit, knowledge_chunk_limit, member_count, updated_at)
                VALUES (:workspace_id, :companies, :members, :files, :stored_bytes,
                :per_file_bytes, :active_jobs, :schedules, :knowledge_chunks, 1, :timestamp)"""
            ),
            {
                "workspace_id": workspace_id,
                "companies": WORKSPACE_QUOTA_LIMITS.companies,
                "members": WORKSPACE_QUOTA_LIMITS.members,
                "files": WORKSPACE_QUOTA_LIMITS.files,
                "stored_bytes": WORKSPACE_QUOTA_LIMITS.stored_bytes,
                "per_file_bytes": WORKSPACE_QUOTA_LIMITS.per_file_bytes,
                "active_jobs": WORKSPACE_QUOTA_LIMITS.active_jobs,
                "schedules": WORKSPACE_QUOTA_LIMITS.schedules,
                "knowledge_chunks": WORKSPACE_QUOTA_LIMITS.knowledge_chunks,
                "timestamp": timestamp,
            },
        )

    def lock(self, executor: Connection | SqlAlchemySession, workspace_id: UUID) -> None:
        """Serialize all quota-changing transactions for one workspace."""
        _ = executor.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:quota_key, 0))"),
            {"quota_key": f"samurai-workspace-quota:{workspace_id}"},
        )

    def reserve(
        self,
        executor: Connection | SqlAlchemySession,
        workspace_id: UUID,
        resource: QuotaResource,
        *,
        amount: int = 1,
    ) -> None:
        """Reserve a positive amount after locking the workspace authority."""
        if amount <= 0:
            raise WorkspaceQuotaStateError(QuotaStateIssue.INVALID_RESERVATION)
        self.lock(executor, workspace_id)
        columns = RESOURCE_COLUMNS[resource]
        updated = executor.execute(
            self._sql(
                f"""UPDATE "{{schema}}".samurai_workspace_quotas
                SET {columns.count} = {columns.count} + :amount, updated_at = :timestamp
                WHERE workspace_id = :workspace_id
                AND {columns.count} + :amount <= {columns.limit}
                RETURNING workspace_id"""  # noqa: S608 - enum-owned column identifiers.
            ),
            {"workspace_id": workspace_id, "amount": amount, "timestamp": int(time.time())},
        ).scalar_one_or_none()
        if updated is None:
            raise WorkspaceQuotaExceededError(resource)

    def release(
        self,
        executor: Connection | SqlAlchemySession,
        workspace_id: UUID,
        resource: QuotaResource,
        *,
        amount: int = 1,
    ) -> None:
        """Release an owned reservation without allowing an underflow."""
        if amount <= 0:
            raise WorkspaceQuotaStateError(QuotaStateIssue.INVALID_RELEASE)
        self.lock(executor, workspace_id)
        columns = RESOURCE_COLUMNS[resource]
        updated = executor.execute(
            self._sql(
                f"""UPDATE "{{schema}}".samurai_workspace_quotas
                SET {columns.count} = {columns.count} - :amount, updated_at = :timestamp
                WHERE workspace_id = :workspace_id AND {columns.count} >= :amount
                RETURNING workspace_id"""  # noqa: S608 - enum-owned column identifiers.
            ),
            {"workspace_id": workspace_id, "amount": amount, "timestamp": int(time.time())},
        ).scalar_one_or_none()
        if updated is None:
            raise WorkspaceQuotaStateError(QuotaStateIssue.COUNTER_UNDERFLOW)

    def reserve_file(
        self,
        executor: Connection | SqlAlchemySession,
        workspace_id: UUID,
        byte_size: int,
    ) -> None:
        """Reserve one file and its committed bytes in the metadata transaction."""
        if byte_size < 0:
            raise WorkspaceQuotaStateError(QuotaStateIssue.INVALID_FILE_SIZE)
        self.lock(executor, workspace_id)
        row = self._file_row(executor, workspace_id)
        if (
            byte_size > row.per_file_bytes_limit
            or row.file_count >= row.file_limit
            or row.stored_bytes + byte_size > row.stored_bytes_limit
        ):
            raise WorkspaceQuotaExceededError(QuotaResource.FILE)
        _ = executor.execute(
            self._sql(
                """UPDATE "{schema}".samurai_workspace_quotas
                SET file_count = file_count + 1, stored_bytes = stored_bytes + :byte_size,
                updated_at = :timestamp WHERE workspace_id = :workspace_id"""
            ),
            {
                "workspace_id": workspace_id,
                "byte_size": byte_size,
                "timestamp": int(time.time()),
            },
        )

    def release_file(
        self,
        executor: Connection | SqlAlchemySession,
        workspace_id: UUID,
        byte_size: int,
    ) -> None:
        """Release one file and exactly its committed byte reservation."""
        if byte_size < 0:
            raise WorkspaceQuotaStateError(QuotaStateIssue.INVALID_FILE_SIZE)
        self.lock(executor, workspace_id)
        updated = executor.execute(
            self._sql(
                """UPDATE "{schema}".samurai_workspace_quotas
                SET file_count = file_count - 1, stored_bytes = stored_bytes - :byte_size,
                updated_at = :timestamp WHERE workspace_id = :workspace_id
                AND file_count >= 1 AND stored_bytes >= :byte_size RETURNING workspace_id"""
            ),
            {
                "workspace_id": workspace_id,
                "byte_size": byte_size,
                "timestamp": int(time.time()),
            },
        ).scalar_one_or_none()
        if updated is None:
            raise WorkspaceQuotaStateError(QuotaStateIssue.FILE_COUNTER_UNDERFLOW)

    def _file_row(self, executor: Connection | SqlAlchemySession, workspace_id: UUID) -> _QuotaRow:
        row = (
            executor.execute(
                self._sql(
                    """SELECT file_limit, stored_bytes_limit, per_file_bytes_limit,
                    file_count, stored_bytes FROM "{schema}".samurai_workspace_quotas
                    WHERE workspace_id = :workspace_id FOR UPDATE"""
                ),
                {"workspace_id": workspace_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise WorkspaceQuotaStateError(QuotaStateIssue.MISSING_ROW)
        return _QuotaRow.model_validate(row)

    def _sql(self, source: str) -> TextClause:
        return text(source.format(schema=self._schema))
