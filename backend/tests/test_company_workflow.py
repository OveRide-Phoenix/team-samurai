"""Company journey state-machine acceptance scenarios. # noqa: SIZE_OK."""

from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Never, final, override
from uuid import uuid4

import anyio
import pytest
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.workflow import WorkflowRunOutput
from agno.workflow import StepOutput
from pydantic import HttpUrl, JsonValue, ValidationError

from samurai.agents import ROLE_CAPABILITIES, ConfiguredRole
from samurai.company_workflow import (
    CompanyJourneyFailure,
    CompanyJourneyRequest,
    create_company_workflow,
)
from samurai.config import Settings
from samurai.contracts import (
    Assumption,
    CompanyBrief,
    CompanyMismatchError,
    CompanyState,
    IntakeArtifact,
    ProductPlanArtifact,
    ResearchArtifact,
    Role,
    SourcedClaim,
    SourceReference,
    StaleRevisionError,
    StrategyArtifact,
    VerificationArtifact,
    VerificationFinding,
    WorkflowRequest,
    WorkflowResult,
)
from samurai.research import ResearchAgent, ResearchResult
from samurai.workflow_state import WorkflowContextError, load_company_state, save_company_state

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Mapping
    from pathlib import Path

    from agno.models.message import Message
    from agno.workflow import Workflow


def _run_context(
    *,
    user_id: str = "founder-1",
    session_id: str = "child-1",
    trusted_child_session_id: str | None = None,
) -> RunContext:
    return RunContext(
        run_id="run-1",
        session_id=session_id,
        user_id=user_id,
        dependencies={
            "trusted_parent_session_id": "parent-1",
            "trusted_user_id": "founder-1",
            "child_session_id": trusted_child_session_id or session_id,
        },
        session_state={},
    )


def test_workflow_request_distinguishes_new_company_from_continuation() -> None:
    # Given the shared new-company and continuation request shapes.
    company_id = uuid4()

    # When parsed at the workflow boundary.
    new = WorkflowRequest(company_id=None, expected_revision=0)
    continuation = WorkflowRequest(company_id=company_id, expected_revision=0)

    # Then both valid states remain explicit and ambiguous new revisions fail closed.
    assert new.company_id is None
    assert continuation.company_id == company_id
    with pytest.raises(ValidationError, match="new company requests must start at revision zero"):
        _ = WorkflowRequest(company_id=None, expected_revision=1)


def test_workflow_result_requires_questions_only_for_missing_input() -> None:
    # Given a workflow result at a founder decision boundary.
    company_id = uuid4()

    # When the result needs input, then it carries at least one concise question.
    result = WorkflowResult(
        company_id=company_id,
        revision=1,
        outcome="needs_input",
        questions=("What budget can you commit?",),
    )
    assert result.questions == ("What budget can you commit?",)

    # When the result is terminal, then questions are rejected as stale UI state.
    with pytest.raises(ValidationError, match="questions are only valid for needs_input"):
        _ = WorkflowResult(
            company_id=company_id,
            revision=1,
            outcome="verified",
            questions=("This should not remain",),
        )
    with pytest.raises(ValidationError, match="at least 1 character"):
        _ = WorkflowResult(
            company_id=company_id,
            revision=1,
            outcome="needs_input",
            questions=("",),
        )


def test_context_boundary_creates_and_saves_only_canonical_child_state() -> None:
    # Given trusted native workflow context with a distinct child session.
    run_context = _run_context()
    parent_binding = {
        "company_id": None,
        "child_session_id": "child-1",
        "current_revision": 0,
    }

    # When a first request creates and saves canonical company state.
    state = load_company_state(
        WorkflowRequest(company_id=None, expected_revision=0),
        run_context,
        created_at=datetime(2026, 10, 11, tzinfo=UTC),
    )
    save_company_state(state, run_context)

    # Then canonical state belongs to the trusted parent binding without mutating it.
    assert state.context.authenticated_session_id == "parent-1"
    assert run_context.session_state == {"company": state.model_dump(mode="json")}
    assert parent_binding == {
        "company_id": None,
        "child_session_id": "child-1",
        "current_revision": 0,
    }


