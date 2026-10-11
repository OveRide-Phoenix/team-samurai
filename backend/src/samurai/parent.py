"""Founder-facing Samurai agent with four bounded workflow tools."""

from __future__ import annotations

import asyncio
import json
from collections import abc  # noqa: TC003 - Agno resolves tool annotations at runtime.
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, unique
from functools import wraps
from inspect import isasyncgenfunction, iscoroutinefunction, isgeneratorfunction, signature
from pathlib import Path
from time import time
from types import MethodType
from typing import TYPE_CHECKING, ClassVar, Final, TypedDict, cast, override
from uuid import NAMESPACE_URL, UUID, uuid5

import anyio
from agno.agent import Agent
from agno.agent.factory import AgentFactory
from agno.db.base import SessionType
from agno.exceptions import OutputCheckError, StopAgentRun
from agno.models.base import Model
from agno.run import RunContext
from agno.run.agent import CustomEvent, RunOutput
from agno.run.cancel import acancel_run, acleanup_run, ais_cancelled
from agno.run.workflow import (
    StepProgressEvent,
    StepStartedEvent,
    WorkflowCancelledEvent,
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
)
from agno.session.workflow import WorkflowSession
from agno.skills import LocalSkills, Skills
from agno.tools.function import Function
from agno.workflow import Step, StepInput, Workflow
from agno.workflow.types import OnError
from pydantic import AwareDatetime, ConfigDict, JsonValue, ValidationError

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
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

    from agno.db.base import BaseDb
    from agno.factory import RequestContext
    from agno.models.response import ModelResponse
    from agno.workflow.step import StepExecutor

PARENT_AGENT_ID: Final = "samurai"
PARENT_AGENT_NAME: Final = "Samurai"
PARENT_DESCRIPTION: Final = "Build and improve one evidence-linked company with Samurai."
TOOL_RESULT_MARKER: Final = "\nSAMURAI_WORKFLOW_RESULT="
TOOL_ERROR_MARKER: Final = "SAMURAI_WORKFLOW_ERROR="
CHILD_FAILURE_MESSAGE: Final = "child workflow failed"
CHILD_WORKFLOW_MODEL_CALL_BUDGET: Final = 7
CORE_EXECUTOR_AGENT_FIELDS: Final = (
    "intake_agent",
    "research_agent",
    "strategy_agent",
    "product_agent",
    "verifier_agent",
)
PARENT_BINDING_KEYS: Final = frozenset({"child_session_id", "company_id", "current_revision"})
AGNO_SESSION_KEYS: Final = frozenset({"current_user_id", "current_session_id", "current_run_id"})
STARTER_PROMPTS: Final = [
    "Build my business: describe the idea, customer, geography, budget, founder skills, and goal.",
    "Continue my company plan using the context and decisions already retained.",
    "Create reviewable Builder, Marketer, and Sales drafts from my verified plan.",
    "Analyze these provenance-labelled business metrics and recommend what to improve.",
]
METRIC_INPUT_QUESTIONS: Final = (
    "What exact unit, UTC window_start, UTC window_end, and UTC collected_at apply to each metric?",
    "What source_label identifies where each founder-supplied metric came from?",
)
ANALYZE_METRICS_PARAMETERS: Final[dict[str, JsonValue]] = {
    "type": "object",
    "properties": {
        "measurements": {
            "type": "array",
            "items": FounderMetricInput.model_json_schema(),
        }
    },
    "required": ["measurements"],
}


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


class _ChildWorkflowFailure(Contract):
    outcome: str = "failed"
    error_code: str = "child_workflow_failed"


class _FounderMetricToolInput(TypedDict):
    name: str
    value: float
    unit: str
    window_start: AwareDatetime
    window_end: AwareDatetime
    source_label: str
    collected_at: AwareDatetime


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
            tool.stop_after_tool_call = False
            tool.show_result = False
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


class _ChildWorkflowError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(CHILD_FAILURE_MESSAGE)


class _CoreWorkflowBoundaryError(TypeError):
    pass


