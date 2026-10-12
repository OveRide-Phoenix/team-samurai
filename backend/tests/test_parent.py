from __future__ import annotations

import json
from collections import abc  # noqa: TC003 - Agno resolves model annotations at runtime.
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Never, cast, final, override
from uuid import UUID

import anyio
import pytest
from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.agent import CustomEvent
from agno.run.base import RunStatus
from agno.run.cancel import aget_active_runs
from agno.session.agent import AgentSession
from agno.session.workflow import WorkflowSession
from agno.tools.function import Function
from agno.utils.gemini import format_function_definitions
from agno.workflow import Step, StepInput, StepOutput, Workflow
from agno.workflow.types import HumanReview, OnError
from fastapi.testclient import TestClient
from pydantic import HttpUrl, JsonValue

from samurai.agents import ROLE_CAPABILITIES, ConfiguredRole
from samurai.app import create_app
from samurai.config import Settings
from samurai.contracts import (
    AnalysisDraft,
    Assumption,
    CompanyBrief,
    CompanyState,
    IntakeArtifact,
    ProductPlanArtifact,
    ResearchArtifact,
    Role,
    SourcedClaim,
    SourceReference,
    StrategyArtifact,
    VerificationArtifact,
    VerificationFinding,
    WorkflowResult,
    create_company_state,
)
from samurai.launch_workflows import LaunchAction, LaunchKind
from samurai.parent import (
    PARENT_AGENT_ID,
    _create_launch_drafts,  # pyright: ignore[reportPrivateUsage]
    child_session_id,
    create_parent_agent,
)
from samurai.research import ResearchAgent, ResearchResult

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Awaitable, Callable

    from agno.models.message import Message
    from agno.run.agent import RunOutput

NOW = datetime(2026, 10, 11, tzinfo=UTC)
METRIC_TIME_FIELDS = "unit, UTC window_start, UTC window_end, and UTC collected_at"
EXPECTED_METRIC_QUESTIONS = (
    f"What exact {METRIC_TIME_FIELDS} apply to each metric?",
    "What source_label identifies where each founder-supplied metric came from?",
)


@final
class _ToolSequenceModel(Model):
    def __init__(
        self,
        *tool_names: str,
        repeat: bool = False,
        arguments: dict[str, str] | None = None,
    ) -> None:
        super().__init__(id="parent-test", name="Parent test", provider="test")
        self.id: str = "parent-test"
        self.tool_names = tool_names
        self.repeat = repeat
        self.arguments = arguments or {}
        self.calls = 0
        self.advertised_tools_json = ""

    @override
    def invoke(self, *_args: Never, **_kwargs: Never) -> ModelResponse:
        return ModelResponse()

    @override
    async def ainvoke(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, object]] | None = None,
        **_kwargs: Never,
    ) -> ModelResponse:
        assert messages
        self.advertised_tools_json = json.dumps(tools or ())
        index = self.calls
        self.calls += 1
        if self.tool_names and (index < len(self.tool_names) or self.repeat):
            name = self.tool_names[min(index, len(self.tool_names) - 1)]
            arguments = self.arguments.get(name, "{}")
            if name.startswith("get_skill"):
                arguments = '{"skill_name":"evidence-discipline"}'
            if name == "run_company_journey" and name not in self.arguments:
                arguments = json.dumps(
                    {
                        "idea": "offline failure probe",
                        "target_customer": "",
                        "geography": "",
                        "budget": "",
                        "founder_skills": "",
                        "goal": "",
                    }
                )
            return ModelResponse(
                tool_calls=[
                    {
                        "id": f"tool-{self.calls}",
                        "type": "function",
                        "function": {"name": name, "arguments": arguments},
                    }
                ]
            )
        return ModelResponse(content="done")

    @override
    def invoke_stream(self, *_args: Never, **_kwargs: Never) -> abc.Iterator[ModelResponse]:
        return iter(())

    @override
    async def ainvoke_stream(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, object]] | None = None,
        **_kwargs: Never,
    ) -> abc.AsyncIterator[ModelResponse]:
        yield await self.ainvoke(messages, tools=tools)

    @override
    def _parse_provider_response(self, response: ModelResponse, **_kwargs: Never) -> ModelResponse:
        return response

    @override
    def _parse_provider_response_delta(self, response: ModelResponse) -> ModelResponse:
        return response


@final
class _StaticRoleModel(Model):
    def __init__(self, content: str) -> None:
        super().__init__(id="role-test", name="Role test", provider="test")
        self.id: str = "role-test"
        self.content = content

    @override
    def invoke(self, *_args: Never, **_kwargs: Never) -> ModelResponse:
        return ModelResponse()

    @override
    async def ainvoke(self, messages: list[Message], **_kwargs: Never) -> ModelResponse:
        assert messages
        return ModelResponse(content=self.content)

    @override
    def invoke_stream(self, *_args: Never, **_kwargs: Never) -> abc.Iterator[ModelResponse]:
        return iter(())

    @override
    async def ainvoke_stream(
        self, *_args: Never, **_kwargs: Never
    ) -> abc.AsyncIterator[ModelResponse]:
        yield ModelResponse()

    @override
    def _parse_provider_response(self, response: ModelResponse, **_kwargs: Never) -> ModelResponse:
        return response

    @override
    def _parse_provider_response_delta(self, response: ModelResponse) -> ModelResponse:
        return response


