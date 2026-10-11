"""Application factory for the local AgentOS bootstrap."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final, Literal, Protocol, cast, final, runtime_checkable

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.os import AgentOS
from agno.os.authz import Authorization
from agno.os.config import AgentOSConfig, ChatConfig
from agno.os.middleware.user_scope import get_scoped_user_id
from agno.os.settings import AgnoAPISettings
from agno.os.utils import resolve_agent
from agno.session.agent import AgentSession
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict
from starlette.formparsers import MultiPartException
from starlette.requests import Request

from samurai.config import Settings
from samurai.parent import (
    PARENT_AGENT_ID,
    STARTER_PROMPTS,
    create_parent_factory,
)

__all__ = ["Settings"]

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from agno.agent.factory import AgentFactory
    from agno.db.base import BaseDb
    from agno.models.base import Model
    from starlette.routing import BaseRoute
    from starlette.types import ASGIApp, Message, Receive, Scope, Send
RUN_PATH: Final = f"/agentos/agents/{PARENT_AGENT_ID}/runs"
RUN_READ_PATH: Final = "/agents/{agent_id}/runs/{run_id}"
RUN_CONTINUE_PREFIX: Final = f"{RUN_PATH}/"
RUN_CONTINUE_SUFFIX: Final = "/continue"
CONTINUE_FORM_OVERHEAD_BYTES: Final = 16_384


class _FactoryRunReadRouteMissingError(RuntimeError):
    pass


@runtime_checkable
class _IncludedRouter(Protocol):
    original_router: APIRouter


def _find_factory_run_read_route(routes: list[BaseRoute]) -> APIRoute | None:
    for route in routes:
        if isinstance(route, APIRoute) and route.path == RUN_READ_PATH and route.methods == {"GET"}:
            return route
        if isinstance(route, _IncludedRouter):
            nested = _find_factory_run_read_route(route.original_router.routes)
            if nested is not None:
                return nested
    return None


def _install_factory_run_read_compat(runtime: FastAPI, factory: AgentFactory) -> None:
    async def get_factory_run(
        request: Request,
        agent_id: str,
        run_id: str,
        session_id: str,
    ) -> dict[str, object]:
        user_id = get_scoped_user_id(request)
        agent = await resolve_agent(
            agent_id,
            [factory],
            factory.db,
            request=request,
            user_id=user_id,
            session_id=session_id,
            published_only=False,
        )
        if not isinstance(agent, Agent):
            raise HTTPException(status_code=404, detail="Agent not found")
        session = await agent.aget_session(session_id=session_id, user_id=user_id)
        if not isinstance(session, AgentSession) or session.agent_id != agent_id:
            raise HTTPException(status_code=404, detail="Run not found")
        run_output = await agent.aget_run_output(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
        )
        if run_output is None or run_output.agent_id != agent_id:
            raise HTTPException(status_code=404, detail="Run not found")
        return cast("dict[str, object]", run_output.to_dict())

    route = _find_factory_run_read_route(runtime.routes)
    if route is None:
        raise _FactoryRunReadRouteMissingError
    # shortcut: Remove after Agno >3.1.2 passes Request to resolve_agent on factory reads.
    route.endpoint = get_factory_run
    route.dependant.call = get_factory_run


class _HttpRequestMessage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    type: Literal["http.request", "http.disconnect"]
    body: bytes = b""
    more_body: bool = False


def _input_fields_for_path(path: str) -> tuple[str, ...] | None:
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


def _replay_body_once(payload: bytes, receive: Receive) -> Receive:
    replayed = False

    async def replay() -> Message:
        nonlocal replayed
        if not replayed:
            replayed = True
            return {"type": "http.request", "body": payload, "more_body": False}
        return await receive()

    return replay


@final
@dataclass(frozen=True, slots=True)
class _ParentInputBoundary:
    app: ASGIApp
    max_input_chars: int

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
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


def create_app(
    *,
    db: BaseDb | None = None,
    settings: Settings | None = None,
    parent_model_factory: Callable[[], Model] | None = None,
) -> FastAPI:
    """Build a local secured runtime; registration does not invoke Gemini."""
    settings = settings or Settings.model_validate({})
    runtime_db = db or PostgresDb(id="samurai", db_url=str(settings.database_url))
    api_key = settings.google_api_key.get_secret_value()
    parent_factory = create_parent_factory(
        runtime_db,
        settings,
        model_factory=parent_model_factory,
    )

    runtime = AgentOS(
        id="samurai",
        name="AI Idea to Company",
        db=runtime_db,
        agents=[parent_factory] if api_key or parent_model_factory is not None else [],
        workflows=[],
        config=AgentOSConfig(chat=ChatConfig(quick_prompts={PARENT_AGENT_ID: STARTER_PROMPTS})),
        settings=AgnoAPISettings(os_security_key=settings.os_security_key.get_secret_value()),
        authorization=Authorization(
            verification_keys=[settings.jwt_verification_key],
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
        tracing=db is None,
        telemetry=False,
    ).get_app()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        # Mounted apps do not receive startup/shutdown automatically.
        async with runtime.router.lifespan_context(runtime):
            if api_key or parent_model_factory is not None:
                _install_factory_run_read_compat(runtime, parent_factory)
            yield

    app = FastAPI(title="Samurai API", lifespan=lifespan, docs_url=None, redoc_url=None)

    app.mount("/agentos", runtime, name="agentos")
    app.add_middleware(_ParentInputBoundary, max_input_chars=settings.gemini_max_input_chars)
    return app
