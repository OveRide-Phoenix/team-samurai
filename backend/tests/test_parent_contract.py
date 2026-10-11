"""Real Agno parent contract kept in one assigned file. # noqa: SIZE_OK"""

from __future__ import annotations

import json
from collections import abc  # noqa: TC003 - Agno resolves tool annotations at runtime.
from time import time
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Never,
    Protocol,
    final,
    override,
    runtime_checkable,
)

import anyio
import pytest
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.exceptions import StopAgentRun
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.agent import (
    CustomEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunOutput,
    RunOutputEvent,
    ToolCallErrorEvent,
)
from agno.run.base import RunContext, RunStatus
from agno.run.cancel import acancel_run, aget_active_runs, ais_cancelled
from agno.run.workflow import (
    StepProgressEvent,
    WorkflowCancelledEvent,
    WorkflowCompletedEvent,
    WorkflowRunOutput,
)
from agno.session.agent import AgentSession
from agno.session.workflow import WorkflowSession
from agno.workflow import Step, StepInput, StepOutput, Workflow
from agno.workflow.types import StepProgress
from openinference.instrumentation.agno import AgnoInstrumentor
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    import pathlib

USER_ID = "founder-1"
COMPANY_ID = "company-1"
PARENT_SESSION_ID = "parent-session"
CHILD_SESSION_ID = "company-1-workflow"
PARENT_RUN_ID = "parent-run"
CHILD_RUN_ID = "child-run"


@pytest.fixture(scope="module", autouse=True)
def isolate_contract_from_app_tracing() -> abc.Iterator[None]:
    instrumentor = AgnoInstrumentor()
    was_instrumented = instrumentor.is_instrumented_by_opentelemetry
    if was_instrumented:
        instrumentor.uninstrument()
    yield
    if was_instrumented:
        instrumentor.instrument()


class NestedResult(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)
    company_id: str
    revision: int
    outcome: str


@final
class ContextMismatchError(Exception):
    def __init__(self, trusted_user_id: str, claimed_user_id: str) -> None:
        self.trusted_user_id: str = trusted_user_id
        self.claimed_user_id: str = claimed_user_id
        super().__init__(f"context_mismatch:{claimed_user_id}!={trusted_user_id}")


@final
class DeterministicToolModel(Model):
    def __init__(self, tool_args: dict[str, str], result: NestedResult) -> None:
        super().__init__(
            id="deterministic-tool-model",
            name="Deterministic contract model",
            provider="contract-test",
        )
        self.id: str = "deterministic-tool-model"
        self.tool_args: dict[str, str] = tool_args
        self.result: NestedResult = result
        self.calls: int = 0

    @override
    def invoke(self, *_args: Never, **_kwargs: Never) -> ModelResponse:
        return ModelResponse()

    @override
    async def ainvoke(self, *_args: Never, **_kwargs: Never) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                tool_calls=[
                    {
                        "id": "tool-call-1",
                        "type": "function",
                        "function": {
                            "name": "run_company_workflow",
                            "arguments": json.dumps(self.tool_args),
                        },
                    }
                ]
            )
        return ModelResponse(content=self.result.model_dump_json())

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


@runtime_checkable
class ParentRunner(Protocol):
    arun: abc.Callable[..., abc.AsyncIterator[RunOutputEvent | RunOutput]]


def _create_child_workflow(db: SqliteDb, *, block_child: bool, expected: NestedResult) -> Workflow:
    async def child_step(_: StepInput) -> abc.AsyncIterator[StepProgress | StepOutput]:
        yield StepProgress(content="child-started", data={"revision": 4})
        while block_child:
            await anyio.lowlevel.checkpoint()
            yield StepProgress(content="child-running", data={"revision": 4})
        yield StepOutput(content=expected)

    return Workflow(
        id="contract-child",
        db=db,
        steps=[Step(name="Apply company revision", executor=child_step)],
        store_events=True,
        telemetry=False,
    )


def _build_parent(
    db: SqliteDb,
    *,
    claimed_user_id: str = USER_ID,
    block_child: bool = False,
) -> tuple[ParentRunner, list[str]]:
    child_terminals: list[str] = []
    expected = NestedResult(company_id=COMPANY_ID, revision=4, outcome="validated")
    workflow = _create_child_workflow(db, block_child=block_child, expected=expected)

    async def stream_company_workflow(run_context: RunContext) -> abc.AsyncIterator[CustomEvent]:
        child_state = {"company": {"company_id": COMPANY_ID, "name": "Fixture Co", "revision": 4}}
        # Agno does not cascade arbitrary nested Workflow cancellation from an Agent tool.
        child_events = workflow.arun(
            "advance",
            user_id=run_context.user_id,
            run_id=CHILD_RUN_ID,
            session_id=CHILD_SESSION_ID,
            session_state=child_state,
            stream=True,
            stream_events=True,
        )
        async for event in child_events:
            if isinstance(event, StepProgressEvent) and await ais_cancelled(run_context.run_id):
                _ = await acancel_run(CHILD_RUN_ID)
                continue
            if isinstance(event, StepProgressEvent):
                yield CustomEvent(
                    created_at=int(time()),
                    event="CustomEvent",
                    agent_id="contract-parent",
                    agent_name="",
                    run_id=run_context.run_id,
                    parent_run_id=None,
                    session_id=run_context.session_id,
                    workflow_id=None,
                    workflow_run_id=None,
                    step_id=None,
                    step_name=None,
                    step_index=None,
                    nested_depth=0,
                    tools=None,
                    content=event.content,
                    kind="nested_progress",
                    company_id=COMPANY_ID,
                    child_session_id=CHILD_SESSION_ID,
                )
            if isinstance(event, (WorkflowCompletedEvent, WorkflowCancelledEvent)):
                child_terminals.append(event.event)

    def run_company_workflow(
        claimed_user_id: str, company_id: str, run_context: RunContext
    ) -> abc.AsyncIterator[CustomEvent]:
        if claimed_user_id != run_context.user_id:
            raise StopAgentRun(ContextMismatchError(run_context.user_id or "", claimed_user_id))
        session_state = run_context.session_state
        if session_state is None or company_id != session_state["company_id"]:
            mismatch = "company_context_mismatch"
            raise StopAgentRun(mismatch)
        return stream_company_workflow(run_context)

    parent = Agent(
        id="contract-parent",
        db=db,
        model=DeterministicToolModel(
            {"claimed_user_id": claimed_user_id, "company_id": COMPANY_ID}, expected
        ),
        tools=[run_company_workflow],
        output_schema=NestedResult,
        store_events=True,
        telemetry=False,
    )
    assert isinstance(parent, ParentRunner)
    return parent, child_terminals


