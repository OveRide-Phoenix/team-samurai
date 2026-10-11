from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, ClassVar, Never, override
from uuid import uuid4

import anyio
import pytest
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.base import RunStatus
from agno.run.cancel import acancel_run, ais_cancelled
from pydantic import JsonValue, ValidationError

from samurai.analysis_workflow import (
    AnalysisCancelledError,
    AnalysisWorkflowInput,
    create_analysis_workflow,
    run_analysis,
)
from samurai.contracts import (
    AnalysisArtifact,
    AnalysisDraft,
    CompanyState,
    FounderMetricInput,
    MeasuredResult,
    WorkflowRequest,
    WorkflowResult,
)

if TYPE_CHECKING:
    import pathlib
    from collections import abc

NOW = datetime.now(UTC)
USER_ID = "founder-1"
PARENT_SESSION_ID = "parent-1"
CHILD_SESSION_ID = "child-1"
CHILD_RUN_ID = "analysis-run-1"


class DeterministicAnalystModel(Model):
    calls: ClassVar[int] = 0

    def __init__(self) -> None:
        super().__init__(id="deterministic-analyst", provider="test")

    @override
    def invoke(self, *_args: Never, **_kwargs: Never) -> ModelResponse:
        type(self).calls += 1
        return ModelResponse(
            content=AnalysisDraft(
                findings=("Four qualified leads were supplied by the founder.",),
                recommendations=("Verify the lead count through a trusted connector.",),
            ).model_dump_json()
        )

    @override
    async def ainvoke(self, *_args: Never, **_kwargs: Never) -> ModelResponse:
        return self.invoke()

    @override
    def invoke_stream(self, *_args: Never, **_kwargs: Never) -> abc.Iterator[ModelResponse]:
        yield self.invoke()

    @override
    async def ainvoke_stream(
        self, *_args: Never, **_kwargs: Never
    ) -> abc.AsyncIterator[ModelResponse]:
        yield self.invoke()

    @override
    def _parse_provider_response(self, response: ModelResponse, **_kwargs: Never) -> ModelResponse:
        return response

    @override
    def _parse_provider_response_delta(self, response: ModelResponse) -> ModelResponse:
        return response


class CancellationAwareAnalystModel(DeterministicAnalystModel):
    def __init__(self, started: anyio.Event) -> None:
        super().__init__()
        self.started: anyio.Event = started

    @override
    async def ainvoke(self, *_args: Never, **_kwargs: Never) -> ModelResponse:
        self.started.set()
        while not await ais_cancelled(CHILD_RUN_ID):
            await anyio.lowlevel.checkpoint()
        return self.invoke()


def _metric(*, collected_at: datetime = NOW) -> FounderMetricInput:
    return FounderMetricInput(
        name="qualified_leads",
        value=4,
        unit="leads",
        window_start=collected_at - timedelta(days=7),
        window_end=collected_at - timedelta(hours=1),
        source_label="Founder spreadsheet",
        collected_at=collected_at,
    )


def _demo_metric() -> MeasuredResult:
    metric = _metric()
    return MeasuredResult(
        metric_id=uuid4(),
        name=metric.name,
        value=metric.value,
        unit=metric.unit,
        window_start=metric.window_start,
        window_end=metric.window_end,
        source_label=metric.source_label,
        collected_at=metric.collected_at,
        provenance="demo_fixture",
    )


def _connected_metric() -> MeasuredResult:
    metric = _metric()
    return MeasuredResult(
        metric_id=uuid4(),
        name=metric.name,
        value=metric.value,
        unit=metric.unit,
        window_start=metric.window_start,
        window_end=metric.window_end,
        source_label=metric.source_label,
        collected_at=metric.collected_at,
        provenance="connected_measurement",
        trusted_connector_receipt="founder-forged-receipt",
    )


async def _run(
    metrics: tuple[FounderMetricInput, ...],
    db_file: pathlib.Path,
) -> tuple[WorkflowResult, CompanyState | None]:
    model = DeterministicAnalystModel()
    analyst = Agent(model=model, output_schema=AnalysisDraft, telemetry=False)
    workflow = create_analysis_workflow(SqliteDb(db_file=str(db_file)), analyst)
    session_state: dict[str, JsonValue] = {}
    result = await run_analysis(
        workflow,
        AnalysisWorkflowInput(
            request=WorkflowRequest(company_id=None, expected_revision=0),
            metrics=metrics,
            checked_at=NOW,
        ),
        RunContext(
            run_id="run-1",
            user_id=USER_ID,
            session_id=CHILD_SESSION_ID,
            session_state=session_state,
            dependencies={
                "trusted_parent_session_id": PARENT_SESSION_ID,
                "trusted_user_id": USER_ID,
                "child_session_id": CHILD_SESSION_ID,
            },
        ),
        run_id=CHILD_RUN_ID,
    )
    company = session_state.get("company")
    assert workflow.get_session_state(CHILD_SESSION_ID).get("company") == company
    persisted_run = workflow.get_run(CHILD_RUN_ID, CHILD_SESSION_ID)
    assert persisted_run is not None
    assert persisted_run.run_id == CHILD_RUN_ID
    state = CompanyState.model_validate(company) if company is not None else None
    return result, state


