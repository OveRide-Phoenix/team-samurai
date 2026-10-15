"""Workspace directory records."""

from __future__ import annotations

from typing import ClassVar
from uuid import UUID  # noqa: TC003 - Pydantic resolves directory UUID fields at runtime.

from pydantic import BaseModel, ConfigDict, Field

from samurai.company_store_contracts import WorkspaceRole  # noqa: TC001
from samurai.contracts import ArtifactEnvelope  # noqa: TC001
from samurai.parent import CompanyStateSummary  # noqa: TC001


class WorkspaceRecord(BaseModel):
    """Workspace metadata with actor authority."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    workspace_id: UUID
    display_name: str
    role: WorkspaceRole
    authorization_epoch: int


class MemberRecord(BaseModel):
    """Persisted workspace membership."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    workspace_id: UUID
    user_id: str
    role: WorkspaceRole
    authorization_epoch: int


class CompanySnapshot(BaseModel):
    """Canonical company data safe for members."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    summary: CompanyStateSummary
    artifacts: tuple[ArtifactEnvelope, ...]


class CompanyRecord(BaseModel):
    """Shared company metadata and actor binding."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    workspace_id: UUID
    company_id: UUID
    current_revision: int
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: int
    parent_session_id: str | None
    child_session_id: str | None
    snapshot: CompanySnapshot | None = None


class MembershipRow(BaseModel):
    """Locked membership mutation state."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    role: WorkspaceRole
    authorization_epoch: int
    active: bool


class BindingRow(BaseModel):
    """Actor-native company session binding."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    current_revision: int
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: int
    parent_session_id: str
    child_session_id: str
