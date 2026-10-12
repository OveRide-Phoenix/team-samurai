"""Typed boundaries for the founder-platform legacy migration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, override

from pydantic import BaseModel, ConfigDict, JsonValue

from samurai.contracts import CompanyState  # noqa: TC001 - Pydantic resolves this at runtime.


class LegacyMigrationIssue(StrEnum):
    """Enumerate stable redacted migration refusals."""

    INVALID_SCHEMA = "invalid database schema name"
    INVALID_FILENAME = "invalid migration filename"
    INVALID_ORDER = "founder-platform migration order is invalid"
    SOURCE_DRIFT = "applied migration source hash does not match"
    DUPLICATE_COMPANY = "ambiguous duplicate legacy company UUID"
    MISSING_OWNER = "legacy company owner is missing"
    INVALID_LINEAGE = "invalid legacy company lineage"
    COMPANY_CONFLICT = "existing founder-platform company conflicts with legacy state"


@dataclass(slots=True)
class LegacyMigrationError(Exception):
    """Expose one redacted refusal at the migration CLI boundary."""

    issue: LegacyMigrationIssue

    @override
    def __str__(self) -> str:
        return self.issue.value


@dataclass(frozen=True, slots=True)
class MigrationReceipt:
    """Carry sanitized migration reconciliation counts and hashes."""

    status: str
    owners: int
    companies: int
    revisions: int
    state_sha256: tuple[str, ...]
    migration_versions: tuple[str, ...]

    def as_json(self) -> dict[str, JsonValue]:
        """Return the stable operator receipt shape."""
        return {
            "status": self.status,
            "owners": self.owners,
            "companies": self.companies,
            "revisions": self.revisions,
            "state_sha256": list(self.state_sha256),
            "migration_versions": list(self.migration_versions),
        }


class LegacySessionState(BaseModel):
    """Parse the canonical company field while retaining unrelated legacy fields."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow", frozen=True)

    company: CompanyState


class LegacySessionData(BaseModel):
    """Parse the legacy session-state envelope without rewriting it."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow", frozen=True)

    session_state: LegacySessionState


class LegacyRow(BaseModel):
    """Parse one selected Agno workflow session row."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    session_id: str
    user_id: str | None
    session_data: LegacySessionData
    created_at: int
    updated_at: int | None


@dataclass(frozen=True, slots=True)
class LegacyCompany:
    """Carry a validated company and its immutable legacy pointers."""

    owner_id: str
    child_session_id: str
    parent_session_id: str
    created_at: int
    updated_at: int
    state: CompanyState
    state_sha256: str


def canonical_state_hash(state: CompanyState) -> str:
    """Hash canonical JSON independently of PostgreSQL JSONB key ordering."""
    payload = json.dumps(
        state.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()
