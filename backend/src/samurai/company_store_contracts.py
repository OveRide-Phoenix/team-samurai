"""Typed company persistence requests, results, and domain failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, override
from uuid import UUID  # noqa: TC003 - Pydantic resolves database UUID fields at runtime.

from pydantic import BaseModel, JsonValue

if TYPE_CHECKING:
    from datetime import datetime

    from samurai.contracts import CompanyState


@unique
class WorkspaceRole(StrEnum):
    """Workspace roles recognized by canonical company persistence."""

    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


@unique
class CompanyStoreIssue(StrEnum):
    """Stable rejection reasons from canonical company persistence."""

    NOT_FOUND = "company binding is missing"
    PERMISSION_DENIED = "active workspace editor membership is required"
    STALE_AUTHORIZATION = "workspace authorization changed before acceptance"
    STALE_REVISION = "canonical company revision changed before acceptance"
    BINDING_CONFLICT = "actor session is already bound to another company"
    MIRROR_MISSING = "legacy owner session is missing"
    WORKSPACE_QUOTA = "workspace quota exceeded"
    CHANGED_RESERVATION = "idempotency key was reused for another workspace"


@dataclass(slots=True)
class CompanyStoreError(Exception):
    """Reject an unsafe company-store operation."""

    issue: CompanyStoreIssue

    @override
    def __str__(self) -> str:
        return self.issue.value


@dataclass(frozen=True, slots=True)
class CompanyReservation:
    """Reserve a server-owned company and its founding actor binding."""

    workspace_id: UUID
    actor_id: str
    parent_session_id: str
    child_session_id: str
    created_at: datetime
    idempotency_key: UUID | None = None


@dataclass(frozen=True, slots=True)
class ActorBinding:
    """Bind one authenticated actor session to an existing company."""

    company_id: UUID
    actor_id: str
    parent_session_id: str
    child_session_id: str


@dataclass(frozen=True, slots=True)
class CompanyAccess:
    """Canonical company state paired with one actor's current authority."""

    state: CompanyState
    workspace_id: UUID
    role: WorkspaceRole
    authorization_epoch: int
    parent_session_id: str
    child_session_id: str


@dataclass(frozen=True, slots=True)
class CompanyAcceptance:
    """All immutable fences required to accept a company revision."""

    state: CompanyState
    workspace_id: UUID
    actor_id: str
    parent_session_id: str
    child_session_id: str
    authorization_epoch: int
    expected_revision: int


class _CompanyAccessRow(BaseModel):
    canonical_state: dict[str, JsonValue]
    workspace_id: UUID
    role: WorkspaceRole
    authorization_epoch: int
    parent_session_id: str
    child_session_id: str


class _MembershipRow(BaseModel):
    role: WorkspaceRole
    authorization_epoch: int


class _CompanyAcceptanceRow(BaseModel):
    workspace_id: UUID
    current_revision: int
    legacy_owner_id: str
    legacy_session_id: str
    created_at: int


class _WorkspaceRow(BaseModel):
    workspace_id: UUID


CompanyAccessRow = _CompanyAccessRow
MembershipRow = _MembershipRow
CompanyAcceptanceRow = _CompanyAcceptanceRow
WorkspaceRow = _WorkspaceRow
