"""Fail-closed loading for attributed founder framework references."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, model_validator
from pydantic_core import PydanticCustomError

from samurai.contracts import Role

FRAMEWORK_MANIFEST: Final = Path(__file__).with_name("frameworks") / "manifest.json"
FRAMEWORK_ROLES: Final = frozenset({Role.INTAKE, Role.STRATEGIST, Role.VERIFIER})
FRAMEWORK_IDS: Final = frozenset({"founder_truth", "offer_diagnostic"})
MANIFEST_INVALID: Final = "manifest_invalid"
RESOURCE_PATH_INVALID: Final = "resource_path_invalid"
RESOURCE_UNAVAILABLE: Final = "resource_unavailable"
RESOURCE_HASH_MISMATCH: Final = "resource_hash_mismatch"
RESOURCE_ENCODING_INVALID: Final = "resource_encoding_invalid"
RESOURCE_EMPTY: Final = "resource_empty"
ALLOWED_ROLES_INVALID: Final = "allowed_roles"
SOURCE_URL_INVALID: Final = "source_url"
DUPLICATE_ID_INVALID: Final = "duplicate_id"
FRAMEWORK_IDS_INVALID: Final = "framework_ids"
REVIEW_DATE_INVALID: Final = "review_date"


class FrameworkValidationError(RuntimeError):
    """A reviewed framework resource failed its trust-boundary checks."""


class FrameworkMetadata(BaseModel):
    """Public provenance for one loaded framework without local file paths."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)
    id: Literal["founder_truth", "offer_diagnostic"]
    version: str
    source_repository: str
    source_revision: str
    source_url: HttpUrl
    license: Literal["MIT"]
    attribution: str
    allowed_roles: tuple[Role, ...]
    sha256: str
    review_date: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class _ManifestEntry(FrameworkMetadata):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    source_repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    attribution: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resource: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_provenance_and_roles(self) -> Self:
        if (
            not self.allowed_roles
            or len(set(self.allowed_roles)) != len(self.allowed_roles)
            or any(role not in FRAMEWORK_ROLES for role in self.allowed_roles)
        ):
            raise PydanticCustomError(ALLOWED_ROLES_INVALID, "allowed_roles are not reviewed")
        expected_url = f"https://github.com/{self.source_repository}/tree/{self.source_revision}"
        if str(self.source_url).rstrip("/") != expected_url:
            raise PydanticCustomError(SOURCE_URL_INVALID, "source_url does not match provenance")
        try:
            _ = time.strptime(self.review_date, "%Y-%m-%d")
        except ValueError as error:
            raise PydanticCustomError(REVIEW_DATE_INVALID, "review_date is invalid") from error
        return self

    def public_metadata(self) -> FrameworkMetadata:
        return FrameworkMetadata.model_validate(self.model_dump(exclude={"resource"}))


class _Manifest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)
    frameworks: tuple[_ManifestEntry, ...]

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        ids = tuple(item.id for item in self.frameworks)
        if len(set(ids)) != len(ids):
            raise PydanticCustomError(DUPLICATE_ID_INVALID, "framework IDs must be unique")
        if len(ids) != len(FRAMEWORK_IDS) or any(
            str(framework_id) not in FRAMEWORK_IDS for framework_id in ids
        ):
            raise PydanticCustomError(
                FRAMEWORK_IDS_INVALID,
                "reviewed framework IDs are required",
            )
        return self


@dataclass(frozen=True, slots=True)
class _FrameworkResource:
    metadata: FrameworkMetadata
    text: str


@dataclass(frozen=True, slots=True)
class _FrameworkCatalog:
    resources: tuple[_FrameworkResource, ...]

    @property
    def metadata(self) -> tuple[FrameworkMetadata, ...]:
        return tuple(resource.metadata for resource in self.resources)

    def for_role(self, role: Role) -> tuple[_FrameworkResource, ...]:
        return tuple(
            resource for resource in self.resources if role in resource.metadata.allowed_roles
        )


def load_framework_catalog(manifest_path: Path = FRAMEWORK_MANIFEST) -> _FrameworkCatalog:
    """Validate manifest structure, paths, hashes, and UTF-8 before returning text."""
    try:
        manifest = _Manifest.model_validate_json(manifest_path.read_bytes())
    except (OSError, ValidationError) as error:
        raise FrameworkValidationError(MANIFEST_INVALID) from error

    root = manifest_path.parent.resolve()
    resources: list[_FrameworkResource] = []
    for entry in manifest.frameworks:
        unresolved = root / entry.resource
        resource_path = unresolved.resolve()
        if (
            Path(entry.resource).name != entry.resource
            or resource_path.parent != root
            or unresolved.is_symlink()
        ):
            raise FrameworkValidationError(RESOURCE_PATH_INVALID)
        try:
            payload = resource_path.read_bytes()
        except OSError as error:
            raise FrameworkValidationError(RESOURCE_UNAVAILABLE) from error
        if hashlib.sha256(payload).hexdigest() != entry.sha256:
            raise FrameworkValidationError(RESOURCE_HASH_MISMATCH)
        try:
            text = payload.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise FrameworkValidationError(RESOURCE_ENCODING_INVALID) from error
        if not text:
            raise FrameworkValidationError(RESOURCE_EMPTY)
        resources.append(_FrameworkResource(metadata=entry.public_metadata(), text=text))
    return _FrameworkCatalog(resources=tuple(resources))


def format_framework_instructions(resources: tuple[_FrameworkResource, ...]) -> str:
    """Render verified framework text without attaching runtime skill tools."""
    return "\n\n".join(
        f"## Founder framework: {resource.metadata.id}@{resource.metadata.version}\n{resource.text}"
        for resource in resources
    )