def test_context_boundary_rejects_identity_session_company_and_revision_mismatch() -> None:
    # Given canonical state created under trusted user, parent, and child bindings.
    run_context = _run_context()
    state = load_company_state(
        WorkflowRequest(company_id=None, expected_revision=0),
        run_context,
        created_at=datetime(2026, 10, 11, tzinfo=UTC),
    )
    save_company_state(state, run_context)

    # When any caller-controlled binding differs, then loading fails before model work.
    with pytest.raises(WorkflowContextError, match="trusted user does not match"):
        _ = load_company_state(
            WorkflowRequest(company_id=state.context.company_id, expected_revision=0),
            _run_context(user_id="attacker"),
            created_at=datetime(2026, 10, 11, tzinfo=UTC),
        )
    with pytest.raises(WorkflowContextError, match="child session does not match"):
        _ = load_company_state(
            WorkflowRequest(company_id=state.context.company_id, expected_revision=0),
            _run_context(session_id="other-child", trusted_child_session_id="child-1"),
            created_at=datetime(2026, 10, 11, tzinfo=UTC),
        )
    with pytest.raises(CompanyMismatchError):
        _ = load_company_state(
            WorkflowRequest(company_id=uuid4(), expected_revision=0),
            run_context,
            created_at=datetime(2026, 10, 11, tzinfo=UTC),
        )
    with pytest.raises(StaleRevisionError):
        _ = load_company_state(
            WorkflowRequest(company_id=state.context.company_id, expected_revision=1),
            run_context,
            created_at=datetime(2026, 10, 11, tzinfo=UTC),
        )


def test_save_rejects_canonical_history_rewrite() -> None:
    # Given canonical state already saved in the child workflow session.
    run_context = _run_context()
    first = load_company_state(
        WorkflowRequest(company_id=None, expected_revision=0),
        run_context,
        created_at=datetime(2026, 10, 11, tzinfo=UTC),
    )
    save_company_state(first, run_context)
    replacement = load_company_state(
        WorkflowRequest(company_id=None, expected_revision=0),
        _run_context(session_id="child-2"),
        created_at=datetime(2026, 10, 11, tzinfo=UTC),
    )

    # When another company state targets the same child session, then save fails closed.
    with pytest.raises(WorkflowContextError, match="cannot rewrite canonical company history"):
        save_company_state(replacement, run_context)


@final
class _StaticModel(Model):
    def __init__(
        self,
        content: (
            IntakeArtifact
            | ResearchArtifact
            | StrategyArtifact
            | ProductPlanArtifact
            | VerificationArtifact
        ),
    ) -> None:
        super().__init__(id="static", name="Static", provider="test")
        self.id: str = "static"
        self.content: (
            IntakeArtifact
            | ResearchArtifact
            | StrategyArtifact
            | ProductPlanArtifact
            | VerificationArtifact
        ) = content
        self.calls: int = 0

    @override
    def invoke(self, *_args: Never, **_kwargs: Never) -> ModelResponse:
        return ModelResponse()

    @override
    async def ainvoke(self, messages: list[Message], **_kwargs: Never) -> ModelResponse:
        assert messages
        self.calls += 1
        raw = self.content.model_dump_json()
        if isinstance(self.content, IntakeArtifact):
            raw = raw.replace('"artifact_type":"intake"', '"artifact_type":"founder_intake"')
        return ModelResponse(content=raw)

    @override
    def invoke_stream(self, *_args: Never, **_kwargs: Never) -> Iterator[ModelResponse]:
        return iter(())

    @override
    async def ainvoke_stream(self, *_args: Never, **_kwargs: Never) -> AsyncIterator[ModelResponse]:
        yield ModelResponse()

    @override
    def _parse_provider_response(self, response: ModelResponse, **_kwargs: Never) -> ModelResponse:
        return response

    @override
    def _parse_provider_response_delta(self, response: ModelResponse) -> ModelResponse:
        return response


def _settings() -> Settings:
    return Settings.model_validate(
        {
            "os_security_key": "x" * 32,
            "database_url": "postgresql+psycopg://samurai:test@localhost:5432/samurai",
        }
    )


