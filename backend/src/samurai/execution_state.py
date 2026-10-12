"""PostgreSQL admission and acceptance fences for durable Samurai work."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, Final, Literal, override
from uuid import UUID, uuid4

from agno.db.postgres import PostgresDb
from agno.run.concurrency import get_worker_ownership
from agno.session import AgentSession, WorkflowSession
from pydantic import BaseModel, Field, JsonValue, TypeAdapter
from sqlalchemy import BigInteger, Column, Index, MetaData, String, Table, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as SqlAlchemySession

from samurai.contracts import ArtifactType, CompanyState, Contract

if TYPE_CHECKING:
    from agno.session import Session


JSON_ADAPTER = TypeAdapter(JsonValue)
JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])
OBJECT_DICT_ADAPTER = TypeAdapter(dict[str, object])

WORK_INTENT_METADATA_KEY: Final = "samurai_work_intent"
PARENT_BINDING_KEYS: Final = ("child_session_id", "company_id", "current_revision")


@unique
class WorkOperation(StrEnum):
    """Bounded parent operations that may own durable work."""

    JOURNEY = "journey"
    LAUNCH_DRAFTS = "launch_drafts"
    METRICS_ANALYSIS = "metrics_analysis"
    READ_ONLY_STATE = "read_only_state"


@unique
class ApprovedStage(StrEnum):
    """Founder-approved journey ceilings."""

    BRIEF = "brief"
    RESEARCH = "research"
    STRATEGY = "strategy"
    PLAN = "plan"


class WorkIntentInput(Contract):
    """Authenticated immutable approval attached to native queue admission."""

    owner_id: str = Field(min_length=1)
    parent_session_id: str = Field(min_length=1)
    child_session_id: str = Field(min_length=1)
    company_id: UUID | None = None
    operation: WorkOperation
    stage: ApprovedStage
    expected_revision: int = Field(ge=0)
    approved_input: JsonValue


class NormalizedWorkInput(Contract):
    """Typed first-tool arguments constrained by immutable approved work scope."""

    operation: WorkOperation
    stage: ApprovedStage
    expected_revision: int = Field(ge=0)
    arguments: dict[str, JsonValue]


class AcceptanceToken(Contract):
    """Trusted queue ownership carried into a child workflow."""

    parent_run_id: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    parent_session_id: str = Field(min_length=1)
    child_session_id: str = Field(min_length=1)
    worker_id: str = Field(min_length=1)
    attempt: int = Field(ge=1)
    fingerprint: str = Field(min_length=64, max_length=64)


class BoundWorkIntent(Contract):
    """Persisted approved arguments bound to the claimed native attempt."""

    approval: WorkIntentInput
    normalized_input: NormalizedWorkInput
    token: AcceptanceToken


type WorkReceiptStatus = Literal["PENDING", "RUNNING", "PAUSED", "COMPLETED", "ERROR", "CANCELLED"]


class WorkReceipt(Contract):
    """Owner-safe view of a native durable ticket and accepted company revision."""

    run_id: str
    session_id: str
    status: WorkReceiptStatus
    attempt: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    recovering: bool
    failure_reason: str | None = None
    company_id: UUID | None = None
    revision: int | None = Field(default=None, ge=0)
    updated_at: int | None = None


class ParentBinding(Contract):
    """Recoverable parent pointer committed with canonical child state."""

    child_session_id: str
    company_id: UUID
    current_revision: int = Field(ge=0)


class _JobFenceRow(BaseModel):
    status: str
    locked_by: str | None = None
    attempt: int
    max_attempts: int = 1


class _IntentRow(BaseModel):
    logical_work_id: str
    owner_id: str
    parent_session_id: str
    child_session_id: str
    company_id: UUID | None = None
    operation: WorkOperation
    stage: ApprovedStage
    expected_revision: int
    approved_input: JsonValue
    fingerprint: str
    bound_input: JsonValue | None = None
    bound_fingerprint: str | None = None
    state: str
    accepted_revision: int | None = None


class _ChildSessionRow(BaseModel):
    session_data: dict[str, JsonValue] | None = None


class _WorkReceiptRow(BaseModel):
    run_id: str
    session_id: str
    status: str
    attempt: int
    max_attempts: int
    updated_at: int | None = None
    company_id: UUID | None = None
    accepted_revision: int | None = None


@unique
class WorkIntentIssue(StrEnum):
    """Fail-closed admission and acceptance outcomes."""

    MISSING_APPROVAL = "trusted work approval is missing"
    FORGED_APPROVAL = "trusted work approval does not match the native job"
    CHANGED_APPROVAL = "idempotency key was reused with changed approved work"
    ACTIVE_WORK = "another write job is active for this company"
    MISSING_INTENT = "accepted native job has no work intent"
    STALE_WORKER = "worker no longer owns this job attempt"
    CANCELLED = "cancelled or terminal work cannot accept company state"
    SESSION_MISSING = "canonical child session is missing"
    STALE_REVISION = "canonical company revision changed before acceptance"


@dataclass(frozen=True, slots=True)
class WorkIntentError(Exception):
    """Reject unsafe queue admission or company-state acceptance."""

    issue: WorkIntentIssue

    @override
    def __str__(self) -> str:
        return self.issue.value


def _fingerprint(intent: WorkIntentInput) -> str:
    normalized = json.dumps(
        intent.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


def _execution_fingerprint(approval_fingerprint: str, normalized_input: NormalizedWorkInput) -> str:
    normalized = json.dumps(
        {
            "approval_fingerprint": approval_fingerprint,
            "normalized_input": normalized_input.model_dump(mode="json"),
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


def _terminal_acceptance(
    operation: str,
    stage: str,
    state: CompanyState,
    expected_revision: int,
) -> bool:
    if operation != WorkOperation.JOURNEY:
        return operation != WorkOperation.READ_ONLY_STATE
    targets = {
        ApprovedStage.BRIEF: ArtifactType.INTAKE,
        ApprovedStage.RESEARCH: ArtifactType.RESEARCH,
        ApprovedStage.STRATEGY: ArtifactType.STRATEGY,
        ApprovedStage.PLAN: ArtifactType.VERIFICATION,
    }
    target = targets[ApprovedStage(stage)]
    return any(
        artifact.artifact_type == target and artifact.revision > expected_revision
        for artifact in state.artifacts
    )


class SamuraiPostgresDb(PostgresDb):
    """Keep Agno's Postgres API while fencing Samurai work in the same database."""

    work_intent_table_name: str = "samurai_work_intents"

    def _work_intent_table(self, *, create: bool = False) -> Table:
        metadata = MetaData(schema=self.db_schema)
        table = Table(
            self.work_intent_table_name,
            metadata,
            Column("logical_work_id", String, primary_key=True),
            Column("job_id", String, nullable=False, unique=True),
            Column("parent_run_id", String, nullable=False, unique=True),
            Column("parent_session_id", String, nullable=False),
            Column("owner_id", String, nullable=False),
            Column("child_session_id", String, nullable=False),
            Column("company_id", String, nullable=True),
            Column("operation", String, nullable=False),
            Column("stage", String, nullable=False),
            Column("expected_revision", BigInteger, nullable=False),
            Column("approved_input", JSONB, nullable=False),
            Column("fingerprint", String(64), nullable=False),
            Column("bound_input", JSONB, nullable=True),
            Column("bound_fingerprint", String(64), nullable=True),
            Column("state", String, nullable=False),
            Column("accepted_artifact_ids", JSONB, nullable=False),
            Column("accepted_revision", BigInteger, nullable=True),
            Column("parent_binding", JSONB, nullable=True),
            Column("created_at", BigInteger, nullable=False),
            Column("updated_at", BigInteger, nullable=False),
        )
        _ = Index(
            "uq_samurai_active_company_work",
            table.c.owner_id,
            func.coalesce(table.c.company_id, table.c.parent_session_id),
            unique=True,
            postgresql_where=text("state = 'active'"),
        )
        if create:
            metadata.create_all(self.db_engine, tables=[table], checkfirst=True)
        return table

    def ensure_work_intents_table(self) -> None:
        """Provision additive intent storage beside Agno's native tables."""
        self.ensure_jobs_table()
        _ = self._get_table(table_type="sessions", create_table_if_not_found=True)
        _ = self._work_intent_table(create=True)

    @override
    def enqueue_job(self, job: object, max_depth: int = 0) -> dict[str, object]:
        """Admit a native job only with authenticated immutable work approval."""
        if not isinstance(job, Mapping):
            raise WorkIntentError(WorkIntentIssue.MISSING_APPROVAL)
        clean_job = copy.deepcopy(OBJECT_DICT_ADAPTER.validate_python(job))
        payload_value = clean_job.get("payload")
        if not isinstance(payload_value, Mapping):
            raise WorkIntentError(WorkIntentIssue.MISSING_APPROVAL)
        payload = JSON_OBJECT_ADAPTER.validate_python(payload_value)
        kwargs_value = payload.get("kwargs")
        if not isinstance(kwargs_value, Mapping):
            raise WorkIntentError(WorkIntentIssue.MISSING_APPROVAL)
        kwargs = JSON_OBJECT_ADAPTER.validate_python(kwargs_value)
        metadata_value = kwargs.get("metadata")
        if not isinstance(metadata_value, Mapping):
            raise WorkIntentError(WorkIntentIssue.MISSING_APPROVAL)
        metadata = JSON_OBJECT_ADAPTER.validate_python(metadata_value)
        approval = metadata.pop(WORK_INTENT_METADATA_KEY, None)
        if not metadata:
            _ = kwargs.pop("metadata", None)
        else:
            kwargs["metadata"] = metadata
        payload["kwargs"] = kwargs
        clean_job["payload"] = payload
        if approval is None:
            raise WorkIntentError(WorkIntentIssue.MISSING_APPROVAL)
        intent = WorkIntentInput.model_validate(approval)
        return self.enqueue_work_job(clean_job, intent, max_depth=max_depth)

    def enqueue_work_job(
        self,
        job: Mapping[str, object],
        intent: WorkIntentInput,
        *,
        max_depth: int = 0,
    ) -> dict[str, object]:
        """Commit one intent and its native queue ticket atomically."""
        self.ensure_work_intents_table()
        jobs = self._get_table(table_type="jobs")
        intents = self._work_intent_table()
        if jobs is None:
            message = "native job table is unavailable"
            raise RuntimeError(message)
        clean_job = dict(job)
        clean_job["idempotency_key"] = clean_job.get("idempotency_key") or None
        if (
            clean_job.get("user_id") != intent.owner_id
            or clean_job.get("session_id") != intent.parent_session_id
        ):
            raise WorkIntentError(WorkIntentIssue.FORGED_APPROVAL)
        fingerprint = _fingerprint(intent)

        try:
            with SqlAlchemySession(self.db_engine) as session, session.begin():
                if (
                    duplicate := self._existing_job(
                        session,
                        jobs,
                        intents,
                        (clean_job.get("idempotency_key"), clean_job.get("user_id")),
                        fingerprint,
                    )
                ) is not None:
                    return duplicate
                if max_depth:
                    queued = session.execute(
                        select(func.count()).select_from(jobs).where(jobs.c.status == "queued")
                    ).scalar_one()
                    if queued >= max_depth:
                        return {"accepted": False, "reason": "queue_full", "job": None}
                now = int(time.time())
                _ = session.execute(jobs.insert().values(**clean_job))
                _ = session.execute(
                    intents.insert().values(
                        logical_work_id=str(uuid4()),
                        job_id=clean_job["id"],
                        parent_run_id=clean_job["id"],
                        parent_session_id=intent.parent_session_id,
                        owner_id=intent.owner_id,
                        child_session_id=intent.child_session_id,
                        company_id=(
                            str(intent.company_id) if intent.company_id is not None else None
                        ),
                        operation=intent.operation.value,
                        stage=intent.stage.value,
                        expected_revision=intent.expected_revision,
                        approved_input=intent.approved_input,
                        fingerprint=fingerprint,
                        state="active",
                        accepted_artifact_ids=[],
                        created_at=now,
                        updated_at=now,
                    )
                )
        except IntegrityError as error:
            with SqlAlchemySession(self.db_engine) as session:
                if (
                    duplicate := self._existing_job(
                        session,
                        jobs,
                        intents,
                        (clean_job.get("idempotency_key"), clean_job.get("user_id")),
                        fingerprint,
                    )
                ) is not None:
                    return duplicate
            raise WorkIntentError(WorkIntentIssue.ACTIVE_WORK) from error
        else:
            return {"accepted": True, "reason": None, "job": clean_job}

    def get_work_receipt(
        self,
        owner_id: str,
        parent_session_id: str,
        submission_id: UUID,
    ) -> WorkReceipt | None:
        """Return one owner-scoped ticket without exposing its payload or raw error."""
        jobs = self._get_table(table_type="jobs")
        if jobs is None:
            return None
        intents = self._work_intent_table()
        row = None
        with SqlAlchemySession(self.db_engine) as session:
            row = (
                session.execute(
                    select(
                        jobs.c.id.label("run_id"),
                        jobs.c.session_id,
                        jobs.c.status,
                        jobs.c.attempt,
                        jobs.c.max_attempts,
                        jobs.c.updated_at,
                        intents.c.company_id,
                        intents.c.accepted_revision,
                    )
                    .select_from(jobs.join(intents, intents.c.job_id == jobs.c.id))
                    .where(
                        jobs.c.idempotency_key == str(submission_id),
                        jobs.c.user_id == owner_id,
                        jobs.c.session_id == parent_session_id,
                        intents.c.owner_id == owner_id,
                        intents.c.parent_session_id == parent_session_id,
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        receipt_row = _WorkReceiptRow.model_validate(row)
        queue_status = receipt_row.status
        statuses: dict[str, WorkReceiptStatus] = {
            "queued": "PENDING",
            "running": "RUNNING",
            "paused": "PAUSED",
            "completed": "COMPLETED",
            "failed": "ERROR",
            "cancelled": "CANCELLED",
        }
        status = statuses.get(queue_status)
        if status is None:
            message = "native job has an unsupported status"
            raise RuntimeError(message)
        attempt = receipt_row.attempt
        return WorkReceipt(
            run_id=receipt_row.run_id,
            session_id=receipt_row.session_id,
            status=status,
            attempt=attempt,
            max_attempts=receipt_row.max_attempts,
            recovering=queue_status == "queued" and attempt > 0,
            failure_reason=(
                "work stopped after the allowed attempts"
                if queue_status == "failed"
                else "work was cancelled"
                if queue_status == "cancelled"
                else None
            ),
            company_id=receipt_row.company_id,
            revision=receipt_row.accepted_revision,
            updated_at=receipt_row.updated_at,
        )

    @staticmethod
    def _existing_job(
        session: SqlAlchemySession,
        jobs: Table,
        intents: Table,
        identity: tuple[object, object],
        fingerprint: str,
    ) -> dict[str, object] | None:
        key, user_id = identity
        if key is None:
            return None
        row = (
            session.execute(
                select(jobs).where(
                    jobs.c.idempotency_key == key,
                    jobs.c.user_id.is_not_distinct_from(user_id),
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        existing: dict[str, object] = dict(row)
        job_id = existing.get("id")
        admitted = session.execute(
            select(intents.c.fingerprint).where(intents.c.job_id == job_id)
        ).scalar_one_or_none()
        if admitted != fingerprint:
            raise WorkIntentError(WorkIntentIssue.CHANGED_APPROVAL)
        return {"accepted": False, "reason": "duplicate", "job": existing}

    def bind_work_intent(
        self,
        parent_run_id: str,
        normalized_input: NormalizedWorkInput | Mapping[str, object] | None = None,
    ) -> BoundWorkIntent:
        """Bind a claimed native attempt to its persisted approved operation."""
        ownership = get_worker_ownership(parent_run_id)
        if ownership is None:
            raise WorkIntentError(WorkIntentIssue.STALE_WORKER)
        jobs = self._get_table(table_type="jobs")
        intents = self._work_intent_table()
        if jobs is None:
            raise WorkIntentError(WorkIntentIssue.MISSING_INTENT)
        with SqlAlchemySession(self.db_engine) as session, session.begin():
            job = (
                session.execute(select(jobs).where(jobs.c.id == parent_run_id).with_for_update())
                .mappings()
                .first()
            )
            admitted = (
                session.execute(
                    select(intents)
                    .where(intents.c.parent_run_id == parent_run_id)
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if admitted is None:
                raise WorkIntentError(WorkIntentIssue.MISSING_INTENT)
            job_row = _JobFenceRow.model_validate(job)
            self._check_job_owner(job_row, ownership.worker_id, ownership.attempt)
            intent_row = _IntentRow.model_validate(admitted)
            approval = WorkIntentInput(
                owner_id=intent_row.owner_id,
                parent_session_id=intent_row.parent_session_id,
                child_session_id=intent_row.child_session_id,
                company_id=intent_row.company_id,
                operation=intent_row.operation,
                stage=intent_row.stage,
                expected_revision=intent_row.expected_revision,
                approved_input=intent_row.approved_input,
            )
            bound_input = intent_row.bound_input
            bound_fingerprint = intent_row.bound_fingerprint
            proposed = (
                NormalizedWorkInput.model_validate(normalized_input)
                if normalized_input is not None
                else None
            )
            if proposed is not None and (
                proposed.operation != approval.operation
                or proposed.stage != approval.stage
                or proposed.expected_revision != approval.expected_revision
            ):
                raise WorkIntentError(WorkIntentIssue.CHANGED_APPROVAL)
            if bound_input is None:
                if proposed is None:
                    raise WorkIntentError(WorkIntentIssue.MISSING_APPROVAL)
                bound = proposed
                bound_fingerprint = _execution_fingerprint(intent_row.fingerprint, bound)
                _ = session.execute(
                    intents.update()
                    .where(intents.c.logical_work_id == intent_row.logical_work_id)
                    .values(
                        bound_input=bound.model_dump(mode="json"),
                        bound_fingerprint=bound_fingerprint,
                        updated_at=int(time.time()),
                    )
                )
            else:
                bound = NormalizedWorkInput.model_validate(bound_input)
            if (
                proposed is not None
                and _execution_fingerprint(intent_row.fingerprint, proposed) != bound_fingerprint
            ):
                raise WorkIntentError(WorkIntentIssue.CHANGED_APPROVAL)
            if bound_fingerprint is None:
                raise WorkIntentError(WorkIntentIssue.MISSING_INTENT)
        return BoundWorkIntent(
            approval=approval,
            normalized_input=bound,
            token=AcceptanceToken(
                parent_run_id=parent_run_id,
                owner_id=approval.owner_id,
                parent_session_id=approval.parent_session_id,
                child_session_id=approval.child_session_id,
                worker_id=ownership.worker_id,
                attempt=ownership.attempt,
                fingerprint=bound_fingerprint,
            ),
        )

    @staticmethod
    def _check_job_owner(job: _JobFenceRow, worker_id: str, attempt: int) -> None:
        if job.status != "running":
            raise WorkIntentError(WorkIntentIssue.CANCELLED)
        if job.locked_by != worker_id or job.attempt != attempt:
            raise WorkIntentError(WorkIntentIssue.STALE_WORKER)

    def accept_company_state(self, state: CompanyState, token: AcceptanceToken) -> CompanyState:
        """Atomically accept canonical child state for the current job attempt."""
        ownership = get_worker_ownership(token.parent_run_id)
        if ownership is None or (ownership.worker_id, ownership.attempt) != (
            token.worker_id,
            token.attempt,
        ):
            raise WorkIntentError(WorkIntentIssue.STALE_WORKER)
        jobs = self._get_table(table_type="jobs")
        sessions = self._get_table(table_type="sessions")
        intents = self._work_intent_table()
        if jobs is None or sessions is None:
            raise WorkIntentError(WorkIntentIssue.SESSION_MISSING)
        with SqlAlchemySession(self.db_engine) as session, session.begin():
            job = (
                session.execute(
                    select(jobs).where(jobs.c.id == token.parent_run_id).with_for_update()
                )
                .mappings()
                .first()
            )
            self._check_job_owner(_JobFenceRow.model_validate(job), token.worker_id, token.attempt)
            intent = (
                session.execute(
                    select(intents)
                    .where(intents.c.parent_run_id == token.parent_run_id)
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if intent is None or intent["bound_fingerprint"] != token.fingerprint:
                raise WorkIntentError(WorkIntentIssue.MISSING_INTENT)
            intent_row = _IntentRow.model_validate(intent)
            if (
                intent_row.owner_id,
                intent_row.parent_session_id,
                intent_row.child_session_id,
            ) != (
                token.owner_id,
                token.parent_session_id,
                token.child_session_id,
            ):
                raise WorkIntentError(WorkIntentIssue.FORGED_APPROVAL)
            _ = session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:session_id, 0))"),
                {"session_id": token.child_session_id},
            )
            child = (
                session.execute(
                    select(sessions)
                    .where(
                        sessions.c.session_id == token.child_session_id,
                        sessions.c.user_id == token.owner_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if child is None:
                raise WorkIntentError(WorkIntentIssue.SESSION_MISSING)
            child_row = _ChildSessionRow.model_validate(child)
            session_data = copy.deepcopy(child_row.session_data or {})
            session_state = JSON_OBJECT_ADAPTER.validate_python(
                session_data.get("session_state") or {}
            )
            current_payload = session_state.get("company")
            if intent_row.state == "accepted":
                return CompanyState.model_validate(current_payload)
            expected = intent_row.accepted_revision
            expected = intent_row.expected_revision if expected is None else expected
            revision_path = (
                "CAST(session_data #>> '{session_state,company,current_revision}' AS BIGINT)"
            )
            revision_guard = (
                text("session_data #> '{session_state,company}' IS NULL")
                if expected == 0 and current_payload is None
                else text(revision_path + " = :expected_revision")
            )
            session_state["company"] = JSON_ADAPTER.validate_python(state.model_dump(mode="json"))
            session_data["session_state"] = session_state
            updated_id = session.execute(
                sessions.update()
                .where(sessions.c.session_id == token.child_session_id, revision_guard)
                .values(session_data=session_data, updated_at=int(time.time()))
                .returning(sessions.c.session_id),
                {"expected_revision": expected},
            ).scalar_one_or_none()
            if updated_id is None:
                raise WorkIntentError(WorkIntentIssue.STALE_REVISION)
            accepted_ids = [
                str(artifact.artifact_id)
                for artifact in state.artifacts
                if artifact.revision > intent_row.expected_revision
            ]
            binding = ParentBinding(
                child_session_id=token.child_session_id,
                company_id=state.context.company_id,
                current_revision=state.current_revision,
            )
            terminal = _terminal_acceptance(
                intent_row.operation,
                intent_row.stage,
                state,
                intent_row.expected_revision,
            )
            _ = session.execute(
                intents.update()
                .where(intents.c.logical_work_id == intent_row.logical_work_id)
                .values(
                    company_id=str(state.context.company_id),
                    state="accepted" if terminal else "active",
                    accepted_artifact_ids=accepted_ids,
                    accepted_revision=state.current_revision,
                    parent_binding=binding.model_dump(mode="json"),
                    updated_at=int(time.time()),
                )
            )
        return state

    def get_parent_binding(self, parent_run_id: str, owner_id: str) -> ParentBinding | None:
        """Recover the parent pointer committed by accepted child work."""
        intents = self._work_intent_table()
        with SqlAlchemySession(self.db_engine) as session:
            payload = session.execute(
                select(intents.c.parent_binding).where(
                    intents.c.parent_run_id == parent_run_id,
                    intents.c.owner_id == owner_id,
                )
            ).scalar_one_or_none()
        return ParentBinding.model_validate(payload) if payload is not None else None

    @staticmethod
    def _release_terminal_intent(
        session: SqlAlchemySession,
        intents: Table,
        job_id: str,
        status: str,
        now: int,
    ) -> None:
        if status in {"cancelled", "failed"}:
            _ = session.execute(
                intents.update()
                .where(intents.c.job_id == job_id, intents.c.state == "active")
                .values(state=status, updated_at=now)
            )

    @override
    def complete_job(
        self,
        job_id: str,
        worker_id: str,
        attempt: int,
        status: str,
        error: str | None = None,
    ) -> bool:
        """Settle a claimed job and release failed or cancelled intent scope atomically."""
        jobs = self._get_table(table_type="jobs")
        intents = self._work_intent_table()
        if jobs is None:
            return False
        now = int(time.time())
        with SqlAlchemySession(self.db_engine) as session, session.begin():
            job = session.execute(
                select(jobs)
                .where(
                    jobs.c.id == job_id,
                    jobs.c.locked_by == worker_id,
                    jobs.c.attempt == attempt,
                    jobs.c.status == "running",
                )
                .with_for_update()
            ).first()
            if job is None:
                return False
            _ = session.execute(
                select(intents.c.logical_work_id)
                .where(intents.c.job_id == job_id)
                .with_for_update()
            ).first()
            _ = session.execute(
                jobs.update()
                .where(jobs.c.id == job_id)
                .values(
                    status=status,
                    error=error,
                    locked_by=None,
                    locked_at=None,
                    completed_at=now,
                    updated_at=now,
                )
            )
            self._release_terminal_intent(session, intents, job_id, status, now)
        return True

    @override
    def retry_or_fail_job(
        self,
        job_id: str,
        worker_id: str,
        attempt: int,
        error: str,
        retry_delay_seconds: int = 30,
    ) -> str | None:
        """Keep retry scope active, releasing it only when attempts are exhausted."""
        jobs = self._get_table(table_type="jobs")
        intents = self._work_intent_table()
        if jobs is None:
            return None
        now = int(time.time())
        with SqlAlchemySession(self.db_engine) as session, session.begin():
            job = (
                session.execute(
                    select(jobs)
                    .where(
                        jobs.c.id == job_id,
                        jobs.c.locked_by == worker_id,
                        jobs.c.attempt == attempt,
                        jobs.c.status == "running",
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if job is None:
                return None
            _ = session.execute(
                select(intents.c.logical_work_id)
                .where(intents.c.job_id == job_id)
                .with_for_update()
            ).first()
            job_row = _JobFenceRow.model_validate(job)
            terminal = job_row.attempt >= job_row.max_attempts
            status = "failed" if terminal else "queued"
            values: dict[str, object] = {
                "status": status,
                "error": error,
                "locked_by": None,
                "locked_at": None,
                "updated_at": now,
            }
            if terminal:
                values["completed_at"] = now
            else:
                values["available_at"] = now + retry_delay_seconds
            _ = session.execute(jobs.update().where(jobs.c.id == job_id).values(**values))
            self._release_terminal_intent(session, intents, job_id, status, now)
        return status

    @override
    def cancel_job(self, job_id: str) -> bool:
        """Cancel a waiting ticket and release its intent in the same transaction."""
        jobs = self._get_table(table_type="jobs")
        intents = self._work_intent_table()
        if jobs is None:
            return False
        now = int(time.time())
        with SqlAlchemySession(self.db_engine) as session, session.begin():
            job = session.execute(
                select(jobs)
                .where(jobs.c.id == job_id, jobs.c.status.in_(["queued", "paused"]))
                .with_for_update()
            ).first()
            if job is None:
                return False
            _ = session.execute(
                select(intents.c.logical_work_id)
                .where(intents.c.job_id == job_id)
                .with_for_update()
            ).first()
            _ = session.execute(
                jobs.update()
                .where(jobs.c.id == job_id)
                .values(status="cancelled", completed_at=now, updated_at=now)
            )
            self._release_terminal_intent(session, intents, job_id, "cancelled", now)
        return True

    def cancel_work_job(
        self,
        job_id: str,
        owner_id: str,
        parent_session_id: str,
    ) -> bool:
        """Atomically cancel an owner-scoped work ticket, run, and intent."""
        jobs = self._get_table(table_type="jobs")
        runs = self._get_table(table_type="runs")
        intents = self._work_intent_table()
        if jobs is None or runs is None:
            return False
        now = int(time.time())
        with SqlAlchemySession(self.db_engine) as session, session.begin():
            job = (
                session.execute(
                    select(jobs)
                    .where(
                        jobs.c.id == job_id,
                        jobs.c.user_id == owner_id,
                        jobs.c.session_id == parent_session_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            intent = (
                session.execute(
                    select(intents)
                    .where(
                        intents.c.job_id == job_id,
                        intents.c.owner_id == owner_id,
                        intents.c.parent_session_id == parent_session_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if job is None or intent is None:
                return False
            status = _JobFenceRow.model_validate(job).status
            if status in {"completed", "failed"}:
                return False
            if status == "cancelled":
                return True
            run = (
                session.execute(
                    select(runs)
                    .where(
                        runs.c.run_id == job_id,
                        runs.c.user_id == owner_id,
                        runs.c.session_id == parent_session_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if run is None:
                return False
            run_data = copy.deepcopy(OBJECT_DICT_ADAPTER.validate_python(run["run_data"] or {}))
            run_data.update(
                {
                    "status": "CANCELLED",
                    "content": run_data.get("content") or "work was cancelled",
                    "cancellation_stage": "executing",
                }
            )
            _ = session.execute(
                runs.update()
                .where(runs.c.run_id == job_id)
                .values(status="CANCELLED", run_data=run_data, updated_at=now)
            )
            _ = session.execute(
                jobs.update()
                .where(jobs.c.id == job_id, jobs.c.status == status)
                .values(
                    status="cancelled",
                    locked_by=None,
                    locked_at=None,
                    completed_at=now,
                    updated_at=now,
                )
            )
            self._release_terminal_intent(session, intents, job_id, "cancelled", now)
        return True

    def _settle_unclaimed_terminal(
        self,
        job_id: str,
        status: str,
        error: str | None,
        *,
        required_status: str,
        worker_id: str | None = None,
    ) -> bool:
        if status not in {"completed", "cancelled", "failed", "paused"}:
            return False
        jobs = self._get_table(table_type="jobs")
        intents = self._work_intent_table()
        if jobs is None:
            return False
        now = int(time.time())
        with SqlAlchemySession(self.db_engine) as session, session.begin():
            predicate = [jobs.c.id == job_id, jobs.c.status == required_status]
            if worker_id is not None:
                predicate.append(jobs.c.locked_by == worker_id)
            job = session.execute(select(jobs).where(*predicate).with_for_update()).first()
            if job is None:
                return False
            _ = session.execute(
                select(intents.c.logical_work_id)
                .where(intents.c.job_id == job_id)
                .with_for_update()
            ).first()
            _ = session.execute(
                jobs.update()
                .where(jobs.c.id == job_id)
                .values(
                    status=status,
                    error=error,
                    locked_by=None,
                    locked_at=None,
                    completed_at=now,
                    updated_at=now,
                )
            )
            self._release_terminal_intent(session, intents, job_id, status, now)
        return True

    @override
    def settle_paused_job(self, job_id: str, status: str, error: str | None = None) -> bool:
        """Settle paused work while releasing failed or cancelled intent scope."""
        if status not in {"completed", "cancelled", "failed"}:
            return False
        return self._settle_unclaimed_terminal(job_id, status, error, required_status="paused")

    @override
    def settle_swept_job(
        self,
        job_id: str,
        worker_id: str,
        status: str,
        error: str | None = None,
    ) -> bool:
        """Settle exhausted work while releasing failed or cancelled intent scope."""
        return self._settle_unclaimed_terminal(
            job_id,
            status,
            error,
            required_status="running",
            worker_id=worker_id,
        )

    @override
    def upsert_session(
        self, session: Session, deserialize: bool | None = True
    ) -> Session | dict[str, object] | None:
        """Preserve fenced company and parent binding fields on Agno upsert."""
        if not isinstance(session, AgentSession | WorkflowSession) or not self.table_exists(
            self.work_intent_table_name
        ):
            return super().upsert_session(session, deserialize=deserialize)
        protected = copy.deepcopy(session)
        with self.db_engine.connect() as lock_connection:
            _ = lock_connection.execute(
                text("SELECT pg_advisory_lock(hashtextextended(:session_id, 0))"),
                {"session_id": session.session_id},
            )
            sessions = self._get_table(table_type="sessions")
            intents = self._work_intent_table()
            if sessions is None:
                message = "native session table is unavailable"
                raise RuntimeError(message)
            existing: object = lock_connection.execute(
                select(sessions.c.session_data).where(sessions.c.session_id == session.session_id)
            ).scalar_one_or_none()
            incoming = JSON_OBJECT_ADAPTER.validate_python(
                copy.deepcopy(session.session_data or {})
            )
            if isinstance(session, WorkflowSession) and existing:
                existing_data = JSON_OBJECT_ADAPTER.validate_python(existing)
                existing_state = JSON_OBJECT_ADAPTER.validate_python(
                    existing_data.get("session_state") or {}
                )
                retained = existing_state.get("company")
                if retained:
                    incoming_state = JSON_OBJECT_ADAPTER.validate_python(
                        incoming.get("session_state") or {}
                    )
                    incoming_state["company"] = retained
                    incoming["session_state"] = incoming_state
            if isinstance(session, AgentSession) and session.user_id:
                binding: object = lock_connection.execute(
                    select(intents.c.parent_binding)
                    .where(
                        intents.c.owner_id == session.user_id,
                        intents.c.parent_session_id == session.session_id,
                        intents.c.parent_binding.is_not(None),
                    )
                    .order_by(intents.c.updated_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if binding is not None:
                    binding_data = JSON_OBJECT_ADAPTER.validate_python(binding)
                    state = JSON_OBJECT_ADAPTER.validate_python(incoming.get("session_state") or {})
                    state.update({key: binding_data[key] for key in PARENT_BINDING_KEYS})
                    incoming["session_state"] = state
            protected.session_data = incoming
            try:
                return super().upsert_session(protected, deserialize=deserialize)
            finally:
                _ = lock_connection.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:session_id, 0))"),
                    {"session_id": session.session_id},
                )