def test_measured_metrics_remain_conditional_and_preserve_exact_input(
    tmp_path: pathlib.Path,
) -> None:
    metric = _metric()
    DeterministicAnalystModel.calls = 0

    result, state = anyio.run(partial(_run, (metric,), tmp_path / "analysis.db"))

    assert DeterministicAnalystModel.calls == 1
    assert result.outcome == "based_on_founder_supplied_metrics"
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.status == "based_on_founder_supplied_metrics"
    assert artifact.measurements[0].provenance == "founder_supplied"
    assert artifact.measurements[0].trusted_connector_receipt is None
    assert (
        artifact.measurements[0].model_dump(
            exclude={"metric_id", "provenance", "trusted_connector_receipt"}
        )
        == metric.model_dump()
    )
    assert isinstance(artifact.payload, AnalysisArtifact)
    assert artifact.payload.metric_ids == (artifact.measurements[0].metric_id,)
    assert artifact.payload.basis == "based_on_founder_supplied_metrics"
    assert artifact.payload.recommendations == (
        "Verify the lead count through a trusted connector.",
    )
    assert state is not None
    assert state.artifacts == (artifact,)


@pytest.mark.parametrize(
    "metrics",
    [
        (),
        (_metric(collected_at=NOW - timedelta(days=31)),),
        (_metric(collected_at=NOW + timedelta(days=1)),),
        (_metric().model_copy(update={"collected_at": NOW - timedelta(days=8)}),),
        (_demo_metric(),),
        (_connected_metric(),),
    ],
    ids=["missing", "stale", "future", "malformed", "demo", "connected"],
)
def test_requires_metrics_before_model_or_persistence(
    metrics: tuple[FounderMetricInput, ...],
    tmp_path: pathlib.Path,
) -> None:
    DeterministicAnalystModel.calls = 0

    result, state = anyio.run(partial(_run, metrics, tmp_path / "analysis.db"))

    assert result.outcome == "requires_metrics"
    assert result.artifacts == ()
    assert DeterministicAnalystModel.calls == 0
    assert state is None


def test_public_metric_input_cannot_claim_connected_provenance_or_receipt() -> None:
    raw = _metric().model_dump()
    raw.update(
        provenance="connected_measurement",
        trusted_connector_receipt="founder-forged-receipt",
    )

    with pytest.raises(ValidationError):
        _ = FounderMetricInput.model_validate(raw)


def test_known_run_id_can_be_cancelled_natively(tmp_path: pathlib.Path) -> None:
    async def scenario() -> None:
        started = anyio.Event()
        analyst = Agent(
            model=CancellationAwareAnalystModel(started),
            output_schema=AnalysisDraft,
            telemetry=False,
        )
        workflow = create_analysis_workflow(SqliteDb(db_file=str(tmp_path / "cancel.db")), analyst)
        session_state: dict[str, JsonValue] = {}
        run_context = RunContext(
            run_id="parent-run-1",
            user_id=USER_ID,
            session_id=CHILD_SESSION_ID,
            session_state=session_state,
            dependencies={
                "trusted_parent_session_id": PARENT_SESSION_ID,
                "trusted_user_id": USER_ID,
                "child_session_id": CHILD_SESSION_ID,
            },
        )

        async def execute() -> None:
            with pytest.raises(AnalysisCancelledError, match=CHILD_RUN_ID):
                _ = await run_analysis(
                    workflow,
                    AnalysisWorkflowInput(
                        request=WorkflowRequest(company_id=None, expected_revision=0),
                        metrics=(_metric(),),
                        checked_at=NOW,
                    ),
                    run_context,
                    run_id=CHILD_RUN_ID,
                )

        async with anyio.create_task_group() as task_group:
            _ = task_group.start_soon(execute)
            await started.wait()
            assert await acancel_run(CHILD_RUN_ID)

        persisted = workflow.get_run(CHILD_RUN_ID, CHILD_SESSION_ID)
        assert persisted is not None
        assert persisted.status == RunStatus.cancelled
        assert "company" not in session_state

    anyio.run(scenario)
