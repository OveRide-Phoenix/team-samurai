"""Transactional workspace membership and shared-company directory."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, NoReturn, cast, final
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import HTTPException

from samurai import workspace_directory_queries as queries
from samurai.company_store import CompanyStore
from samurai.company_store_contracts import (
    ActorBinding,
    CompanyAccess,
    CompanyReservation,
    CompanyStoreError,
    CompanyStoreIssue,
    WorkspaceRole,
)
from samurai.contracts import CompanyState, FounderTruth, IntakeArtifact, ResearchArtifact
from samurai.frameworks import load_framework_catalog
from samurai.parent import CompanyStateSummary
from samurai.schema_contracts import canonical_state_hash
from samurai.workspace_directory_contracts import (
    BindingRow,
    CompanyRecord,
    CompanySnapshot,
    MemberRecord,
    WorkspaceRecord,
)
from samurai.workspace_membership import WorkspaceMembership

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.engine import Connection
    from sqlalchemy.sql.elements import TextClause

    from samurai.execution_state import SamuraiPostgresDb


@final
class WorkspaceDirectory:
    """Own workspace membership transactions and company discovery."""

    def __init__(self, database: SamuraiPostgresDb) -> None:
        """Use the canonical schema and CompanyStore owned by the app."""
        self._engine = database.db_engine
        self._schema = database.db_schema
        self._store = CompanyStore(self._engine, schema=self._schema)
        self._members = WorkspaceMembership(self._engine, self._schema)

    def create_workspace(self, actor_id: str, display_name: str) -> WorkspaceRecord:
        """Create a workspace with the actor as owner."""
        return self._members.create(actor_id, display_name)

    def list_workspaces(self, actor_id: str) -> list[WorkspaceRecord]:
        """List workspaces visible to the actor."""
        return self._members.list(actor_id)

    def put_member(
        self, actor_id: str, workspace_id: UUID, user_id: str, role: WorkspaceRole
    ) -> MemberRecord:
        """Create or update an active workspace member."""
        return self._members.put(actor_id, workspace_id, user_id, role)

    def delete_member(self, actor_id: str, workspace_id: UUID, user_id: str) -> None:
        """Deactivate a workspace member."""
        self._members.delete(actor_id, workspace_id, user_id)

    def create_company(
        self, actor_id: str, workspace_id: UUID, idempotency_key: UUID | None = None
    ) -> CompanyRecord:
        """Reserve a canonical company before brief collection begins."""
        parent_session_id = (
            str(uuid4())
            if idempotency_key is None
            else str(uuid5(NAMESPACE_URL, f"samurai-company:{actor_id}:{idempotency_key}:parent"))
        )
        child_session_id = (
            str(uuid4())
            if idempotency_key is None
            else str(uuid5(NAMESPACE_URL, f"samurai-company:{actor_id}:{idempotency_key}:child"))
        )
        access = self._store_call(
            lambda: self._store.reserve(
                CompanyReservation(
                    workspace_id=workspace_id,
                    actor_id=actor_id,
                    parent_session_id=parent_session_id,
                    child_session_id=child_session_id,
                    created_at=datetime.now(UTC),
                    idempotency_key=idempotency_key,
                )
            )
        )
        return self._company_record(access, include_snapshot=False)

    def list_companies(self, actor_id: str, workspace_id: UUID) -> list[CompanyRecord]:
        """List company metadata without mutating or exposing another actor's binding."""
        with self._engine.connect() as connection:
            _ = self._members.require_member(connection, workspace_id, actor_id)
            rows = connection.execute(
                self._sql(queries.LIST_COMPANIES),
                {"workspace_id": workspace_id, "actor_id": actor_id},
            ).mappings()
            return [CompanyRecord.model_validate(row) for row in rows]

    def open_company(self, actor_id: str, workspace_id: UUID, company_id: UUID) -> CompanyRecord:
        """Bind the actor once and return its canonical company snapshot."""
        with self._engine.connect() as connection:
            _ = self._members.require_member(connection, workspace_id, actor_id)
            actual_workspace = cast(
                "UUID | None",
                connection.execute(
                    self._sql(queries.READ_COMPANY_WORKSPACE),
                    {"company_id": company_id},
                ).scalar_one_or_none(),
            )
            if actual_workspace != workspace_id:
                raise HTTPException(status_code=404, detail="company not found in workspace")
            binding = self._binding(connection, company_id, actor_id)
        if binding is None:
            binding = self._bind_actor(actor_id, company_id)
        access = self._store.read_for_actor(actor_id, binding.parent_session_id)
        if access is None or access.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="company snapshot not found")
        return self._company_record(access, include_snapshot=True)

    def _bind_actor(self, actor_id: str, company_id: UUID) -> BindingRow:
        try:
            access = self._store.bind_actor(
                ActorBinding(
                    company_id=company_id,
                    actor_id=actor_id,
                    parent_session_id=str(uuid4()),
                    child_session_id=str(uuid4()),
                )
            )
            return BindingRow(
                current_revision=access.state.current_revision,
                state_sha256=canonical_state_hash(access.state),
                created_at=int(access.state.context.created_at.timestamp()),
                parent_session_id=access.parent_session_id,
                child_session_id=access.child_session_id,
            )
        except CompanyStoreError as error:
            if error.issue is not CompanyStoreIssue.BINDING_CONFLICT:
                self._raise_store(error)
        with self._engine.connect() as connection:
            binding = self._binding(connection, company_id, actor_id)
        if binding is None:
            raise HTTPException(status_code=409, detail="company session binding conflict")
        return binding

    def _binding(
        self, connection: Connection, company_id: UUID, actor_id: str
    ) -> BindingRow | None:
        row = (
            connection.execute(
                self._sql(queries.READ_BINDING),
                {"company_id": company_id, "actor_id": actor_id},
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else BindingRow.model_validate(row)

    def _company_record(self, access: CompanyAccess, *, include_snapshot: bool) -> CompanyRecord:
        return CompanyRecord(
            workspace_id=access.workspace_id,
            company_id=access.state.context.company_id,
            current_revision=access.state.current_revision,
            state_sha256=canonical_state_hash(access.state),
            created_at=int(access.state.context.created_at.timestamp()),
            parent_session_id=access.parent_session_id,
            child_session_id=access.child_session_id,
            snapshot=self._public_snapshot(access.state) if include_snapshot else None,
        )

    @staticmethod
    def _public_snapshot(state: CompanyState) -> CompanySnapshot:
        framework_metadata = load_framework_catalog().metadata
        intake = next(
            (
                artifact.payload
                for artifact in reversed(state.artifacts)
                if isinstance(artifact.payload, IntakeArtifact)
            ),
            None,
        )
        brief = intake.brief if intake is not None else None
        founder_truth = intake.founder_truth if intake is not None else FounderTruth()
        retained_frameworks = intake.frameworks if intake is not None else ()
        conflicts = tuple(
            conflict
            for artifact in state.artifacts
            if isinstance(artifact.payload, ResearchArtifact)
            for conflict in artifact.payload.conflicts
        )
        findings = tuple(
            finding for artifact in state.artifacts for finding in artifact.verification_findings
        )[-20:]
        sources = tuple(source for artifact in state.artifacts for source in artifact.sources)[-20:]
        next_decision = founder_truth.next_decision
        return CompanySnapshot(
            summary=CompanyStateSummary(
                company_id=state.context.company_id,
                revision=state.current_revision,
                artifact_count=len(state.artifacts),
                status="active",
                brief=brief,
                sources=sources,
                evidence_conflicts=conflicts,
                verification_findings=findings,
                next_decision=next_decision,
                founder_truth=founder_truth,
                frameworks=retained_frameworks or framework_metadata,
            ),
            artifacts=state.artifacts,
        )

    def _store_call(self, operation: Callable[[], CompanyAccess]) -> CompanyAccess:
        try:
            return operation()
        except CompanyStoreError as error:
            self._raise_store(error)

    @staticmethod
    def _raise_store(error: CompanyStoreError) -> NoReturn:
        code = 403 if error.issue is CompanyStoreIssue.PERMISSION_DENIED else 409
        if error.issue is CompanyStoreIssue.NOT_FOUND:
            code = 404
        raise HTTPException(status_code=code, detail=str(error)) from error

    @staticmethod
    def _now() -> int:
        return int(datetime.now(UTC).timestamp())

    def _sql(self, source: str) -> TextClause:
        return queries.render(source, self._schema)