def _sanitize_async_model_failures(model: Model, *, max_calls: int | None = None) -> Model:
    original_ainvoke = cast("Callable[..., Awaitable[ModelResponse]]", model.ainvoke)
    original_ainvoke_stream = cast(
        "Callable[..., AsyncIterator[ModelResponse]]", model.ainvoke_stream
    )
    calls = 0

    def check_budget() -> None:
        nonlocal calls
        calls += 1
        if max_calls is not None and calls > max_calls:
            raise _ParentModelError

    async def safe_ainvoke(
        _model: Model,
        *args: object,
        **kwargs: object,
    ) -> ModelResponse:
        try:
            check_budget()
            return await original_ainvoke(*args, **kwargs)
        except Exception:  # noqa: BLE001 - provider details must stop at this trust boundary.
            raise _ParentModelError from None

    async def safe_ainvoke_stream(
        _model: Model,
        *args: object,
        **kwargs: object,
    ) -> abc.AsyncIterator[ModelResponse]:
        try:
            check_budget()
            async for response in original_ainvoke_stream(*args, **kwargs):
                yield response
        except Exception:  # noqa: BLE001 - provider details must stop at this trust boundary.
            raise _ParentModelError from None

    model.ainvoke = MethodType(safe_ainvoke, model)
    model.ainvoke_stream = MethodType(safe_ainvoke_stream, model)
    return model


def _sanitize_step_executor(executor: StepExecutor) -> StepExecutor:  # noqa: C901
    accepts_run_context = "run_context" in signature(executor).parameters
    if isasyncgenfunction(executor):
        async_executor = cast("Callable[..., AsyncIterator[object]]", executor)

        @wraps(executor)
        async def safe_async_generator(
            step_input: StepInput,
            run_context: RunContext | None = None,
        ) -> abc.AsyncIterator[object]:
            try:
                iterator = (
                    async_executor(step_input, run_context=run_context)
                    if accepts_run_context
                    else async_executor(step_input)
                )
                async for output in iterator:
                    yield output
            except Exception:  # noqa: BLE001 - child details must stop before Agno logs them.
                raise _ChildWorkflowError from None

        return cast("StepExecutor", safe_async_generator)
    if iscoroutinefunction(executor):
        async_executor = cast("Callable[..., Awaitable[object]]", executor)

        @wraps(executor)
        async def safe_coroutine(
            step_input: StepInput,
            run_context: RunContext | None = None,
        ) -> object:
            try:
                if accepts_run_context:
                    return await async_executor(step_input, run_context=run_context)
                return await async_executor(step_input)
            except Exception:  # noqa: BLE001 - child details must stop before Agno logs them.
                raise _ChildWorkflowError from None

        return cast("StepExecutor", safe_coroutine)
    if isgeneratorfunction(executor):
        generator_executor = cast("Callable[..., Iterator[object]]", executor)

        @wraps(executor)
        def safe_generator(
            step_input: StepInput,
            run_context: RunContext | None = None,
        ) -> abc.Iterator[object]:
            try:
                iterator = (
                    generator_executor(step_input, run_context=run_context)
                    if accepts_run_context
                    else generator_executor(step_input)
                )
                yield from iterator
            except Exception:  # noqa: BLE001 - child details must stop before Agno logs them.
                raise _ChildWorkflowError from None

        return cast("StepExecutor", safe_generator)
    sync_executor = cast("Callable[..., object]", executor)

    @wraps(executor)
    def safe_sync(
        step_input: StepInput,
        run_context: RunContext | None = None,
    ) -> object:
        try:
            if accepts_run_context:
                return sync_executor(step_input, run_context=run_context)
            return sync_executor(step_input)
        except Exception:  # noqa: BLE001 - child details must stop before Agno logs them.
            raise _ChildWorkflowError from None

    return cast("StepExecutor", safe_sync)


def _core_executor_agents(executor: StepExecutor) -> tuple[Agent, ...]:
    owner = getattr(executor, "__self__", None)
    candidates = tuple(
        getattr(owner, field_name, None) for field_name in CORE_EXECUTOR_AGENT_FIELDS
    )
    if not any(candidate is not None for candidate in candidates):
        return ()
    if not all(isinstance(candidate, Agent) for candidate in candidates):
        raise _CoreWorkflowBoundaryError
    return cast("tuple[Agent, ...]", candidates)


def _sanitize_agent_model(
    agent: Agent,
    *,
    max_model_calls: int,
    sanitized_models: set[int],
) -> None:
    model = agent.model
    if not isinstance(model, Model) or id(model) in sanitized_models:
        return
    sanitized_models.add(id(model))
    agent.model = _sanitize_async_model_failures(model, max_calls=max_model_calls)