def _catalog(
    *, pricing_assumptions: tuple[str, ...] = ("Validate willingness to pay.",)
) -> tuple[Mapping[Role, ConfiguredRole], dict[Role, _StaticModel]]:
    outputs = {
        Role.INTAKE: IntakeArtifact(
            brief=CompanyBrief(
                idea="model proposal is never trusted as founder input",
                target_customer="invented",
                geography="invented",
                budget="invented",
                founder_skills="invented",
                goal="invented",
                supplied_context=[],
                assumptions=[],
                open_questions=[],
                next_actions=["Answer the remaining founder questions."],
            )
        ),
        Role.RESEARCHER: ResearchArtifact(summary="unused test research", conflicts=()),
        Role.STRATEGIST: StrategyArtifact(
            ideal_customer_profile="Independent Indian dental clinics",
            positioning="Recover missed patient calls",
            offer="A managed receptionist pilot",
            pricing_assumptions=pricing_assumptions,
        ),
        Role.PRODUCT_MANAGER: ProductPlanArtifact(
            minimum_viable_offering=("Answer and route clinic calls",),
            delivery_requirements=("Clinic call-forwarding access",),
            user_stories=("As a clinic owner, I can review captured enquiries.",),
            roadmap=("Pilot with one clinic",),
        ),
        Role.VERIFIER: VerificationArtifact(
            checked_artifact_ids=(uuid4(),),
            outcome="verified",
        ),
    }
    models = {role: _StaticModel(payload) for role, payload in outputs.items()}
    catalog = {
        role: ConfiguredRole(
            agent_id=f"test-{role.value}",
            agent=Agent(
                id=f"test-{role.value}",
                model=models[role],
                output_schema=type(payload),
                telemetry=False,
            ),
            capability=ROLE_CAPABILITIES[role],
            instructions="test",
        )
        for role, payload in outputs.items()
    }
    return catalog, models


async def _complete_research(
    _agent: ResearchAgent, _brief: CompanyBrief, *, max_sources: int = 5
) -> ResearchResult:
    assert max_sources == 5
    return _research_result()


def _research_result(*, conflicts: tuple[str, ...] = ()) -> ResearchResult:
    source_id = uuid4()
    segment = "Clinics report missed calls and compare monthly services."
    return ResearchResult(
        status="complete",
        payload=ResearchArtifact(summary=segment, conflicts=conflicts),
        sources=(
            SourceReference(
                source_id=source_id,
                url=HttpUrl("https://example.com/clinic-study"),
                title="Clinic study",
                retrieved_at=datetime(2026, 10, 11, tzinfo=UTC),
                search_query="India dental clinic missed calls",
                excerpt=segment,
            ),
        ),
        claims=(
            SourcedClaim(
                claim_id=uuid4(),
                text=segment,
                source_ids=(source_id,),
                support_status="mapped",
                support_segments=(segment,),
                verification_status="unverified",
            ),
        ),
        assumptions=(Assumption(assumption_id=uuid4(), text="Clinics may adopt the service"),),
        verification_findings=(
            VerificationFinding(
                code="research_lineage_retained",
                message="Source lineage retained.",
                severity="info",
            ),
        ),
    )


def _unmapped_research_result() -> ResearchResult:
    result = _research_result()
    return replace(
        result,
        claims=(result.claims[0].model_copy(update={"support_status": "unmapped"}),),
    )


def _complete_request() -> CompanyJourneyRequest:
    return CompanyJourneyRequest(
        company_id=None,
        expected_revision=0,
        idea="AI receptionist for Indian dental clinics",
        target_customer="Independent Indian dental clinics",
        geography="India",
        budget="INR 50000",
        founder_skills="Python and Next.js",
        goal="Validate demand",
    )


async def _run_workflow(
    workflow: Workflow,
    request: CompanyJourneyRequest,
    session_state: dict[str, JsonValue],
) -> WorkflowRunOutput:
    output = await workflow.arun(
        request,
        user_id="founder-1",
        session_id="child-journey",
        session_state=session_state,
        dependencies={
            "trusted_parent_session_id": "parent-1",
            "trusted_user_id": "founder-1",
            "child_session_id": "child-journey",
        },
    )
    assert isinstance(output, WorkflowRunOutput)
    return output


def test_complete_company_journey_persists_verified_ordered_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given deterministic role outputs and mapped grounded research.
    catalog, _ = _catalog()

    def catalog_factory(_settings: Settings) -> Mapping[Role, ConfiguredRole]:
        return catalog

    monkeypatch.setattr("samurai.company_workflow.create_role_catalog", catalog_factory)
    monkeypatch.setattr("samurai.company_workflow.run_research", _complete_research)
    workflow = create_company_workflow(SqliteDb(db_file=str(tmp_path) + "/journey.db"), _settings())
    session_state: dict[str, JsonValue] = {}
    request = _complete_request()

    # When the native workflow completes.
    output = anyio.run(partial(_run_workflow, workflow, request, session_state))

    # Then five artifact types form monotonic verified lineage in canonical child state.
    result = WorkflowResult.model_validate(output.content)
    assert result.outcome == "verified"
    assert [artifact.revision for artifact in result.artifacts] == [1, 2, 3, 4, 5]
    assert [artifact.input_revision for artifact in result.artifacts] == [0, 1, 2, 3, 4]
    step_names: list[str] = []
    for step in output.step_results or ():
        assert isinstance(step, StepOutput)
        step_names.append(step.step_name or "")
    assert step_names == [
        "Intake",
        "Verify brief",
        "Research",
        "Verify evidence",
        "Strategy",
        "Product plan",
        "Verify journey",
    ]
    assert all(
        claim.verification_status == "unverified"
        for artifact in result.artifacts
        for claim in artifact.claims
    )
    verification = VerificationArtifact.model_validate(result.artifacts[-1].payload)
    assert verification.checked_artifact_ids == tuple(
        artifact.artifact_id for artifact in result.artifacts[:-1]
    )
    assert CompanyState.model_validate(session_state["company"]).current_revision == 5