@final
class _FailingRoleModel(Model):
    def __init__(self, marker: str) -> None:
        super().__init__(id="failing-role-test", name="Failing role test", provider="test")
        self.id: str = "failing-role-test"
        self.marker = marker
        self.calls = 0

    @override
    def invoke(self, *_args: Never, **_kwargs: Never) -> ModelResponse:
        return ModelResponse()

    @override
    async def ainvoke(self, messages: list[Message], **_kwargs: Never) -> ModelResponse:
        assert messages
        self.calls += 1
        raise TimeoutError(self.marker)

    @override
    def invoke_stream(self, *_args: Never, **_kwargs: Never) -> abc.Iterator[ModelResponse]:
        return iter(())

    @override
    async def ainvoke_stream(
        self, *_args: Never, **_kwargs: Never
    ) -> abc.AsyncIterator[ModelResponse]:
        yield ModelResponse()

    @override
    def _parse_provider_response(self, response: ModelResponse, **_kwargs: Never) -> ModelResponse:
        return response

    @override
    def _parse_provider_response_delta(self, response: ModelResponse) -> ModelResponse:
        return response


def _deterministic_catalog() -> dict[Role, ConfiguredRole]:
    outputs = {
        Role.INTAKE: IntakeArtifact(
            brief=CompanyBrief(
                idea="retained founder idea",
                target_customer="retained target",
                geography="retained geography",
                budget="retained budget",
                founder_skills="retained skills",
                goal="retained goal",
                supplied_context=[],
                assumptions=[],
                open_questions=[],
                next_actions=["Interview clinic owners."],
            )
        ),
        Role.RESEARCHER: ResearchArtifact(summary="unused", conflicts=()),
        Role.STRATEGIST: StrategyArtifact(
            ideal_customer_profile="Independent Indian dental clinics",
            positioning="Recover missed patient calls",
            offer="A managed receptionist pilot",
            pricing_assumptions=("Validate willingness to pay.",),
        ),
        Role.PRODUCT_MANAGER: ProductPlanArtifact(
            minimum_viable_offering=("Answer and route clinic calls",),
            delivery_requirements=("Clinic call-forwarding access",),
            user_stories=("As a clinic owner, I can review captured enquiries.",),
            roadmap=("Pilot with one clinic",),
        ),
        Role.VERIFIER: VerificationArtifact(
            checked_artifact_ids=(UUID("00000000-0000-0000-0000-000000000104"),),
            outcome="verified",
        ),
    }
    catalog: dict[Role, ConfiguredRole] = {}
    for role, output in outputs.items():
        raw = output.model_dump_json()
        if role is Role.INTAKE:
            raw = raw.replace('"artifact_type":"intake"', '"artifact_type":"founder_intake"')
        agent = Agent(
            id=f"test-{role.value}",
            model=_StaticRoleModel(raw),
            output_schema=None if role is Role.RESEARCHER else type(output),
            telemetry=False,
        )
        catalog[role] = ConfiguredRole(
            agent_id=f"test-{role.value}",
            agent=agent,
            capability=ROLE_CAPABILITIES[role],
            instructions="test",
        )
    return catalog


async def _mapped_research(
    _agent: ResearchAgent,
    _brief: CompanyBrief,
    *,
    max_sources: int = 5,
) -> ResearchResult:
    assert max_sources == 5
    source_id = UUID("00000000-0000-0000-0000-000000000101")
    segment = "Clinics report missed calls and compare monthly services."
    return ResearchResult(
        status="complete",
        payload=ResearchArtifact(summary=segment, conflicts=()),
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
                claim_id=UUID("00000000-0000-0000-0000-000000000102"),
                text=segment,
                source_ids=(source_id,),
                support_status="mapped",
                support_segments=(segment,),
                verification_status="unverified",
            ),
        ),
        assumptions=(
            Assumption(
                assumption_id=UUID("00000000-0000-0000-0000-000000000103"),
                text="Clinics may adopt the service.",
            ),
        ),
        verification_findings=(
            VerificationFinding(
                code="research_lineage_retained",
                message="Source lineage retained.",
                severity="info",
            ),
        ),
    )


async def _run_agent(agent: Agent, message: str, session_id: str) -> RunOutput:
    run = cast("Callable[..., Awaitable[RunOutput]]", agent.arun)
    return await run(message, user_id="founder", session_id=session_id, stream=False)


def test_parent_exposes_only_four_bounded_business_tools(tmp_path: pathlib.Path) -> None:
    agent = create_parent_agent(
        SqliteDb(db_file=str(tmp_path / "parent.db")),
        Settings.model_validate({}),
    )
    assert agent.id == PARENT_AGENT_ID
    assert agent.tool_call_limit == Settings.model_validate({}).agent_tool_call_limit
    raw_tools = cast("object", agent.tools)
    assert isinstance(raw_tools, list)
    tools = cast("list[object]", raw_tools)
    assert {tool.name for tool in tools if isinstance(tool, Function)} == {
        "run_company_journey",
        "create_launch_drafts",
        "analyze_metrics",
        "read_company_state",
    }
    assert agent.skills is not None
    assert {tool.name for tool in agent.skills.get_tools()} == {
        "get_skill_instructions",
        "get_skill_reference",
    }
    assert all(not tool.stop_after_tool_call for tool in agent.skills.get_tools())


