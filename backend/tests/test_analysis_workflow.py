from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Never, cast, final, override
from uuid import uuid4

import anyio
import pytest
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.google import Gemini
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.base import RunStatus
from agno.session.workflow import WorkflowSession
from pydantic import HttpUrl

from samurai import parent as parent_module
from samurai.agents import ROLE_CAPABILITIES, ConfiguredRole, create_role_catalog
from samurai.config import Settings
from samurai.contracts import (
    ArtifactEnvelope,
    ArtifactType,
    CompanyBrief,
    CompanyState,
    FounderMetricInput,
    IntakeArtifact,
    Role,
    SourceReference,
    VerificationFinding,
    WorkflowResult,
    accept_artifact,
    create_company_state,
)
from samurai.parent import child_session_id

if TYPE_CHECKING:
    import pathlib
    from collections import abc
    from collections.abc import Awaitable, Callable

    from agno.models.message import Message
    from google.genai.types import Content

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
ANALYZE_METRICS = cast(
    "Callable[..., Awaitable[WorkflowResult]]",
    parent_module.__dict__["_analyze_metrics"],
)


@final
class _AnalysisDraftModel(Model):
    def __init__(self, *, invalid_output: bool = False) -> None:
        super().__init__(id="analysis-draft-test", provider="test")
        self.id = "analysis-draft-test"
        self.invalid_output = invalid_output

    @override
    def invoke(self, *_args: Never, **_kwargs: Never) -> ModelResponse:
        return ModelResponse()

    @override
    async def ainvoke(self, messages: list[Message], **_kwargs: Never) -> ModelResponse:
        assert messages
        formatter = cast(
            "Callable[[Gemini, list[Message]], tuple[list[Content], object]]",
            Gemini.__dict__["_format_messages"],
        )
        contents, _ = formatter(Gemini(api_key="offline-test-key"), messages)
        request_json = json.dumps(
            [content.model_dump(mode="json") for content in contents]
        )
        assert contents
        assert '"role": "user"' in request_json
        assert "qualified_leads" in request_json
        content: dict[str, object] = (
            {"artifact_type": "analyst_brief"}
            if self.invalid_output
            else {
                "findings": ["Twelve qualified leads were founder supplied."],
                "recommendations": ["Verify the lead count through a trusted connector."],
            }
        )
        return ModelResponse(
            content=json.dumps(content)
        )

    @override
    def invoke_stream(self, *_args: Never, **_kwargs: Never) -> abc.Iterator[ModelResponse]:
        return iter(())

    @override
    async def ainvoke_stream(
        self, *_args: Never, **_kwargs: Never
    ) -> abc.AsyncIterator[ModelResponse]:
        yield ModelResponse()

    @override
    def _parse_provider_response(
        self, response: ModelResponse, **_kwargs: Never
    ) -> ModelResponse:
        return response

    @override
    def _parse_provider_response_delta(self, response: ModelResponse) -> ModelResponse:
        return response


def _grounded_state(parent_session_id: str) -> CompanyState:
    state = create_company_state(parent_session_id, created_at=NOW)
    source = SourceReference(
        source_id=uuid4(),
        url=HttpUrl("https://example.com/grounded-market-source"),
        title="Grounded market source",
        retrieved_at=NOW,
        search_query="qualified lead benchmarks",
        excerpt="A retained source used by the accepted intake artifact.",
    )
    artifact = ArtifactEnvelope(
        artifact_id=uuid4(),
        company_id=state.context.company_id,
        artifact_type=ArtifactType.INTAKE,
        revision=1,
        input_revision=0,
        producer=Role.INTAKE,
        status="complete",
        payload=IntakeArtifact(
            brief=CompanyBrief(
                idea="A grounded company",
                target_customer="Revenue teams",
                geography="India",
                budget="INR 100000",
                founder_skills="Sales",
                goal="Validate demand",
                supplied_context=[],
                assumptions=[],
                open_questions=[],
                next_actions=[],
            )
        ),
        sources=(source,),
        assumptions=(),
        verification_findings=(
            VerificationFinding(
                code="intake_retained",
                message="Founder input was retained.",
                severity="info",
            ),
        ),
    )
    return accept_artifact(
        state,
        artifact,
        authenticated_session_id=parent_session_id,
    )