def _sanitize_workflow_steps(
    workflow: Workflow,
    *,
    max_model_calls: int,
    sanitized_models: set[int],
) -> None:
    if not isinstance(workflow.steps, list):
        return
    for step in workflow.steps:
        if not isinstance(step, Step):
            continue
        step.max_retries = 0
        step.human_review.on_error = OnError.fail
        if step.executor is not None:
            for agent in _core_executor_agents(step.executor):
                _sanitize_agent_model(
                    agent,
                    max_model_calls=max_model_calls,
                    sanitized_models=sanitized_models,
                )
            step.executor = _sanitize_step_executor(step.executor)
            step.active_executor = step.executor
        if step.agent is not None:
            _sanitize_agent_model(
                step.agent,
                max_model_calls=max_model_calls,
                sanitized_models=sanitized_models,
            )
        if step.workflow is not None:
            _sanitize_workflow_steps(
                step.workflow,
                max_model_calls=max_model_calls,
                sanitized_models=sanitized_models,
            )


def _sanitize_workflow(workflow: Workflow, *, max_model_calls: int) -> Workflow:
    _sanitize_workflow_steps(
        workflow,
        max_model_calls=max_model_calls,
        sanitized_models=set(),
    )
    return workflow


def _fail_closed_tool_errors(run_output: RunOutput) -> None:
    content = run_output.content
    failed_tool = any(tool.tool_call_error for tool in run_output.tools or ())
    if isinstance(content, str) and content.startswith(TOOL_ERROR_MARKER):
        failed_tool = True
    if failed_tool:
        run_output.content = _ChildWorkflowFailure().model_dump_json()
        raise OutputCheckError(CHILD_FAILURE_MESSAGE)


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
    operation_scope: anyio.CancelScope,
) -> None:
    while not done.is_set():
        if await ais_cancelled(parent_run_id):
            for child_run_id in child_run_ids:
                _ = await acancel_run(child_run_id)
            operation_scope.cancel()
            return
        await anyio.sleep(0.01)


async def _cancel_children(child_run_ids: tuple[str, ...]) -> None:
    for child_run_id in child_run_ids:
        _ = await acancel_run(child_run_id)


async def _cancel_children_after_timeout(
    child_run_ids: tuple[str, ...],
    done: anyio.Event,
    operation_scope: anyio.CancelScope,
    timeout_seconds: float,
    timed_out: anyio.Event,
) -> None:
    with anyio.move_on_after(timeout_seconds) as deadline:
        await done.wait()
    if not deadline.cancel_called or done.is_set():
        return
    timed_out.set()
    await _cancel_children(child_run_ids)
    operation_scope.cancel()


def _cancelled_tool_run() -> StopAgentRun:
    return StopAgentRun("parent run cancelled")


async def _await_with_cancel_watch[T](
    operation: Callable[[], Awaitable[T]],
    run_context: RunContext,
    child_run_ids: tuple[str, ...],
    timeout_seconds: float,
) -> T:
    done = anyio.Event()
    timed_out = anyio.Event()
    operation_scope = anyio.CancelScope()
    result: list[T] = []
    errors: list[Exception] = []

    async def execute() -> None:
        with operation_scope:
            try:
                result.append(await operation())
            except Exception as error:  # noqa: BLE001 - re-raised after sibling tasks drain.
                errors.append(error)
            finally:
                done.set()

    async with anyio.create_task_group() as tasks:
        _ = tasks.start_soon(
            _cancel_children_when_parent_stops,
            run_context.run_id,
            child_run_ids,
            done,
            operation_scope,
        )
        _ = tasks.start_soon(
            _cancel_children_after_timeout,
            child_run_ids,
            done,
            operation_scope,
            timeout_seconds,
            timed_out,
        )
        _ = tasks.start_soon(execute)
        await done.wait()
        tasks.cancel_scope.cancel()
    for child_run_id in child_run_ids:
        await acleanup_run(child_run_id)
    if timed_out.is_set():
        raise _ChildWorkflowError
    if errors:
        raise errors[0]
    return result[0]


