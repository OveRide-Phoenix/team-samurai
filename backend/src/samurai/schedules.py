"""Persist and execute bounded provider-free workspace schedules."""

# allow: SIZE_OK - task-owned atomic admission, lease, dispatch, and receipt state machine.

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum, unique
from typing import TYPE_CHECKING, ClassVar, Literal, final, override
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter
from sqlalchemy import text

from samurai.company_store_contracts import WorkspaceRole
from samurai.company_store_queries import valid_schema
from samurai.contracts import CompanyState  # noqa: TC001 - Pydantic resolves the state at runtime.
from samurai.quota import QuotaResource, WorkspaceQuota

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy import Engine
    from sqlalchemy.engine import Connection
    from sqlalchemy.sql.elements import TextClause

LEASE_SECONDS = 300
INT_ADAPTER = TypeAdapter(int)
ROLE_ADAPTER = TypeAdapter(WorkspaceRole)
UUID_ADAPTER = TypeAdapter(UUID)


@unique
class ScheduleCadence(StrEnum):
    """Supported bounded recurrence classes."""

    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"


class ScheduleRecord(BaseModel):
    """Persisted schedule state."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)

    schedule_id: UUID
    workspace_id: UUID
    company_id: UUID
    created_by: str
    creator_authorization_epoch: int
    cadence: ScheduleCadence
    timezone: str
    action_kind: str
    payload: dict[str, JsonValue]
    pinned_revision: int
    enabled: bool
    next_run_at: int | None
    last_run_at: int | None
    created_at: int
    updated_at: int


class ScheduleRun(BaseModel):
    """Terminal run receipt."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)

    schedule_id: UUID
    scheduled_for: int
    status: Literal["completed", "failed", "skipped"]
    result: dict[str, JsonValue] | None = None
    error_code: str | None = None


@unique
class ScheduleIssue(StrEnum):
    """Stable schedule boundary failures."""

    INVALID_TIMEZONE = "unknown IANA timezone"
    NO_RECURRENCE = "one-shot schedules do not recur"
    INVALID_SCHEMA = "invalid schedule schema"
    OFFSET_REQUIRED = "schedule time must include an offset"
    EDITOR_REQUIRED = "workspace editor role required"
    COMPANY_NOT_FOUND = "company not found in workspace"
    REVISION_CHANGED = "company revision changed"
    MEMBER_REQUIRED = "active workspace membership required"


@dataclass(frozen=True, slots=True)
class ScheduleError(ValueError):
    """Typed schedule boundary error."""

    issue: ScheduleIssue

    @override
    def __str__(self) -> str:
        return self.issue.value


