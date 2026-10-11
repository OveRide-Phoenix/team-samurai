"""Metrics-gated Analyst workflow with deterministic provenance and persistence."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final
from uuid import uuid4

from agno.workflow import Step, StepInput, StepOutput, Workflow
from pydantic import AwareDatetime  # noqa: TC002 - Pydantic resolves this field type at runtime.

from samurai.contracts import (
    AnalysisArtifact,
    AnalysisDraft,
    ArtifactEnvelope,
    ArtifactType,
    CompanyState,
    Contract,
    FounderMetricInput,
    MeasuredResult,
    Role,
    VerificationFinding,
    WorkflowRequest,
    WorkflowResult,
    accept_artifact,
)
from samurai.workflow_state import load_company_state, save_company_state

if TYPE_CHECKING:
    from agno.agent import Agent
    from agno.db.base import BaseDb
    from agno.run import RunContext
    from agno.run.workflow import WorkflowRunOutput
    from agno.workflow.workflow import WorkflowSteps

MAX_METRIC_AGE: Final = timedelta(days=30)
GATE_STEP: Final = "Check metric eligibility"


class AnalysisCancelledError(RuntimeError):
    """Native analysis workflow cancellation."""

    def __init__(self, run_id: str) -> None:
        """Identify the cancelled child run."""
        self.run_id: str = run_id
        super().__init__(f"Analysis run {run_id} was cancelled")


class AnalysisWorkflowInput(Contract):
    """Trusted request time and founder metric input for one analysis run."""

    request: WorkflowRequest
    metrics: tuple[FounderMetricInput, ...]
    checked_at: AwareDatetime


class _PreparedAnalysis(Contract):
    state: CompanyState
    measurements: tuple[MeasuredResult, ...]


class _AnalysisExecutionInput(Contract):
    state: CompanyState
    metrics: tuple[FounderMetricInput | MeasuredResult, ...]
    checked_at: AwareDatetime


def _step_output(content: Contract, *, stop: bool = False) -> StepOutput:
    return StepOutput(content=content.model_dump(mode="json"), stop=stop)


def _eligible(metric: FounderMetricInput, *, checked_at: datetime) -> bool:
    return (
        type(metric) is FounderMetricInput
        and metric.window_end <= metric.collected_at <= checked_at
        and metric.window_end <= checked_at
        and checked_at - metric.collected_at <= MAX_METRIC_AGE
    )


def _founder_measurement(metric: FounderMetricInput) -> MeasuredResult:
    return MeasuredResult(
        metric_id=uuid4(),
        name=metric.name,
        value=metric.value,
        unit=metric.unit,
        window_start=metric.window_start,
        window_end=metric.window_end,
        source_label=metric.source_label,
        collected_at=metric.collected_at,
        provenance="founder_supplied",
    )


def _gate_metrics(step_input: StepInput) -> StepOutput:
    workflow_input = _AnalysisExecutionInput.model_validate(step_input.input)
    state = workflow_input.state
    if not workflow_input.metrics or any(
        not _eligible(metric, checked_at=workflow_input.checked_at)
        for metric in workflow_input.metrics
    ):
        return _step_output(
            WorkflowResult(
                company_id=state.context.company_id,
                revision=state.current_revision,
                outcome="requires_metrics",
            ),
            stop=True,
        )
    return _step_output(
        _PreparedAnalysis(
            state=state,
            measurements=tuple(_founder_measurement(metric) for metric in workflow_input.metrics),
        )
    )


def _complete_analysis(step_input: StepInput) -> StepOutput:
    assessment = AnalysisDraft.model_validate(step_input.previous_step_content)
    previous_outputs = step_input.previous_step_outputs or {}
    prepared = _PreparedAnalysis.model_validate(previous_outputs[GATE_STEP].content)
    state = prepared.state
    payload = AnalysisArtifact(
        metric_ids=tuple(metric.metric_id for metric in prepared.measurements),
        findings=assessment.findings,
        recommendations=assessment.recommendations,
        basis="based_on_founder_supplied_metrics",
    )
    artifact = ArtifactEnvelope(
        artifact_id=uuid4(),
        company_id=state.context.company_id,
        artifact_type=ArtifactType.ANALYSIS,
        revision=state.current_revision + 1,
        input_revision=state.current_revision,
        producer=Role.ANALYST,
        status="based_on_founder_supplied_metrics",
        payload=payload,
        measurements=prepared.measurements,
        assumptions=(),
        verification_findings=(
            VerificationFinding(
                code="founder_metrics_unverified",
                message="Analysis is conditional on founder-supplied metrics.",
                severity="warning",
            ),
        ),
    )
    updated = accept_artifact(
        state,
        artifact,
        authenticated_session_id=state.context.authenticated_session_id,
    )
    accepted = updated.artifacts[-1]
    return _step_output(
        WorkflowResult(
            company_id=updated.context.company_id,
            revision=updated.current_revision,
            outcome="based_on_founder_supplied_metrics",
            artifacts=(accepted,),
        )
    )


def create_analysis_workflow(db: BaseDb, analyst: Agent) -> Workflow:
    """Build the explicit metric gate, Analyst, and deterministic completion steps."""
    steps: WorkflowSteps = [
        Step(name=GATE_STEP, executor=_gate_metrics, max_retries=0),
        Step(name="Analyze eligible founder metrics", agent=analyst, max_retries=0),
        Step(name="Complete conditional analysis", executor=_complete_analysis, max_retries=0),
    ]
    return Workflow(
        id="company-analysis",
        name="Samurai — Analyze Business Metrics",
        db=db,
        steps=steps,
        store_events=True,
        telemetry=False,
    )


async def run_analysis(
    workflow: Workflow,
    workflow_input: AnalysisWorkflowInput,
    run_context: RunContext,
    *,
    run_id: str | None = None,
) -> WorkflowResult:
    """Run analysis inside validated company context and persist only an accepted artifact."""
    state = load_company_state(
        workflow_input.request,
        run_context,
        created_at=workflow_input.checked_at,
    )
    execution_input = _AnalysisExecutionInput(
        state=state,
        metrics=workflow_input.metrics,
        checked_at=workflow_input.checked_at,
    )
    output: WorkflowRunOutput = await workflow.arun(
        execution_input.model_dump(mode="json"),
        user_id=run_context.user_id,
        session_id=run_context.session_id,
        session_state=run_context.session_state,
        dependencies=run_context.dependencies,
        run_id=run_id,
        stream=False,
    )
    if output.is_cancelled:
        cancelled_run_id = output.run_id or run_id or "unknown"
        raise AnalysisCancelledError(cancelled_run_id)
    result = WorkflowResult.model_validate(output.content)
    if result.artifacts:
        updated = CompanyState(
            context=state.context,
            current_revision=result.revision,
            artifacts=(*state.artifacts, *result.artifacts),
        )
        save_company_state(updated, run_context)
        _ = await workflow.aupdate_session_state(
            {"company": updated.model_dump(mode="json")},
            session_id=run_context.session_id,
        )
    return result
