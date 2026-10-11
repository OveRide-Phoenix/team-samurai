"""Ordered company-journey state machine kept intact for native step review. # noqa: SIZE_OK."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Literal, Self, override
from uuid import uuid4

from agno.workflow import Step, StepInput, StepOutput, Workflow
from pydantic import BaseModel, Field, model_validator
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
    FounderStatement,
    IntakeArtifact,
    ProductPlanArtifact,
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
from samurai.research import ResearchAgent, ResearchResult, run_research
from samurai.workflow_state import WorkflowContextError, load_company_state, save_company_state

if TYPE_CHECKING:
    from agno.db.base import BaseDb
    from agno.run import RunContext

    from samurai.config import Settings

WORKFLOW_ID = "company-journey"
REQUIRED_CONTEXT = ("target_customer", "geography", "budget", "founder_skills", "goal")
QUESTIONS = {
    "target_customer": "Who is the first target customer?",
    "geography": "Which geography should the company serve first?",
    "budget": "What budget can you commit?",
    "founder_skills": "Which founder skills can support delivery?",
    "goal": "What outcome and timeframe define success?",
}
JOURNEY_TYPES = (
    ArtifactType.INTAKE,
    ArtifactType.RESEARCH,
    ArtifactType.STRATEGY,
    ArtifactType.PRODUCT_PLAN,
    ArtifactType.VERIFICATION,
)
type ArtifactStatus = Literal["complete", "insufficient_evidence", "needs_input", "needs_rework"]
type FailureCode = Literal["invalid_context", "invalid_revision", "invalid_company_input"]


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


class _StrategyDraft(BaseModel):
    ideal_customer_profile: str
    positioning: str
    offer: str
    pricing_assumptions: tuple[str, ...]


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


def _save(state: CompanyState, envelope: ArtifactEnvelope, run_context: RunContext) -> CompanyState:
    updated = accept_artifact(
        state,
        envelope,
        authenticated_session_id=state.context.authenticated_session_id,
    )
    save_company_state(updated, run_context)
    return updated


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
            state = load_company_state(request, context, created_at=datetime.now(UTC))
        except (
            CompanyMismatchError,
            SessionMismatchError,
            StaleRevisionError,
            WorkflowContextError,
        ) as error:
            return StepOutput(content=_boundary_failure(error), stop=True)
        verified = _latest(state, ArtifactType.VERIFICATION)
        if verified is not None and verified.status == "complete":
            return StepOutput(content=_result(state, "verified"), stop=True)
        prior = _latest(state, ArtifactType.INTAKE)
        existing = IntakeArtifact.model_validate(prior.payload).brief if prior is not None else None
        try:
            brief = _brief(request, existing)
        except JourneyInputError as error:
            return StepOutput(content=_boundary_failure(error), stop=True)
        if existing == brief and prior is not None:
            return StepOutput(content=prior)
        proposed = await _agent_payload(
            self.intake_agent,
            brief.model_dump_json(),
            _IntakeDraft,
        )
        missing = tuple(name for name in REQUIRED_CONTEXT if getattr(brief, name) is None)
        brief = brief.model_copy(
            update={
                "open_questions": [QUESTIONS[name] for name in missing],
                "next_actions": proposed.brief.next_actions,
            }
        )
        finding = VerificationFinding(
            code="founder_context_retained",
            message="Founder input retained without treating it as market evidence.",
            severity="info",
        )
        statements = tuple(
            FounderStatement(statement_id=uuid4(), text=value)
            for value in (brief.idea, *(getattr(brief, name) for name in REQUIRED_CONTEXT))
            if value
        )
        envelope = _envelope(
            state,
            _ArtifactCandidate(
                payload=IntakeArtifact(brief=brief),
                producer=Role.INTAKE,
                status="needs_input"
                if any(getattr(brief, name) is None for name in REQUIRED_CONTEXT)
                else "complete",
                findings=(finding,),
                founder_statements=statements,
                assumptions=tuple(
                    Assumption(assumption_id=uuid4(), text=text) for text in brief.assumptions
                ),
            ),
        )
        _ = _save(state, envelope, context)
        return StepOutput(content=envelope)

    def brief_check(
        self, _step_input: StepInput, run_context: RunContext | None = None
    ) -> StepOutput:
        state = _state(_context(run_context))
        intake = _latest(state, ArtifactType.INTAKE)
        brief = IntakeArtifact.model_validate(intake.payload if intake is not None else None).brief
        missing = tuple(name for name in REQUIRED_CONTEXT if getattr(brief, name) is None)
        if missing:
            return StepOutput(
                content=_result(
                    state,
                    "needs_input",
                    questions=tuple(QUESTIONS[name] for name in missing),
                ),
                stop=True,
            )
        return StepOutput(content=intake)

    async def research(
        self, _step_input: StepInput, run_context: RunContext | None = None
    ) -> StepOutput:
        state = _state(_context(run_context))
        prior = _latest(state, ArtifactType.RESEARCH)
        if prior is not None and prior.status == "complete":
            return StepOutput(content=prior)
        intake = _latest(state, ArtifactType.INTAKE)
        brief = IntakeArtifact.model_validate(intake.payload if intake is not None else None).brief
        return StepOutput(content=await run_research(self.research_agent, brief))

    def evidence_check(
        self, step_input: StepInput, run_context: RunContext | None = None
    ) -> StepOutput:
        context = _context(run_context)
        state = _state(context)
        if isinstance(step_input.previous_step_content, ArtifactEnvelope):
            return StepOutput(content=step_input.previous_step_content)
        research = step_input.previous_step_content
        if not isinstance(research, ResearchResult):
            message = "research result is missing"
            raise JourneyInputError(message)
        mapped = _has_retained_mappings(research)
        outcome = (
            "needs_rework"
            if research.payload.conflicts
            else "complete"
            if research.status == "complete" and mapped
            else "insufficient_evidence"
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
                else "Research is conflicting, unmapped, or lacks retained support content.",
                severity="info" if outcome == "complete" else "warning",
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
        updated = _save(state, envelope, context)
        return StepOutput(
            content=envelope if outcome == "complete" else _result(updated, outcome),
            stop=outcome != "complete",
        )

    async def strategy(
        self, _step_input: StepInput, run_context: RunContext | None = None
    ) -> StepOutput:
        context = _context(run_context)
        state = _state(context)
        prior = _latest(state, ArtifactType.STRATEGY)
        if prior is not None:
            return StepOutput(content=prior)
        research = _research_lineage(state)
        draft = await _agent_payload(
            self.strategy_agent,
            state.model_dump_json(),
            _StrategyDraft,
        )
        payload = StrategyArtifact.model_validate(draft.model_dump())
        envelope = _envelope(
            state,
            _ArtifactCandidate(
                payload=payload,
                producer=Role.STRATEGIST,
                status="complete",
                findings=(
                    VerificationFinding(
                        code="strategy_typed",
                        message="Strategy schema validated.",
                        severity="info",
                    ),
                ),
                sources=research.sources,
                claims=research.claims,
                assumptions=tuple(
                    Assumption(assumption_id=uuid4(), text=text)
                    for text in payload.pricing_assumptions
                ),
            ),
        )
        _ = _save(state, envelope, context)
        return StepOutput(content=envelope)

    async def product(
        self, _step_input: StepInput, run_context: RunContext | None = None
    ) -> StepOutput:
        context = _context(run_context)
        state = _state(context)
        prior = _latest(state, ArtifactType.PRODUCT_PLAN)
        if prior is not None:
            return StepOutput(content=prior)
        research = _research_lineage(state)
        draft = await _agent_payload(
            self.product_agent,
            state.model_dump_json(),
            _ProductDraft,
        )
        payload = ProductPlanArtifact.model_validate(draft.model_dump())
        envelope = _envelope(
            state,
            _ArtifactCandidate(
                payload=payload,
                producer=Role.PRODUCT_MANAGER,
                status="complete",
                findings=(
                    VerificationFinding(
                        code="product_typed",
                        message="Product plan schema validated.",
                        severity="info",
                    ),
                ),
                sources=research.sources,
                claims=research.claims,
            ),
        )
        _ = _save(state, envelope, context)
        return StepOutput(content=envelope)

    async def verify(
        self, _step_input: StepInput, run_context: RunContext | None = None
    ) -> StepOutput:
        context = _context(run_context)
        state = _state(context)
        proposal = await _agent_payload(
            self.verifier_agent,
            state.model_dump_json(),
            _VerificationDraft,
        )
        upstream = tuple(_latest(state, artifact_type) for artifact_type in JOURNEY_TYPES[:-1])
        accepted = tuple(artifact for artifact in upstream if artifact is not None)
        strategy = StrategyArtifact.model_validate(accepted[2].payload)
        supported_text = " ".join(claim.text for claim in accepted[1].claims)
        numbers: set[str] = {
            token
            for assumption in strategy.pricing_assumptions
            for token in _numeric_tokens(assumption)
        }
        unsupported = tuple(sorted(token for token in numbers if token not in supported_text))
        outcome = "needs_rework" if unsupported else proposal.outcome
        finding = VerificationFinding(
            code="unsupported_numeric_claim" if unsupported else "journey_verified",
            message=f"Unsupported numeric claims: {', '.join(unsupported)}"
            if unsupported
            else (
                "Schema, lineage, and retained support mappings passed; market demand, "
                "pricing, and source factualness remain unverified."
            ),
            severity="warning" if unsupported else "info",
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
                findings=(finding,),
            ),
        )
        updated = _save(state, envelope, context)
        questions = (
            ("Which founder decision remains unresolved before verification?",)
            if outcome == "needs_input"
            else ()
        )
        return StepOutput(content=_result(updated, outcome, questions=questions))


def create_company_workflow(db: BaseDb, settings: Settings) -> Workflow:
    """Create the ordered company journey without registering it in AgentOS."""
    catalog = create_role_catalog(settings)
    journey = _Journey(
        intake_agent=catalog[Role.INTAKE].agent,
        research_agent=catalog[Role.RESEARCHER].agent,
        strategy_agent=catalog[Role.STRATEGIST].agent,
        product_agent=catalog[Role.PRODUCT_MANAGER].agent,
        verifier_agent=catalog[Role.VERIFIER].agent,
    )
    return Workflow(
        id=WORKFLOW_ID,
        name="Samurai verified company journey",
        db=db,
        input_schema=CompanyJourneyRequest,
        steps=[
            Step(name="Intake", executor=journey.intake, max_retries=0),
            Step(name="Verify brief", executor=journey.brief_check, max_retries=0),
            Step(name="Research", executor=journey.research, max_retries=0),
            Step(name="Verify evidence", executor=journey.evidence_check, max_retries=0),
            Step(name="Strategy", executor=journey.strategy, max_retries=0),
            Step(name="Product plan", executor=journey.product, max_retries=0),
            Step(name="Verify journey", executor=journey.verify, max_retries=0),
        ],
        store_events=True,
        telemetry=False,
    )