def test_parent_analysis_persists_json_safe_child_run_and_preserves_sources(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = "founder"
    parent_session_id = "grounded-analysis-session"
    parent_run_id = "parent-analysis-run"
    child_id = child_session_id(user_id, parent_session_id)
    database = SqliteDb(db_file=str(tmp_path / "grounded-analysis.db"))
    original_state = _grounded_state(parent_session_id)
    _ = database.upsert_session(
        WorkflowSession(
            session_id=child_id,
            user_id=user_id,
            workflow_id="company-journey",
            session_data={"session_state": {"company": original_state.model_dump(mode="json")}},
        )
    )
    settings = Settings.model_validate({})
    configured = create_role_catalog(settings)[Role.ANALYST]
    configured.agent.model = _AnalysisDraftModel()

    def analyst_catalog(_settings: Settings) -> dict[Role, ConfiguredRole]:
        return {
            Role.ANALYST: ConfiguredRole(
                agent_id=configured.agent_id,
                agent=configured.agent,
                capability=ROLE_CAPABILITIES[Role.ANALYST],
                instructions=configured.instructions,
            )
        }

    monkeypatch.setattr("samurai.parent.create_role_catalog", analyst_catalog)
    metric = FounderMetricInput(
        name="qualified_leads",
        value=12,
        unit="leads",
        window_start=NOW - timedelta(days=7),
        window_end=NOW - timedelta(hours=2),
        source_label="manual founder spreadsheet",
        collected_at=NOW - timedelta(hours=1),
    )
    parent_context = RunContext(
        run_id=parent_run_id,
        user_id=user_id,
        session_id=parent_session_id,
        session_state={},
    )

    result = anyio.run(
        partial(ANALYZE_METRICS, database, settings, (metric,), parent_context)
    )

    child = database.get_session(
        child_id,
        session_type=SessionType.WORKFLOW,
        user_id=user_id,
    )
    assert isinstance(child, WorkflowSession)
    assert child.runs is not None
    persisted_run = next(run for run in child.runs if run.workflow_id == "company-analysis")
    persisted_result = WorkflowResult.model_validate(persisted_run.content)
    session_data = cast("dict[str, object]", child.session_data)
    session_state = cast("dict[str, object]", session_data["session_state"])
    persisted_state = CompanyState.model_validate(session_state["company"])
    measurement = result.artifacts[0].measurements[0]

    assert persisted_run.status == RunStatus.completed
    assert persisted_result == result
    assert result.outcome == "based_on_founder_supplied_metrics"
    assert measurement.model_dump(
        exclude={"metric_id", "provenance", "trusted_connector_receipt"}
    ) == metric.model_dump()
    assert measurement.provenance == "founder_supplied"
    assert measurement.trusted_connector_receipt is None
    assert persisted_state.artifacts[0].sources == original_state.artifacts[0].sources
    assert persisted_state.artifacts[-1] == result.artifacts[0]


def test_invalid_analysis_output_fails_without_mutating_company_state(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = "founder"
    parent_session_id = "invalid-analysis-session"
    child_id = child_session_id(user_id, parent_session_id)
    database = SqliteDb(db_file=str(tmp_path / "invalid-analysis.db"))
    original_state = _grounded_state(parent_session_id)
    expected_session_data = {
        "session_state": {"company": original_state.model_dump(mode="json")}
    }
    _ = database.upsert_session(
        WorkflowSession(
            session_id=child_id,
            user_id=user_id,
            workflow_id="company-journey",
            session_data=expected_session_data,
        )
    )
    settings = Settings.model_validate({})
    configured = create_role_catalog(settings)[Role.ANALYST]
    configured.agent.model = _AnalysisDraftModel(invalid_output=True)

    def analyst_catalog(_settings: Settings) -> dict[Role, ConfiguredRole]:
        return {Role.ANALYST: configured}

    monkeypatch.setattr("samurai.parent.create_role_catalog", analyst_catalog)
    metric = FounderMetricInput(
        name="qualified_leads",
        value=12,
        unit="leads",
        window_start=NOW - timedelta(days=7),
        window_end=NOW - timedelta(hours=2),
        source_label="manual founder spreadsheet",
        collected_at=NOW - timedelta(hours=1),
    )
    parent_context = RunContext(
        run_id="invalid-parent-analysis-run",
        user_id=user_id,
        session_id=parent_session_id,
        session_state={},
    )

    with pytest.raises(RuntimeError, match="invalid analyst output"):
        _ = anyio.run(
            partial(ANALYZE_METRICS, database, settings, (metric,), parent_context)
        )

    child = database.get_session(
        child_id,
        session_type=SessionType.WORKFLOW,
        user_id=user_id,
    )
    assert isinstance(child, WorkflowSession)
    assert cast("dict[str, object]", child.session_data)["session_state"] == (
        expected_session_data["session_state"]
    )
    assert child.runs is not None
    failed_run = next(run for run in child.runs if run.workflow_id == "company-analysis")
    assert failed_run.status == RunStatus.error
