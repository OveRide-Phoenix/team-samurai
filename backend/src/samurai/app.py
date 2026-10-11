"""Application factory for the local AgentOS bootstrap."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final, Literal, final

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
from samurai.parent import (
    PARENT_AGENT_ID,
    STARTER_PROMPTS,
    create_parent_factory,
)

__all__ = ["Settings"]

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from agno.db.base import BaseDb
    from agno.models.base import Model
    from starlette.types import ASGIApp, Message, Receive, Scope, Send
RUN_PATH: Final = f"/agentos/agents/{PARENT_AGENT_ID}/runs"


class _HttpRequestMessage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    type: Literal["http.request", "http.disconnect"]
    body: bytes = b""
    more_body: bool = False


@final
@dataclass(frozen=True, slots=True)
class _ParentInputBoundary:
    app: ASGIApp
    max_input_chars: int

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != RUN_PATH:
            await self.app(scope, receive, send)
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

        async def replay() -> Message:
            return {"type": "http.request", "body": payload, "more_body": False}

        try:
            form = await Request(scope, replay).form()
        except MultiPartException, UnicodeDecodeError:
            response = JSONResponse(status_code=422, content={"detail": "invalid request body"})
            await response(scope, replay, send)
            return
        messages = form.getlist("message")
        forbidden_context = "session_state" in form or "dependencies" in form
        oversized = any(
            isinstance(message, str) and len(message) > self.max_input_chars for message in messages
        )
        if forbidden_context or oversized:
            response = JSONResponse(
                status_code=422,
                content={"detail": "request contains forbidden or oversized context"},
            )
            await response(scope, replay, send)
            return
        await self.app(scope, replay, send)


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

    runtime = AgentOS(
        id="samurai",
        name="AI Idea to Company",
        db=runtime_db,
        agents=[
            create_parent_factory(
                runtime_db,
                settings,
                model_factory=parent_model_factory,
            )
        ]
        if api_key or parent_model_factory is not None
        else [],
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
            yield

    app = FastAPI(title="Samurai API", lifespan=lifespan, docs_url=None, redoc_url=None)

    app.mount("/agentos", runtime, name="agentos")
    app.add_middleware(_ParentInputBoundary, max_input_chars=settings.gemini_max_input_chars)
    return app
