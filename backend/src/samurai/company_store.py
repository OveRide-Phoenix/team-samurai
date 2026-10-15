"""App-owned canonical company persistence over founder-platform rows."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Final

from sqlalchemy import Engine, Table, select
from sqlalchemy.exc import IntegrityError

from samurai import company_store_queries as queries
from samurai.company_store_contracts import (
    ActorBinding,
    CompanyAcceptance,
    CompanyAcceptanceRow,
    CompanyAccess,
    CompanyAccessRow,
    CompanyReservation,
    CompanyStoreError,
    CompanyStoreIssue,
    MembershipRow,
    WorkspaceRole,
    WorkspaceRow,
)
from samurai.contracts import CompanyState, create_company_state
from samurai.knowledge import KnowledgeAcceptance, KnowledgeReferenceGuard
from samurai.quota import QuotaResource, WorkspaceQuota, WorkspaceQuotaExceededError
from samurai.schema_contracts import canonical_state_hash

_READ_CANONICAL_STATE: Final = (
    'SELECT canonical_state FROM "{schema}".samurai_companies WHERE company_id=:company_id'
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.engine import Connection
    from sqlalchemy.orm import Session as SqlAlchemySession


class CompanyStore:
    """Read and mutate the single canonical company store."""

    def __init__(self, engine: Engine, *, schema: str) -> None:
        """Bind canonical persistence to one validated application schema."""
        if not queries.valid_schema(schema):
            raise CompanyStoreError(CompanyStoreIssue.NOT_FOUND)
        self._engine: Engine = engine
        self._schema: str = schema
        self._quota: WorkspaceQuota = WorkspaceQuota(schema)

    def reserve(self, reservation: CompanyReservation) -> CompanyAccess:
        """Create one company for an active owner or editor membership."""
        with self._engine.begin() as connection:
            _ = self._membership(
                connection,
                reservation.workspace_id,
                reservation.actor_id,
                writable=True,
                lock=False,
            )
            self._quota.lock(connection, reservation.workspace_id)
            membership = self._membership(
                connection,
                reservation.workspace_id,
                reservation.actor_id,
                writable=True,
            )
            existing_row = None
            if reservation.idempotency_key is not None:
                existing_row = (
                    connection.execute(
                        queries.render_company_sql(queries.READ_ACCESS, self._schema),
                        {
                            "actor_id": reservation.actor_id,
                            "parent_session_id": reservation.parent_session_id,
                        },
                    )
                    .mappings()
                    .one_or_none()
                )
            if existing_row is not None:
                existing = CompanyAccessRow.model_validate(existing_row)
                if existing.workspace_id != reservation.workspace_id:
                    raise CompanyStoreError(CompanyStoreIssue.CHANGED_RESERVATION)
                return CompanyAccess(
                    state=CompanyState.model_validate(existing.canonical_state),
                    workspace_id=existing.workspace_id,
                    role=membership.role,
                    authorization_epoch=membership.authorization_epoch,
                    parent_session_id=existing.parent_session_id,
                    child_session_id=existing.child_session_id,
                )
            try:
                self._quota.reserve(connection, reservation.workspace_id, QuotaResource.COMPANY)
            except WorkspaceQuotaExceededError as error:
                raise CompanyStoreError(CompanyStoreIssue.WORKSPACE_QUOTA) from error
            state = create_company_state(
                reservation.parent_session_id,
                created_at=reservation.created_at,
                workspace_id=reservation.workspace_id,
            )
            timestamp = int(reservation.created_at.timestamp())
            parameters = {
                "company_id": state.context.company_id,
                "workspace_id": reservation.workspace_id,
                "state": json.dumps(state.model_dump(mode="json"), separators=(",", ":")),
                "state_sha256": canonical_state_hash(state),
                "actor_id": reservation.actor_id,
                "parent_session_id": reservation.parent_session_id,
                "child_session_id": reservation.child_session_id,
                "timestamp": timestamp,
            }
            try:
                _ = connection.execute(
                    queries.render_company_sql(queries.INSERT_COMPANY, self._schema),
                    parameters,
                )
                _ = connection.execute(
                    queries.render_company_sql(queries.INSERT_BINDING, self._schema),
                    parameters,
                )
            except IntegrityError as error:
                raise CompanyStoreError(CompanyStoreIssue.BINDING_CONFLICT) from error
        return CompanyAccess(
            state=state,
            workspace_id=reservation.workspace_id,
            role=membership.role,
            authorization_epoch=membership.authorization_epoch,
            parent_session_id=reservation.parent_session_id,
            child_session_id=reservation.child_session_id,
        )

    def bind_actor(self, binding: ActorBinding) -> CompanyAccess:
        """Attach one active workspace member's isolated sessions to a company."""
        with self._engine.begin() as connection:
            workspace = (
                connection.execute(
                    queries.render_company_sql(queries.READ_COMPANY_WORKSPACE, self._schema),
                    {"company_id": binding.company_id},
                )
                .mappings()
                .one_or_none()
            )
            if workspace is None:
                raise CompanyStoreError(CompanyStoreIssue.NOT_FOUND)
            workspace_id = WorkspaceRow.model_validate(workspace).workspace_id
            _ = self._membership(connection, workspace_id, binding.actor_id, writable=False)
            try:
                _ = connection.execute(
                    queries.render_company_sql(queries.INSERT_BINDING, self._schema),
                    {
                        "company_id": binding.company_id,
                        "actor_id": binding.actor_id,
                        "parent_session_id": binding.parent_session_id,
                        "child_session_id": binding.child_session_id,
                        "timestamp": int(time.time()),
                    },
                )
            except IntegrityError as error:
                raise CompanyStoreError(CompanyStoreIssue.BINDING_CONFLICT) from error
        access = self.read_for_actor(binding.actor_id, binding.parent_session_id)
        if access is None:
            raise CompanyStoreError(CompanyStoreIssue.NOT_FOUND)
        return access

    def read_for_actor(self, actor_id: str, parent_session_id: str) -> CompanyAccess | None:
        """Read canonical state through an active actor and parent binding."""
        return self._read_access(
            queries.READ_ACCESS,
            {"actor_id": actor_id, "parent_session_id": parent_session_id},
        )

    def read_for_child(self, actor_id: str, child_session_id: str) -> CompanyAccess | None:
        """Read canonical state through an active actor and child binding."""
        return self._read_access(
            queries.READ_ACCESS_BY_CHILD,
            {"actor_id": actor_id, "child_session_id": child_session_id},
        )

    def _read_access(self, query: str, parameters: dict[str, str]) -> CompanyAccess | None:
        statement = queries.render_company_sql(query, self._schema)
        with self._engine.connect() as connection:
            row = connection.execute(statement, parameters).mappings().one_or_none()
        if row is None:
            return None
        parsed = CompanyAccessRow.model_validate(row)
        return CompanyAccess(
            state=CompanyState.model_validate(parsed.canonical_state),
            workspace_id=parsed.workspace_id,
            role=parsed.role,
            authorization_epoch=parsed.authorization_epoch,
            parent_session_id=parsed.parent_session_id,
            child_session_id=parsed.child_session_id,
        )

    def accept_in_transaction(
        self,
        session: SqlAlchemySession,
        sessions: Table,
        acceptance: CompanyAcceptance,
    ) -> CompanyState:
        """Accept one revision inside the caller's locked job transaction."""
        self._quota.lock(session, acceptance.workspace_id)
        company = (
            session.execute(
                queries.render_company_sql(queries.READ_COMPANY_FOR_UPDATE, self._schema),
                {"company_id": acceptance.state.context.company_id},
            )
            .mappings()
            .one_or_none()
        )
        if company is None:
            raise CompanyStoreError(CompanyStoreIssue.NOT_FOUND)
        canonical = CompanyAcceptanceRow.model_validate(company)
        if canonical.workspace_id != acceptance.workspace_id:
            raise CompanyStoreError(CompanyStoreIssue.PERMISSION_DENIED)
        membership = (
            session.execute(
                queries.render_company_sql(queries.READ_MEMBERSHIP + " FOR UPDATE", self._schema),
                {"workspace_id": acceptance.workspace_id, "actor_id": acceptance.actor_id},
            )
            .mappings()
            .one_or_none()
        )
        if membership is None:
            raise CompanyStoreError(CompanyStoreIssue.PERMISSION_DENIED)
        authorized = MembershipRow.model_validate(membership)
        if authorized.role is WorkspaceRole.VIEWER:
            raise CompanyStoreError(CompanyStoreIssue.PERMISSION_DENIED)
        if authorized.authorization_epoch != acceptance.authorization_epoch:
            raise CompanyStoreError(CompanyStoreIssue.STALE_AUTHORIZATION)
        if canonical.current_revision != acceptance.expected_revision:
            raise CompanyStoreError(CompanyStoreIssue.STALE_REVISION)
        binding = session.execute(
            queries.render_company_sql(queries.READ_BINDING, self._schema),
            {
                "company_id": acceptance.state.context.company_id,
                "actor_id": acceptance.actor_id,
                "parent_session_id": acceptance.parent_session_id,
                "child_session_id": acceptance.child_session_id,
            },
        ).scalar_one_or_none()
        if binding is None:
            raise CompanyStoreError(CompanyStoreIssue.NOT_FOUND)
        canonical_state = CompanyState.model_validate(
            session.execute(
                queries.render_company_sql(
                    _READ_CANONICAL_STATE,
                    self._schema,
                ),
                {"company_id": acceptance.state.context.company_id},
            ).scalar_one()
        )
        new_references = tuple(
            reference
            for artifact in acceptance.state.artifacts
            if artifact.revision > acceptance.expected_revision
            for reference in artifact.knowledge_references
        )
        KnowledgeReferenceGuard(self._schema).validate(
            session,
            KnowledgeAcceptance(
                workspace_id=acceptance.workspace_id,
                company_id=acceptance.state.context.company_id,
                canonical_state=canonical_state,
                references=new_references,
            ),
        )
        if (
            acceptance.state.context.workspace_id is not None
            and acceptance.state.context.workspace_id != acceptance.workspace_id
        ):
            raise CompanyStoreError(CompanyStoreIssue.PERMISSION_DENIED)
        mirror = (
            session.execute(
                select(sessions)
                .where(
                    sessions.c.session_id == canonical.legacy_session_id,
                    sessions.c.user_id == canonical.legacy_owner_id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if mirror is None:
            raise CompanyStoreError(CompanyStoreIssue.MIRROR_MISSING)
        session_data = dict(mirror["session_data"] or {})
        session_state = dict(session_data.get("session_state") or {})
        payload = acceptance.state.model_dump(mode="json")
        session_state["company"] = payload
        session_data["session_state"] = session_state
        timestamp = max(int(time.time()), canonical.created_at)
        _ = session.execute(
            queries.render_company_sql(queries.UPDATE_COMPANY, self._schema),
            {
                "state": json.dumps(payload, separators=(",", ":")),
                "state_sha256": canonical_state_hash(acceptance.state),
                "revision": acceptance.state.current_revision,
                "updated_at": timestamp,
                "company_id": acceptance.state.context.company_id,
            },
        )
        _ = session.execute(
            sessions.update()
            .where(sessions.c.session_id == canonical.legacy_session_id)
            .values(session_data=session_data, updated_at=timestamp)
        )
        return acceptance.state

    def _membership(
        self,
        connection: Connection,
        workspace_id: UUID,
        actor_id: str,
        *,
        writable: bool,
        lock: bool = True,
    ) -> MembershipRow:
        statement = queries.READ_MEMBERSHIP + (" FOR SHARE" if lock else "")
        row = (
            connection.execute(
                queries.render_company_sql(statement, self._schema),
                {"workspace_id": workspace_id, "actor_id": actor_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise CompanyStoreError(CompanyStoreIssue.PERMISSION_DENIED)
        membership = MembershipRow.model_validate(row)
        if writable and membership.role is WorkspaceRole.VIEWER:
            raise CompanyStoreError(CompanyStoreIssue.PERMISSION_DENIED)
        return membership