def test_clarification_continuation_preserves_idea_without_duplicate_research(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given one partial founder request and counted downstream executions.
    catalog, models = _catalog()
    research_calls: list[str] = []

    async def fake_research(
        _agent: ResearchAgent, _brief: CompanyBrief, *, max_sources: int = 5
    ) -> ResearchResult:
        assert max_sources == 5
        research_calls.append("research")
        return _research_result()

    def catalog_factory(_settings: Settings) -> Mapping[Role, ConfiguredRole]:
        return catalog

    monkeypatch.setattr("samurai.company_workflow.create_role_catalog", catalog_factory)
    monkeypatch.setattr("samurai.company_workflow.run_research", fake_research)
    workflow = create_company_workflow(
        SqliteDb(db_file=str(tmp_path) + "/continue.db"), _settings()
    )
    session_state: dict[str, JsonValue] = {}
    first = CompanyJourneyRequest(
        company_id=None,
        expected_revision=0,
        idea="AI receptionist for Indian dental clinics",
    )

    # When missing context stops and the same child session continues once.
    partial_result = WorkflowResult.model_validate(
        anyio.run(partial(_run_workflow, workflow, first, session_state)).content
    )
    complete = CompanyJourneyRequest(
        company_id=partial_result.company_id,
        expected_revision=partial_result.revision,
        target_customer="Independent Indian dental clinics",
        geography="India",
        budget="INR 50000",
        founder_skills="Python and Next.js",
        goal="Validate demand",
    )
    final_result = WorkflowResult.model_validate(
        anyio.run(partial(_run_workflow, workflow, complete, session_state)).content
    )

    # Then the amended intake is intentional, while completed downstream stages run once.
    assert partial_result.outcome == "needs_input"
    assert final_result.outcome == "verified"
    intake = IntakeArtifact.model_validate(final_result.artifacts[0].payload)
    assert intake.brief.idea == first.idea
    assert research_calls == ["research"]
    assert models[Role.INTAKE].calls == 2
    assert models[Role.STRATEGIST].calls == 1
    assert models[Role.PRODUCT_MANAGER].calls == 1


@pytest.mark.parametrize(
    ("research", "label"),
    [
        (
            replace(
                _research_result(),
                status="insufficient_evidence",
                sources=(),
                claims=(),
            ),
            "source-free",
        ),
        (_unmapped_research_result(), "unmapped"),
    ],
)
def test_invalid_research_stops_before_strategy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    research: ResearchResult,
    label: str,
) -> None:
    # Given source-free or structurally invalid research from the grounded boundary.
    catalog, models = _catalog()

    async def invalid_research(
        _agent: ResearchAgent, _brief: CompanyBrief, *, max_sources: int = 5
    ) -> ResearchResult:
        assert max_sources == 5
        return research

    def catalog_factory(_settings: Settings) -> Mapping[Role, ConfiguredRole]:
        return catalog

    monkeypatch.setattr("samurai.company_workflow.create_role_catalog", catalog_factory)
    monkeypatch.setattr("samurai.company_workflow.run_research", invalid_research)
    workflow = create_company_workflow(SqliteDb(db_file=str(tmp_path / f"{label}.db")), _settings())

    # When deterministic evidence validation evaluates the result.
    output = anyio.run(partial(_run_workflow, workflow, _complete_request(), {}))

    # Then the honest evidence outcome is persisted and no downstream model runs.
    result = WorkflowResult.model_validate(output.content)
    assert result.outcome == "insufficient_evidence"
    assert [artifact.artifact_type for artifact in result.artifacts] == ["intake", "research"]
    assert models[Role.STRATEGIST].calls == 0
    assert models[Role.PRODUCT_MANAGER].calls == 0
    assert models[Role.VERIFIER].calls == 0