async def _stream_with_cancel_watch[T](
    events: AsyncIterator[T],
    run_context: RunContext,
    child_run_id: str,
    timeout_seconds: float,
) -> abc.AsyncGenerator[T]:
    done = anyio.Event()
    timed_out = anyio.Event()
    operation_scope = anyio.CancelScope()
    errors: list[Exception] = []
    send, receive = anyio.create_memory_object_stream[T](max_buffer_size=1)

    async def produce() -> None:
        with operation_scope:
            try:
                async with send:
                    async for event in events:
                        await send.send(event)
            except Exception as error:  # noqa: BLE001 - re-raised after sibling tasks drain.
                errors.append(error)
            finally:
                done.set()

    async def supervise() -> None:
        async with anyio.create_task_group() as tasks:
            _ = tasks.start_soon(
                _cancel_children_when_parent_stops,
                run_context.run_id,
                (child_run_id,),
                done,
                operation_scope,
            )
            _ = tasks.start_soon(
                _cancel_children_after_timeout,
                (child_run_id,),
                done,
                operation_scope,
                timeout_seconds,
                timed_out,
            )
            _ = tasks.start_soon(produce)
            await done.wait()
            tasks.cancel_scope.cancel()

    supervisor = asyncio.create_task(supervise())
    try:
        async with receive:
            async for event in receive:
                yield event
    finally:
        with anyio.move_on_after(1, shield=True):
            if not supervisor.done():
                await _cancel_children((child_run_id,))
                _ = supervisor.cancel()
            with suppress(asyncio.CancelledError):
                await supervisor
            await acleanup_run(child_run_id)
    if timed_out.is_set():
        raise _ChildWorkflowError
    if errors:
        raise errors[0]


def _child_workflow_timeout(settings: Settings) -> float:
    return settings.gemini_timeout_seconds * CHILD_WORKFLOW_MODEL_CALL_BUDGET


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
    for workflow in workflows.values():
        _ = _sanitize_workflow(
            workflow,
            max_model_calls=settings.agent_tool_call_limit + 1,
        )
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
            _child_workflow_timeout(settings),
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
    workflow = _sanitize_workflow(
        create_analysis_workflow(db, analyst),
        max_model_calls=settings.agent_tool_call_limit + 1,
    )

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
        result = await _await_with_cancel_watch(
            operation,
            run_context,
            (child_run_id,),
            _child_workflow_timeout(settings),
        )
    except AnalysisCancelledError:
        if await ais_cancelled(run_context.run_id):
            raise _cancelled_tool_run() from None
        raise
    _bind_parent(run_context, child_id, result)
    return result


def _requires_metrics(
    db: BaseDb,
    run_context: RunContext,
    *,
    ask_for_details: bool = False,
) -> WorkflowResult:
    _, state = _child_state(db, run_context)
    if state is None:
        raise ParentContextError(ParentContextIssue.JOURNEY_REQUIRED_FOR_ANALYSIS)
    if ask_for_details:
        return WorkflowResult(
            company_id=state.context.company_id,
            revision=state.current_revision,
            outcome="needs_input",
            questions=METRIC_INPUT_QUESTIONS,
        )
    return WorkflowResult(
        company_id=state.context.company_id,
        revision=state.current_revision,
        outcome="requires_metrics",
    )


