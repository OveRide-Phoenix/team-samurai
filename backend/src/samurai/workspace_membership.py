"""Transactional workspace membership mutations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast, final
from uuid import UUID, uuid4

from fastapi import HTTPException

from samurai import workspace_directory_queries as queries
from samurai.company_store_contracts import WorkspaceRole
from samurai.quota import QuotaResource, WorkspaceQuota, WorkspaceQuotaExceededError
from samurai.workspace_directory_contracts import MemberRecord, MembershipRow, WorkspaceRecord

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine


@final
class WorkspaceMembership:
    """Serialize owner and member changes for one app schema."""

    def __init__(self, engine: Engine, schema: str) -> None:
        """Use the app-owned engine and schema."""
        self._engine = engine
        self._schema = schema
        self._quota = WorkspaceQuota(schema)

    def create(self, actor_id: str, display_name: str) -> WorkspaceRecord:
        """Create a shared workspace and first owner."""
        workspace_id = uuid4()
        timestamp = self._now()
        with self._engine.begin() as connection:
            _ = connection.execute(
                queries.render(queries.CREATE_WORKSPACE, self._schema),
                {
                    "workspace_id": workspace_id,
                    "display_name": display_name,
                    "timestamp": timestamp,
                },
            )
            _ = connection.execute(
                queries.render(queries.CREATE_OWNER, self._schema),
                {"workspace_id": workspace_id, "actor_id": actor_id, "timestamp": timestamp},
            )
            self._quota.create(connection, workspace_id, timestamp)
        return WorkspaceRecord(
            workspace_id=workspace_id,
            display_name=display_name,
            role=WorkspaceRole.OWNER,
            authorization_epoch=1,
        )

    def list(self, actor_id: str) -> list[WorkspaceRecord]:
        """List active workspace memberships."""
        with self._engine.connect() as connection:
            rows = connection.execute(
                queries.render(queries.LIST_WORKSPACES, self._schema), {"actor_id": actor_id}
            ).mappings()
            return [WorkspaceRecord.model_validate(row) for row in rows]

    def put(
        self, actor_id: str, workspace_id: UUID, user_id: str, role: WorkspaceRole
    ) -> MemberRecord:
        """Create, reactivate, or change a member as an owner."""
        timestamp = self._now()
        with self._engine.begin() as connection:
            self._quota.lock(connection, workspace_id)
            self.require_owner(connection, workspace_id, actor_id)
            raw_target = (
                connection.execute(
                    queries.render(queries.LOCK_MEMBERSHIP, self._schema),
                    {"workspace_id": workspace_id, "user_id": user_id},
                )
                .mappings()
                .one_or_none()
            )
            target = None if raw_target is None else MembershipRow.model_validate(raw_target)
            if target is not None and target.active and target.role is role:
                epoch = target.authorization_epoch
            else:
                if target is None or not target.active:
                    try:
                        self._quota.reserve(connection, workspace_id, QuotaResource.MEMBER)
                    except WorkspaceQuotaExceededError as error:
                        raise HTTPException(status_code=409, detail=str(error)) from error
                if target is not None and target.active and target.role is WorkspaceRole.OWNER:
                    self._protect_last_owner(connection, workspace_id)
                epoch = 1 if target is None else target.authorization_epoch + 1
                statement = queries.INSERT_MEMBER if target is None else queries.UPDATE_MEMBER
                _ = connection.execute(
                    queries.render(statement, self._schema),
                    {
                        "workspace_id": workspace_id,
                        "user_id": user_id,
                        "role": role,
                        "epoch": epoch,
                        "timestamp": timestamp,
                    },
                )
        return MemberRecord(
            workspace_id=workspace_id,
            user_id=user_id,
            role=role,
            authorization_epoch=epoch,
        )

    def delete(self, actor_id: str, workspace_id: UUID, user_id: str) -> None:
        """Deactivate a member while advancing its authorization epoch."""
        timestamp = self._now()
        with self._engine.begin() as connection:
            self._quota.lock(connection, workspace_id)
            self.require_owner(connection, workspace_id, actor_id)
            role = cast(
                "str | None",
                connection.execute(
                    queries.render(queries.LOCK_ACTIVE_MEMBER_ROLE, self._schema),
                    {"workspace_id": workspace_id, "user_id": user_id},
                ).scalar_one_or_none(),
            )
            if role is None:
                raise HTTPException(status_code=404, detail="active workspace member not found")
            if WorkspaceRole(str(role)) is WorkspaceRole.OWNER:
                self._protect_last_owner(connection, workspace_id)
            _ = connection.execute(
                queries.render(queries.DEACTIVATE_MEMBER, self._schema),
                {"workspace_id": workspace_id, "user_id": user_id, "timestamp": timestamp},
            )
            self._quota.release(connection, workspace_id, QuotaResource.MEMBER)

    def require_owner(self, connection: Connection, workspace_id: UUID, actor_id: str) -> None:
        """Lock a workspace and require owner authority."""
        _ = connection.execute(
            queries.render(queries.LOCK_WORKSPACE, self._schema), {"workspace_id": workspace_id}
        ).one_or_none()
        if self.require_member(connection, workspace_id, actor_id) is not WorkspaceRole.OWNER:
            raise HTTPException(status_code=403, detail="workspace owner role required")

    def require_member(
        self, connection: Connection, workspace_id: UUID, actor_id: str
    ) -> WorkspaceRole:
        """Return the actor's active workspace role."""
        role = cast(
            "str | None",
            connection.execute(
                queries.render(queries.READ_ACTIVE_ROLE, self._schema),
                {"workspace_id": workspace_id, "actor_id": actor_id},
            ).scalar_one_or_none(),
        )
        if role is None:
            raise HTTPException(status_code=403, detail="active workspace membership required")
        return WorkspaceRole(str(role))

    def _protect_last_owner(self, connection: Connection, workspace_id: UUID) -> None:
        owners = cast(
            "int",
            connection.execute(
                queries.render(queries.COUNT_OWNERS, self._schema), {"workspace_id": workspace_id}
            ).scalar_one(),
        )
        if owners <= 1:
            raise HTTPException(status_code=409, detail="workspace must retain an owner")

    @staticmethod
    def _now() -> int:
        return int(datetime.now(UTC).timestamp())
