# ruff: noqa: D102, D107, EM101, TRY003
"""Authenticated AG-UI transport for the request-scoped Samurai parent."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Annotated, ClassVar, cast, final, override

from ag_ui.core import CustomEvent, RunAgentInput, RunErrorEvent, RunStartedEvent
from ag_ui.encoder import EventEncoder
from agno.os.interfaces.agui.handlers import is_completion_event, process_completion, process_event
from agno.os.interfaces.agui.state import StreamState
from agno.os.interfaces.base import BaseInterface
from agno.os.middleware.user_scope import assert_session_writable, resolve_run_user_id
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import ConfigDict, Field, model_validator

from samurai.agui_queue import QueuedTurn, enqueue_turn
from samurai.execution_state import SamuraiPostgresDb
from samurai.parent import create_parent_agent
from samurai.team_areas import selected_area
from samurai.work_admission import WorkApproval

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from agno.agent import Agent
    from agno.db.base import BaseDb
    from agno.models.base import Model
    from agno.run.agent import RunOutputEvent

    from samurai.config import Settings


class SamuraiRunInput(RunAgentInput):
    """Only the latest text turn enters the agent; persisted history and state are authoritative."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", populate_by_name=True)
    thread_id: Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")]
    run_id: Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")]

    @model_validator(mode="after")
    def trusted_context(self) -> SamuraiRunInput:
        if self.tools or self.context or self.state:
            raise ValueError("Client tools, identity and company state overrides are forbidden")
        if len(self.messages) != 1 or self.messages[0].role != "user":
            raise ValueError("Exactly one user turn is required")
        if not isinstance(self.messages[0].content, str) or not self.messages[0].content.strip():
            raise ValueError("Text input is required")
        props = cast("dict[str, object]", self.forwarded_props or {})
        if props.keys() - {"team_area", "work_approval"}:
            raise ValueError("Only team navigation and bounded work approval may be forwarded")
        _ = selected_area({"team_area": props.get("team_area", "overview")})
        if "work_approval" in props:
            _ = WorkApproval.model_validate(props["work_approval"])
        if self.resume:
            raise ValueError("Client tool continuation is not supported")
        return self


@final
class SamuraiAGUI(BaseInterface):
    """Use Agno's protocol mapping while preserving fresh models, native scopes and owner checks."""

    type: str = "agui"
    prefix: str = "/agents/samurai"
    tags: list[str]

    def __init__(
        self, db: BaseDb, settings: Settings, model_factory: Callable[[], Model] | None
    ) -> None:
        self.tags = ["AGUI"]
        self.router = APIRouter(prefix=self.prefix, tags=["AGUI"])
        self.db = db
        self.settings = settings
        self.model_factory = model_factory

    @override
    def get_scope_mappings(self) -> dict[str, list[str]]:
        return {"POST /agents/samurai/agui": ["agents:samurai:run"]}

    @override
    def get_router(self, use_async: bool = True, **kwargs: object) -> APIRouter:
        del use_async, kwargs
        router = APIRouter(prefix=self.prefix, tags=["AGUI"])
        self.router = router

        @router.post("/agui")
        async def run(request: Request, run_input: SamuraiRunInput) -> StreamingResponse:
            user_id = resolve_run_user_id(request, None)
            if not user_id:
                raise HTTPException(403, "Authenticated founder required")
            if (
                len(cast("str", run_input.messages[0].content))
                > self.settings.gemini_max_input_chars
            ):
                raise HTTPException(422, "Input exceeds the size limit")
            await assert_session_writable(self.db, run_input.thread_id, user_id, is_admin=False)
            if self.db.get_run(run_input.run_id) is not None:
                raise HTTPException(409, "Run identifier already used")
            props = cast("dict[str, object]", run_input.forwarded_props or {})
            area = selected_area({"team_area": props.get("team_area", "overview")})
            if isinstance(self.db, SamuraiPostgresDb):
                chunks = await enqueue_turn(
                    request,
                    self.db,
                    self.settings,
                    QueuedTurn(
                        run_id=run_input.run_id,
                        session_id=run_input.thread_id,
                        owner_id=user_id,
                        message=cast("str", run_input.messages[0].content),
                        team_area=area,
                        approval=WorkApproval.model_validate(props["work_approval"])
                        if "work_approval" in props
                        else None,
                    ),
                )
                return StreamingResponse(
                    _encoded_events(chunks, run_input),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
                )
            if "work_approval" in props:
                raise HTTPException(
                    503, "Approved work requires Samurai's durable execution worker."
                )
            agent = create_parent_agent(
                self.db,
                self.settings,
                model=self.model_factory() if self.model_factory is not None else None,
                team_area=area,
                read_only=True,
            )
            return StreamingResponse(
                _events(agent, run_input, user_id),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            )

        return router


