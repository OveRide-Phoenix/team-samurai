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


def _exclude_none(value: object) -> bool:
    return value is None


class CompanyContext(Contract):
    workspace_id: UUID | None = Field(default=None, exclude_if=_exclude_none)
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


class SourceAdjudication(Contract):
    research_artifact_id: UUID
    research_revision: int = Field(ge=1)
    claim_id: UUID
    claim_text: str = Field(min_length=1)
    source_id: UUID
    source_url: HttpUrl
    attempted_at: AwareDatetime
    fetched_at: AwareDatetime | None = None
    final_url: HttpUrl | None = None
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    media_type: str | None = Field(default=None, min_length=1, max_length=200)
    evidence_quote: str = Field(max_length=500)
    verdict: Literal["supported", "contradicted", "insufficient", "inaccessible"]
    rationale: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_fetched_provenance(self) -> Self:
        fetched_fields = (
            self.fetched_at,
            self.final_url,
            self.content_sha256,
            self.media_type,
        )
        has_fetched_provenance = all(fetched_fields)
        has_no_fetched_provenance = not any(fetched_fields)
        if self.fetched_at is not None and self.fetched_at < self.attempted_at:
            raise PydanticCustomError("adjudication_time", "fetched_at cannot precede attempted_at")
        match self.verdict:
            case "inaccessible":
                if not has_no_fetched_provenance or self.evidence_quote:
                    raise PydanticCustomError(
                        "inaccessible_provenance",
                        "inaccessible adjudications require no fetched provenance or quote",
                    )
            case "insufficient":
                if not has_fetched_provenance or self.evidence_quote:
                    raise PydanticCustomError(
                        "insufficient_provenance",
                        "insufficient adjudications require fetched provenance and no quote",
                    )
            case "supported" | "contradicted":
                if not has_fetched_provenance or not self.evidence_quote.strip():
                    raise PydanticCustomError(
                        "adjudication_provenance",
                        "supported and contradicted adjudications require a fetched quote",
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


type FounderContextKey = Literal[
    "idea",
    "target_customer",
    "geography",
    "budget",
    "founder_skills",
    "goal",
    "supplied_context",
]
type FounderTruthText = Annotated[str, Field(min_length=1)]


class FounderKnownFact(Contract):
    text: str = Field(min_length=1)
    basis: Literal["founder_context", "retained_evidence"]
    context_key: FounderContextKey | None = None
    evidence_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def validate_basis(self) -> Self:
        context_bound = self.context_key is not None and not self.evidence_ids
        evidence_bound = self.context_key is None and bool(self.evidence_ids)
        if (self.basis == "founder_context") != context_bound or (
            self.basis == "retained_evidence"
        ) != evidence_bound:
            raise PydanticCustomError(
                "founder_known_basis",
                "known facts require exactly one matching context or evidence basis",
            )
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise PydanticCustomError("founder_known_evidence", "known evidence IDs must be unique")
        return self


class FounderTruth(Contract):
    known: tuple[FounderKnownFact, ...] = ()
    believed: tuple[FounderTruthText, ...] = ()
    hoped: tuple[FounderTruthText, ...] = ()
    evidence_gaps: tuple[FounderTruthText, ...] = ()
    bottleneck: FounderTruthText | None = None
    next_decision: FounderTruthText | None = None

    @model_validator(mode="after")
    def validate_categories(self) -> Self:
        categories = (
            tuple(item.text for item in self.known),
            self.believed,
            self.hoped,
        )
        normalized = tuple(tuple(text.casefold() for text in category) for category in categories)
        if any(len(category) != len(set(category)) for category in normalized) or any(
            set(normalized[left]) & set(normalized[right])
            for left, right in ((0, 1), (0, 2), (1, 2))
        ):
            raise PydanticCustomError("founder_truth_overlap", "truth categories must be disjoint")
        return self


class FrameworkReference(Contract):
    id: Literal["founder_truth", "offer_diagnostic"]
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    source_repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_url: HttpUrl
    license: Literal["MIT"]
    attribution: str = Field(min_length=1)
    allowed_roles: tuple[Role, ...] = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_date: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        expected_url = f"https://github.com/{self.source_repository}/tree/{self.source_revision}"
        if str(self.source_url).rstrip("/") != expected_url:
            raise PydanticCustomError(
                "framework_source_url", "source_url does not match framework provenance"
            )
        if len(self.allowed_roles) != len(set(self.allowed_roles)):
            raise PydanticCustomError("framework_roles", "allowed framework roles must be unique")
        if any(
            role not in {Role.INTAKE, Role.STRATEGIST, Role.VERIFIER} for role in self.allowed_roles
        ):
            raise PydanticCustomError("framework_roles", "framework role is not reviewed")
        return self


class OfferDiagnostic(Contract):
    market: str = Field(min_length=1)
    painful_problem: str = Field(min_length=1)
    purchasing_power_assumption: Assumption
    draft_offer: str = Field(min_length=1)
    evidence_needed: tuple[Annotated[str, Field(min_length=1)], ...] = Field(min_length=1)
    framework: FrameworkReference

    @model_validator(mode="after")
    def validate_framework(self) -> Self:
        if (
            self.framework.id != "offer_diagnostic"
            or Role.STRATEGIST not in self.framework.allowed_roles
        ):
            raise PydanticCustomError(
                "offer_framework", "offer diagnostics require the reviewed strategist framework"
            )
        return self


class IntakeArtifact(Contract):
    artifact_type: Literal[ArtifactType.INTAKE] = ArtifactType.INTAKE
    brief: CompanyBrief
    founder_truth: FounderTruth = FounderTruth()
    frameworks: tuple[FrameworkReference, ...] = ()

    @model_validator(mode="after")
    def validate_frameworks(self) -> Self:
        if self.frameworks and (
            len(self.frameworks) != 1
            or self.frameworks[0].id != "founder_truth"
            or Role.INTAKE not in self.frameworks[0].allowed_roles
        ):
            raise PydanticCustomError(
                "intake_frameworks", "Intake accepts one reviewed founder_truth reference"
            )
        return self


class ResearchArtifact(Contract):
    artifact_type: Literal[ArtifactType.RESEARCH] = ArtifactType.RESEARCH
    summary: str = Field(min_length=1)
    conflicts: tuple[str, ...]
    adjudicated_from_artifact_id: UUID | None = None
    adjudicated_from_revision: int | None = Field(default=None, ge=1)
    adjudications: tuple[SourceAdjudication, ...] = ()

    @property
    def is_adjudicated(self) -> bool:
        return self.adjudicated_from_artifact_id is not None

    @model_validator(mode="after")
    def validate_adjudication_reference(self) -> Self:
        has_reference = self.adjudicated_from_artifact_id is not None
        has_revision = self.adjudicated_from_revision is not None
        has_adjudications = bool(self.adjudications)
        if not has_reference and not has_revision and not has_adjudications:
            return self
        if not has_reference or not has_revision:
            raise PydanticCustomError(
                "incomplete_adjudication_reference",
                "adjudicated research requires both original artifact ID and revision",
            )
        if any(
            adjudication.research_artifact_id != self.adjudicated_from_artifact_id
            or adjudication.research_revision != self.adjudicated_from_revision
            for adjudication in self.adjudications
        ):
            raise PydanticCustomError(
                "adjudication_reference_mismatch",
                "every adjudication must bind the referenced original research revision",
            )
        return self


class StrategyArtifact(Contract):
    artifact_type: Literal[ArtifactType.STRATEGY] = ArtifactType.STRATEGY
    ideal_customer_profile: str = Field(min_length=1)
    positioning: str = Field(min_length=1)
    offer: str = Field(min_length=1)
    pricing_assumptions: tuple[str, ...]
    offer_diagnostic: OfferDiagnostic | None = None


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


class AnalysisDraft(Contract):
    findings: tuple[str, ...]
    recommendations: tuple[str, ...]


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
        if error := _adjudication_payload_error(self):
            raise PydanticCustomError("invalid_adjudication", "{error}", {"error": error})
        if error := _artifact_evidence_error(self):
            raise PydanticCustomError("invalid_artifact_evidence", "{error}", {"error": error})
        return self


type FetchedProvenance = tuple[AwareDatetime | None, HttpUrl | None, str | None, str | None]


def _research_payload(artifact: ArtifactEnvelope) -> ResearchArtifact | None:
    match artifact.payload:
        case ResearchArtifact() as research:
            return research
        case (
            IntakeArtifact()
            | StrategyArtifact()
            | ProductPlanArtifact()
            | BuilderDraftArtifact()
            | MarketingDraftArtifact()
            | SalesDraftArtifact()
            | AnalysisArtifact()
            | VerificationArtifact()
        ):
            return None


def _adjudication_payload_error(artifact: ArtifactEnvelope) -> str | None:
    research = _research_payload(artifact)
    if research is None or not research.is_adjudicated:
        return None
    return _research_adjudication_error(research, artifact)


def _research_adjudication_error(
    research: ResearchArtifact, artifact: ArtifactEnvelope
) -> str | None:
    source_by_id = {source.source_id: source for source in artifact.sources}
    claim_by_id = {claim.claim_id: claim for claim in artifact.claims}
    if len(source_by_id) != len(artifact.sources) or len(claim_by_id) != len(artifact.claims):
        return "adjudicated research requires unique claim and source IDs"
    expected_pairs = {
        (claim.claim_id, source_id) for claim in artifact.claims for source_id in claim.source_ids
    }
    actual_pairs = tuple(
        (adjudication.claim_id, adjudication.source_id) for adjudication in research.adjudications
    )
    if len(actual_pairs) != len(set(actual_pairs)) or set(actual_pairs) != expected_pairs:
        return "adjudications must contain one decision for every retained claim-source pair"
    return _adjudication_decision_error(research, source_by_id, claim_by_id)


def _adjudication_decision_error(
    research: ResearchArtifact,
    source_by_id: dict[UUID, SourceReference],
    claim_by_id: dict[UUID, SourcedClaim],
) -> str | None:
    fetched_provenance: dict[UUID, FetchedProvenance] = {}
    for adjudication in research.adjudications:
        claim = claim_by_id.get(adjudication.claim_id)
        source = source_by_id.get(adjudication.source_id)
        if claim is None or source is None:
            return "adjudication references an unknown retained claim or source"
        if (
            adjudication.claim_text != claim.text
            or adjudication.source_url != source.url
            or adjudication.source_id not in claim.source_ids
        ):
            return "adjudication claim and source bindings must match retained research"
        provenance: FetchedProvenance = (
            adjudication.fetched_at,
            adjudication.final_url,
            adjudication.content_sha256,
            adjudication.media_type,
        )
        previous = fetched_provenance.get(adjudication.source_id)
        if previous is not None and previous != provenance:
            return "adjudications for one source must retain identical fetched provenance"
        fetched_provenance[adjudication.source_id] = provenance
        match adjudication.verdict:
            case "supported" | "contradicted":
                if adjudication.evidence_quote not in source.excerpt:
                    return (
                        "supported and contradicted quotes must be retained in the source excerpt"
                    )
            case "insufficient" | "inaccessible":
                pass
    for claim in claim_by_id.values():
        verdicts = tuple(
            adjudication.verdict
            for adjudication in research.adjudications
            if adjudication.claim_id == claim.claim_id
        )
        expected_status = _verification_status_for_verdicts(verdicts)
        if claim.verification_status != expected_status:
            return "claim verification status must match its source adjudication verdicts"
    return None


def _verification_status_for_verdicts(
    verdicts: tuple[str, ...],
) -> Literal["unverified", "supported", "contradicted"]:
    if "contradicted" in verdicts:
        return "contradicted"
    if "supported" in verdicts:
        return "supported"
    return "unverified"


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


def _adjudication_transition_error(
    accepted_artifacts: tuple[ArtifactEnvelope, ...], artifact: ArtifactEnvelope
) -> str | None:
    research = _research_payload(artifact)
    if research is None or not research.is_adjudicated:
        return None
    return _research_transition_error(accepted_artifacts, artifact, research)


def _research_transition_error(
    accepted_artifacts: tuple[ArtifactEnvelope, ...],
    artifact: ArtifactEnvelope,
    research: ResearchArtifact,
) -> str | None:
    if not accepted_artifacts:
        return "adjudicated research requires an accepted raw research revision"
    previous = accepted_artifacts[-1]
    raw = _research_payload(previous)
    if raw is None or raw.is_adjudicated:
        return "adjudicated research must append immediately from raw research"
    if (
        research.adjudicated_from_artifact_id != previous.artifact_id
        or research.adjudicated_from_revision != previous.revision
    ):
        return "adjudicated research must reference the immediately preceding raw revision"
    return _raw_adjudication_match_error(accepted_artifacts, previous, artifact, raw, research)


def _raw_adjudication_match_error(
    accepted_artifacts: tuple[ArtifactEnvelope, ...],
    raw_artifact: ArtifactEnvelope,
    adjudicated_artifact: ArtifactEnvelope,
    raw: ResearchArtifact,
    research: ResearchArtifact,
) -> str | None:
    if research.summary != raw.summary or research.conflicts != raw.conflicts:
        return "adjudicated research must preserve raw summary and conflicts"
    raw_claims = {claim.claim_id: (claim.text, claim.source_ids) for claim in raw_artifact.claims}
    next_claims = {
        claim.claim_id: (claim.text, claim.source_ids) for claim in adjudicated_artifact.claims
    }
    raw_sources = {source.source_id: source.url for source in raw_artifact.sources}
    next_sources = {source.source_id: source.url for source in adjudicated_artifact.sources}
    if raw_claims != next_claims or raw_sources != next_sources:
        return "adjudicated research must preserve raw claim and source bindings"
    if _is_replayed_adjudication(accepted_artifacts, raw_artifact):
        return "an accepted raw research revision cannot be adjudicated twice"
    return None


def _is_replayed_adjudication(
    accepted_artifacts: tuple[ArtifactEnvelope, ...],
    raw_artifact: ArtifactEnvelope,
) -> bool:
    for candidate in accepted_artifacts:
        candidate_research = _research_payload(candidate)
        if (
            candidate_research is not None
            and candidate_research.is_adjudicated
            and candidate_research.adjudicated_from_artifact_id == raw_artifact.artifact_id
            and candidate_research.adjudicated_from_revision == raw_artifact.revision
        ):
            return True
    return False


class CompanyState(Contract):
    context: CompanyContext
    current_revision: int = Field(ge=0)
    artifacts: tuple[ArtifactEnvelope, ...] = ()

    @model_validator(mode="after")
    def validate_canonical_lineage(self) -> Self:
        revision = 0
        for index, artifact in enumerate(self.artifacts):
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
            if error := _adjudication_payload_error(artifact):
                raise PydanticCustomError("invalid_adjudication", "{error}", {"error": error})
            if error := _artifact_evidence_error(artifact):
                raise PydanticCustomError(
                    "invalid_artifact_evidence",
                    "{error}",
                    {"error": error},
                )
            if error := _adjudication_transition_error(self.artifacts[:index], artifact):
                raise PydanticCustomError(
                    "invalid_adjudication_transition", "{error}", {"error": error}
                )
            revision = artifact.revision
        if self.current_revision != revision:
            raise PydanticCustomError(
                "current_revision", "current_revision must match artifact lineage"
            )
        return self


class WorkflowRequest(Contract):
    company_id: UUID | None
    expected_revision: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_new_company_revision(self) -> Self:
        if self.company_id is None and self.expected_revision != 0:
            raise PydanticCustomError(
                "new_company_revision", "new company requests must start at revision zero"
            )
        return self


class WorkflowResult(Contract):
    company_id: UUID
    revision: int = Field(ge=0)
    outcome: Literal[
        "verified",
        "needs_input",
        "needs_rework",
        "insufficient_evidence",
        "draft_only",
        "requires_metrics",
        "based_on_founder_supplied_metrics",
    ]
    artifacts: tuple[ArtifactEnvelope, ...] = ()
    questions: tuple[Annotated[str, Field(min_length=1, max_length=200)], ...] = ()

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if self.outcome == "needs_input" and not self.questions:
            raise PydanticCustomError(
                "missing_workflow_questions", "needs_input requires at least one question"
            )
        if self.outcome != "needs_input" and self.questions:
            raise PydanticCustomError(
                "unexpected_workflow_questions", "questions are only valid for needs_input"
            )
        if any(artifact.company_id != self.company_id for artifact in self.artifacts):
            raise PydanticCustomError(
                "workflow_company_mismatch", "workflow artifacts must belong to the result company"
            )
        if any(artifact.revision > self.revision for artifact in self.artifacts):
            raise PydanticCustomError(
                "workflow_revision_mismatch", "workflow artifacts cannot exceed the result revision"
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


def create_company_state(
    authenticated_session_id: str,
    *,
    created_at: datetime,
    workspace_id: UUID | None = None,
) -> CompanyState:
    context = CompanyContext(
        workspace_id=workspace_id,
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
    if error := _adjudication_payload_error(artifact):
        raise InvalidArtifactTransitionError(error)
    if error := _artifact_evidence_error(artifact):
        raise InvalidArtifactTransitionError(error)
    if error := _adjudication_transition_error(state.artifacts, artifact):
        raise InvalidArtifactTransitionError(error)
    accepted_artifact = artifact.model_copy(update={"acceptance_status": "accepted"})
    return CompanyState(
        context=state.context,
        current_revision=accepted_artifact.revision,
        artifacts=(*state.artifacts, accepted_artifact),
    )