def test_native_parent_advertises_complete_gemini_metric_schema(
    tmp_path: pathlib.Path,
) -> None:
    model = _ToolSequenceModel()
    agent = create_parent_agent(
        SqliteDb(db_file=str(tmp_path / "metric-schema.db")),
        Settings.model_validate({}),
        model=model,
    )

    result = anyio.run(_run_agent, agent, "What metrics can you analyze?", "schema-session")
    advertised = cast("list[dict[str, JsonValue]]", json.loads(model.advertised_tools_json))
    metric_function = next(
        cast("dict[str, JsonValue]", item["function"])
        for item in advertised
        if cast("dict[str, JsonValue]", item["function"])["name"] == "analyze_metrics"
    )
    parameters = cast("dict[str, JsonValue]", metric_function["parameters"])
    measurement_array = cast(
        "dict[str, JsonValue]",
        cast("dict[str, JsonValue]", parameters["properties"])["measurements"],
    )
    measurement = cast("dict[str, JsonValue]", measurement_array["items"])
    required_fields = [
        "name",
        "value",
        "unit",
        "window_start",
        "window_end",
        "source_label",
        "collected_at",
    ]

    gemini_tool = format_function_definitions(advertised)
    assert gemini_tool is not None
    gemini_payload = cast(
        "dict[str, JsonValue]", gemini_tool.model_dump(mode="json", exclude_none=True)
    )
    declarations = cast("list[dict[str, JsonValue]]", gemini_payload["function_declarations"])
    gemini_function = next(item for item in declarations if item["name"] == "analyze_metrics")
    gemini_parameters = cast("dict[str, JsonValue]", gemini_function["parameters"])
    gemini_measurement_array = cast(
        "dict[str, JsonValue]",
        cast("dict[str, JsonValue]", gemini_parameters["properties"])["measurements"],
    )
    gemini_measurement = cast("dict[str, JsonValue]", gemini_measurement_array["items"])

    assert result.status == RunStatus.completed
    assert list(cast("dict[str, JsonValue]", measurement["properties"])) == required_fields
    assert measurement["required"] == required_fields
    assert list(cast("dict[str, JsonValue]", gemini_measurement["properties"])) == required_fields
    assert gemini_measurement["required"] == required_fields


@pytest.mark.parametrize(
    ("arguments", "expected_outcome", "expected_questions"),
    [
        ({}, "requires_metrics", ()),
        ({"measurements": []}, "requires_metrics", ()),
        (
            {
                "measurements": [
                    {
                        "timeframe": "30 days",
                        "metric_name": "qualified_leads",
                        "metric_value": 12,
                    }
                ]
            },
            "needs_input",
            EXPECTED_METRIC_QUESTIONS,
        ),
        (
            {
                "measurements": [
                    {
                        "time_window": "last 7 days",
                        "source_label": "manual founder spreadsheet",
                        "metric_value": 12,
                        "metric_name": "qualified leads",
                    }
                ]
            },
            "needs_input",
            EXPECTED_METRIC_QUESTIONS,
        ),
    ],
    ids=["omitted", "empty", "unlabeled", "labeled-relative-window"],
)
def test_incomplete_metric_calls_require_exact_evidence_without_child_run(
    arguments: dict[str, JsonValue],
    expected_outcome: str,
    expected_questions: tuple[str, ...],
    tmp_path: pathlib.Path,
) -> None:
    parent_session_id = "metric-input-session"
    database = SqliteDb(db_file=str(tmp_path / "metric-input.db"))
    original_state = create_company_state(parent_session_id, created_at=NOW)
    child_id = child_session_id("founder", parent_session_id)
    _ = database.upsert_session(
        WorkflowSession(
            session_id=child_id,
            user_id="founder",
            workflow_id="company-journey",
            session_data={"session_state": {"company": original_state.model_dump(mode="json")}},
        )
    )
    model = _ToolSequenceModel(
        "analyze_metrics",
        arguments={"analyze_metrics": json.dumps(arguments)},
    )
    settings = Settings.model_validate({})
    with TestClient(
        create_app(
            db=database,
            settings=settings,
            parent_model_factory=lambda: model,
        )
    ) as client:
        response = client.post(
            "/agentos/agents/samurai/runs",
            headers={"Authorization": f"Bearer {settings.os_security_key.get_secret_value()}"},
            data={
                "message": "Analyze the founder metric without inventing missing evidence.",
                "session_id": parent_session_id,
                "user_id": "founder",
                "stream": "false",
            },
        )

    payload = cast("dict[str, object]", response.json())
    result = WorkflowResult.model_validate_json(cast("str", payload["content"]))
    child = database.get_session(child_id, user_id="founder")

    assert response.status_code == 200
    assert payload["status"] == RunStatus.completed.value
    assert result.outcome == expected_outcome
    assert result.artifacts == ()
    assert result.questions == expected_questions
    assert isinstance(child, WorkflowSession)
    assert child.runs in (None, [])
    assert child.session_data == {
        "session_state": {"company": original_state.model_dump(mode="json")}
    }


