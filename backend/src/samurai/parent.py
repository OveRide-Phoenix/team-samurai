"""Founder-facing Samurai agent with four bounded workflow tools."""

from __future__ import annotations

import json
from collections import abc  # noqa: TC003 - Agno resolves tool annotations at runtime.
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, unique
from pathlib import Path
from time import time
from types import MethodType
from typing import TYPE_CHECKING, ClassVar, Final, cast, override
from uuid import NAMESPACE_URL, UUID, uuid5

import anyio
from agno.agent import Agent
from agno.agent.factory import AgentFactory
from agno.db.base import SessionType
from agno.exceptions import StopAgentRun
from agno.run import RunContext
from agno.run.agent import CustomEvent
from agno.run.cancel import acancel_run, ais_cancelled
from agno.run.workflow import (
    StepProgressEvent,
    WorkflowCancelledEvent,
    WorkflowCompletedEvent,
)
from agno.session.workflow import WorkflowSession
from agno.skills import LocalSkills, Skills
from agno.tools.function import Function
from pydantic import ConfigDict, ValidationError

from samurai.agents import ROLE_CAPABILITIES, create_role_catalog
from samurai.analysis_workflow import (
    AnalysisCancelledError,
    AnalysisWorkflowInput,
    create_analysis_workflow,
    run_analysis,
)
from samurai.company_workflow import CompanyJourneyRequest, create_company_workflow
from samurai.config import Settings, create_model
from samurai.contracts import (
    CompanyBrief,
    CompanyState,
    Contract,
    FounderMetricInput,
    IntakeArtifact,
    ResearchArtifact,
    Role,
    SourceReference,
    VerificationFinding,
    WorkflowRequest,
    WorkflowResult,
)
from samurai.launch_workflows import (
    LaunchAction,
    LaunchDraftRequest,
    LaunchKind,
    LaunchRole,
    create_launch_workflows,
    run_launch_drafts,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from agno.db.base import BaseDb
    from agno.factory import RequestContext
    from agno.models.base import Model
    from agno.models.response import ModelResponse

PARENT_AGENT_ID: Final = "samurai"
PARENT_AGENT_NAME: Final = "Samurai"
PARENT_DESCRIPTION: Final = "Build and improve one evidence-linked company with Samurai."
TOOL_RESULT_MARKER: Final = "\nSAMURAI_WORKFLOW_RESULT="
PARENT_BINDING_KEYS: Final = frozenset({"child_session_id", "company_id", "current_revision"})
AGNO_SESSION_KEYS: Final = frozenset({"current_user_id", "current_session_id", "current_run_id"})
STARTER_PROMPTS: Final = [
    "Build my business: describe the idea, customer, geography, budget, founder skills, and goal.",
    "Continue my company plan using the context and decisions already retained.",
    "Create reviewable Builder, Marketer, and Sales drafts from my verified plan.",
    "Analyze these provenance-labelled business metrics and recommend what to improve.",
]


class CompanyStateSummary(Contract):
    """Read-only summary of the company bound to a parent session."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)
    company_id: UUID | None
    revision: int
    artifact_count: int
    status: str
    brief: CompanyBrief | None = None
    sources: tuple[SourceReference, ...] = ()
    evidence_conflicts: tuple[str, ...] = ()
    verification_findings: tuple[VerificationFinding, ...] = ()
    next_decision: str | None = None

    @override
    def __str__(self) -> str:
        return self.model_dump_json()


class _ParentWorkflowResult(WorkflowResult):
    @override
    def __str__(self) -> str:
        return self.model_dump_json()


class _ChildWorkflowState(Contract):
    company: CompanyState | None = None


class _ChildSessionData(Contract):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    session_state: _ChildWorkflowState


class _BoundedSkills(Skills):
    @override
    def get_tools(self) -> list[Function]:
        tools = [tool for tool in super().get_tools() if tool.name != "get_skill_script"]
        for tool in tools:
            tool.stop_after_tool_call = True
            tool.show_result = True
        return tools


@unique
class ParentContextIssue(StrEnum):
    """Stable sanitized parent boundary failures."""

    USER_REQUIRED = "authenticated user is required"
    SESSION_REQUIRED = "parent session is required"
    OWNER_MISMATCH = "child workflow session owner does not match"
    COMPANY_MISMATCH = "child company does not belong to parent session"
    BINDING_MISMATCH = "parent session binding is not canonical"
    JOURNEY_REQUIRED_FOR_DRAFTS = "company journey must exist before launch drafts"
    JOURNEY_REQUIRED_FOR_ANALYSIS = "company journey must exist before analysis"


@dataclass(frozen=True, slots=True)
class ParentContextError(Exception):
    """Reject missing or non-canonical parent identity and company bindings."""

    issue: ParentContextIssue

    @override
    def __str__(self) -> str:
        return self.issue.value


class _ParentModelError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("parent model request failed")


def _sanitize_async_model_failures(model: Model) -> Model:
    original_ainvoke = cast("Callable[..., Awaitable[ModelResponse]]", model.ainvoke)
    original_ainvoke_stream = cast(
        "Callable[..., AsyncIterator[ModelResponse]]", model.ainvoke_stream
    )

    async def safe_ainvoke(
        _model: Model,
        *args: object,
        **kwargs: object,
    ) -> ModelResponse:
        try:
            return await original_ainvoke(*args, **kwargs)
        except Exception:  # noqa: BLE001 - provider details must stop at this trust boundary.
            raise _ParentModelError from None

    async def safe_ainvoke_stream(
        _model: Model,
        *args: object,
        **kwargs: object,
    ) -> abc.AsyncIterator[ModelResponse]:
        try:
            async for response in original_ainvoke_stream(*args, **kwargs):
                yield response
        except Exception:  # noqa: BLE001 - provider details must stop at this trust boundary.
            raise _ParentModelError from None

    model.ainvoke = MethodType(safe_ainvoke, model)
    model.ainvoke_stream = MethodType(safe_ainvoke_stream, model)
    return model


def child_session_id(user_id: str, parent_session_id: str) -> str:
    """Derive one opaque company workflow session from trusted owner context."""
    namespace_value = json.dumps(
        ("samurai", user_id, parent_session_id, "company"),
        separators=(",", ":"),
    )
    return str(uuid5(NAMESPACE_URL, namespace_value))


def _trusted_identity(run_context: RunContext) -> tuple[str, str, str]:
    user_id = run_context.user_id
    if not user_id:
        raise ParentContextError(ParentContextIssue.USER_REQUIRED)
    if not run_context.session_id:
        raise ParentContextError(ParentContextIssue.SESSION_REQUIRED)
    return user_id, run_context.session_id, child_session_id(user_id, run_context.session_id)


def _child_state(db: BaseDb, run_context: RunContext) -> tuple[str, CompanyState | None]:
    user_id, parent_session_id, child_id = _trusted_identity(run_context)
    session = db.get_session(
        child_id,
        session_type=SessionType.WORKFLOW,
        user_id=user_id,
    )
    state: CompanyState | None = None
    if session is not None:
        if not isinstance(session, WorkflowSession) or session.user_id != user_id:
            raise ParentContextError(ParentContextIssue.OWNER_MISMATCH)
        session_data = _ChildSessionData.model_validate(session.session_data)
        company = session_data.session_state.company
        if company is not None:
            state = company
            if state.context.authenticated_session_id != parent_session_id:
                raise ParentContextError(ParentContextIssue.COMPANY_MISMATCH)

    expected = (
        {}
        if state is None
        else {
            "child_session_id": child_id,
            "company_id": str(state.context.company_id),
            "current_revision": state.current_revision,
        }
    )
    supplied = run_context.session_state or {}
    if supplied.keys() - PARENT_BINDING_KEYS - AGNO_SESSION_KEYS:
        raise ParentContextError(ParentContextIssue.BINDING_MISMATCH)
    framework_state = {
        "current_user_id": user_id,
        "current_session_id": parent_session_id,
        "current_run_id": run_context.run_id,
    }
    if any(supplied.get(key, value) != value for key, value in framework_state.items()):
        raise ParentContextError(ParentContextIssue.BINDING_MISMATCH)
    supplied_binding = {key: supplied[key] for key in PARENT_BINDING_KEYS if key in supplied}
    if supplied_binding and supplied_binding != expected:
        raise ParentContextError(ParentContextIssue.BINDING_MISMATCH)
    return child_id, state


def _dependencies(user_id: str, parent_session_id: str, child_id: str) -> dict[str, str]:
    return {
        "trusted_parent_session_id": parent_session_id,
        "trusted_user_id": user_id,
        "child_session_id": child_id,
    }


def _child_context(
    run_context: RunContext,
    child_id: str,
    state: CompanyState | None,
    *,
    run_id: str,
) -> RunContext:
    user_id, parent_session_id, _ = _trusted_identity(run_context)
    return RunContext(
        run_id=run_id,
        session_id=child_id,
        user_id=user_id,
        session_state={} if state is None else {"company": state.model_dump(mode="json")},
        dependencies=_dependencies(user_id, parent_session_id, child_id),
    )


def _bind_parent(run_context: RunContext, child_id: str, result: WorkflowResult) -> None:
    if run_context.session_state is None:
        run_context.session_state = {}
    for key in PARENT_BINDING_KEYS:
        run_context.session_state.pop(key, None)
    run_context.session_state.update(
        {
            "child_session_id": child_id,
            "company_id": str(result.company_id),
            "current_revision": result.revision,
        }
    )


def _child_run_id(run_context: RunContext, operation: str) -> str:
    user_id, parent_session_id, _ = _trusted_identity(run_context)
    namespace_value = json.dumps(
        ("samurai", user_id, parent_session_id, run_context.run_id, operation),
        separators=(",", ":"),
    )
    return str(uuid5(NAMESPACE_URL, namespace_value))


def _progress(run_context: RunContext, child_id: str, content: str) -> CustomEvent:
    return CustomEvent(
        created_at=int(time()),
        event="CustomEvent",
        agent_id=PARENT_AGENT_ID,
        agent_name=PARENT_AGENT_NAME,
        run_id=run_context.run_id,
        session_id=run_context.session_id,
        content=content,
        kind="workflow_progress",
        child_session_id=child_id,
    )


async def _cancel_children_when_parent_stops(
    parent_run_id: str,
    child_run_ids: tuple[str, ...],
    done: anyio.Event,
) -> None:
    while not done.is_set():
        if await ais_cancelled(parent_run_id):
            cancelled = False
            for child_run_id in child_run_ids:
                cancelled = await acancel_run(child_run_id) or cancelled
            if cancelled:
                return
        await anyio.sleep(0.01)


def _cancelled_tool_run() -> StopAgentRun:
    return StopAgentRun("parent run cancelled")


async def _await_with_cancel_watch[T](
    operation: Callable[[], Awaitable[T]],
    run_context: RunContext,
    child_run_ids: tuple[str, ...],
) -> T:
    done = anyio.Event()
    result: list[T] = []
    async with anyio.create_task_group() as tasks:
        _ = tasks.start_soon(
            _cancel_children_when_parent_stops,
            run_context.run_id,
            child_run_ids,
            done,
        )
        try:
            result.append(await operation())
        finally:
            done.set()
            tasks.cancel_scope.cancel()
    return result[0]


async def _create_launch_drafts(
    db: BaseDb,
    settings: Settings,
    run_context: RunContext,
    kind: LaunchKind,
    action: LaunchAction,
) -> WorkflowResult:
    child_id, state = _child_state(db, run_context)
    if state is None:
        raise ParentContextError(ParentContextIssue.JOURNEY_REQUIRED_FOR_DRAFTS)
    context = _child_context(
        run_context,
        child_id,
        state,
        run_id=_child_run_id(run_context, "launch"),
    )
    workflows = create_launch_workflows(create_role_catalog(settings), db=db)
    run_ids: dict[LaunchRole, str] = {
        Role.BUILDER: _child_run_id(run_context, "launch:builder"),
        Role.MARKETER: _child_run_id(run_context, "launch:marketer"),
        Role.SALES: _child_run_id(run_context, "launch:sales"),
    }

    async def operation() -> WorkflowResult:
        return await run_launch_drafts(
            workflows,
            LaunchDraftRequest(
                company_id=state.context.company_id,
                expected_revision=state.current_revision,
                kind=kind,
                action=action,
            ),
            context,
            datetime.now(UTC),
            run_ids=run_ids,
        )

    try:
        result = await _await_with_cancel_watch(
            operation,
            run_context,
            tuple(run_ids.values()),
        )
    except ValidationError:
        if await ais_cancelled(run_context.run_id):
            raise _cancelled_tool_run() from None
        raise
    _bind_parent(run_context, child_id, result)
    return result


async def _analyze_metrics(
    db: BaseDb,
    settings: Settings,
    metrics: tuple[FounderMetricInput, ...],
    run_context: RunContext,
) -> WorkflowResult:
    child_id, state = _child_state(db, run_context)
    if state is None:
        raise ParentContextError(ParentContextIssue.JOURNEY_REQUIRED_FOR_ANALYSIS)
    child_run_id = _child_run_id(run_context, "analysis")
    context = _child_context(run_context, child_id, state, run_id=child_run_id)
    analyst = create_role_catalog(settings)[Role.ANALYST].agent
    workflow = create_analysis_workflow(db, analyst)

    async def operation() -> WorkflowResult:
        return await run_analysis(
            workflow,
            AnalysisWorkflowInput(
                request=WorkflowRequest(
                    company_id=state.context.company_id,
                    expected_revision=state.current_revision,
                ),
                metrics=metrics,
                checked_at=datetime.now(UTC),
            ),
            context,
            run_id=child_run_id,
        )

    try:
        result = await _await_with_cancel_watch(operation, run_context, (child_run_id,))
    except AnalysisCancelledError:
        if await ais_cancelled(run_context.run_id):
            raise _cancelled_tool_run() from None
        raise
    _bind_parent(run_context, child_id, result)
    return result


def create_parent_agent(  # noqa: C901 - closures are the four bounded Agno tool surface.
    db: BaseDb,
    settings: Settings,
    *,
    model: Model | None = None,
) -> Agent:
    """Create a fresh ordinary Samurai Agent and its bounded native tools."""

    async def run_company_journey(  # noqa: PLR0913, PLR0917
        run_context: RunContext,
        idea: str | None = None,
        target_customer: str | None = None,
        geography: str | None = None,
        budget: str | None = None,
        founder_skills: str | None = None,
        goal: str | None = None,
        supplied_context: tuple[str, ...] = (),
        assumptions: tuple[str, ...] = (),
    ) -> abc.AsyncIterator[CustomEvent | str]:
        """Run or continue the verified company journey for this parent session."""
        child_id, state = _child_state(db, run_context)
        user_id, parent_session_id, _ = _trusted_identity(run_context)
        child_run_id = _child_run_id(run_context, "journey")
        request = CompanyJourneyRequest(
            company_id=None if state is None else state.context.company_id,
            expected_revision=0 if state is None else state.current_revision,
            idea=idea,
            target_customer=target_customer,
            geography=geography,
            budget=budget,
            founder_skills=founder_skills,
            goal=goal,
            supplied_context=supplied_context,
            assumptions=assumptions,
        )
        workflow = create_company_workflow(db, settings)
        cancelled = False
        events = workflow.arun(
            request,
            user_id=user_id,
            run_id=child_run_id,
            session_id=child_id,
            session_state={} if state is None else {"company": state.model_dump(mode="json")},
            dependencies=_dependencies(user_id, parent_session_id, child_id),
            stream=True,
            stream_events=True,
        )
        async for event in events:
            if not cancelled and await ais_cancelled(run_context.run_id):
                cancelled = await acancel_run(child_run_id)
            if isinstance(event, StepProgressEvent):
                yield _progress(run_context, child_id, str(event.content))
            if isinstance(event, WorkflowCancelledEvent):
                cancelled = True
            if isinstance(event, WorkflowCompletedEvent) and not cancelled:
                result = WorkflowResult.model_validate(event.content)
                _bind_parent(run_context, child_id, result)
                yield TOOL_RESULT_MARKER + result.model_dump_json()

    async def create_launch_drafts(
        run_context: RunContext,
        kind: LaunchKind = LaunchKind.ALL,
        action: LaunchAction = LaunchAction.DRAFT,
    ) -> WorkflowResult:
        """Create reviewable launch drafts without external action capability."""
        result = await _create_launch_drafts(db, settings, run_context, kind, action)
        return _ParentWorkflowResult.model_validate(result)

    async def analyze_metrics(
        metrics: tuple[FounderMetricInput, ...],
        run_context: RunContext,
    ) -> WorkflowResult:
        """Analyze eligible founder metrics without changing their provenance."""
        result = await _analyze_metrics(db, settings, metrics, run_context)
        return _ParentWorkflowResult.model_validate(result)

    def read_company_state(run_context: RunContext) -> CompanyStateSummary:
        """Read the canonical company state bound to this parent session."""
        _, state = _child_state(db, run_context)
        if state is None:
            return CompanyStateSummary(
                company_id=None,
                revision=0,
                artifact_count=0,
                status="not_started",
            )
        brief = next(
            (
                artifact.payload.brief
                for artifact in reversed(state.artifacts)
                if isinstance(artifact.payload, IntakeArtifact)
            ),
            None,
        )
        conflicts = tuple(
            conflict
            for artifact in state.artifacts
            if isinstance(artifact.payload, ResearchArtifact)
            for conflict in artifact.payload.conflicts
        )
        findings = tuple(
            finding for artifact in state.artifacts for finding in artifact.verification_findings
        )[-20:]
        sources = tuple(source for artifact in state.artifacts for source in artifact.sources)[-20:]
        next_decision = None
        if brief is not None:
            next_decision = next(iter((*brief.open_questions, *brief.next_actions)), None)
        return CompanyStateSummary(
            company_id=state.context.company_id,
            revision=state.current_revision,
            artifact_count=len(state.artifacts),
            status="active",
            brief=brief,
            sources=sources,
            evidence_conflicts=conflicts,
            verification_findings=findings,
            next_decision=next_decision,
        )

    capabilities = ", ".join(
        f"{capability.role.value}={capability.status}" for capability in ROLE_CAPABILITIES.values()
    )
    tools = [
        Function(
            name=tool.__name__,
            entrypoint=tool,
            stop_after_tool_call=True,
            show_result=True,
        )
        for tool in (
            run_company_journey,
            create_launch_drafts,
            analyze_metrics,
            read_company_state,
        )
    ]
    skills = _BoundedSkills(
        loaders=[
            LocalSkills(
                str(Path(__file__).parent / "skills" / "evidence-discipline"),
                validate=True,
            ),
            LocalSkills(str(Path(__file__).parent / "skills" / "action-boundaries"), validate=True),
        ]
    )
    return Agent(
        id=PARENT_AGENT_ID,
        name=PARENT_AGENT_NAME,
        description=PARENT_DESCRIPTION,
        db=db,
        model=_sanitize_async_model_failures(model or create_model(settings)),
        tools=tools,
        skills=skills,
        instructions=[
            (Path(__file__).parent / "prompts" / "main.md").read_text(encoding="utf-8"),
            f"Capability catalogue: {capabilities}",
        ],
        add_history_to_context=True,
        num_history_runs=5,
        tool_call_limit=settings.agent_tool_call_limit,
        store_events=True,
        telemetry=False,
    )


def create_parent_factory(
    db: BaseDb,
    settings: Settings,
    *,
    model_factory: Callable[[], Model] | None = None,
) -> AgentFactory:
    """Create the native request-scoped Samurai Agent factory."""

    def build_parent(_context: RequestContext) -> Agent:
        return create_parent_agent(
            db,
            settings,
            model=model_factory() if model_factory is not None else None,
        )

    return AgentFactory(
        id=PARENT_AGENT_ID,
        name=PARENT_AGENT_NAME,
        description=PARENT_DESCRIPTION,
        db=db,
        factory=build_parent,
    )
