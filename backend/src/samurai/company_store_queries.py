"""SQL projections used by canonical company persistence."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import TextClause

SCHEMA_NAME: Final = re.compile(r"^[a-z_][a-z0-9_]*$")
INSERT_COMPANY: Final = (
    'INSERT INTO "{schema}".samurai_companies '
    "(company_id, workspace_id, canonical_state, state_sha256, current_revision, "
    "legacy_owner_id, legacy_session_id, legacy_parent_session_id, created_at, updated_at) "
    "VALUES (:company_id, :workspace_id, CAST(:state AS jsonb), :state_sha256, 0, "
    ":actor_id, :child_session_id, :parent_session_id, :timestamp, :timestamp)"
)
INSERT_BINDING: Final = (
    'INSERT INTO "{schema}".samurai_company_actor_bindings '
    "(company_id, user_id, parent_session_id, child_session_id, created_at, updated_at) "
    "VALUES (:company_id, :actor_id, :parent_session_id, :child_session_id, "
    ":timestamp, :timestamp)"
)
READ_ACCESS: Final = (
    "SELECT c.canonical_state, c.workspace_id, m.role, m.authorization_epoch, b.parent_session_id, "
    'b.child_session_id FROM "{schema}".samurai_company_actor_bindings b '
    'JOIN "{schema}".samurai_companies c ON c.company_id = b.company_id '
    'JOIN "{schema}".samurai_workspace_memberships m ON m.workspace_id = c.workspace_id '
    "AND m.user_id = b.user_id WHERE b.user_id = :actor_id "
    "AND b.parent_session_id = :parent_session_id AND m.active"
)
READ_ACCESS_BY_CHILD: Final = READ_ACCESS.replace(
    "b.parent_session_id = :parent_session_id",
    "b.child_session_id = :child_session_id",
)
READ_COMPANY_WORKSPACE: Final = (
    'SELECT workspace_id FROM "{schema}".samurai_companies WHERE company_id = :company_id'
)
READ_COMPANY_FOR_UPDATE: Final = (
    "SELECT workspace_id, current_revision, legacy_owner_id, legacy_session_id, created_at "
    'FROM "{schema}".samurai_companies WHERE company_id = :company_id FOR UPDATE'
)
READ_MEMBERSHIP: Final = (
    'SELECT role, authorization_epoch FROM "{schema}".samurai_workspace_memberships '
    "WHERE workspace_id = :workspace_id AND user_id = :actor_id AND active"
)
READ_BINDING: Final = (
    'SELECT 1 FROM "{schema}".samurai_company_actor_bindings '
    "WHERE company_id = :company_id AND user_id = :actor_id "
    "AND parent_session_id = :parent_session_id AND child_session_id = :child_session_id"
)
UPDATE_COMPANY: Final = (
    'UPDATE "{schema}".samurai_companies SET canonical_state = CAST(:state AS jsonb), '
    "state_sha256 = :state_sha256, current_revision = :revision, updated_at = :updated_at "
    "WHERE company_id = :company_id"
)


def valid_schema(schema: str) -> bool:
    """Return whether a schema is safe for fixed SQL interpolation."""
    return SCHEMA_NAME.fullmatch(schema) is not None


def render_company_sql(source: str, schema: str) -> TextClause:
    """Render a fixed query only for a validated PostgreSQL schema identifier."""
    if not valid_schema(schema):
        message = "invalid company schema"
        raise ValueError(message)
    return text(source.format(schema=schema))
