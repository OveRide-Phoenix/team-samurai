"""Founder-facing Samurai agent with four bounded workflow tools."""

from __future__ import annotations

import asyncio
import copy
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
from typing import TYPE_CHECKING, ClassVar, Final, Never, TypedDict, cast, final, override
from uuid import NAMESPACE_URL, UUID, uuid5

import anyio
from agno.agent import Agent
from agno.db.base import SessionType
from agno.exceptions import InputCheckError, OutputCheckError, StopAgentRun
from agno.models.base import Model
from agno.run import RunContext
from agno.run.agent import CustomEvent, RunOutput
from agno.run.cancel import acancel_run, acleanup_run, ais_cancelled
from agno.run.concurrency import get_worker_ownership
from agno.run.workflow import (
    StepCompletedEvent,
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
from samurai.company_store import CompanyStore
from samurai.company_store_contracts import WorkspaceRole
from samurai.company_workflow import (
    WORKFLOW_ID,
    CompanyJourneyRequest,
    JourneyStage,
    create_company_workflow,
)
from samurai.config import Settings, create_model
from samurai.contracts import (
    ArtifactEnvelope,
    CompanyBrief,
    CompanyState,
    Contract,
    FounderMetricInput,
    FounderTruth,
    FrameworkReference,
    IntakeArtifact,
    ResearchArtifact,
    Role,
    SourceReference,
    VerificationFinding,
    WorkflowRequest,
    WorkflowResult,
)
from samurai.execution_state import (
    ApprovedStage,
    BoundWorkIntent,
    NormalizedWorkInput,
    SamuraiPostgresDb,
    WorkIntentError,
    WorkOperation,
)
from samurai.frameworks import load_framework_catalog
from samurai.launch_workflows import (
    LaunchAction,
    LaunchDraftRequest,
    LaunchKind,
    LaunchRole,
    create_launch_workflows,
    run_launch_drafts,
)
from samurai.learning import LearningContext, LearningStore
from samurai.panels import presentation_tools
from samurai.team_areas import TeamArea, journey_handoff, suggest_team_area, team_instructions

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

    from agno.db.base import BaseDb
    from agno.models.response import ModelResponse
    from agno.workflow.step import StepExecutor

PARENT_AGENT_ID: Final = "samurai"
PARENT_AGENT_NAME: Final = "Samurai"
PARENT_DESCRIPTION: Final = "Build and improve one evidence-linked company with Samurai."
REGISTRY_EXECUTION_ERROR: Final = "registered parent cannot execute"
PARENT_COPY_UPDATE_ERROR: Final = "Samurai parent copy does not accept updates"
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
    founder_truth: FounderTruth = FounderTruth()
    artifacts: tuple[ArtifactEnvelope, ...] = ()
    frameworks: tuple[FrameworkReference, ...] = ()
    learning_context: LearningContext = LearningContext(records=())

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


class _JourneyWorkArguments(Contract):
    idea: str
    target_customer: str
    geography: str
    budget: str
    founder_skills: str
    goal: str
    supplied_context: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    stage: JourneyStage = "brief"


class _LaunchWorkArguments(Contract):
    kind: LaunchKind = LaunchKind.ALL
    action: LaunchAction = LaunchAction.DRAFT


class _MetricsWorkArguments(Contract):
    measurements: tuple[FounderMetricInput, ...] = ()


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


@final
class _RegisteredParentModel(Model):
    def __init__(self) -> None:
        super().__init__(
            id="samurai-registered-parent",
            name="Samurai registered parent",
            provider="samurai",
        )
        self.id: str = "samurai-registered-parent"

    @staticmethod
    def _reject() -> Never:
        raise InputCheckError(REGISTRY_EXECUTION_ERROR)

    @override
    def invoke(self, *_args: object, **_kwargs: object) -> Never:
        self._reject()

    @override
    async def ainvoke(self, *_args: object, **_kwargs: object) -> Never:
        self._reject()

    @override
    def invoke_stream(self, *_args: object, **_kwargs: object) -> Never:
        self._reject()

    @override
    async def ainvoke_stream(
        self,
        *_args: object,
        **_kwargs: object,
    ) -> abc.AsyncIterator[ModelResponse]:
        if not self.id:
            yield cast("ModelResponse", object())
        self._reject()

    @override
    def _parse_provider_response(
        self,
        response: object,
        **_kwargs: object,
    ) -> Never:
        _ = response
        self._reject()

    @override
    def _parse_provider_response_delta(self, response: object) -> Never:
        _ = response
        self._reject()


@final
class _LazyParentModel(Model):
    def __init__(self, factory: Callable[[], Model]) -> None:
        super().__init__(
            id="samurai-parent",
            name="Samurai parent",
            provider="samurai",
        )
        self.id: str = "samurai-parent"
        self._factory = factory
        self._resolved: Model | None = None

    def _resolve(self) -> Model:
        if self._resolved is None:
            self._resolved = copy.deepcopy(self._factory())
        return self._resolved

    @override
    def invoke(self, *args: object, **kwargs: object) -> ModelResponse:
        invoke = cast("Callable[..., ModelResponse]", self._resolve().invoke)
        return invoke(*args, **kwargs)

    @override
    async def ainvoke(self, *args: object, **kwargs: object) -> ModelResponse:
        ainvoke = cast("Callable[..., Awaitable[ModelResponse]]", self._resolve().ainvoke)
        return await ainvoke(*args, **kwargs)

    @override
    def invoke_stream(self, *args: object, **kwargs: object) -> abc.Iterator[ModelResponse]:
        invoke_stream = cast(
            "Callable[..., Iterator[ModelResponse]]",
            self._resolve().invoke_stream,
        )
        return invoke_stream(*args, **kwargs)

    @override
    async def ainvoke_stream(
        self,
        *args: object,
        **kwargs: object,
    ) -> abc.AsyncIterator[ModelResponse]:
        ainvoke_stream = cast(
            "Callable[..., AsyncIterator[ModelResponse]]",
            self._resolve().ainvoke_stream,
        )
        async for response in ainvoke_stream(*args, **kwargs):
            yield response

    @override
    def _parse_provider_response(
        self,
        response: object,
        **kwargs: object,
    ) -> ModelResponse:
        _ = kwargs
        return cast("ModelResponse", response)

    @override
    def _parse_provider_response_delta(self, response: object) -> ModelResponse:
        return cast("ModelResponse", response)


@final
class SamuraiParentAgent(Agent):
    """Parent agent that creates isolated copies for each run."""

    def __init__(  # noqa: D107, PLR0913
        self,
        db: BaseDb,
        settings: Settings,
        model_factory: Callable[[], Model],
        *,
        model: Model,
        tools: list[Function],
        skills: Skills,
        instructions: list[str],
        executable: bool,
        team_area: TeamArea,
    ) -> None:
        self.samurai_db = db
        self.samurai_settings = settings
        self.samurai_model_factory = model_factory
        self.samurai_team_area: TeamArea = team_area

        def reject_registry_execution() -> None:
            raise InputCheckError(REGISTRY_EXECUTION_ERROR)

        def require_run_access(run_context: RunContext) -> None:
            _require_canonical_run_access(db, run_context)

        super().__init__(  # pyright: ignore[reportUnknownMemberType]
            id=PARENT_AGENT_ID,
            name=PARENT_AGENT_NAME,
            description=PARENT_DESCRIPTION,
            db=db,
            model=_sanitize_async_model_failures(
                model,
                max_calls=settings.agent_tool_call_limit + 1,
            ),
            tools=tools,
            skills=skills,
            instructions=instructions,
            add_history_to_context=True,
            num_history_runs=5,
            tool_call_limit=settings.agent_tool_call_limit,
            pre_hooks=[require_run_access] if executable else [reject_registry_execution],
            post_hooks=[_fail_closed_tool_errors],
            store_events=True,
            telemetry=False,
        )

    @override
    def deep_copy(self, *, update: dict[str, object] | None = None) -> Agent:
        if update:
            raise TypeError(PARENT_COPY_UPDATE_ERROR)
        return create_parent_agent(
            self.samurai_db,
            self.samurai_settings,
            model_factory=self.samurai_model_factory,
            team_area=self.samurai_team_area,
        )


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


def _require_canonical_run_access(db: BaseDb, run_context: RunContext) -> None:
    if not isinstance(db, SamuraiPostgresDb) or not db.table_exists(
        "samurai_company_actor_bindings"
    ):
        return
    user_id, parent_session_id, _child_id = _trusted_identity(run_context)
    access = CompanyStore(db.db_engine, schema=db.db_schema).read_for_actor(
        user_id,
        parent_session_id,
    )
    if access is None:
        message = "active company membership and session binding required"
        raise InputCheckError(message)
    if access.role is WorkspaceRole.VIEWER:
        message = "viewer access is read-only"
        raise InputCheckError(message)


def _child_state(db: BaseDb, run_context: RunContext) -> tuple[str, CompanyState | None]:
    user_id, parent_session_id, child_id = _trusted_identity(run_context)
    canonical_enabled = False
    if isinstance(db, SamuraiPostgresDb) and db.table_exists("samurai_company_actor_bindings"):
        canonical_enabled = True
        access = CompanyStore(db.db_engine, schema=db.db_schema).read_for_actor(
            user_id,
            parent_session_id,
        )
        if access is not None:
            child_id = access.child_session_id
            state = access.state
        else:
            state = None
    else:
        state = None
    session = db.get_session(
        child_id,
        session_type=SessionType.WORKFLOW,
        user_id=user_id,
    )
    if session is not None:
        if not isinstance(session, WorkflowSession) or session.user_id != user_id:
            raise ParentContextError(ParentContextIssue.OWNER_MISMATCH)
        session_data = _ChildSessionData.model_validate(session.session_data)
        company = session_data.session_state.company
        if company is not None and state is None and not canonical_enabled:
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


def _dependencies(
    user_id: str,
    parent_session_id: str,
    child_id: str,
    parent_context: RunContext | None = None,
) -> dict[str, object]:
    dependencies: dict[str, object] = {
        "trusted_parent_session_id": parent_session_id,
        "trusted_user_id": user_id,
        "child_session_id": child_id,
    }
    if parent_context is not None:
        source = parent_context.dependencies or {}
        for key in ("parent_run_id", "worker_id", "attempt", "fingerprint"):
            if key in source:
                dependencies[key] = source[key]
    return dependencies


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
        dependencies=_dependencies(user_id, parent_session_id, child_id, run_context),
    )


