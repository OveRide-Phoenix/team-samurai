"""Application factory for the local AgentOS bootstrap."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final, Literal, cast, final

from agno.db.postgres import PostgresDb
from agno.os import AgentOS
from agno.os.authz import Authorization
from agno.os.config import AgentOSConfig, ChatConfig
from agno.os.settings import AgnoAPISettings
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.formparsers import MultiPartException
from starlette.requests import Request

from samurai.config import Settings
from samurai.intake import INTAKE_PAGES, IntakePage
from samurai.parent import (
    PARENT_AGENT_ID,
    STARTER_PROMPTS,
    create_parent_agent,
)

__all__ = ["Settings"]

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from agno.db.base import BaseDb
    from agno.models.base import Model
    from starlette.types import ASGIApp, Message, Receive, Scope, Send
RUN_PATH: Final = f"/agentos/agents/{PARENT_AGENT_ID}/runs"
RUN_CONTINUE_PREFIX: Final = f"{RUN_PATH}/"
RUN_CONTINUE_SUFFIX: Final = "/continue"
CONTINUE_FORM_OVERHEAD_BYTES: Final = 16_384


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
    parent = create_parent_agent(
        runtime_db,
        settings,
        model_factory=parent_model_factory,
        executable=False,
    )

    runtime = AgentOS(
        id="samurai",
        name="AI Idea to Company",
        db=runtime_db,
        agents=[parent] if api_key or parent_model_factory is not None else [],
        workflows=[],
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
        tracing=db is None,
        telemetry=False,
    ).get_app()

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