def create_parent_agent(  # noqa: C901, PLR0915 - closures define the bounded tool surface.
    db: BaseDb,
    settings: Settings,
    *,
    model: Model | None = None,
) -> Agent:
    """Create a fresh ordinary Samurai Agent and its bounded native tools."""

    async def run_company_journey(  # noqa: PLR0913, PLR0917
        run_context: RunContext,
        idea: str,
        target_customer: str,
        geography: str,
        budget: str,
        founder_skills: str,
        goal: str,
        supplied_context: tuple[str, ...] = (),
        assumptions: tuple[str, ...] = (),
    ) -> abc.AsyncIterator[CustomEvent | str]:
        """Run or continue the verified company journey for this parent session.

        Args:
            run_context: Trusted server-owned identity and session context.
            idea: Exact founder-supplied company idea; empty if not supplied.
            target_customer: Exact founder-supplied first customer; empty if not supplied.
            geography: Exact founder-supplied first geography; empty if not supplied.
            budget: Exact founder-supplied budget; empty if not supplied.
            founder_skills: Exact founder-supplied skills; empty if not supplied.
            goal: Exact founder-supplied outcome and timeframe; empty if not supplied.
            supplied_context: Other exact context explicitly supplied by the founder.
            assumptions: Founder-labelled hypotheses, never inferred facts.

        """
        child_id, state = _child_state(db, run_context)
        user_id, parent_session_id, _ = _trusted_identity(run_context)
        child_run_id = _child_run_id(run_context, "journey")
        request = CompanyJourneyRequest(
            company_id=None if state is None else state.context.company_id,
            expected_revision=0 if state is None else state.current_revision,
            idea=idea or None,
            target_customer=target_customer or None,
            geography=geography or None,
            budget=budget or None,
            founder_skills=founder_skills or None,
            goal=goal or None,
            supplied_context=supplied_context,
            assumptions=assumptions,
        )
        workflow = _sanitize_workflow(
            create_company_workflow(db, settings),
            max_model_calls=settings.agent_tool_call_limit + 1,
        )
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
        watched_events = _stream_with_cancel_watch(
            events,
            run_context,
            child_run_id,
            _child_workflow_timeout(settings),
        )
        try:
            async for event in watched_events:
                if isinstance(event, StepStartedEvent):
                    yield _progress(
                        run_context,
                        child_id,
                        f"{event.step_name or 'Workflow step'} started",
                    )
                if isinstance(event, StepProgressEvent):
                    yield _progress(run_context, child_id, str(event.content))
                if isinstance(event, WorkflowCancelledEvent):
                    cancelled = True
                if isinstance(event, WorkflowErrorEvent):
                    yield TOOL_ERROR_MARKER + _ChildWorkflowFailure().model_dump_json()
                    return
                if isinstance(event, WorkflowCompletedEvent) and not cancelled:
                    result = WorkflowResult.model_validate(event.content)
                    _bind_parent(run_context, child_id, result)
                    yield TOOL_RESULT_MARKER + result.model_dump_json()
        except _ChildWorkflowError:
            yield TOOL_ERROR_MARKER + _ChildWorkflowFailure().model_dump_json()
        finally:
            await watched_events.aclose()

    async def create_launch_drafts(
        run_context: RunContext,
        kind: LaunchKind = LaunchKind.ALL,
        action: LaunchAction = LaunchAction.DRAFT,
    ) -> WorkflowResult:
        """Create reviewable launch drafts without external action capability."""
        try:
            result = await _create_launch_drafts(db, settings, run_context, kind, action)
        except ParentContextError, StopAgentRun:
            raise
        except Exception:  # noqa: BLE001 - child details must stop before Agno logs them.
            raise _ChildWorkflowError from None
        return _ParentWorkflowResult.model_validate(result)

    async def analyze_metrics(
        run_context: RunContext,
        measurements: tuple[_FounderMetricToolInput, ...] = (),
    ) -> WorkflowResult:
        """Analyze eligible founder metrics without changing their provenance."""
        if not measurements:
            result = _requires_metrics(db, run_context)
            return _ParentWorkflowResult.model_validate(result.model_dump())
        try:
            metrics = tuple(FounderMetricInput.model_validate(metric) for metric in measurements)
        except ValidationError:
            result = _requires_metrics(db, run_context, ask_for_details=True)
            return _ParentWorkflowResult.model_validate(result.model_dump())
        try:
            result = await _analyze_metrics(db, settings, metrics, run_context)
        except ParentContextError, StopAgentRun:
            raise
        except Exception:  # noqa: BLE001 - child details must stop before Agno logs them.
            raise _ChildWorkflowError from None
        return _ParentWorkflowResult.model_validate(result.model_dump())

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
            read_company_state,
        )
    ]
    tools.insert(
        2,
        Function(
            name=analyze_metrics.__name__,
            entrypoint=analyze_metrics,
            parameters=ANALYZE_METRICS_PARAMETERS,
            skip_entrypoint_processing=True,
            stop_after_tool_call=True,
            show_result=True,
        ),
    )
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
        model=_sanitize_async_model_failures(
            model or create_model(settings),
            max_calls=settings.agent_tool_call_limit + 1,
        ),
        tools=tools,
        skills=skills,
        instructions=[
            (Path(__file__).parent / "prompts" / "main.md").read_text(encoding="utf-8"),
            f"Capability catalogue: {capabilities}",
        ],
        add_history_to_context=True,
        num_history_runs=5,
        tool_call_limit=settings.agent_tool_call_limit,
        post_hooks=[_fail_closed_tool_errors],
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