class _DispatchState(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    enabled: bool
    active: bool | None
    authorization_epoch: int | None
    current_revision: int
    schedule_count: int
    schedule_limit: int
    action_kind: str


class _Membership(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    role: WorkspaceRole
    authorization_epoch: int


class _CompanyStateRow(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    canonical_state: CompanyState


@dataclass(frozen=True, slots=True)
class _Claim:
    schedule: ScheduleRecord
    scheduled_for: int


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        raise ScheduleError(ScheduleIssue.INVALID_TIMEZONE) from error


def next_occurrence(current: datetime, cadence: ScheduleCadence, timezone: str) -> datetime:
    """Advance by local calendar time so DST preserves the wall clock."""
    local = current.astimezone(_zone(timezone))
    if cadence is ScheduleCadence.ONCE:
        raise ScheduleError(ScheduleIssue.NO_RECURRENCE)
    days = 1 if cadence is ScheduleCadence.DAILY else 7
    return local + timedelta(days=days)


def _coalesced_occurrence(
    first_due: int, now: int, cadence: ScheduleCadence, timezone: str
) -> tuple[int, int | None]:
    current = datetime.fromtimestamp(first_due, UTC).astimezone(_zone(timezone))
    if cadence is ScheduleCadence.ONCE:
        return first_due, None
    days = 1 if cadence is ScheduleCadence.DAILY else 7
    elapsed_days = (
        datetime.fromtimestamp(now, UTC).astimezone(_zone(timezone)).date() - current.date()
    ).days
    periods = max(0, elapsed_days // days)
    latest = current + timedelta(days=periods * days)
    if int(latest.timestamp()) > now:
        latest -= timedelta(days=days)
    return int(latest.timestamp()), int((latest + timedelta(days=days)).timestamp())


@final
class ScheduleStore:
    """Own admission, leasing, dispatch, and terminal receipts."""

    def __init__(self, engine: Engine, schema: str) -> None:
        """Bind one validated application schema."""
        if not valid_schema(schema):
            raise ScheduleError(ScheduleIssue.INVALID_SCHEMA)
        self._engine = engine
        self._schema = schema
        self._quota = WorkspaceQuota(schema)

    def create(  # noqa: PLR0913
        self,
        *,
        actor_id: str,
        workspace_id: UUID,
        company_id: UUID,
        cadence: ScheduleCadence,
        timezone: str,
        first_run_at: datetime,
        pinned_revision: int,
        action_kind: str,
        payload: Mapping[str, JsonValue],
        created_at: float,
    ) -> ScheduleRecord:
        """Persist one authorized, revision-pinned schedule."""
        zone = _zone(timezone)
        if first_run_at.utcoffset() is None:
            raise ScheduleError(ScheduleIssue.OFFSET_REQUIRED)
        first = int(first_run_at.astimezone(zone).timestamp())
        timestamp = int(created_at)
        schedule_id = uuid4()
        with self._engine.begin() as connection:
            membership_row = (
                connection.execute(
                    self._sql(
                        """SELECT role, authorization_epoch
                        FROM "{schema}".samurai_workspace_memberships
                        WHERE workspace_id = :workspace_id AND user_id = :actor_id AND active"""
                    ),
                    {"workspace_id": workspace_id, "actor_id": actor_id},
                )
                .mappings()
                .one_or_none()
            )
            if membership_row is None:
                raise ScheduleError(ScheduleIssue.EDITOR_REQUIRED)
            membership = _Membership.model_validate(membership_row)
            if membership.role is WorkspaceRole.VIEWER:
                raise ScheduleError(ScheduleIssue.EDITOR_REQUIRED)
            revision = connection.execute(
                self._sql(
                    """SELECT current_revision FROM "{schema}".samurai_companies
                    WHERE company_id = :company_id AND workspace_id = :workspace_id"""
                ),
                {"company_id": company_id, "workspace_id": workspace_id},
            ).scalar_one_or_none()
            if revision is None:
                raise ScheduleError(ScheduleIssue.COMPANY_NOT_FOUND)
            if INT_ADAPTER.validate_python(revision) != pinned_revision:
                raise ScheduleError(ScheduleIssue.REVISION_CHANGED)
            self._quota.reserve(connection, workspace_id, QuotaResource.SCHEDULE)
            parameters = {
                "schedule_id": schedule_id,
                "workspace_id": workspace_id,
                "company_id": company_id,
                "actor_id": actor_id,
                "epoch": membership.authorization_epoch,
                "cadence": cadence.value,
                "timezone": timezone,
                "action_kind": action_kind,
                "payload": json.dumps(dict(payload), separators=(",", ":")),
                "revision": pinned_revision,
                "first": first,
                "timestamp": timestamp,
            }
            row = (
                connection.execute(
                    self._sql(
                        """INSERT INTO "{schema}".samurai_schedules
                    (schedule_id, workspace_id, company_id, created_by,
                    creator_authorization_epoch, cadence, timezone, action_kind, payload,
                    pinned_revision, enabled, next_run_at, created_at, updated_at)
                    VALUES (:schedule_id, :workspace_id, :company_id, :actor_id, :epoch,
                    :cadence, :timezone, :action_kind, CAST(:payload AS jsonb), :revision,
                    true, :first, :timestamp, :timestamp) RETURNING *"""
                    ),
                    parameters,
                )
                .mappings()
                .one()
            )
        return ScheduleRecord.model_validate(row)

    def list(self, actor_id: str, workspace_id: UUID) -> tuple[ScheduleRecord, ...]:
        """List schedules visible to an active workspace member."""
        with self._engine.connect() as connection:
            membership = connection.execute(
                self._sql(
                    """SELECT 1 FROM "{schema}".samurai_workspace_memberships
                    WHERE workspace_id = :workspace_id AND user_id = :actor_id AND active"""
                ),
                {"workspace_id": workspace_id, "actor_id": actor_id},
            ).scalar_one_or_none()
            if membership is None:
                raise ScheduleError(ScheduleIssue.MEMBER_REQUIRED)
            rows = connection.execute(
                self._sql(
                    """SELECT * FROM "{schema}".samurai_schedules
                    WHERE workspace_id = :workspace_id ORDER BY created_at, schedule_id"""
                ),
                {"workspace_id": workspace_id},
            ).mappings()
            return tuple(ScheduleRecord.model_validate(row) for row in rows)

    def disable(self, actor_id: str, workspace_id: UUID, schedule_id: UUID) -> None:
        """Disable a schedule and release its quota once."""
        with self._engine.begin() as connection:
            self._quota.lock(connection, workspace_id)
            authorized = connection.execute(
                self._sql(
                    """SELECT role FROM "{schema}".samurai_workspace_memberships
                    WHERE workspace_id = :workspace_id AND user_id = :actor_id AND active"""
                ),
                {"workspace_id": workspace_id, "actor_id": actor_id},
            ).scalar_one_or_none()
            if (
                authorized is None
                or ROLE_ADAPTER.validate_python(authorized) is WorkspaceRole.VIEWER
            ):
                raise ScheduleError(ScheduleIssue.EDITOR_REQUIRED)
            disabled = connection.execute(
                self._sql(
                    """UPDATE "{schema}".samurai_schedules SET enabled = false,
                    updated_at = EXTRACT(EPOCH FROM clock_timestamp())::bigint
                    WHERE schedule_id = :schedule_id AND workspace_id = :workspace_id AND enabled
                    RETURNING schedule_id"""
                ),
                {"schedule_id": schedule_id, "workspace_id": workspace_id},
            ).scalar_one_or_none()
            if disabled is not None:
                self._quota.release(connection, workspace_id, QuotaResource.SCHEDULE)

    def run_due(self, now: datetime, runner_id: str) -> tuple[ScheduleRun, ...]:
        """Claim and finish every occurrence due at a supplied instant."""
        timestamp = int(now.timestamp())
        completed: list[ScheduleRun] = []
        while claimed := self._claim(timestamp, runner_id):
            receipt = self._execute(claimed, timestamp, runner_id)
            if receipt is not None:
                completed.append(receipt)
        return tuple(completed)

    def _claim(self, now: int, runner_id: str) -> _Claim | None:
        with self._engine.begin() as connection:
            stale = (
                connection.execute(
                    self._sql(
                        """SELECT s.*, r.scheduled_for AS claimed_for
                    FROM "{schema}".samurai_schedule_runs r
                    JOIN "{schema}".samurai_schedules s USING (schedule_id)
                    WHERE r.status = 'claimed' AND r.lease_expires_at <= :now
                    ORDER BY r.lease_expires_at FOR UPDATE OF r SKIP LOCKED LIMIT 1"""
                    ),
                    {"now": now},
                )
                .mappings()
                .one_or_none()
            )
            if stale is not None:
                schedule = ScheduleRecord.model_validate(stale)
                scheduled_for = INT_ADAPTER.validate_python(stale["claimed_for"])
                _ = connection.execute(
                    self._sql(
                        """UPDATE "{schema}".samurai_schedule_runs SET claimed_at = :now,
                        lease_owner = :runner_id, lease_expires_at = :expires
                        WHERE schedule_id = :schedule_id AND scheduled_for = :scheduled_for
                        AND status = 'claimed'"""
                    ),
                    {
                        "now": now,
                        "runner_id": runner_id,
                        "expires": now + LEASE_SECONDS,
                        "schedule_id": schedule.schedule_id,
                        "scheduled_for": scheduled_for,
                    },
                )
                return _Claim(schedule=schedule, scheduled_for=scheduled_for)
            row = (
                connection.execute(
                    self._sql(
                        """SELECT * FROM "{schema}".samurai_schedules
                    WHERE enabled AND next_run_at <= :now ORDER BY next_run_at, schedule_id
                    FOR UPDATE SKIP LOCKED LIMIT 1"""
                    ),
                    {"now": now},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            schedule = ScheduleRecord.model_validate(row)
            if schedule.next_run_at is None:
                return None
            scheduled_for, following = _coalesced_occurrence(
                schedule.next_run_at, now, schedule.cadence, schedule.timezone
            )
            claimed = connection.execute(
                self._sql(
                    """INSERT INTO "{schema}".samurai_schedule_runs
                    (schedule_id, scheduled_for, status, claimed_at, lease_owner, lease_expires_at)
                    VALUES (:schedule_id, :scheduled_for, 'claimed', :now, :runner_id, :expires)
                    ON CONFLICT (schedule_id, scheduled_for) DO NOTHING RETURNING schedule_id"""
                ),
                {
                    "schedule_id": schedule.schedule_id,
                    "scheduled_for": scheduled_for,
                    "now": now,
                    "runner_id": runner_id,
                    "expires": now + LEASE_SECONDS,
                },
            ).scalar_one_or_none()
            if claimed is None:
                return None
            _ = connection.execute(
                self._sql(
                    """UPDATE "{schema}".samurai_schedules SET next_run_at = :following,
                    updated_at = :now WHERE schedule_id = :schedule_id"""
                ),
                {"following": following, "now": now, "schedule_id": schedule.schedule_id},
            )
            return _Claim(schedule=schedule, scheduled_for=scheduled_for)

    def _execute(self, claim: _Claim, now: int, runner_id: str) -> ScheduleRun | None:
        schedule = claim.schedule
        with self._engine.begin() as connection:
            self._quota.lock(connection, schedule.workspace_id)
            valid_lease = connection.execute(
                self._sql(
                    """SELECT lease_owner FROM "{schema}".samurai_schedule_runs
                    WHERE schedule_id = :schedule_id AND scheduled_for = :scheduled_for
                    AND status = 'claimed' AND lease_owner = :runner_id
                    AND lease_expires_at > :now FOR UPDATE"""
                ),
                {
                    "schedule_id": schedule.schedule_id,
                    "scheduled_for": claim.scheduled_for,
                    "runner_id": runner_id,
                    "now": now,
                },
            ).scalar_one_or_none()
            if valid_lease is None:
                return None
            reason = self._invalid_reason(connection, schedule)
            result = None if reason else self._workspace_review(connection, schedule)
            status: Literal["completed", "failed", "skipped"] = "completed"
            if reason == "unregistered_action":
                status = "failed"
            elif reason is not None:
                status = "skipped"
            terminal = schedule.cadence is ScheduleCadence.ONCE or reason is not None
            if terminal:
                disabled = connection.execute(
                    self._sql(
                        """UPDATE "{schema}".samurai_schedules SET enabled = false,
                        updated_at = :now WHERE schedule_id = :schedule_id AND enabled
                        RETURNING schedule_id"""
                    ),
                    {"now": now, "schedule_id": schedule.schedule_id},
                ).scalar_one_or_none()
                if disabled is not None:
                    self._quota.release(connection, schedule.workspace_id, QuotaResource.SCHEDULE)
            _ = UUID_ADAPTER.validate_python(
                connection.execute(
                    self._sql(
                        """UPDATE "{schema}".samurai_schedule_runs SET status = :status,
                    result = CAST(:result AS jsonb), error_code = :error_code, completed_at = :now,
                    lease_owner = NULL, lease_expires_at = NULL
                    WHERE schedule_id = :schedule_id AND scheduled_for = :scheduled_for
                    AND status = 'claimed' AND lease_owner = :runner_id
                    AND lease_expires_at > :now RETURNING schedule_id"""
                    ),
                    {
                        "status": status,
                        "result": (
                            None if result is None else json.dumps(result, separators=(",", ":"))
                        ),
                        "error_code": reason,
                        "now": now,
                        "schedule_id": schedule.schedule_id,
                        "scheduled_for": claim.scheduled_for,
                        "runner_id": runner_id,
                    },
                ).scalar_one()
            )
            _ = connection.execute(
                self._sql(
                    """UPDATE "{schema}".samurai_schedules SET last_run_at = :scheduled_for,
                    updated_at = :now WHERE schedule_id = :schedule_id"""
                ),
                {
                    "scheduled_for": claim.scheduled_for,
                    "now": now,
                    "schedule_id": schedule.schedule_id,
                },
            )
        return ScheduleRun(
            schedule_id=schedule.schedule_id,
            scheduled_for=claim.scheduled_for,
            status=status,
            result=result,
            error_code=reason,
        )

    def _invalid_reason(self, connection: Connection, schedule: ScheduleRecord) -> str | None:
        current = _DispatchState.model_validate(
            connection.execute(
                self._sql(
                    """SELECT s.enabled, s.action_kind, m.active, m.authorization_epoch,
                c.current_revision,
                q.schedule_count, q.schedule_limit FROM "{schema}".samurai_schedules s
                JOIN "{schema}".samurai_workspace_memberships m
                ON m.workspace_id = s.workspace_id AND m.user_id = s.created_by
                JOIN "{schema}".samurai_companies c ON c.company_id = s.company_id
                JOIN "{schema}".samurai_workspace_quotas q ON q.workspace_id = s.workspace_id
                WHERE s.schedule_id = :schedule_id FOR UPDATE OF s, m, c, q"""
                ),
                {"schedule_id": schedule.schedule_id},
            )
            .mappings()
            .one()
        )
        if not current.enabled:
            return "schedule_disabled"
        if (
            not current.active
            or current.authorization_epoch != schedule.creator_authorization_epoch
        ):
            return "authorization_changed"
        if current.current_revision != schedule.pinned_revision:
            return "revision_changed"
        if current.schedule_count > current.schedule_limit:
            return "workspace_quota"
        if current.action_kind != "workspace_review":
            return "unregistered_action"
        return None

    def _workspace_review(
        self, connection: Connection, schedule: ScheduleRecord
    ) -> dict[str, JsonValue]:
        row = (
            connection.execute(
                self._sql(
                    """SELECT canonical_state FROM "{schema}".samurai_companies
                WHERE company_id = :company_id"""
                ),
                {"company_id": schedule.company_id},
            )
            .mappings()
            .one()
        )
        state = _CompanyStateRow.model_validate(row).canonical_state
        source_count = sum(len(artifact.sources) for artifact in state.artifacts)
        unverified = sum(
            claim.verification_status == "unverified"
            for artifact in state.artifacts
            for claim in artifact.claims
        )
        gaps: list[JsonValue] = []
        if not state.artifacts:
            gaps.append("no_company_artifacts")
        if unverified:
            gaps.append("unverified_claims")
        return {
            "action_kind": "workspace_review",
            "company_id": str(schedule.company_id),
            "revision": state.current_revision,
            "artifact_count": len(state.artifacts),
            "source_count": source_count,
            "unverified_claim_count": unverified,
            "evidence_gaps": gaps,
        }

    def _sql(self, source: str) -> TextClause:
        return text(source.format(schema=self._schema))
