"""Application factory for the local AgentOS bootstrap."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final, Literal, cast, final
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from agno.os import AgentOS
from agno.os.auth import acheck_resource_access
from agno.os.authz import Authorization
from agno.os.config import AgentOSConfig, ChatConfig
from agno.os.settings import AgnoAPISettings
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from redis import Redis
from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartException
from starlette.requests import Request

from samurai.agui import SamuraiAGUI
from samurai.config import Settings, create_queue_config
from samurai.execution_state import (
    WORK_INTENT_METADATA_KEY,
    ApprovedStage,
    SamuraiPostgresDb,
    WorkIntentError,
    WorkIntentInput,
    WorkIntentIssue,
    WorkOperation,
    WorkReceipt,
)
from samurai.file_api import file_router
from samurai.guest_access import GuestAccessBoundary
from samurai.intake import INTAKE_PAGES, IntakePage
from samurai.knowledge_api import knowledge_router
from samurai.learning_api import learning_router
from samurai.parent import (
    PARENT_AGENT_ID,
    STARTER_PROMPTS,
    create_parent_agent,
)
from samurai.scenario_api import scenario_router
from samurai.schedule_api import schedule_router
from samurai.work_admission import WorkApproval, build_work_intent
from samurai.workspace_api import workspace_router

__all__ = ["Settings"]

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from agno.db.base import BaseDb
    from agno.models.base import Model
    from starlette.datastructures import FormData
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

RUN_PATH: Final = f"/agentos/agents/{PARENT_AGENT_ID}/runs"
RUN_CONTINUE_PREFIX: Final = f"{RUN_PATH}/"
RUN_CONTINUE_SUFFIX: Final = "/continue"
RUN_CANCEL_SUFFIX: Final = "/cancel"
CONTINUE_FORM_OVERHEAD_BYTES: Final = 16_384
DURABLE_RUN_UNAVAILABLE: Final = "durable Samurai execution is unavailable"
DURABLE_RUN_REQUIRED: Final = "Samurai write runs require background=true"
DURABLE_CONTINUE_UNAVAILABLE: Final = "durable Samurai continuation is unavailable"
DURABLE_RUN_FIELDS: Final = frozenset({"message", "session_id", "stream", "background"})
QUEUE_COORDINATION_UNAVAILABLE: Final = "durable Samurai coordination is unavailable"
QUEUE_DELAYED_SECONDS: Final = 120


class _HttpRequestMessage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    type: Literal["http.request", "http.disconnect"]
    body: bytes = b""
    more_body: bool = False


class _NativeQueueStats(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    counts: dict[str, int]
    oldest_queued_age_seconds: int | None = None


class _QueueReadiness(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)
    status: Literal["healthy", "delayed", "unhealthy"]
    worker_available: bool
    coordination_available: bool
    queued_jobs: int
    oldest_pending_seconds: int | None = None


def _input_fields_for_path(path: str) -> tuple[str, ...] | None:
    if path == "/agentos/agents/samurai/agui":
        return ()
    if path == RUN_PATH:
        return ("message",)
    run_id = path[len(RUN_CONTINUE_PREFIX) : -len(RUN_CONTINUE_SUFFIX)]
    if (
        path.startswith(RUN_CONTINUE_PREFIX)
        and path.endswith(RUN_CONTINUE_SUFFIX)
        and run_id
        and "/" not in run_id
    ):
        return ("input", "additional_instructions")
    return None


def _cancel_run_id(path: str) -> str | None:
    if not path.startswith(RUN_CONTINUE_PREFIX) or not path.endswith(RUN_CANCEL_SUFFIX):
        return None
    run_id = path[len(RUN_CONTINUE_PREFIX) : -len(RUN_CANCEL_SUFFIX)]
    return run_id if run_id and "/" not in run_id else None


def _coordination_available(redis_url: str) -> bool:
    parsed = urlsplit(redis_url)
    client = Redis(
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or 6379,
        db=int(parsed.path.lstrip("/") or "0"),
        username=parsed.username,
        password=parsed.password,
        ssl=parsed.scheme == "rediss",
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        ping = cast("Callable[[], bool]", client.ping)
        return ping()
    except OSError, RedisError:
        return False
    finally:
        client.close()


def _replay_body_once(payload: bytes, receive: Receive) -> Receive:
    replayed = False

    async def replay() -> Message:
        nonlocal replayed
        if not replayed:
            replayed = True
            return {"type": "http.request", "body": payload, "more_body": False}
        return await receive()

    return replay


async def _queue_readiness_response(
    request: Request,
    runtime_db: BaseDb,
    redis_url: str | None,
) -> _QueueReadiness:
    scopes = cast("object", getattr(request.state, "scopes", None))
    if not isinstance(scopes, list):
        raise HTTPException(status_code=401, detail="authenticated queue operator is required")
    typed_scopes = [scope for scope in cast("list[object]", scopes) if isinstance(scope, str)]
    if "agent_os:admin" not in typed_scopes and "*" not in typed_scopes:
        raise HTTPException(status_code=403, detail="queue diagnostics require admin scope")
    request_app = cast("FastAPI", request.app)
    worker_available = getattr(request_app.state, "queue_worker", None) is not None
    coordination_available = redis_url is not None and await run_in_threadpool(
        _coordination_available, redis_url
    )
    stats = (
        _NativeQueueStats.model_validate(await run_in_threadpool(runtime_db.queue_stats))
        if isinstance(runtime_db, SamuraiPostgresDb)
        else _NativeQueueStats(counts={})
    )
    oldest = stats.oldest_queued_age_seconds
    status: Literal["healthy", "delayed", "unhealthy"] = "healthy"
    if not worker_available or not coordination_available:
        status = "unhealthy"
    elif oldest is not None and oldest > QUEUE_DELAYED_SECONDS:
        status = "delayed"
    return _QueueReadiness(
        status=status,
        worker_available=worker_available,
        coordination_available=coordination_available,
        queued_jobs=stats.counts.get("queued", 0),
        oldest_pending_seconds=oldest,
    )


def _work_approval(runtime_db: BaseDb | None, scope: Scope, form: FormData) -> WorkIntentInput:
    message, session_id = form.get("message"), form.get("session_id")
    state = cast("dict[str, object]", scope.setdefault("state", {}))
    owner_id = state.get("user_id")
    if not all(isinstance(value, str) and value for value in (message, session_id, owner_id)):
        detail = "authenticated durable owner is required"
        raise PermissionError(detail)
    headers = dict(cast("list[tuple[bytes, bytes]]", scope.get("headers", [])))
    company_header = headers.get(b"x-samurai-company-id")
    approval = WorkApproval(
        operation=WorkOperation(headers.get(b"x-samurai-operation", b"journey").decode("ascii")),
        stage=ApprovedStage(headers.get(b"x-samurai-stage", b"brief").decode("ascii")),
        expected_revision=int(headers.get(b"x-samurai-expected-revision", b"0").decode("ascii")),
        company_id=None if company_header is None else UUID(company_header.decode("ascii")),
    )
    return build_work_intent(
        runtime_db, cast("str", owner_id), cast("str", session_id), cast("str", message), approval
    )


@final
@dataclass(frozen=True, slots=True)
class _ParentInputBoundary:
    app: ASGIApp
    max_input_chars: int

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:  # noqa: PLR0911 - HTTP boundary exits.
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        input_fields = _input_fields_for_path(cast("str", scope["path"]))
        if input_fields is None:
            await self.app(scope, receive, send)
            return
        max_body_bytes = (
            None
            if input_fields == ("message",)
            else self.max_input_chars * 8 + CONTINUE_FORM_OVERHEAD_BYTES
        )

        body = bytearray()
        more_body = True
        while more_body:
            message = _HttpRequestMessage.model_validate(await receive())
            if message.type == "http.disconnect":
                await self.app(scope, receive, send)
                return
            body.extend(message.body)
            if max_body_bytes is not None and len(body) > max_body_bytes:
                response = JSONResponse(
                    status_code=422,
                    content={"detail": "request contains forbidden or oversized context"},
                )
                await response(scope, receive, send)
                return
            more_body = message.more_body
        payload = bytes(body)
        if not input_fields:
            await self.app(scope, _replay_body_once(payload, receive), send)
            return

        try:
            headers = cast("list[tuple[bytes, bytes]]", scope.get("headers", []))
            if b"application/x-www-form-urlencoded" in dict(headers).get(b"content-type", b""):
                _ = payload.decode("utf-8")
            form = await Request(scope, _replay_body_once(payload, receive)).form()
        except MultiPartException, UnicodeDecodeError:
            response = JSONResponse(status_code=422, content={"detail": "invalid request body"})
            await response(scope, receive, send)
            return
        input_values = [value for field in input_fields for value in form.getlist(field)]
        invalid_encoding = any(
            isinstance(value, str) and "\ufffd" in value for value in input_values
        )
        forbidden_context = "session_state" in form or "dependencies" in form
        oversized = any(
            isinstance(value, str) and len(value) > self.max_input_chars for value in input_values
        )
        detail = (
            "invalid request body"
            if invalid_encoding
            else "request contains forbidden or oversized context"
        )
        if invalid_encoding or forbidden_context or oversized:
            response = JSONResponse(
                status_code=422,
                content={"detail": detail},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, _replay_body_once(payload, receive), send)


@final
@dataclass(frozen=True, slots=True)
class _DurableRunBoundary:
    app: ASGIApp
    enabled: bool
    required: bool
    db: BaseDb | None = None
    redis_url: str | None = None

    async def __call__(  # noqa: C901, PLR0911, PLR0912, PLR0915 - each rejection is a trust boundary.
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        path = cast("str", scope["path"])
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        cancel_run_id = _cancel_run_id(path)
        if cancel_run_id is not None:
            await self._persist_cancel_if_authorized(scope, receive, cancel_run_id)
            await self.app(scope, receive, send)
            return
        if _input_fields_for_path(path) == ("input", "additional_instructions"):
            if self.enabled or self.required:
                await self._reject(scope, receive, send, 409, DURABLE_CONTINUE_UNAVAILABLE)
                return
            await self.app(scope, receive, send)
            return
        if not path.endswith(f"/agents/{PARENT_AGENT_ID}/runs"):
            await self.app(scope, receive, send)
            return
        if not self.enabled:
            if self.required:
                await self._reject(scope, receive, send, 503, DURABLE_RUN_UNAVAILABLE)
                return
            await self.app(scope, receive, send)
            return
        if self.redis_url is not None and not await run_in_threadpool(
            _coordination_available, self.redis_url
        ):
            await self._reject(scope, receive, send, 503, QUEUE_COORDINATION_UNAVAILABLE)
            return

        body = bytearray()
        more_body = True
        while more_body:
            message = _HttpRequestMessage.model_validate(await receive())
            if message.type == "http.disconnect":
                await self.app(scope, receive, send)
                return
            body.extend(message.body)
            more_body = message.more_body
        payload = bytes(body)
        replay = _replay_body_once(payload, receive)
        try:
            form = await Request(scope, replay).form()
        except MultiPartException, UnicodeDecodeError:
            await self._reject(scope, replay, send, 422, "invalid request body")
            return
        if frozenset(form) != DURABLE_RUN_FIELDS or any(
            len(form.getlist(key)) != 1 for key in form
        ):
            await self._reject(
                scope,
                replay,
                send,
                422,
                "durable Samurai runs accept only message, session_id, stream, and background",
            )
            return
        if form.get("background") != "true":
            await self._reject(scope, replay, send, 409, DURABLE_RUN_REQUIRED)
            return
        headers = dict(cast("list[tuple[bytes, bytes]]", scope.get("headers", [])))
        try:
            submission_id = headers[b"idempotency-key"].decode("ascii")
            _ = UUID(submission_id)
        except KeyError, UnicodeDecodeError, ValueError:
            await self._reject(
                scope,
                replay,
                send,
                422,
                "Idempotency-Key must be a UUID",
            )
            return
        state = cast("dict[str, object]", scope.setdefault("state", {}))
        try:
            approval = await run_in_threadpool(_work_approval, self.db, scope, form)
        except PermissionError:
            await self._reject(scope, replay, send, 401, "authenticated durable owner is required")
            return
        except KeyError, UnicodeDecodeError, ValueError:
            await self._reject(scope, replay, send, 422, "invalid or missing Samurai work approval")
            return
        state["metadata"] = {
            WORK_INTENT_METADATA_KEY: approval.model_dump(mode="json"),
        }
        await self.app(scope, _replay_body_once(payload, receive), send)

    async def _persist_cancel_if_authorized(
        self,
        scope: Scope,
        receive: Receive,
        run_id: str,
    ) -> None:
        if not isinstance(self.db, SamuraiPostgresDb):
            return
        query = parse_qs(cast("bytes", scope.get("query_string", b"")).decode("ascii"))
        session_ids = query.get("session_id", [])
        state = cast("dict[str, object]", scope.setdefault("state", {}))
        owner_id = state.get("user_id")
        if (
            len(session_ids) != 1
            or not isinstance(owner_id, str)
            or not owner_id
            or not await acheck_resource_access(
                Request(scope, receive), PARENT_AGENT_ID, "agents", "run"
            )
        ):
            return
        _ = await run_in_threadpool(
            self.db.cancel_work_job,
            run_id,
            owner_id,
            session_ids[0],
        )

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        detail: str,
    ) -> None:
        response = JSONResponse(status_code=status_code, content={"detail": detail})
        await response(scope, receive, send)


async def _work_receipt_response(
    runtime_db: BaseDb,
    submission_id: str,
    session_id: str,
    request: Request,
) -> WorkReceipt:
    try:
        canonical_submission_id = UUID(submission_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="submission id must be a UUID") from None
    owner_id = getattr(request.state, "user_id", None)
    if not isinstance(owner_id, str) or not owner_id:
        raise HTTPException(status_code=401, detail="authenticated receipt owner is required")
    if not await acheck_resource_access(request, PARENT_AGENT_ID, "agents", "read"):
        raise HTTPException(status_code=403, detail="insufficient permissions")
    if not isinstance(runtime_db, SamuraiPostgresDb):
        raise HTTPException(status_code=503, detail=DURABLE_RUN_UNAVAILABLE)
    receipt = await run_in_threadpool(
        runtime_db.get_work_receipt,
        owner_id,
        session_id,
        canonical_submission_id,
    )
    if receipt is None:
        raise HTTPException(status_code=404, detail="work receipt not found")
    return receipt


def create_app(
    *,
    db: BaseDb | None = None,
    settings: Settings | None = None,
    parent_model_factory: Callable[[], Model] | None = None,
) -> FastAPI:
    """Build a local secured runtime; registration does not invoke Gemini."""
    settings = settings or Settings.model_validate({})
    runtime_db = db or SamuraiPostgresDb(id="samurai", db_url=str(settings.database_url))
    if settings.queue_enabled and not isinstance(runtime_db, SamuraiPostgresDb):
        message = "durable Samurai execution requires SamuraiPostgresDb"
        raise ValueError(message)
    api_key = settings.google_api_key.get_secret_value()
    parent = create_parent_agent(
        runtime_db,
        settings,
        model_factory=parent_model_factory,
        executable=False,
    )

    runtime_base = FastAPI(docs_url=None, redoc_url=None)
    if isinstance(runtime_db, SamuraiPostgresDb):
        runtime_base.include_router(workspace_router(runtime_db))
        runtime_base.include_router(file_router(runtime_db, settings.storage_root))
        runtime_base.include_router(knowledge_router(runtime_db, settings.storage_root))
        runtime_base.include_router(learning_router(runtime_db))
        runtime_base.include_router(schedule_router(runtime_db))
        runtime_base.include_router(scenario_router(runtime_db))
    runtime_base.add_middleware(
        _DurableRunBoundary,
        enabled=settings.queue_enabled,
        required=settings.samurai_environment == "production",
        db=runtime_db,
        redis_url=(
            settings.redis_url.get_secret_value() if settings.redis_url is not None else None
        ),
    )

    runtime_base.add_middleware(
        GuestAccessBoundary,
        enabled=settings.guest_access_enabled,
        engine=runtime_db.db_engine if isinstance(runtime_db, SamuraiPostgresDb) else None,
        schema=runtime_db.db_schema if isinstance(runtime_db, SamuraiPostgresDb) else "public",
    )

    @runtime_base.exception_handler(WorkIntentError)
    async def work_intent_error(_request: Request, error: WorkIntentError) -> JSONResponse:
        conflict = error.issue in {
            WorkIntentIssue.ACTIVE_WORK,
            WorkIntentIssue.CHANGED_APPROVAL,
            WorkIntentIssue.WORKSPACE_QUOTA,
        }
        return JSONResponse(status_code=409 if conflict else 422, content={"detail": str(error)})

    @runtime_base.get("/work-receipts/{submission_id}", response_model=WorkReceipt)
    async def work_receipt(
        submission_id: str,
        session_id: str,
        request: Request,
    ) -> WorkReceipt:
        return await _work_receipt_response(runtime_db, submission_id, session_id, request)

    runtime = AgentOS(
        id="samurai",
        name="AI Idea to Company",
        db=runtime_db,
        agents=[parent] if api_key or parent_model_factory is not None else [],
        workflows=[],
        interfaces=[SamuraiAGUI(runtime_db, settings, parent_model_factory)]
        if api_key or parent_model_factory is not None
        else [],
        config=AgentOSConfig(chat=ChatConfig(quick_prompts={PARENT_AGENT_ID: STARTER_PROMPTS})),
        settings=AgnoAPISettings(os_security_key=settings.os_security_key.get_secret_value()),
        authorization=Authorization(
            verification_keys=[
                key
                for key in (settings.jwt_verification_key, settings.frontend_jwt_verification_key)
                if key and key.strip()
            ],
            algorithm="RS256",
        )
        if settings.jwt_verification_key
        else False,
        user_isolation=bool(settings.jwt_verification_key),
        cors_allowed_origins=[
            "http://127.0.0.1:3000",
            "http://localhost:3000",
            "https://os.agno.com",
        ],
        auto_provision_dbs=False,
        base_app=runtime_base,
        queue=create_queue_config(settings, runtime_db),
        tracing=db is None,
        telemetry=False,
    ).get_app()

    @runtime.get("/queue/samurai-readiness", response_model=_QueueReadiness)
    async def queue_readiness(request: Request) -> _QueueReadiness:
        return await _queue_readiness_response(
            request,
            runtime_db,
            settings.redis_url.get_secret_value() if settings.redis_url is not None else None,
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        # Mounted apps do not receive startup/shutdown automatically.
        async with runtime.router.lifespan_context(runtime):
            yield

    app = FastAPI(title="Samurai API", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.get("/api/company/intake")
    def company_intake() -> tuple[IntakePage, ...]:
        return INTAKE_PAGES

    app.mount("/agentos", runtime, name="agentos")
    app.add_middleware(_ParentInputBoundary, max_input_chars=settings.gemini_max_input_chars)
    return app