def test_complete_metric_call_remains_conditional_and_founder_supplied(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_session_id = "complete-metric-session"
    database = SqliteDb(db_file=str(tmp_path / "complete-metric.db"))
    original_state = create_company_state(parent_session_id, created_at=NOW)
    child_id = child_session_id("founder", parent_session_id)
    _ = database.upsert_session(
        WorkflowSession(
            session_id=child_id,
            user_id="founder",
            workflow_id="company-journey",
            session_data={"session_state": {"company": original_state.model_dump(mode="json")}},
        )
    )
    assessment = AnalysisDraft(
        findings=("Twelve qualified leads were founder supplied.",),
        recommendations=("Verify the lead count through a trusted connector.",),
    )
    analyst = Agent(
        id="test-analyst",
        model=_StaticRoleModel(assessment.model_dump_json()),
        output_schema=AnalysisDraft,
        telemetry=False,
    )

    def analyst_catalog(_settings: Settings) -> dict[Role, ConfiguredRole]:
        return {
            Role.ANALYST: ConfiguredRole(
                agent_id="test-analyst",
                agent=analyst,
                capability=ROLE_CAPABILITIES[Role.ANALYST],
                instructions="test",
            )
        }

    monkeypatch.setattr(
        "samurai.parent.create_role_catalog",
        analyst_catalog,
    )
    arguments = {
        "measurements": [
            {
                "name": "qualified_leads",
                "value": 12,
                "unit": "leads",
                "window_start": "2026-10-04T00:00:00Z",
                "window_end": "2026-10-10T23:00:00Z",
                "source_label": "manual founder spreadsheet",
                "collected_at": "2026-10-11T00:00:00Z",
            }
        ]
    }
    model = _ToolSequenceModel(
        "analyze_metrics",
        arguments={"analyze_metrics": json.dumps(arguments)},
    )
    settings = Settings.model_validate({})
    with TestClient(
        create_app(
            db=database,
            settings=settings,
            parent_model_factory=lambda: model,
        )
    ) as client:
        response = client.post(
            "/agentos/agents/samurai/runs",
            headers={"Authorization": f"Bearer {settings.os_security_key.get_secret_value()}"},
            data={
                "message": "Analyze this complete founder-supplied metric conditionally.",
                "session_id": parent_session_id,
                "user_id": "founder",
                "stream": "false",
            },
        )

    payload = cast("dict[str, object]", response.json())
    result = WorkflowResult.model_validate_json(cast("str", payload["content"]))
    measurement = result.artifacts[0].measurements[0]

    assert response.status_code == 200
    assert payload["status"] == RunStatus.completed.value
    assert result.outcome == "based_on_founder_supplied_metrics"
    assert measurement.provenance == "founder_supplied"
    assert measurement.trusted_connector_receipt is None
    assert measurement.source_label == "manual founder spreadsheet"
    assert measurement.name == "qualified_leads"
    assert measurement.value == 12


def test_company_journey_requires_all_brief_fields_before_child_start(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = SqliteDb(db_file=str(tmp_path / "required-brief.db"))
    model = _ToolSequenceModel(
        "run_company_journey",
        arguments={"run_company_journey": '{"idea":"offline failure probe"}'},
    )
    child_starts = 0

    def unexpected_child_start(*_args: object, **_kwargs: object) -> Workflow:
        nonlocal child_starts
        child_starts += 1
        return cast("Workflow", object())

    monkeypatch.setattr("samurai.parent.create_company_workflow", unexpected_child_start)
    agent = create_parent_agent(database, Settings.model_validate({}), model=model)

    async def scenario() -> RunOutput:
        return await _run_agent(agent, "Build my partially described company", "required-session")

    result = anyio.run(scenario)
    advertised_tools = cast("list[dict[str, object]]", json.loads(model.advertised_tools_json))
    journey = next(
        cast("dict[str, object]", item["function"])
        for item in advertised_tools
        if cast("dict[str, object]", item["function"])["name"] == "run_company_journey"
    )
    parameters = cast("dict[str, object]", journey["parameters"])

    assert parameters["required"] == [
        "idea",
        "target_customer",
        "geography",
        "budget",
        "founder_skills",
        "goal",
    ]
    properties = cast("dict[str, dict[str, object]]", parameters["properties"])
    for field in cast("list[str]", parameters["required"]):
        assert properties[field]["type"] == "string"
        assert "Exact founder-supplied" in cast("str", properties[field]["description"])
    assert child_starts == 0
    assert result.status == RunStatus.error
    assert json.loads(cast("str", result.content)) == {
        "outcome": "failed",
        "error_code": "child_workflow_failed",
    }
    assert model.calls == 1
    assert database.get_sessions(session_type=SessionType.WORKFLOW, user_id="founder") == []


def test_child_session_is_deterministic_and_scoped_to_trusted_owner() -> None:
    first = child_session_id("founder-a", "parent-session")

    assert UUID(first)
    assert first == child_session_id("founder-a", "parent-session")
    assert first != child_session_id("founder-b", "parent-session")
    assert first != child_session_id("founder-a", "other-parent-session")
    assert child_session_id("a:b", "c") != child_session_id("a", "b:c")


def test_skill_read_continues_to_bounded_business_tool(tmp_path: pathlib.Path) -> None:
    model = _ToolSequenceModel("get_skill_instructions", "read_company_state")
    agent = create_parent_agent(
        SqliteDb(db_file=str(tmp_path / "skills.db")),
        Settings.model_validate({}),
        model=model,
    )

    async def scenario() -> RunOutput:
        return await _run_agent(
            agent, "read the evidence skill, then read my company", "skill-session"
        )

    result = anyio.run(scenario)

    assert result.status == RunStatus.completed
    assert json.loads(cast("str", result.content))["status"] == "not_started"
    assert model.calls == 2


def test_repeated_skill_reads_end_at_parent_model_budget(tmp_path: pathlib.Path) -> None:
    model = _ToolSequenceModel("get_skill_instructions", repeat=True)
    settings = Settings.model_validate({"agent_tool_call_limit": 2})
    agent = create_parent_agent(
        SqliteDb(db_file=str(tmp_path / "skill-loop.db")),
        settings,
        model=model,
    )

    async def scenario() -> RunOutput:
        return await _run_agent(agent, "loop on the evidence skill", "skill-loop-session")

    result = anyio.run(scenario)

    assert result.status == RunStatus.error
    assert result.content == "parent model request failed"
    assert model.calls == settings.agent_tool_call_limit + 1


def test_native_http_parent_runs_real_company_workflow_to_five_artifacts(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _deterministic_catalog()

    def catalog_factory(_settings: Settings) -> dict[Role, ConfiguredRole]:
        return catalog

    monkeypatch.setattr("samurai.company_workflow.create_role_catalog", catalog_factory)
    monkeypatch.setattr("samurai.company_workflow.run_research", _mapped_research)
    arguments = json.dumps(
        {
            "idea": "AI receptionist for Indian dental clinics",
            "target_customer": "Independent Indian dental clinics",
            "geography": "India",
            "budget": "INR 50000",
            "founder_skills": "Python and Next.js",
            "goal": "Validate demand in 30 days",
            "stage": "plan",
        }
    )
    database = SqliteDb(db_file=str(tmp_path / "parent-real-core.db"))
    settings = Settings.model_validate({})
    with TestClient(
        create_app(
            db=database,
            settings=settings,
            parent_model_factory=lambda: _ToolSequenceModel(
                "run_company_journey",
                arguments={"run_company_journey": arguments},
            ),
        )
    ) as client:
        response = client.post(
            "/agentos/agents/samurai/runs",
            headers={"Authorization": f"Bearer {settings.os_security_key.get_secret_value()}"},
            data={
                "message": "Start the fictional company journey.",
                "session_id": "real-core-parent-session",
                "user_id": "founder",
                "stream": "false",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == RunStatus.completed.value
    sessions = database.get_sessions(session_type=SessionType.WORKFLOW, user_id="founder")
    assert isinstance(sessions, list)
    assert len(sessions) == 1
    child = sessions[0]
    assert isinstance(child, WorkflowSession)
    assert child.runs is not None
    assert len(child.runs) == 1
    child_run = child.runs[0]
    assert child_run.status == RunStatus.completed
    assert child_run.session_id == child.session_id
    assert child_run.workflow_id == "company-journey"
    persisted_result = WorkflowResult.model_validate(child_run.content)
    assert len(child_run.step_results or ()) == 7
    assert child.session_data is not None
    session_state = cast("dict[str, object]", child.session_data["session_state"])
    state = CompanyState.model_validate(session_state["company"])
    intake = IntakeArtifact.model_validate(state.artifacts[0].payload)
    assert intake.brief.target_customer == "Independent Indian dental clinics"
    assert intake.brief.geography == "India"
    assert intake.brief.budget == "INR 50000"
    assert intake.brief.founder_skills == "Python and Next.js"
    assert intake.brief.goal == "Validate demand in 30 days"
    assert persisted_result.company_id == state.context.company_id
    assert persisted_result.revision == state.current_revision
    assert [artifact.artifact_type for artifact in state.artifacts] == [
        "intake",
        "research",
        "strategy",
        "product_plan",
        "verification",
    ]
    assert [artifact.revision for artifact in state.artifacts] == [1, 2, 3, 4, 5]
    assert all(
        claim.verification_status == "unverified"
        for artifact in state.artifacts
        for claim in artifact.claims
    )


def test_real_core_step_failure_is_fail_closed_before_state_mutation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider_marker = "real-core-provider-secret-marker"
    failing_model = _FailingRoleModel(provider_marker)
    catalog = _deterministic_catalog()
    catalog[Role.INTAKE] = ConfiguredRole(
        agent_id="test-failing-intake",
        agent=Agent(
            id="test-failing-intake",
            model=failing_model,
            output_schema=IntakeArtifact,
            telemetry=False,
        ),
        capability=ROLE_CAPABILITIES[Role.INTAKE],
        instructions="test",
    )

    def catalog_factory(_settings: Settings) -> dict[Role, ConfiguredRole]:
        return catalog

    research_calls = 0

    async def unexpected_research(
        agent: ResearchAgent,
        brief: CompanyBrief,
        *,
        max_sources: int = 5,
    ) -> ResearchResult:
        nonlocal research_calls
        research_calls += 1
        return await _mapped_research(agent, brief, max_sources=max_sources)

    monkeypatch.setattr("samurai.company_workflow.create_role_catalog", catalog_factory)
    monkeypatch.setattr("samurai.company_workflow.run_research", unexpected_research)
    arguments = json.dumps(
        {
            "idea": "AI receptionist for Indian dental clinics",
            "target_customer": "Independent Indian dental clinics",
            "geography": "India",
            "budget": "INR 50000",
            "founder_skills": "Python and Next.js",
            "goal": "Validate demand in 30 days",
            "stage": "plan",
        }
    )
    database = SqliteDb(db_file=str(tmp_path / "parent-real-core-failure.db"))
    settings = Settings.model_validate({})
    with TestClient(
        create_app(
            db=database,
            settings=settings,
            parent_model_factory=lambda: _ToolSequenceModel(
                "run_company_journey",
                arguments={"run_company_journey": arguments},
            ),
        )
    ) as client:
        response = client.post(
            "/agentos/agents/samurai/runs",
            headers={"Authorization": f"Bearer {settings.os_security_key.get_secret_value()}"},
            data={
                "message": "Start the fictional company journey.",
                "session_id": "real-core-failure-parent-session",
                "user_id": "founder",
                "stream": "false",
            },
        )

    assert response.status_code == 200
    payload = cast("dict[str, object]", response.json())
    assert payload["status"] == RunStatus.error.value
    assert json.loads(cast("str", payload["content"])) == {
        "outcome": "failed",
        "error_code": "child_workflow_failed",
    }
    assert provider_marker not in response.text
    assert provider_marker not in caplog.text
    assert failing_model.calls == 1
    assert research_calls == 0
    sessions = database.get_sessions(session_type=SessionType.WORKFLOW, user_id="founder")
    assert isinstance(sessions, list)
    assert len(sessions) == 1
    child = sessions[0]
    assert isinstance(child, WorkflowSession)
    assert child.runs is not None
    child_run = child.runs[-1]
    assert child_run.status == RunStatus.error.value
    assert len(child_run.step_results or ()) == 1
    assert child.session_data is not None
    session_state = cast("dict[str, object]", child.session_data["session_state"])
    assert "company" not in session_state


def test_launch_child_steps_are_fail_closed_without_losing_review_policy(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_session_id = "launch-policy-session"
    database = SqliteDb(db_file=str(tmp_path / "launch-policy.db"))
    state = create_company_state(parent_session_id, created_at=NOW)
    child_id = child_session_id("founder", parent_session_id)
    _ = database.upsert_session(
        WorkflowSession(
            session_id=child_id,
            user_id="founder",
            workflow_id="company-journey",
            session_data={"session_state": {"company": state.model_dump(mode="json")}},
        )
    )
    workflows = {
        role: Workflow(
            id=f"test-{role.value}-draft",
            steps=[
                Step(
                    name=f"Create {role.value} draft",
                    agent=Agent(
                        id=f"test-{role.value}",
                        model=_StaticRoleModel("unused"),
                        telemetry=False,
                    ),
                    human_review=HumanReview(
                        requires_confirmation=True,
                        confirmation_message="Review draft",
                        on_error="skip",
                    ),
                )
            ],
            telemetry=False,
        )
        for role in (Role.BUILDER, Role.MARKETER, Role.SALES)
    }

    def launch_factory(*_args: object, **_kwargs: object) -> dict[Role, Workflow]:
        return workflows

    async def inspect_launch_policy(*_args: object, **_kwargs: object) -> WorkflowResult:
        supplied = cast("dict[Role, Workflow]", _args[0])
        assert supplied == workflows
        for workflow in supplied.values():
            assert isinstance(workflow.steps, list)
            step = cast("Step", workflow.steps[0])
            assert step.max_retries == 0
            assert step.human_review.on_error is OnError.fail
            assert step.human_review.requires_confirmation
            assert step.human_review.confirmation_message == "Review draft"
        return WorkflowResult(
            company_id=state.context.company_id,
            revision=state.current_revision,
            outcome="draft_only",
        )

    monkeypatch.setattr("samurai.parent.create_launch_workflows", launch_factory)
    monkeypatch.setattr("samurai.parent.run_launch_drafts", inspect_launch_policy)
    result = anyio.run(
        _create_launch_drafts,
        database,
        Settings.model_validate({}),
        RunContext(
            run_id="launch-policy-run",
            session_id=parent_session_id,
            user_id="founder",
            session_state={},
        ),
        LaunchKind.ALL,
        LaunchAction.DRAFT,
    )

    assert result.outcome == "draft_only"


def test_explicit_empty_brief_fields_remain_missing_input(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def catalog_factory(_settings: Settings) -> dict[Role, ConfiguredRole]:
        return _deterministic_catalog()

    monkeypatch.setattr("samurai.company_workflow.create_role_catalog", catalog_factory)
    arguments = json.dumps(
        {
            "idea": "AI receptionist for Indian dental clinics",
            "target_customer": "Independent Indian dental clinics",
            "geography": "India",
            "budget": "INR 50000",
            "founder_skills": "",
            "goal": "",
        }
    )
    database = SqliteDb(db_file=str(tmp_path / "missing-brief.db"))
    agent = create_parent_agent(
        database,
        Settings.model_validate({}),
        model=_ToolSequenceModel(
            "run_company_journey",
            arguments={"run_company_journey": arguments},
        ),
    )

    async def scenario() -> RunOutput:
        return await _run_agent(
            agent, "Build this company with my supplied facts", "missing-session"
        )

    result = anyio.run(scenario)
    sessions = database.get_sessions(session_type=SessionType.WORKFLOW, user_id="founder")
    assert isinstance(sessions, list)
    assert len(sessions) == 1
    session = sessions[0]
    assert isinstance(session, WorkflowSession)
    assert session.session_data is not None
    state_payload = cast("dict[str, object]", session.session_data["session_state"])
    state = CompanyState.model_validate(state_payload["company"])
    intake = IntakeArtifact.model_validate(state.artifacts[0].payload)

    assert result.status == RunStatus.completed
    assert len(state.artifacts) == 1
    assert intake.brief.founder_skills is None
    assert intake.brief.goal is None
    assert intake.brief.open_questions == [
        "Which founder skills can support delivery?",
        "What outcome and timeframe define success?",
    ]


def test_parent_tool_emits_progress_before_blocked_research_and_closes_cross_task(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _deterministic_catalog()

    def catalog_factory(_settings: Settings) -> dict[Role, ConfiguredRole]:
        return catalog

    entered_research = anyio.Event()
    research_finished = anyio.Event()

    async def blocked_research(
        agent: ResearchAgent,
        brief: CompanyBrief,
        *,
        max_sources: int = 5,
    ) -> ResearchResult:
        entered_research.set()
        await anyio.sleep_forever()
        research_finished.set()
        return await _mapped_research(agent, brief, max_sources=max_sources)

    monkeypatch.setattr("samurai.company_workflow.create_role_catalog", catalog_factory)
    monkeypatch.setattr("samurai.company_workflow.run_research", blocked_research)
    database = SqliteDb(db_file=str(tmp_path / "parent-progress-close.db"))
    agent = create_parent_agent(database, Settings.model_validate({}), model=_ToolSequenceModel())
    raw_tools = cast("list[object]", agent.tools)
    tool = next(
        item
        for item in raw_tools
        if isinstance(item, Function) and item.name == "run_company_journey"
    )
    entrypoint = cast("Callable[..., abc.AsyncGenerator[CustomEvent | str]]", tool.entrypoint)

    async def scenario() -> None:
        stream = entrypoint(
            run_context=RunContext(
                run_id="parent-progress-run",
                session_id="parent-progress-session",
                user_id="founder",
                session_state={},
            ),
            idea="AI receptionist for Indian dental clinics",
            target_customer="Independent Indian dental clinics",
            geography="India",
            budget="INR 50000",
            founder_skills="Python and Next.js",
            goal="Validate demand in 30 days",
            stage="plan",
        )
        first = await anext(stream)
        assert isinstance(first, CustomEvent)
        with anyio.fail_after(1):
            while not entered_research.is_set():
                _ = await anext(stream)
        assert not research_finished.is_set()

        async with anyio.create_task_group() as tasks:
            _ = tasks.start_soon(stream.aclose)

    anyio.run(scenario)
    assert anyio.run(aget_active_runs) == {}


def test_child_failure_is_sanitized_and_parent_is_terminal_error(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider_marker = "child-provider-secret-marker"
    attempts = 0

    def failing_workflow(_db: SqliteDb, _settings: Settings, *, stage: str) -> Workflow:
        assert stage == "brief"

        async def fail(_: StepInput) -> StepOutput:
            nonlocal attempts
            attempts += 1
            raise TimeoutError(provider_marker)

        return Workflow(
            id="company-journey",
            name="Failing child",
            db=_db,
            steps=[Step(name="fail", executor=fail, max_retries=0)],
            telemetry=False,
        )

    monkeypatch.setattr("samurai.parent.create_company_workflow", failing_workflow)
    db = SqliteDb(db_file=str(tmp_path / "child-failure.db"))
    settings = Settings.model_validate({})
    with TestClient(
        create_app(
            db=db,
            settings=settings,
            parent_model_factory=lambda: _ToolSequenceModel("run_company_journey"),
        )
    ) as client:
        response = client.post(
            "/agentos/agents/samurai/runs",
            headers={"Authorization": f"Bearer {settings.os_security_key.get_secret_value()}"},
            data={
                "message": "start a company",
                "session_id": "failure-session",
                "user_id": "founder",
                "stream": "false",
            },
        )

    assert response.status_code == 200
    payload = cast("dict[str, object]", response.json())
    assert payload["status"] == RunStatus.error.value
    assert json.loads(cast("str", payload["content"])) == {
        "outcome": "failed",
        "error_code": "child_workflow_failed",
    }
    assert provider_marker not in caplog.text
    assert "Attempted to exit cancel scope in a different task" not in caplog.text
    assert provider_marker not in response.text
    assert attempts == 1
    session = db.get_session("failure-session", user_id="founder")
    assert isinstance(session, AgentSession)
    assert session.runs is not None
    assert session.runs[-1].status == RunStatus.error.value


def test_child_timeout_cancels_drains_and_returns_terminal_error(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def hang(_: StepInput) -> Never:
        await anyio.sleep_forever()
        raise AssertionError

    def hanging_workflow(_db: SqliteDb, _settings: Settings, *, stage: str) -> Workflow:
        assert stage == "brief"
        return Workflow(
            id="company-journey",
            name="Hanging child",
            db=_db,
            steps=[Step(name="hang", executor=hang)],
            telemetry=False,
        )

    monkeypatch.setattr("samurai.parent.create_company_workflow", hanging_workflow)
    database = SqliteDb(db_file=str(tmp_path / "child-timeout.db"))
    settings = Settings.model_validate({"gemini_timeout_seconds": 0.01})
    with TestClient(
        create_app(
            db=database,
            settings=settings,
            parent_model_factory=lambda: _ToolSequenceModel("run_company_journey"),
        )
    ) as client:
        response = client.post(
            "/agentos/agents/samurai/runs",
            headers={"Authorization": f"Bearer {settings.os_security_key.get_secret_value()}"},
            data={
                "message": "start a company",
                "session_id": "timeout-session",
                "user_id": "founder",
                "stream": "false",
            },
        )

    assert response.status_code == 200
    payload = cast("dict[str, object]", response.json())
    assert payload["status"] == RunStatus.error.value
    assert json.loads(cast("str", payload["content"]))["error_code"] == ("child_workflow_failed")
    sessions = database.get_sessions(
        session_type=SessionType.WORKFLOW,
        user_id="founder",
    )
    assert isinstance(sessions, list)
    assert len(sessions) == 1
    child_session = sessions[0]
    assert isinstance(child_session, WorkflowSession)
    assert child_session.runs is not None
    assert child_session.runs[-1].status == RunStatus.cancelled.value
    assert anyio.run(aget_active_runs) == {}


def test_nonstreaming_child_failures_share_sanitized_terminal_boundary(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider_marker = "launch-analysis-provider-marker"
    attempts = 0

    async def fail(*_args: object, **_kwargs: object) -> Never:
        nonlocal attempts
        attempts += 1
        raise TimeoutError(provider_marker)

    metric_arguments = json.dumps(
        {
            "measurements": [
                {
                    "name": "revenue",
                    "value": 10,
                    "unit": "INR",
                    "window_start": "2026-10-01T00:00:00Z",
                    "window_end": "2026-10-02T00:00:00Z",
                    "source_label": "founder spreadsheet",
                    "collected_at": "2026-10-03T00:00:00Z",
                }
            ]
        }
    )
    cases = (
        ("_create_launch_drafts", "create_launch_drafts", "{}"),
        ("_analyze_metrics", "analyze_metrics", metric_arguments),
    )

    for index, (target, tool_name, arguments) in enumerate(cases):
        monkeypatch.setattr(f"samurai.parent.{target}", fail)
        model = _ToolSequenceModel(tool_name, arguments={tool_name: arguments})
        settings = Settings.model_validate({})
        with TestClient(
            create_app(
                db=SqliteDb(db_file=str(tmp_path / f"child-{index}.db")),
                settings=settings,
                parent_model_factory=lambda model=model: model,
            )
        ) as client:
            response = client.post(
                "/agentos/agents/samurai/runs",
                headers={"Authorization": f"Bearer {settings.os_security_key.get_secret_value()}"},
                data={
                    "message": "run child operation",
                    "session_id": f"child-session-{index}",
                    "user_id": "founder",
                    "stream": "false",
                },
            )

        assert response.status_code == 200
        payload = cast("dict[str, object]", response.json())
        assert payload["status"] == RunStatus.error.value
        assert json.loads(cast("str", payload["content"]))["error_code"] == (
            "child_workflow_failed"
        )
        assert model.calls == 1
        assert provider_marker not in response.text
        assert provider_marker not in caplog.text
        if tool_name == "analyze_metrics":
            assert '"measurements"' in model.advertised_tools_json
            assert '"checked_at"' not in model.advertised_tools_json
        caplog.clear()

    assert attempts == len(cases)


def test_parent_stream_reports_start_and_completion_for_real_workflow_steps(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = _deterministic_catalog()

    def catalog_factory(_settings: Settings) -> dict[Role, ConfiguredRole]:
        return catalog

    monkeypatch.setattr("samurai.company_workflow.create_role_catalog", catalog_factory)
    monkeypatch.setattr("samurai.company_workflow.run_research", _mapped_research)
    database = SqliteDb(db_file=str(tmp_path / "step-completion.db"))
    agent = create_parent_agent(database, Settings.model_validate({}), model=_ToolSequenceModel())
    raw_tools = cast("list[object]", agent.tools)
    tool = next(
        item
        for item in raw_tools
        if isinstance(item, Function) and item.name == "run_company_journey"
    )
    entrypoint = cast("Callable[..., abc.AsyncGenerator[CustomEvent | str]]", tool.entrypoint)

    async def scenario() -> list[str]:
        return [
            cast("dict[str, str]", event.to_dict()["content"])["detail"]
            async for event in entrypoint(
                run_context=RunContext(
                    run_id="completion-run",
                    session_id="completion-session",
                    user_id="founder",
                    session_state={},
                ),
                idea="Synthetic test business",
                target_customer="Test customers",
                geography="Test market",
                budget="No budget",
                founder_skills="Test delivery skills",
                goal="Validate a test offer",
                stage="plan",
            )
            if isinstance(event, CustomEvent)
        ]

    progress = anyio.run(scenario)
    for step in (
        "Intake",
        "Research",
        "Verify evidence",
        "Strategy",
        "Product plan",
        "Verify journey",
    ):
        assert f"{step} started" in progress
        assert f"{step} completed" in progress
        assert progress.index(f"{step} started") < progress.index(f"{step} completed")
