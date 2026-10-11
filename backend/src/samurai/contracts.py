# ruff: noqa: D101, D102, D103, EM101, TRY003
"""Shared role contracts kept together for downstream consumers. # noqa: SIZE_OK."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, Annotated, ClassVar, Literal, Self, override
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, model_validator
from pydantic_core import PydanticCustomError

if TYPE_CHECKING:
    from datetime import datetime


class Contract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid", frozen=True, allow_inf_nan=False
    )


@unique
class Role(StrEnum):
    INTAKE = "intake"
    RESEARCHER = "researcher"
    STRATEGIST = "strategist"
    PRODUCT_MANAGER = "product_manager"
    BUILDER = "builder"
    MARKETER = "marketer"
    SALES = "sales"
    ANALYST = "analyst"
    VERIFIER = "verifier"


@unique
class ArtifactType(StrEnum):
    INTAKE = "intake"
    RESEARCH = "research"
    STRATEGY = "strategy"
    PRODUCT_PLAN = "product_plan"
    BUILDER_DRAFT = "builder_draft"
    MARKETING_DRAFT = "marketing_draft"
    SALES_DRAFT = "sales_draft"
    ANALYSIS = "analysis"
    VERIFICATION = "verification"


class CompanyBrief(Contract):
    """Founder-supplied context and hypotheses, never researched facts."""

    idea: str = Field(min_length=1)
    target_customer: str | None
    geography: str | None
    budget: str | None
    founder_skills: str | None
    goal: str | None
    supplied_context: list[str]
    assumptions: list[str]
    open_questions: list[str]
    next_actions: list[str]


class CompanyContext(Contract):
    company_id: UUID
    authenticated_session_id: str = Field(min_length=1)
    created_at: AwareDatetime


class FounderStatement(Contract):
    statement_id: UUID
    text: str = Field(min_length=1)


class Assumption(Contract):
    assumption_id: UUID
    text: str = Field(min_length=1)


class SourceReference(Contract):
    source_id: UUID
    url: HttpUrl
    title: str = Field(min_length=1)
    retrieved_at: AwareDatetime
    search_query: str = Field(min_length=1)
    excerpt: str = Field(min_length=1, max_length=2000)


class SourcedClaim(Contract):
    claim_id: UUID
    text: str = Field(min_length=1)
    source_ids: tuple[UUID, ...] = Field(min_length=1)
    support_status: Literal["mapped", "unmapped"]
    support_segments: tuple[str, ...]
    verification_status: Literal["unverified", "supported", "contradicted"]

    @model_validator(mode="after")
    def validate_support_mapping(self) -> Self:
        if self.support_status == "mapped" and not self.support_segments:
            raise PydanticCustomError(
                "missing_support_segments", "mapped claims require support segments"
            )
        return self


class FounderMetricInput(Contract):
    name: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    window_start: AwareDatetime
    window_end: AwareDatetime
    source_label: str = Field(min_length=1)
    collected_at: AwareDatetime

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.window_end <= self.window_start:
            raise PydanticCustomError("metric_window", "window_end must follow window_start")
        return self


class MeasuredResult(FounderMetricInput):
    metric_id: UUID
    provenance: Literal["connected_measurement", "founder_supplied", "demo_fixture"]
    trusted_connector_receipt: str | None = None

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        has_receipt = bool(self.trusted_connector_receipt)
        if (self.provenance == "connected_measurement") != has_receipt:
            raise PydanticCustomError(
                "metric_provenance",
                "only connected measurements require a trusted connector receipt",
            )
        return self


class VerificationFinding(Contract):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: Literal["info", "warning", "error"]


class IntakeArtifact(Contract):
    artifact_type: Literal[ArtifactType.INTAKE] = ArtifactType.INTAKE
    brief: CompanyBrief


class ResearchArtifact(Contract):
    artifact_type: Literal[ArtifactType.RESEARCH] = ArtifactType.RESEARCH
    summary: str = Field(min_length=1)
    conflicts: tuple[str, ...]


class StrategyArtifact(Contract):
    artifact_type: Literal[ArtifactType.STRATEGY] = ArtifactType.STRATEGY
    ideal_customer_profile: str = Field(min_length=1)
    positioning: str = Field(min_length=1)
    offer: str = Field(min_length=1)
    pricing_assumptions: tuple[str, ...]


class ProductPlanArtifact(Contract):
    artifact_type: Literal[ArtifactType.PRODUCT_PLAN] = ArtifactType.PRODUCT_PLAN
    minimum_viable_offering: tuple[str, ...]
    delivery_requirements: tuple[str, ...]
    user_stories: tuple[str, ...]
    roadmap: tuple[str, ...]


class BuilderDraftArtifact(Contract):
    artifact_type: Literal[ArtifactType.BUILDER_DRAFT] = ArtifactType.BUILDER_DRAFT
    architecture: tuple[str, ...]
    database_schema: tuple[str, ...]
    apis: tuple[str, ...]
    user_interface: tuple[str, ...]
    deployment_configuration: tuple[str, ...]


class MarketingDraftArtifact(Contract):
    artifact_type: Literal[ArtifactType.MARKETING_DRAFT] = ArtifactType.MARKETING_DRAFT
    landing_page: str = Field(min_length=1)
    ads: tuple[str, ...]
    social_posts: tuple[str, ...]
    emails: tuple[str, ...]


class SalesDraftArtifact(Contract):
    artifact_type: Literal[ArtifactType.SALES_DRAFT] = ArtifactType.SALES_DRAFT
    prospect_criteria: tuple[str, ...]
    outreach: tuple[str, ...]
    scripts: tuple[str, ...]
    objection_handling: tuple[str, ...]


class AnalysisArtifact(Contract):
    artifact_type: Literal[ArtifactType.ANALYSIS] = ArtifactType.ANALYSIS
    metric_ids: tuple[UUID, ...] = Field(min_length=1)
    findings: tuple[str, ...]
    recommendations: tuple[str, ...]
    basis: Literal["connected_measurements", "based_on_founder_supplied_metrics"]


class VerificationArtifact(Contract):
    artifact_type: Literal[ArtifactType.VERIFICATION] = ArtifactType.VERIFICATION
    checked_artifact_ids: tuple[UUID, ...] = Field(min_length=1)
    outcome: Literal["verified", "needs_input", "needs_rework"]


type ArtifactPayload = Annotated[
    IntakeArtifact
    | ResearchArtifact
    | StrategyArtifact
    | ProductPlanArtifact
    | BuilderDraftArtifact
    | MarketingDraftArtifact
    | SalesDraftArtifact
    | AnalysisArtifact
    | VerificationArtifact,
    Field(discriminator="artifact_type"),
]


class ArtifactEnvelope(Contract):
    artifact_id: UUID
    company_id: UUID
    artifact_type: ArtifactType
    revision: int = Field(ge=1)
    input_revision: int = Field(ge=0)
    producer: Role
    status: Literal[
        "complete",
        "insufficient_evidence",
        "needs_input",
        "needs_rework",
        "draft_only",
        "requires_metrics",
        "based_on_founder_supplied_metrics",
    ]
    acceptance_status: Literal["pending", "accepted"] = "pending"
    payload: ArtifactPayload
    founder_statements: tuple[FounderStatement, ...] = ()
    sources: tuple[SourceReference, ...] = ()
    claims: tuple[SourcedClaim, ...] = ()
    measurements: tuple[MeasuredResult, ...] = ()
    assumptions: tuple[Assumption, ...]
    verification_findings: tuple[VerificationFinding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_artifact_type(self) -> Self:
        if self.artifact_type != self.payload.artifact_type:
            raise PydanticCustomError(
                "artifact_type_mismatch", "artifact_type must match payload artifact_type"
            )
        source_ids = {source.source_id for source in self.sources}
        if any(not set(claim.source_ids) <= source_ids for claim in self.claims):
            raise PydanticCustomError(
                "unknown_claim_source", "every claim source must be retained in the artifact"
            )
        if error := _artifact_evidence_error(self):
            raise PydanticCustomError("invalid_artifact_evidence", "{error}", {"error": error})
        return self


def _artifact_evidence_error(artifact: ArtifactEnvelope) -> str | None:
    error: str | None = None
    if any(
        measurement.provenance == "connected_measurement" for measurement in artifact.measurements
    ):
        error = "connected measurements require trusted backend connector validation"
    elif isinstance(artifact.payload, AnalysisArtifact):
        metric_ids = artifact.payload.metric_ids
        retained_ids = tuple(measurement.metric_id for measurement in artifact.measurements)
        if artifact.payload.basis == "connected_measurements":
            error = "connected analysis requires trusted backend connector validation"
        elif (
            len(metric_ids) != len(set(metric_ids))
            or len(retained_ids) != len(set(retained_ids))
            or set(metric_ids) != set(retained_ids)
        ):
            error = "analysis metric IDs must exactly reference retained measurements"
        elif any(
            measurement.provenance != "founder_supplied" for measurement in artifact.measurements
        ):
            error = "founder-supplied analysis requires founder-supplied measurements"
        elif artifact.status != "based_on_founder_supplied_metrics":
            error = "founder-supplied analysis must remain conditional"
    return error


class CompanyState(Contract):
    context: CompanyContext
    current_revision: int = Field(ge=0)
    artifacts: tuple[ArtifactEnvelope, ...] = ()

    @model_validator(mode="after")
    def validate_canonical_lineage(self) -> Self:
        revision = 0
        for artifact in self.artifacts:
            if artifact.company_id != self.context.company_id:
                raise PydanticCustomError("company_mismatch", "artifact belongs to another company")
            if artifact.input_revision != revision or artifact.revision != revision + 1:
                raise PydanticCustomError(
                    "invalid_lineage", "artifact revisions are not contiguous"
                )
            if artifact.acceptance_status != "accepted":
                raise PydanticCustomError(
                    "rejected_canonical_state", "canonical state accepts accepted artifacts only"
                )
            if error := _artifact_evidence_error(artifact):
                raise PydanticCustomError(
                    "invalid_artifact_evidence",
                    "{error}",
                    {"error": error},
                )
            revision = artifact.revision
        if self.current_revision != revision:
            raise PydanticCustomError(
                "current_revision", "current_revision must match artifact lineage"
            )
        return self


class RoleCapability(Contract):
    role: Role
    status: Literal["active", "draft_only", "requires_metrics"]
    output_artifact: ArtifactType
    tools: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompanyMismatchError(Exception):
    expected_company_id: UUID
    received_company_id: UUID

    @override
    def __str__(self) -> str:
        return "artifact company does not match the authenticated session company"


@dataclass(frozen=True, slots=True)
class StaleRevisionError(Exception):
    expected_revision: int
    received_revision: int

    @override
    def __str__(self) -> str:
        return (
            f"stale artifact input revision: expected {self.expected_revision}, "
            f"received {self.received_revision}"
        )


@dataclass(frozen=True, slots=True)
class SessionMismatchError(Exception):
    expected_session_id: str
    received_session_id: str

    @override
    def __str__(self) -> str:
        return "company state does not belong to the authenticated session"


@dataclass(frozen=True, slots=True)
class InvalidArtifactTransitionError(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


def create_company_state(authenticated_session_id: str, *, created_at: datetime) -> CompanyState:
    context = CompanyContext(
        company_id=uuid4(),
        authenticated_session_id=authenticated_session_id,
        created_at=created_at,
    )
    return CompanyState(context=context, current_revision=0)


def accept_artifact(
    state: CompanyState,
    artifact: ArtifactEnvelope,
    *,
    authenticated_session_id: str,
) -> CompanyState:
    if authenticated_session_id != state.context.authenticated_session_id:
        raise SessionMismatchError(state.context.authenticated_session_id, authenticated_session_id)
    if artifact.company_id != state.context.company_id:
        raise CompanyMismatchError(state.context.company_id, artifact.company_id)
    if artifact.input_revision != state.current_revision:
        raise StaleRevisionError(state.current_revision, artifact.input_revision)
    if artifact.revision != state.current_revision + 1:
        raise InvalidArtifactTransitionError("artifact revision must advance exactly once")
    if artifact.acceptance_status != "pending":
        raise InvalidArtifactTransitionError(
            "artifact acceptance must be decided by the state transition"
        )
    if any(finding.severity == "error" for finding in artifact.verification_findings):
        raise InvalidArtifactTransitionError("accepted artifacts cannot contain error findings")
    if error := _artifact_evidence_error(artifact):
        raise InvalidArtifactTransitionError(error)
    accepted_artifact = artifact.model_copy(update={"acceptance_status": "accepted"})
    return CompanyState(
        context=state.context,
        current_revision=accepted_artifact.revision,
        artifacts=(*state.artifacts, accepted_artifact),
    )