async def _checkpoint_start(agent: Agent, run_input: SamuraiRunInput, user_id: str) -> None:
    # Inline Agno runs normally persist only at completion; cancellation requires an owned row.
    session = await agent.aget_session(session_id=run_input.thread_id, user_id=user_id)
    if session is None:
        session = AgentSession(session_id=run_input.thread_id, user_id=user_id, agent_id="samurai")
    if not isinstance(session, AgentSession):
        raise TypeError("Agent company session required")
    now = int(time.time())
    session.created_at = session.created_at or now
    session.updated_at = now
    pending = RunOutput(
        run_id=run_input.run_id,
        session_id=run_input.thread_id,
        user_id=user_id,
        agent_id="samurai",
        status=RunStatus.running,
        metadata={
            "team_area": selected_area(
                {
                    "team_area": cast("dict[str, object]", run_input.forwarded_props or {}).get(
                        "team_area", "overview"
                    )
                }
            )
        },
    )
    session.upsert_run(pending)
    if session.session_data is None:
        session.session_data = {}
    await agent.asave_session(session)
    cast("BaseDb", agent.db).upsert_run(pending, session_id=run_input.thread_id, user_id=user_id)


async def _inline_events(
    agent: Agent, run_input: SamuraiRunInput, user_id: str
) -> AsyncIterator[RunOutputEvent]:
    run = cast("Callable[..., AsyncIterator[RunOutputEvent]]", agent.arun)
    response = run(
        input=cast("str", run_input.messages[0].content),
        session_id=run_input.thread_id,
        run_id=run_input.run_id,
        user_id=user_id,
        stream=True,
        stream_events=True,
        metadata={
            "team_area": selected_area(
                {
                    "team_area": cast("dict[str, object]", run_input.forwarded_props or {}).get(
                        "team_area", "overview"
                    )
                }
            )
        },
    )
    async for chunk in response:
        if chunk.event == "RunStarted":
            await _checkpoint_start(agent, run_input, user_id)
        yield chunk


async def _events(agent: Agent, run_input: SamuraiRunInput, user_id: str) -> AsyncIterator[str]:
    async for event in _encoded_events(_inline_events(agent, run_input, user_id), run_input):
        yield event


async def _encoded_events(
    response: AsyncIterator[RunOutputEvent], run_input: SamuraiRunInput
) -> AsyncIterator[str]:
    encoder = EventEncoder()
    state = StreamState(thread_id=run_input.thread_id, run_id=run_input.run_id)
    terminal = False
    yield encoder.encode(RunStartedEvent(thread_id=run_input.thread_id, run_id=run_input.run_id))
    try:
        async for chunk in response:
            # Retain native completion/progress semantics for saved-run recovery and cancellation.
            if chunk.event in {
                "RunStarted",
                "ToolCallCompleted",
                "CustomEvent",
                "RunCompleted",
                "RunCancelled",
                "RunError",
            }:
                value = chunk.to_dict()
                if chunk.event == "RunError":
                    value = {
                        key: value[key] for key in ("event", "run_id", "session_id", "agent_id")
                    }
                    value["content"] = "Samurai could not complete this run."
                yield encoder.encode(CustomEvent(name="samurai", value=value))
            completed = is_completion_event(chunk) or chunk.event == "RunCancelled"
            terminal = terminal or completed
            if chunk.event == "RunError":
                yield encoder.encode(RunErrorEvent(message="Samurai could not complete this run."))
            else:
                for event in (
                    process_completion(chunk, state) if completed else process_event(chunk, state)
                ):
                    yield encoder.encode(event)
        if not terminal:
            yield encoder.encode(RunErrorEvent(message="Samurai stream ended before completion."))
    except Exception:  # noqa: BLE001 - provider details must not cross the HTTP boundary.
        yield encoder.encode(RunErrorEvent(message="Samurai could not complete this run."))