def _ensure_durable_child_session(
    db: BaseDb,
    owner_id: str,
    child_id: str,
    state: CompanyState | None,
) -> None:
    if not isinstance(db, SamuraiPostgresDb):
        return
    existing = db.get_session(
        child_id,
        session_type=SessionType.WORKFLOW,
        user_id=owner_id,
    )
    if existing is not None:
        return
    _ = db.upsert_session(
        WorkflowSession(
            session_id=child_id,
            user_id=owner_id,
            workflow_id=WORKFLOW_ID,
            session_data={
                "session_state": {} if state is None else {"company": state.model_dump(mode="json")}
            },
        )
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
        content={"kind": "workflow_progress", "detail": content},
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


def _bind_normalized_work(
    db: BaseDb,
    run_context: RunContext,
    proposed: NormalizedWorkInput,
) -> NormalizedWorkInput:
    ownership = get_worker_ownership(run_context.run_id)
    if ownership is None:
        return proposed
    binder = getattr(db, "bind_work_intent", None)
    if not callable(binder):
        message = "durable work intent store is required"
        raise InputCheckError(message)
    try:
        candidate = binder(run_context.run_id, proposed if ownership.attempt == 1 else None)
    except WorkIntentError as error:
        raise InputCheckError(str(error)) from None
    if not isinstance(candidate, BoundWorkIntent):
        message = "durable work intent store returned an invalid binding"
        raise InputCheckError(message)
    bound = candidate
    user_id, parent_session_id, child_id = _trusted_identity(run_context)
    if (
        bound.approval.owner_id,
        bound.approval.parent_session_id,
        bound.approval.child_session_id,
    ) != (user_id, parent_session_id, child_id):
        message = "durable work intent identity does not match"
        raise InputCheckError(message)
    dependencies = run_context.dependencies or {}
    dependencies.update(
        {
            "parent_run_id": bound.token.parent_run_id,
            "worker_id": bound.token.worker_id,
            "attempt": bound.token.attempt,
            "fingerprint": bound.token.fingerprint,
        }
    )
    run_context.dependencies = dependencies
    return bound.normalized_input


def _require_work_operation(
    normalized: NormalizedWorkInput,
    operation: WorkOperation,
) -> None:
    if normalized.operation is not operation:
        message = "durable work operation does not match"
        raise InputCheckError(message)


def create_parent_agent(  # noqa: C901, PLR0913, PLR0915 - bounded tool surface.
    db: BaseDb,
    settings: Settings,
    *,
    model: Model | None = None,
    model_factory: Callable[[], Model] | None = None,
    executable: bool = True,
    team_area: TeamArea = "overview",
) -> SamuraiParentAgent:
    """Create a fresh ordinary Samurai Agent and its bounded native tools."""
    framework_metadata = load_framework_catalog().metadata
    if model_factory is None:
        if model is None:

            def build_model() -> Model:
                return create_model(settings)
        else:
            model_template = copy.deepcopy(model)

            def build_model() -> Model:
                return copy.deepcopy(model_template)
    else:
        build_model = model_factory
    active_model = (
        _RegisteredParentModel()
        if not executable
        else model
        if model is not None
        else _LazyParentModel(build_model)
    )

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
        stage: JourneyStage = "brief",
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
            stage: Founder-requested phase; new companies start with brief.

        """
        child_id, state = _child_state(db, run_context)
        handoff = journey_handoff(team_area, stage, state)
        if handoff:
            yield handoff
            return
        requested = _JourneyWorkArguments(
            idea=idea,
            target_customer=target_customer,
            geography=geography,
            budget=budget,
            founder_skills=founder_skills,
            goal=goal,
            supplied_context=supplied_context,
            assumptions=assumptions,
            stage=stage,
        )
        normalized = _bind_normalized_work(
            db,
            run_context,
            NormalizedWorkInput(
                operation=WorkOperation.JOURNEY,
                stage=ApprovedStage(stage),
                expected_revision=0 if state is None else state.current_revision,
                arguments=requested.model_dump(mode="json"),
            ),
        )
        _require_work_operation(normalized, WorkOperation.JOURNEY)
        requested = _JourneyWorkArguments.model_validate(normalized.arguments)
        user_id, parent_session_id, _ = _trusted_identity(run_context)
        _ensure_durable_child_session(db, user_id, child_id, state)
        child_run_id = _child_run_id(run_context, "journey")
        request = CompanyJourneyRequest(
            company_id=None if state is None else state.context.company_id,
            expected_revision=0 if state is None else state.current_revision,
            idea=requested.idea or None,
            target_customer=requested.target_customer or None,
            geography=requested.geography or None,
            budget=requested.budget or None,
            founder_skills=requested.founder_skills or None,
            goal=requested.goal or None,
            supplied_context=requested.supplied_context,
            assumptions=requested.assumptions,
        )
        workflow = _sanitize_workflow(
            create_company_workflow(db, settings, stage=requested.stage),
            max_model_calls=settings.agent_tool_call_limit + 1,
        )
        cancelled = False
        events = workflow.arun(
            request,
            user_id=user_id,
            run_id=child_run_id,
            session_id=child_id,
            session_state={} if state is None else {"company": state.model_dump(mode="json")},
            dependencies=_dependencies(user_id, parent_session_id, child_id, run_context),
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
                if isinstance(event, StepCompletedEvent):
                    yield _progress(
                        run_context, child_id, f"{event.step_name or 'Workflow step'} completed"
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
    ) -> WorkflowResult | str:
        """Create reviewable launch drafts without external action capability."""
        if team_area not in {"overview", "sales"} or (
            team_area == "sales" and kind is not LaunchKind.SALES
        ):
            return suggest_team_area("sales" if kind is LaunchKind.SALES else "overview")
        requested = _LaunchWorkArguments(kind=kind, action=action)
        if get_worker_ownership(run_context.run_id) is not None:
            _, state = _child_state(db, run_context)
            if state is None:
                raise ParentContextError(ParentContextIssue.JOURNEY_REQUIRED_FOR_DRAFTS)
            normalized = _bind_normalized_work(
                db,
                run_context,
                NormalizedWorkInput(
                    operation=WorkOperation.LAUNCH_DRAFTS,
                    stage=ApprovedStage.PLAN,
                    expected_revision=state.current_revision,
                    arguments=requested.model_dump(mode="json"),
                ),
            )
            _require_work_operation(normalized, WorkOperation.LAUNCH_DRAFTS)
            requested = _LaunchWorkArguments.model_validate(normalized.arguments)
        try:
            result = await _create_launch_drafts(
                db,
                settings,
                run_context,
                requested.kind,
                requested.action,
            )
        except ParentContextError, StopAgentRun:
            raise
        except Exception:  # noqa: BLE001 - child details must stop before Agno logs them.
            raise _ChildWorkflowError from None
        return _ParentWorkflowResult.model_validate(result)

    async def analyze_metrics(
        run_context: RunContext,
        measurements: tuple[_FounderMetricToolInput, ...] = (),
    ) -> WorkflowResult | str:
        """Analyze eligible founder metrics without changing their provenance."""
        if team_area != "overview":
            return suggest_team_area("overview")
        try:
            requested = _MetricsWorkArguments(
                measurements=tuple(
                    FounderMetricInput.model_validate(metric) for metric in measurements
                )
            )
        except ValidationError:
            result = _requires_metrics(db, run_context, ask_for_details=True)
            return _ParentWorkflowResult.model_validate(result.model_dump())
        if get_worker_ownership(run_context.run_id) is not None:
            _, state = _child_state(db, run_context)
            if state is None:
                raise ParentContextError(ParentContextIssue.JOURNEY_REQUIRED_FOR_ANALYSIS)
            normalized = _bind_normalized_work(
                db,
                run_context,
                NormalizedWorkInput(
                    operation=WorkOperation.METRICS_ANALYSIS,
                    stage=ApprovedStage.PLAN,
                    expected_revision=state.current_revision,
                    arguments=requested.model_dump(mode="json"),
                ),
            )
            _require_work_operation(normalized, WorkOperation.METRICS_ANALYSIS)
            requested = _MetricsWorkArguments.model_validate(normalized.arguments)
        if not requested.measurements:
            result = _requires_metrics(db, run_context)
            return _ParentWorkflowResult.model_validate(result.model_dump())
        try:
            result = await _analyze_metrics(db, settings, requested.measurements, run_context)
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
                frameworks=framework_metadata,
            )
        intake = next(
            (
                artifact.payload
                for artifact in reversed(state.artifacts)
                if isinstance(artifact.payload, IntakeArtifact)
            ),
            None,
        )
        brief = intake.brief if intake is not None else None
        founder_truth = intake.founder_truth if intake is not None else FounderTruth()
        retained_frameworks = intake.frameworks if intake is not None else ()
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
        next_decision = founder_truth.next_decision
        learning_context = LearningContext(records=())
        if isinstance(db, SamuraiPostgresDb):
            user_id, parent_session_id, _child_id = _trusted_identity(run_context)
            access = CompanyStore(db.db_engine, schema=db.db_schema).read_for_actor(
                user_id, parent_session_id
            )
            if access is not None and access.state.context.company_id == state.context.company_id:
                learning_context = LearningStore(db.db_engine, schema=db.db_schema).list(
                    user_id,
                    access.workspace_id,
                    state.context.company_id,
                )
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
            founder_truth=founder_truth,
            artifacts=tuple({item.artifact_type: item for item in state.artifacts}.values()),
            frameworks=retained_frameworks or framework_metadata,
            learning_context=learning_context,
        )

    capabilities = ", ".join(
        f"{capability.role.value}={capability.status}" for capability in ROLE_CAPABILITIES.values()
    )
    tools = [
        Function(
            name=tool.__name__,
            entrypoint=tool,
            stop_after_tool_call=team_area == "overview" or tool is not read_company_state,
            show_result=team_area == "overview" or tool is not read_company_state,
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
    return SamuraiParentAgent(
        db,
        settings,
        build_model,
        model=active_model,
        tools=[
            *tools,
            *presentation_tools(),
            Function(
                name="suggest_team_area",
                entrypoint=suggest_team_area,
                stop_after_tool_call=True,
                show_result=True,
            ),
        ],
        skills=skills,
        instructions=[
            (Path(__file__).parent / "prompts" / "main.md").read_text(encoding="utf-8"),
            f"Capability catalogue: {capabilities}",
            team_instructions(team_area),
        ],
        executable=executable,
        team_area=team_area,
    )