def test_conflicting_grounded_research_reaches_provisional_final_rework(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given complete, mapped research that retains a source conflict.
    catalog, models = _catalog()
    conflict = "Two retained sources disagree about clinic adoption."

    async def conflicting_research(
        _agent: ResearchAgent, _brief: CompanyBrief, *, max_sources: int = 5
    ) -> ResearchResult:
        assert max_sources == 5
        return _research_result(conflicts=(conflict,))

    def catalog_factory(_settings: Settings) -> Mapping[Role, ConfiguredRole]:
        return catalog

    monkeypatch.setattr("samurai.company_workflow.create_role_catalog", catalog_factory)
    monkeypatch.setattr("samurai.company_workflow.run_research", conflicting_research)
    workflow = create_company_workflow(
        SqliteDb(db_file=str(tmp_path / "conflicting-research.db")), _settings()
    )

    # When the ordered journey prepares provisional plans and runs final verification.
    output = anyio.run(partial(_run_workflow, workflow, _complete_request(), {}))

    # Then all five typed artifacts persist, while the unresolved conflict forces rework.
    result = WorkflowResult.model_validate(output.content)
    assert result.outcome == "needs_rework"
    assert [artifact.artifact_type for artifact in result.artifacts] == [
        "intake",
        "research",
        "strategy",
        "product_plan",
        "verification",
    ]
    research, strategy, product, verification = result.artifacts[1:]
    assert research.status == "complete"
    assert ResearchArtifact.model_validate(research.payload).conflicts == (conflict,)
    assert any(
        finding.code == "research_conflicts_retained" for finding in research.verification_findings
    )
    assert any(finding.code == "strategy_provisional" for finding in strategy.verification_findings)
    assert any(finding.code == "product_provisional" for finding in product.verification_findings)
    assert verification.status == "needs_rework"
    assert any(
        finding.code == "research_conflicts_unresolved"
        for finding in verification.verification_findings
    )
    assert all(
        claim.verification_status == "unverified"
        for artifact in result.artifacts
        for claim in artifact.claims
    )
    assert models[Role.STRATEGIST].calls == 1
    assert models[Role.PRODUCT_MANAGER].calls == 1
    assert models[Role.VERIFIER].calls == 1


def test_unsupported_strategy_number_requires_rework(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a strategy that invents a number absent from retained research claims.
    catalog, _ = _catalog(pricing_assumptions=("Charge INR 9000 each month.",))

    def catalog_factory(_settings: Settings) -> Mapping[Role, ConfiguredRole]:
        return catalog

    monkeypatch.setattr("samurai.company_workflow.create_role_catalog", catalog_factory)
    monkeypatch.setattr("samurai.company_workflow.run_research", _complete_research)
    workflow = create_company_workflow(
        SqliteDb(db_file=str(tmp_path / "unsupported-number.db")), _settings()
    )

    # When final verification checks numeric support.
    output = anyio.run(partial(_run_workflow, workflow, _complete_request(), {}))

    # Then the run needs rework and records the unsupported number explicitly.
    result = WorkflowResult.model_validate(output.content)
    verification = result.artifacts[-1]
    assert result.outcome == "needs_rework"
    assert verification.status == "needs_rework"
    assert verification.verification_findings[0].code == "unsupported_numeric_claim"
    assert "9000" in verification.verification_findings[0].message


def test_stale_continuation_fails_before_another_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a child session with one persisted partial intake.
    catalog, models = _catalog()

    def catalog_factory(_settings: Settings) -> Mapping[Role, ConfiguredRole]:
        return catalog

    monkeypatch.setattr("samurai.company_workflow.create_role_catalog", catalog_factory)
    workflow = create_company_workflow(SqliteDb(db_file=str(tmp_path / "stale.db")), _settings())
    session_state: dict[str, JsonValue] = {}
    first = WorkflowResult.model_validate(
        anyio.run(
            partial(
                _run_workflow,
                workflow,
                CompanyJourneyRequest(company_id=None, expected_revision=0, idea="Clinic tool"),
                session_state,
            )
        ).content
    )

    # When the same session submits a stale expected revision.
    stale = CompanyJourneyRequest(company_id=first.company_id, expected_revision=0)
    output = anyio.run(partial(_run_workflow, workflow, stale, session_state))

    # Then the native workflow stops with a sanitized boundary failure before model work.
    failure = CompanyJourneyFailure.model_validate(output.content)
    assert failure.error_code == "invalid_revision"
    assert models[Role.INTAKE].calls == 1
    assert models[Role.RESEARCHER].calls == 0
