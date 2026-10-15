"""Ordered company-journey state machine kept intact for native step review. # noqa: SIZE_OK."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Literal, Self, override
from uuid import uuid4

from agno.workflow import Step, StepInput, StepOutput, Workflow
from pydantic import BaseModel, Field, JsonValue, TypeAdapter, ValidationError, model_validator
from pydantic_core import PydanticCustomError

from samurai.agents import create_role_catalog
from samurai.contracts import (
    ArtifactEnvelope,
    ArtifactPayload,
    ArtifactType,
    Assumption,
    CompanyBrief,
    CompanyMismatchError,
    CompanyState,
    FounderKnownFact,
    FounderStatement,
    FounderTruth,
    FrameworkReference,
    IntakeArtifact,
    OfferDiagnostic,
    ProductPlanArtifact,
    ResearchArtifact,
    Role,
    SessionMismatchError,
    SourcedClaim,
    SourceReference,
    StaleRevisionError,
    StrategyArtifact,
    VerificationArtifact,
    VerificationFinding,
    WorkflowRequest,
    WorkflowResult,
    accept_artifact,
)
from samurai.frameworks import load_framework_catalog
from samurai.research import ResearchAgent, ResearchResult, run_research
from samurai.workflow_state import WorkflowContextError, load_company_state, save_company_state

if TYPE_CHECKING:
    from agno.db.base import BaseDb
    from agno.run import RunContext
    from agno.workflow.workflow import WorkflowStep

    from samurai.config import Settings

JourneyStage = Literal["brief", "research", "strategy", "plan", "verify"]

WORKFLOW_ID = "company-journey"
REQUIRED_CONTEXT = ("target_customer", "geography", "budget", "founder_skills", "goal")
QUESTIONS = {
    "target_customer": "Who is the first target customer?",
    "geography": "Which geography should the company serve first?",
    "budget": "What budget can you commit?",
    "founder_skills": "Which founder skills can support delivery?",
    "goal": "What outcome and timeframe define success?",
}
UNRESOLVED_RESEARCH = "retained research conflicts and factual claims remain unresolved."
EVIDENCE_DECISION = "What retained evidence supports the claimed known facts?"
JOURNEY_TYPES = (
    ArtifactType.INTAKE,
    ArtifactType.RESEARCH,
    ArtifactType.STRATEGY,
    ArtifactType.PRODUCT_PLAN,
    ArtifactType.VERIFICATION,
)
type ArtifactStatus = Literal[
    "complete", "insufficient_evidence", "needs_input", "needs_rework", "draft_only"
]
type FailureCode = Literal["invalid_context", "invalid_revision", "invalid_company_input"]
RESEARCH_RESULT_ADAPTER = TypeAdapter(ResearchResult)
JSON_VALUE_ADAPTER = TypeAdapter(JsonValue)


class CompanyJourneyRequest(WorkflowRequest):
    """Founder input for a new company or an amendment to its current brief."""

    idea: Annotated[str, Field(min_length=1)] | None = None
    target_customer: Annotated[str, Field(min_length=1)] | None = None
    geography: Annotated[str, Field(min_length=1)] | None = None
    budget: Annotated[str, Field(min_length=1)] | None = None
    founder_skills: Annotated[str, Field(min_length=1)] | None = None
    goal: Annotated[str, Field(min_length=1)] | None = None
    supplied_context: tuple[Annotated[str, Field(min_length=1)], ...] = ()
    assumptions: tuple[Annotated[str, Field(min_length=1)], ...] = ()

    @model_validator(mode="after")
    def validate_new_idea(self) -> Self:
        """Require founder intent before creating a company identity."""
        if self.company_id is None and self.idea is None:
            code = "missing_company_idea"
            raise PydanticCustomError(code, "a new company requires an idea")
        return self


class CompanyJourneyFailure(BaseModel):
    """Sanitized fail-closed result for an invalid trusted workflow boundary."""

    outcome: Literal["failed"] = "failed"
    error_code: FailureCode


class _IntakeDraft(BaseModel):
    brief: CompanyBrief
    founder_truth: FounderTruth = FounderTruth()


class _OfferDiagnosticDraft(BaseModel):
    market: str
    painful_problem: str
    purchasing_power_assumption: str
    draft_offer: str
    evidence_needed: tuple[str, ...]


class _StrategyDraft(BaseModel):
    ideal_customer_profile: str
    positioning: str
    offer: str
    pricing_assumptions: tuple[str, ...]
    offer_diagnostic: _OfferDiagnosticDraft | None = None


class _ProductDraft(BaseModel):
    minimum_viable_offering: tuple[str, ...]
    delivery_requirements: tuple[str, ...]
    user_stories: tuple[str, ...]
    roadmap: tuple[str, ...]


class _VerificationDraft(BaseModel):
    outcome: Literal["verified", "needs_input", "needs_rework"]


@dataclass(frozen=True, slots=True)
class JourneyInputError(Exception):
    """Reject founder changes that would rewrite accepted journey history."""

    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


def _step_output(content: BaseModel, *, stop: bool = False) -> StepOutput:
    return StepOutput(
        content=JSON_VALUE_ADAPTER.validate_python(content.model_dump(mode="json")),
        stop=stop,
    )


def _latest(state: CompanyState, artifact_type: ArtifactType) -> ArtifactEnvelope | None:
    return next(
        (
            artifact
            for artifact in reversed(state.artifacts)
            if artifact.artifact_type == artifact_type
        ),
        None,
    )


def _result(
    state: CompanyState,
    outcome: Literal["verified", "needs_input", "needs_rework", "insufficient_evidence"],
    *,
    questions: tuple[str, ...] = (),
) -> WorkflowResult:
    latest = tuple(
        artifact
        for artifact_type in JOURNEY_TYPES
        if (artifact := _latest(state, artifact_type)) is not None
    )
    return WorkflowResult(
        company_id=state.context.company_id,
        revision=state.current_revision,
        outcome=outcome,
        artifacts=latest,
        questions=questions,
    )


@dataclass(frozen=True, slots=True)
class _ArtifactCandidate:
    payload: ArtifactPayload
    producer: Role
    status: ArtifactStatus
    findings: tuple[VerificationFinding, ...]
    sources: tuple[SourceReference, ...] = ()
    claims: tuple[SourcedClaim, ...] = ()
    assumptions: tuple[Assumption, ...] = ()
    founder_statements: tuple[FounderStatement, ...] = ()


def _envelope(state: CompanyState, candidate: _ArtifactCandidate) -> ArtifactEnvelope:
    return ArtifactEnvelope(
        artifact_id=uuid4(),
        company_id=state.context.company_id,
        artifact_type=candidate.payload.artifact_type,
        revision=state.current_revision + 1,
        input_revision=state.current_revision,
        producer=candidate.producer,
        status=candidate.status,
        payload=candidate.payload,
        founder_statements=candidate.founder_statements,
        sources=candidate.sources,
        claims=candidate.claims,
        assumptions=candidate.assumptions,
        verification_findings=candidate.findings,
    )


def _save(
    state: CompanyState,
    envelope: ArtifactEnvelope,
    run_context: RunContext,
    db: BaseDb,
) -> CompanyState:
    updated = accept_artifact(
        state,
        envelope,
        authenticated_session_id=state.context.authenticated_session_id,
    )
    return save_company_state(updated, run_context, db=db)


def _request(step_input: StepInput) -> CompanyJourneyRequest:
    return CompanyJourneyRequest.model_validate(step_input.input)


def _state(run_context: RunContext) -> CompanyState:
    if run_context.session_state is None:
        message = "canonical company state is missing"
        raise JourneyInputError(message)
    return CompanyState.model_validate(run_context.session_state.get("company"))


def _context(run_context: RunContext | None) -> RunContext:
    if run_context is None:
        message = "native workflow run context is missing"
        raise JourneyInputError(message)
    return run_context


def _boundary_failure(error: Exception) -> CompanyJourneyFailure:
    codes: dict[type[Exception], FailureCode] = {
        StaleRevisionError: "invalid_revision",
        CompanyMismatchError: "invalid_company_input",
        JourneyInputError: "invalid_company_input",
        SessionMismatchError: "invalid_context",
        WorkflowContextError: "invalid_context",
    }
    code = codes.get(type(error))
    if code is None:
        raise error
    return CompanyJourneyFailure(error_code=code)


def _brief(request: CompanyJourneyRequest, existing: CompanyBrief | None) -> CompanyBrief:
    if existing is not None and request.idea is not None and request.idea != existing.idea:
        message = "the original company idea cannot be rewritten"
        raise JourneyInputError(message)
    values = {
        name: getattr(request, name) or (getattr(existing, name) if existing is not None else None)
        for name in ("idea", *REQUIRED_CONTEXT)
    }
    return CompanyBrief(
        idea=values["idea"] or "",
        target_customer=values["target_customer"],
        geography=values["geography"],
        budget=values["budget"],
        founder_skills=values["founder_skills"],
        goal=values["goal"],
        supplied_context=list(
            dict.fromkeys((*existing.supplied_context, *request.supplied_context))
        )
        if existing is not None
        else list(request.supplied_context),
        assumptions=list(dict.fromkeys((*existing.assumptions, *request.assumptions)))
        if existing is not None
        else list(request.assumptions),
        open_questions=[],
        next_actions=[],
    )


def _context_fact_is_retained(fact: FounderKnownFact, brief: CompanyBrief) -> bool:
    if fact.basis != "founder_context" or fact.context_key is None:
        return False
    match fact.context_key:
        case "idea":
            values = (brief.idea,)
        case "target_customer":
            values = (brief.target_customer,)
        case "geography":
            values = (brief.geography,)
        case "budget":
            values = (brief.budget,)
        case "founder_skills":
            values = (brief.founder_skills,)
        case "goal":
            values = (brief.goal,)
        case "supplied_context":
            values = tuple(brief.supplied_context)
    return any(item is not None and str(item).casefold() == fact.text.casefold() for item in values)


def _verified_founder_truth(
    proposed: FounderTruth, brief: CompanyBrief
) -> tuple[FounderTruth, tuple[str, ...]]:
    known = tuple(fact for fact in proposed.known if _context_fact_is_retained(fact, brief))
    unsupported = tuple(fact.text for fact in proposed.known if fact not in known)
    believed = tuple(dict.fromkeys((*proposed.believed, *unsupported)))
    gaps = tuple(
        dict.fromkeys(
            (
                *proposed.evidence_gaps,
                *(f"Retained evidence is missing for: {text}" for text in unsupported),
            )
        )
    )
    if unsupported:
        next_decision = EVIDENCE_DECISION
    elif proposed.bottleneck is None:
        next_decision = None
    else:
        next_decision = proposed.next_decision
    return (
        FounderTruth.model_validate(
            {
                **proposed.model_dump(),
                "known": known,
                "believed": believed,
                "evidence_gaps": gaps,
                "bottleneck": None if unsupported else proposed.bottleneck,
                "next_decision": next_decision,
            }
        ),
        unsupported,
    )


def _intake_frameworks() -> tuple[FrameworkReference, ...]:
    return tuple(
        FrameworkReference.model_validate(resource.metadata.model_dump())
        for resource in load_framework_catalog().for_role(Role.INTAKE)
        if resource.metadata.id == "founder_truth"
    )


def _research_lineage(state: CompanyState) -> ArtifactEnvelope:
    research = _latest(state, ArtifactType.RESEARCH)
    if research is None:
        message = "validated research is missing"
        raise JourneyInputError(message)
    return research


def _numeric_tokens(text: str) -> set[str]:
    normalized = "".join(
        character if character.isdigit() or character in ".," else " " for character in text
    )
    return {token.strip(".,") for token in normalized.split() if token.strip(".,")}


def _has_retained_mappings(result: ResearchResult) -> bool:
    sources = {source.source_id: source for source in result.sources}
    return bool(result.claims) and all(
        claim.support_status == "mapped"
        and bool(claim.support_segments)
        and all(
            any(
                (source := sources.get(source_id)) is not None and segment in source.excerpt
                for source_id in claim.source_ids
            )
            for segment in claim.support_segments
        )
        for claim in result.claims
    )


def _supported_research_claim(research: ArtifactEnvelope) -> SourcedClaim | None:
    sources = {source.source_id: source for source in research.sources}
    return next(
        (
            claim
            for claim in research.claims
            if claim.support_status == "mapped"
            and claim.verification_status == "supported"
            and bool(claim.support_segments)
            and all(
                any(
                    (source := sources.get(source_id)) is not None and segment in source.excerpt
                    for source_id in claim.source_ids
                )
                for segment in claim.support_segments
            )
        ),
        None,
    )


def _has_critical_contradiction(research: ArtifactEnvelope) -> bool:
    return bool(ResearchArtifact.model_validate(research.payload).conflicts) or any(
        claim.verification_status == "contradicted" for claim in research.claims
    )


def _offer_framework() -> FrameworkReference:
    references = tuple(
        FrameworkReference.model_validate(resource.metadata.model_dump())
        for resource in load_framework_catalog().for_role(Role.STRATEGIST)
        if resource.metadata.id == "offer_diagnostic"
    )
    if len(references) != 1:
        message = "reviewed offer framework is unavailable"
        raise JourneyInputError(message)
    return references[0]


def _offer_diagnostic(draft: _StrategyDraft, supported_problem: str) -> OfferDiagnostic:
    proposed = draft.offer_diagnostic
    if proposed is None:
        proposed = _OfferDiagnosticDraft(
            market=draft.ideal_customer_profile,
            painful_problem=supported_problem,
            purchasing_power_assumption=(
                "Purchasing power requires retained willingness-to-pay evidence."
            ),
            draft_offer=draft.offer,
            evidence_needed=("Retained willingness-to-pay evidence.",),
        )
    return OfferDiagnostic(
        market=proposed.market,
        painful_problem=supported_problem,
        purchasing_power_assumption=Assumption(
            assumption_id=uuid4(), text=proposed.purchasing_power_assumption
        ),
        draft_offer=proposed.draft_offer,
        evidence_needed=proposed.evidence_needed,
        framework=_offer_framework(),
    )


async def _agent_payload[PayloadT: BaseModel](
    agent: ResearchAgent, prompt: str, schema: type[PayloadT]
) -> PayloadT:
    output = await agent.arun(prompt, stream=False)
    content = output.content
    if isinstance(content, str):
        return schema.model_validate_json(content)
    if isinstance(content, BaseModel):
        return schema.model_validate(content.model_dump())
    return schema.model_validate(content)


@dataclass(frozen=True, slots=True)
class _Journey:
    db: BaseDb
    intake_agent: ResearchAgent
    research_agent: ResearchAgent
    strategy_agent: ResearchAgent
    product_agent: ResearchAgent
    verifier_agent: ResearchAgent

    async def intake(
        self, step_input: StepInput, run_context: RunContext | None = None
    ) -> StepOutput:
        context = _context(run_context)
        request = _request(step_input)
        try:
            state = load_company_state(
                request,
                context,
                created_at=datetime.now(UTC),
                db=self.db,
            )
        except (
            CompanyMismatchError,
            SessionMismatchError,
            StaleRevisionError,
            WorkflowContextError,
        ) as error:
            return _step_output(_boundary_failure(error), stop=True)
        verified = _latest(state, ArtifactType.VERIFICATION)
        if verified is not None and verified.status == "complete":
            return _step_output(_result(state, "verified"), stop=True)
        prior = _latest(state, ArtifactType.INTAKE)
        existing = IntakeArtifact.model_validate(prior.payload).brief if prior is not None else None
        try:
            brief = _brief(request, existing)
        except JourneyInputError as error:
            return _step_output(_boundary_failure(error), stop=True)
        if (
            existing is not None
            and prior is not None
            and existing.model_dump(exclude={"open_questions", "next_actions"})
            == brief.model_dump(exclude={"open_questions", "next_actions"})
        ):
            return _step_output(prior)
        proposed = await _agent_payload(
            self.intake_agent,
            brief.model_dump_json(),
            _IntakeDraft,
        )
        founder_truth, unsupported_known = _verified_founder_truth(proposed.founder_truth, brief)
        missing = tuple(name for name in REQUIRED_CONTEXT if getattr(brief, name) is None)
        brief = brief.model_copy(
            update={
                "open_questions": [QUESTIONS[name] for name in missing],
                "next_actions": []
                if unsupported_known or founder_truth.next_decision is None
                else proposed.brief.next_actions,
            }
        )
        findings = [
            VerificationFinding(
                code="founder_context_retained",
                message="Founder input retained without treating it as market evidence.",
                severity="info",
            )
        ]
        if unsupported_known:
            findings.append(
                VerificationFinding(
                    code="unsupported_known_claim",
                    message="Claims without retained context or evidence remain beliefs.",
                    severity="warning",
                )
            )
        truth_incomplete = founder_truth.bottleneck is None or founder_truth.next_decision is None
        if truth_incomplete:
            findings.append(
                VerificationFinding(
                    code="founder_decision_missing",
                    message="The current bottleneck and one next founder decision are required.",
                    severity="warning",
                )
            )
        statements = tuple(
            FounderStatement(statement_id=uuid4(), text=value)
            for value in (brief.idea, *(getattr(brief, name) for name in REQUIRED_CONTEXT))
            if value
        )
        envelope = _envelope(
            state,
            _ArtifactCandidate(
                payload=IntakeArtifact(
                    brief=brief,
                    founder_truth=founder_truth,
                    frameworks=_intake_frameworks(),
                ),
                producer=Role.INTAKE,
                status="needs_input"
                if missing or unsupported_known or truth_incomplete
                else "complete",
                findings=tuple(findings),
                founder_statements=statements,
                assumptions=tuple(
                    Assumption(assumption_id=uuid4(), text=text)
                    for text in (*brief.assumptions, *unsupported_known)
                ),
            ),
        )
        _ = _save(state, envelope, context, self.db)
        return _step_output(envelope)

    def brief_check(
        self, _step_input: StepInput, run_context: RunContext | None = None
    ) -> StepOutput:
        state = _state(_context(run_context))
        intake = _latest(state, ArtifactType.INTAKE)
        payload = IntakeArtifact.model_validate(intake.payload if intake is not None else None)
        brief = payload.brief
        missing = tuple(name for name in REQUIRED_CONTEXT if getattr(brief, name) is None)
        truth_questions = tuple(
            question
            for present, question in (
                (
                    payload.founder_truth.bottleneck is not None,
                    "What uncertainty is the current bottleneck?",
                ),
                (
                    payload.founder_truth.next_decision is not None,
                    "What one founder decision should come next?",
                ),
                (
                    intake is not None
                    and not any(
                        finding.code == "unsupported_known_claim"
                        for finding in intake.verification_findings
                    ),
                    EVIDENCE_DECISION,
                ),
            )
            if not present
        )
        if missing or truth_questions:
            return _step_output(
                _result(
                    state,
                    "needs_input",
                    questions=(*tuple(QUESTIONS[name] for name in missing), *truth_questions),
                ),
                stop=True,
            )
        return _step_output(ArtifactEnvelope.model_validate(intake))

    async def research(
        self, _step_input: StepInput, run_context: RunContext | None = None
    ) -> StepOutput:
        state = _state(_context(run_context))
        prior = _latest(state, ArtifactType.RESEARCH)
        if prior is not None and prior.status == "complete":
            return _step_output(prior)
        intake = _latest(state, ArtifactType.INTAKE)
        brief = IntakeArtifact.model_validate(intake.payload if intake is not None else None).brief
        result = await run_research(self.research_agent, brief)
        return StepOutput(content=RESEARCH_RESULT_ADAPTER.dump_json(result).decode())

    def evidence_check(
        self, step_input: StepInput, run_context: RunContext | None = None
    ) -> StepOutput:
        context = _context(run_context)
        state = _state(context)
        previous = step_input.previous_step_content
        try:
            prior = ArtifactEnvelope.model_validate(previous)
        except ValidationError:
            prior = None
        if prior is not None:
            return _step_output(prior)
        try:
            research = (
                RESEARCH_RESULT_ADAPTER.validate_json(previous)
                if isinstance(previous, str)
                else RESEARCH_RESULT_ADAPTER.validate_python(previous)
            )
        except ValidationError as error:
            message = "research result is missing"
            raise JourneyInputError(message) from error
        mapped = _has_retained_mappings(research)
        outcome = (
            "complete" if research.status == "complete" and mapped else "insufficient_evidence"
        )
        findings = (
            *research.verification_findings,
            VerificationFinding(
                code="research_lineage_valid"
                if outcome == "complete"
                else "research_evidence_blocked",
                message=(
                    "Grounding segments and source IDs were retained; factual claims "
                    "remain unverified."
                )
                if outcome == "complete"
                else "Research is unmapped or lacks retained support content.",
                severity="info" if outcome == "complete" else "warning",
            ),
            *(
                (
                    VerificationFinding(
                        code="research_conflicts_retained",
                        message=(
                            "Research conflicts were retained for final verification; "
                            "factual claims remain unverified."
                        ),
                        severity="warning",
                    ),
                )
                if research.payload.conflicts and outcome == "complete"
                else ()
            ),
        )
        envelope = _envelope(
            state,
            _ArtifactCandidate(
                payload=research.payload,
                producer=Role.RESEARCHER,
                status=outcome,
                findings=findings,
                sources=research.sources,
                claims=research.claims,
                assumptions=research.assumptions,
            ),
        )
        updated = _save(state, envelope, context, self.db)
        return _step_output(
            envelope if outcome == "complete" else _result(updated, outcome),
            stop=outcome != "complete",
        )

    async def strategy(
        self, _step_input: StepInput, run_context: RunContext | None = None
    ) -> StepOutput:
        context = _context(run_context)
        state = _state(context)
        prior = _latest(state, ArtifactType.STRATEGY)
        if prior is not None:
            return _step_output(prior)
        research = _research_lineage(state)
        if _has_critical_contradiction(research):
            return _step_output(_result(state, "needs_rework"), stop=True)
        supported_claim = _supported_research_claim(research)
        if supported_claim is None:
            return _step_output(
                _result(
                    state,
                    "needs_input",
                    questions=("What retained source segment supports the painful problem?",),
                ),
                stop=True,
            )
        draft = await _agent_payload(
            self.strategy_agent,
            state.model_dump_json(),
            _StrategyDraft,
        )
        diagnostic = _offer_diagnostic(draft, supported_claim.text)
        payload = StrategyArtifact.model_validate(
            {**draft.model_dump(exclude={"offer_diagnostic"}), "offer_diagnostic": diagnostic}
        )
        conflicts = ResearchArtifact.model_validate(research.payload).conflicts
        envelope = _envelope(
            state,
            _ArtifactCandidate(
                payload=payload,
                producer=Role.STRATEGIST,
                status="draft_only",
                findings=(
                    *tuple(
                        finding
                        for finding in research.verification_findings
                        if finding.code == "research_conflicts_retained"
                    ),
                    VerificationFinding(
                        code="strategy_provisional" if conflicts else "strategy_typed",
                        message=(
                            f"Strategy schema validated as provisional; {UNRESOLVED_RESEARCH}"
                            if conflicts
                            else "Strategy schema validated."
                        ),
                        severity="warning" if conflicts else "info",
                    ),
                ),
                sources=research.sources,
                claims=research.claims,
                assumptions=(
                    *tuple(
                        Assumption(assumption_id=uuid4(), text=text)
                        for text in (
                            *payload.pricing_assumptions,
                            payload.offer,
                            diagnostic.draft_offer,
                        )
                    ),
                    diagnostic.purchasing_power_assumption,
                ),
            ),
        )
        _ = _save(state, envelope, context, self.db)
        return _step_output(envelope)

    async def product(
        self, _step_input: StepInput, run_context: RunContext | None = None
    ) -> StepOutput:
        context = _context(run_context)
        state = _state(context)
        prior = _latest(state, ArtifactType.PRODUCT_PLAN)
        if prior is not None:
            return _step_output(prior)
        research = _research_lineage(state)
        draft = await _agent_payload(
            self.product_agent,
            state.model_dump_json(),
            _ProductDraft,
        )
        payload = ProductPlanArtifact.model_validate(draft.model_dump())
        conflicts = ResearchArtifact.model_validate(research.payload).conflicts
        envelope = _envelope(
            state,
            _ArtifactCandidate(
                payload=payload,
                producer=Role.PRODUCT_MANAGER,
                status="complete",
                findings=(
                    *tuple(
                        finding
                        for finding in research.verification_findings
                        if finding.code == "research_conflicts_retained"
                    ),
                    VerificationFinding(
                        code="product_provisional" if conflicts else "product_typed",
                        message=(
                            f"Product plan schema validated as provisional; {UNRESOLVED_RESEARCH}"
                            if conflicts
                            else "Product plan schema validated."
                        ),
                        severity="warning" if conflicts else "info",
                    ),
                ),
                sources=research.sources,
                claims=research.claims,
            ),
        )
        _ = _save(state, envelope, context, self.db)
        return _step_output(envelope)

    async def verify(
        self, _step_input: StepInput, run_context: RunContext | None = None
    ) -> StepOutput:
        context = _context(run_context)
        state = _state(context)
        if any(_latest(state, kind) is None for kind in JOURNEY_TYPES[:-1]):
            return _step_output(
                _result(
                    state,
                    "needs_input",
                    questions=(
                        "Finish research, strategy and delivery planning before full verification.",
                    ),
                ),
                stop=True,
            )
        proposal = await _agent_payload(
            self.verifier_agent,
            state.model_dump_json(),
            _VerificationDraft,
        )
        upstream = tuple(_latest(state, artifact_type) for artifact_type in JOURNEY_TYPES[:-1])
        accepted = tuple(artifact for artifact in upstream if artifact is not None)
        research = ResearchArtifact.model_validate(accepted[1].payload)
        intake_truth = IntakeArtifact.model_validate(accepted[0].payload).founder_truth
        supported_text = " ".join(claim.text for claim in accepted[1].claims)
        numbers: set[str] = {
            token
            for assumption in accepted[2].assumptions
            for token in _numeric_tokens(assumption.text)
        }
        unsupported = tuple(sorted(token for token in numbers if token not in supported_text))
        outcome = "needs_rework" if unsupported or research.conflicts else proposal.outcome
        findings: list[VerificationFinding] = []
        if research.conflicts:
            findings.append(
                VerificationFinding(
                    code="research_conflicts_unresolved",
                    message=(
                        "Retained research conflicts require resolution before "
                        "verification; factual claims remain unverified."
                    ),
                    severity="warning",
                )
            )
        if unsupported:
            findings.append(
                VerificationFinding(
                    code="unsupported_numeric_claim",
                    message=f"Unsupported numeric claims: {', '.join(unsupported)}",
                    severity="warning",
                )
            )
        if not findings:
            fallback = {
                "verified": VerificationFinding(
                    code="journey_verified",
                    message=(
                        "Schema, lineage, and retained support mappings passed; market "
                        "demand, pricing, and source factualness remain unverified."
                    ),
                    severity="info",
                ),
                "needs_input": VerificationFinding(
                    code="verifier_follow_up_required",
                    message="The verifier requested founder input before verification.",
                    severity="warning",
                ),
                "needs_rework": VerificationFinding(
                    code="verifier_rework_requested",
                    message="The verifier requested rework before verification.",
                    severity="warning",
                ),
            }
            findings.append(fallback[outcome])
        if any((intake_truth.known, intake_truth.believed, intake_truth.hoped)):
            findings.append(
                VerificationFinding(
                    code="founder_truth_distinction_retained",
                    message=(
                        "Known, believed, and hoped statements retained their Intake categories."
                    ),
                    severity="info",
                )
            )
        envelope = _envelope(
            state,
            _ArtifactCandidate(
                payload=VerificationArtifact(
                    checked_artifact_ids=tuple(artifact.artifact_id for artifact in accepted),
                    outcome=outcome,
                ),
                producer=Role.VERIFIER,
                status="complete" if outcome == "verified" else outcome,
                findings=tuple(findings),
            ),
        )
        updated = _save(state, envelope, context, self.db)
        questions = (
            ("Which founder decision remains unresolved before verification?",)
            if outcome == "needs_input"
            else ()
        )
        return _step_output(_result(updated, outcome, questions=questions))


def create_company_workflow(
    db: BaseDb, settings: Settings, *, stage: JourneyStage = "plan"
) -> Workflow:
    """Create the ordered company journey without registering it in AgentOS."""
    catalog = create_role_catalog(settings)
    journey = _Journey(
        db=db,
        intake_agent=catalog[Role.INTAKE].agent,
        research_agent=catalog[Role.RESEARCHER].agent,
        strategy_agent=catalog[Role.STRATEGIST].agent,
        product_agent=catalog[Role.PRODUCT_MANAGER].agent,
        verifier_agent=catalog[Role.VERIFIER].agent,
    )
    steps: list[WorkflowStep] = [
        Step(name="Intake", executor=journey.intake, max_retries=0),
        Step(name="Verify brief", executor=journey.brief_check, max_retries=0),
        Step(name="Research", executor=journey.research, max_retries=0),
        Step(name="Verify evidence", executor=journey.evidence_check, max_retries=0),
        Step(name="Strategy", executor=journey.strategy, max_retries=0),
        Step(name="Product plan", executor=journey.product, max_retries=0),
        Step(name="Verify journey", executor=journey.verify, max_retries=0),
    ]
    if stage == "verify":

        def load_existing(
            step_input: StepInput, run_context: RunContext | None = None
        ) -> StepOutput:
            context = _context(run_context)
            try:
                state = load_company_state(
                    _request(step_input), context, created_at=datetime.now(UTC)
                )
            except (
                CompanyMismatchError,
                SessionMismatchError,
                StaleRevisionError,
                WorkflowContextError,
            ) as error:
                return _step_output(_boundary_failure(error), stop=True)
            return _step_output(state)

        steps = [
            Step(name="Load existing company", executor=load_existing, max_retries=0),
            Step(name="Verify journey", executor=journey.verify, max_retries=0),
        ]
    elif stage != "plan":
        questions = {
            "brief": "Ready to research your market?",
            "research": "Ready to shape your offer?",
            "strategy": "Ready to plan the first version?",
        }

        def pause(_step_input: StepInput, run_context: RunContext | None = None) -> StepOutput:
            return _step_output(
                _result(
                    _state(_context(run_context)), "needs_input", questions=(questions[stage],)
                ),
                stop=True,
            )

        steps = steps[: {"brief": 2, "research": 4, "strategy": 5}[stage]]
        steps.append(Step(name="Await founder decision", executor=pause, max_retries=0))
    return Workflow(
        id=WORKFLOW_ID,
        name="Samurai verified company journey",
        db=db,
        input_schema=CompanyJourneyRequest,
        steps=steps,
        store_events=True,
        telemetry=False,
    )
