"""Admit AG-UI turns to the same native durable worker used by AgentOS runs."""

from __future__ import annotations

import json
from contextlib import suppress
from typing import TYPE_CHECKING, Protocol, cast
from uuid import UUID

from agno.db.schemas.jobs import QueuedJob
from agno.os.event_streams import get_event_stream
from agno.os.job_queue import QueueWorker, aprepare_accepted_or_abort
from agno.os.utils import queued_run_tail_streamer
from agno.run.agent import (
    RunStartedEvent,
    run_output_event_from_dict,  # pyright: ignore[reportUnknownVariableType]
)
from agno.run.base import RunStatus
from fastapi import HTTPException
from pydantic import BaseModel, JsonValue
from redis import Redis
from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool

from samurai.execution_state import WORK_INTENT_METADATA_KEY, SamuraiPostgresDb
from samurai.parent import create_parent_agent
from samurai.team_areas import TeamArea  # noqa: TC001 - Pydantic resolves the queued turn schema.
from samurai.work_admission import WorkApproval, build_work_intent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from agno.run.agent import RunOutputEvent
    from fastapi import Request

    from samurai.config import Settings


class _EnqueueResult(BaseModel):
    accepted: bool
    reason: str | None
    job: dict[str, JsonValue] | None


class _Store(Protocol):
    async def enqueue_job(self, job: dict[str, object], max_depth: int = 0) -> object: ...


class QueuedTurn(BaseModel):
    """Validated founder turn; identity is supplied by authenticated middleware."""

    run_id: str
    session_id: str
    owner_id: str
    message: str
    team_area: TeamArea
    approval: WorkApproval | None = None


def _coordination_available(url: str) -> bool:
    with Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1) as client:  # pyright: ignore[reportUnknownMemberType]
        try:
            return cast("Callable[[], bool]", client.ping)()
        except OSError, RedisError:
            return False


async def enqueue_turn(
    request: Request, database: SamuraiPostgresDb, settings: Settings, turn: QueuedTurn
) -> AsyncIterator[RunOutputEvent]:
    """Commit immutable work approval before emitting any accepted run event."""
    worker: object = getattr(request.app.state, "queue_worker", None)  # pyright: ignore[reportAny]
    if (
        not settings.queue_enabled
        or not isinstance(worker, QueueWorker)
        or settings.redis_url is None
    ):
        raise HTTPException(503, "Samurai's durable execution worker is unavailable.")
    if not await run_in_threadpool(_coordination_available, settings.redis_url.get_secret_value()):
        raise HTTPException(503, "Samurai's execution coordination is unavailable.")
    try:
        submission_id = UUID(turn.run_id)
        intent = await run_in_threadpool(
            build_work_intent, database, turn.owner_id, turn.session_id, turn.message, turn.approval
        )
    except PermissionError:
        raise HTTPException(
            403, "Company access or revision no longer permits this work."
        ) from None
    except ValueError:
        raise HTTPException(422, "Invalid company work approval or run identifier.") from None
    # Include navigation in the fingerprint: reusing an ID cannot change its team scope.
    intent = intent.model_copy(
        update={"approved_input": {"message": turn.message, "team_area": turn.team_area}}
    )
    job = QueuedJob(
        id=turn.run_id,
        component_type="agent",
        component_id="samurai",
        session_id=turn.session_id,
        user_id=turn.owner_id,
        idempotency_key=str(submission_id),
        deployment_id=worker.config.deployment_id,
        max_attempts=worker.config.max_attempts,
        payload={
            "input": turn.message,
            "stream": True,
            "kwargs": {
                "metadata": {
                    WORK_INTENT_METADATA_KEY: intent.model_dump(mode="json"),
                    "team_area": turn.team_area,
                    "samurai_work_operation": intent.operation.value,
                }
            },
        },
    )
    result = _EnqueueResult.model_validate(
        await cast("_Store", worker.store).enqueue_job(
            cast("dict[str, object]", job.to_dict()), max_depth=worker.config.max_queue_depth
        )
    )
    if result.reason == "queue_full":
        raise HTTPException(429, "Samurai's execution queue is full.")
    if not result.accepted and result.reason != "duplicate":
        raise HTTPException(503, "Samurai could not accept this work.")
    if result.job is None or result.job.get("id") != turn.run_id:
        raise HTTPException(409, "The work identifier belongs to another run.")
    if result.reason != "duplicate":
        with suppress(OSError, RedisError):
            await get_event_stream().register_run(turn.run_id, RunStatus.pending)
        await aprepare_accepted_or_abort(
            worker,
            create_parent_agent(database, settings),
            "agent",
            turn.run_id,
            turn.session_id,
            turn.owner_id,
            turn.message,
        )
    return _native_events(turn)


async def _native_events(turn: QueuedTurn) -> AsyncIterator[RunOutputEvent]:
    # The accepted ID is durable and cancellable before the first model response.
    yield RunStartedEvent(run_id=turn.run_id, session_id=turn.session_id, agent_id="samurai")
    frames = cast("AsyncIterator[str]", cast("object", queued_run_tail_streamer(turn.run_id)))
    async for frame in frames:
        data = "\n".join(
            line[5:].lstrip() for line in frame.splitlines() if line.startswith("data:")
        )
        if not data:
            continue
        value: object = cast("object", json.loads(data))
        if not isinstance(value, dict):
            message = "Invalid execution event"
            raise TypeError(message)
        value = cast("dict[str, object]", value)
        if value.get("run_id") != turn.run_id:
            message = "Invalid execution event identity"
            raise ValueError(message)
        yield cast("RunOutputEvent", run_output_event_from_dict(value))