async def _collect_parent_events(
    parent: ParentRunner, *, cancel_on_progress: bool = False
) -> list[RunOutputEvent]:
    events: list[RunOutputEvent] = []
    stream = parent.arun(
        "advance my company",
        user_id=USER_ID,
        session_id=PARENT_SESSION_ID,
        run_id=PARENT_RUN_ID,
        session_state={
            "company_id": COMPANY_ID,
            "child_session_id": CHILD_SESSION_ID,
            "current_revision": 3,
        },
        stream=True,
        stream_events=True,
    )
    async for event in stream:
        if isinstance(event, RunOutput):
            continue
        events.append(event)
        if cancel_on_progress and isinstance(event, CustomEvent):
            assert await acancel_run(PARENT_RUN_ID)
    return events


def test_parent_agent_invokes_workflow_with_typed_nested_progress(
    tmp_path: pathlib.Path,
) -> None:
    db = SqliteDb(db_file=str(tmp_path / "contract.db"))
    parent, child_terminals = _build_parent(db)
    events = anyio.run(_collect_parent_events, parent)

    progress = [event for event in events if isinstance(event, CustomEvent)]
    completed = [event for event in events if isinstance(event, RunCompletedEvent)]
    assert [event.content for event in progress] == ["child-started"]
    assert len(completed) == 1
    assert completed[0].content == NestedResult(
        company_id=COMPANY_ID, revision=4, outcome="validated"
    )
    assert child_terminals == ["WorkflowCompleted"]

    parent_session = db.get_session(PARENT_SESSION_ID)
    child_session = db.get_session(CHILD_SESSION_ID)
    assert isinstance(parent_session, AgentSession)
    assert isinstance(child_session, WorkflowSession)
    assert parent_session.user_id == child_session.user_id == USER_ID
    assert parent_session.session_data is not None
    assert child_session.session_data is not None
    assert parent_session.session_data["session_state"] == {
        "company_id": COMPANY_ID,
        "child_session_id": CHILD_SESSION_ID,
        "current_revision": 3,
    }
    assert child_session.session_data["session_state"] == {
        "company": {"company_id": COMPANY_ID, "name": "Fixture Co", "revision": 4}
    }
    assert json.loads(json.dumps(parent_session.session_data["session_state"])) == {
        "company_id": COMPANY_ID,
        "child_session_id": CHILD_SESSION_ID,
        "current_revision": 3,
    }
    assert json.loads(json.dumps(child_session.session_data["session_state"])) == {
        "company": {"company_id": COMPANY_ID, "name": "Fixture Co", "revision": 4}
    }


def test_parent_cancellation_cancels_child_workflow(tmp_path: pathlib.Path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "cancel.db"))
    parent, child_terminals = _build_parent(db, block_child=True)

    async def run_and_cancel() -> list[RunOutputEvent]:
        return await _collect_parent_events(parent, cancel_on_progress=True)

    events = anyio.run(run_and_cancel)

    assert sum(isinstance(event, RunCancelledEvent) for event in events) == 1
    assert sum(isinstance(event, RunCompletedEvent) for event in events) == 1
    assert child_terminals == ["WorkflowCancelled", "WorkflowCompleted"]
    parent_run = db.get_run(PARENT_RUN_ID)
    child_run = db.get_run(CHILD_RUN_ID)
    assert isinstance(parent_run, RunOutput)
    assert isinstance(child_run, WorkflowRunOutput)
    assert parent_run.status == RunStatus.cancelled.value
    assert child_run.status == RunStatus.cancelled.value
    assert anyio.run(aget_active_runs) == {}


def test_parent_agent_rejects_identity_override_without_child_artifact(
    tmp_path: pathlib.Path,
) -> None:
    db = SqliteDb(db_file=str(tmp_path / "spoof.db"))
    parent, child_terminals = _build_parent(db, claimed_user_id="attacker")
    events = anyio.run(_collect_parent_events, parent)

    errors = [event for event in events if isinstance(event, ToolCallErrorEvent)]
    assert len(errors) == 1
    assert errors[0].error == "context_mismatch:attacker!=founder-1"
    assert errors[0].tool is not None
    assert errors[0].tool.tool_call_error is True
    assert child_terminals == []
    assert db.get_session(CHILD_SESSION_ID) is None
    assert db.get_run(CHILD_RUN_ID) is None
