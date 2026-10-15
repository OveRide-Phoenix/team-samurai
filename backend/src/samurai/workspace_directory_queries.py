"""PostgreSQL queries for the workspace directory."""

from typing import TYPE_CHECKING, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import TextClause

CREATE_WORKSPACE: Final = """INSERT INTO "{schema}".samurai_workspaces
(workspace_id, workspace_kind, display_name, created_at, updated_at)
VALUES (:workspace_id, 'shared', :display_name, :timestamp, :timestamp)"""
CREATE_OWNER: Final = """INSERT INTO "{schema}".samurai_workspace_memberships
(workspace_id, user_id, role, authorization_epoch, active, created_at, updated_at)
VALUES (:workspace_id, :actor_id, 'owner', 1, true, :timestamp, :timestamp)"""
LIST_WORKSPACES: Final = """SELECT w.workspace_id, w.display_name, m.role,
m.authorization_epoch FROM "{schema}".samurai_workspaces w
JOIN "{schema}".samurai_workspace_memberships m ON m.workspace_id = w.workspace_id
WHERE m.user_id = :actor_id AND m.active ORDER BY w.created_at, w.workspace_id"""
LOCK_MEMBERSHIP: Final = """SELECT role, authorization_epoch, active
FROM "{schema}".samurai_workspace_memberships
WHERE workspace_id = :workspace_id AND user_id = :user_id FOR UPDATE"""
INSERT_MEMBER: Final = """INSERT INTO "{schema}".samurai_workspace_memberships
(workspace_id, user_id, role, authorization_epoch, active, created_at, updated_at)
VALUES (:workspace_id, :user_id, :role, 1, true, :timestamp, :timestamp)"""
UPDATE_MEMBER: Final = """UPDATE "{schema}".samurai_workspace_memberships
SET role = :role, authorization_epoch = :epoch, active = true, updated_at = :timestamp
WHERE workspace_id = :workspace_id AND user_id = :user_id"""
LOCK_ACTIVE_MEMBER_ROLE: Final = """SELECT role
FROM "{schema}".samurai_workspace_memberships
WHERE workspace_id = :workspace_id AND user_id = :user_id AND active FOR UPDATE"""
DEACTIVATE_MEMBER: Final = """UPDATE "{schema}".samurai_workspace_memberships
SET active = false, authorization_epoch = authorization_epoch + 1, updated_at = :timestamp
WHERE workspace_id = :workspace_id AND user_id = :user_id"""
LIST_COMPANIES: Final = """SELECT c.workspace_id, c.company_id, c.current_revision, c.state_sha256,
c.created_at, b.parent_session_id, b.child_session_id
FROM "{schema}".samurai_companies c
LEFT JOIN "{schema}".samurai_company_actor_bindings b
ON b.company_id = c.company_id AND b.user_id = :actor_id
WHERE c.workspace_id = :workspace_id ORDER BY c.created_at, c.company_id"""
READ_COMPANY_WORKSPACE: Final = """SELECT workspace_id FROM "{schema}".samurai_companies
WHERE company_id = :company_id"""
READ_BINDING: Final = """SELECT c.current_revision, c.state_sha256, c.created_at,
b.parent_session_id, b.child_session_id FROM "{schema}".samurai_companies c
JOIN "{schema}".samurai_company_actor_bindings b ON b.company_id = c.company_id
WHERE c.company_id = :company_id AND b.user_id = :actor_id"""
LOCK_WORKSPACE: Final = """SELECT workspace_id FROM "{schema}".samurai_workspaces
WHERE workspace_id = :workspace_id FOR UPDATE"""
READ_ACTIVE_ROLE: Final = """SELECT role FROM "{schema}".samurai_workspace_memberships
WHERE workspace_id = :workspace_id AND user_id = :actor_id AND active"""
COUNT_OWNERS: Final = """SELECT count(*) FROM "{schema}".samurai_workspace_memberships
WHERE workspace_id = :workspace_id AND active AND role = 'owner'"""


def render(source: str, schema: str) -> TextClause:
    """Bind the app-owned schema to a fixed query."""
    return text(source.format(schema=schema))
