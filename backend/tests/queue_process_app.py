from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Never, cast, final, override
from unittest.mock import patch

from agno.agent import Agent
from agno.exceptions import InputCheckError
from agno.models.base import Model
from agno.models.google import Gemini
from agno.models.response import ModelResponse

from samurai import company_workflow
from samurai.agents import ROLE_CAPABILITIES, ConfiguredRole
from samurai.app import create_app
from samurai.config import Settings
from samurai.contracts import CompanyState, Role
from samurai.execution_state import AcceptanceToken, SamuraiPostgresDb
from samurai.parent import SamuraiParentAgent

if TYPE_CHECKING:
    from collections import abc
    from collections.abc import Sequence

    from agno.models.message import Message
    from fastapi import FastAPI


@final
class _QueueProcessModel(Model):
    def __init__(self) -> None:
        super().__init__(id="queue-process-model", name="Queue process model", provider="test")
        self.id: str = "queue-process-model"
        self.calls: int = 0

    async def _response(self, messages: list[Message]) -> ModelResponse:
        assert messages
        self.calls += 1
        mode = os.environ["SAMURAI_QUEUE_MODEL_MODE"]
        marker = Path(os.environ["SAMURAI_QUEUE_MODEL_MARKER"])
        if mode.startswith("journey_") and self.calls == 1:
            return ModelResponse(
                tool_calls=[
                    {
                        "id": "journey-tool",
                        "type": "function",
                        "function": {
                            "name": "run_company_journey",
                            "arguments": json.dumps(
                                {
                                    "idea": "AI receptionist for dental clinics",
                                    "target_customer": "Indian dental clinics",
                                    "geography": "India",
                                    "budget": "INR 50,000",
                                    "founder_skills": "Python and product",
                                    "goal": "Validate demand in 30 days",
                                    "stage": "brief",
                                }
                            ),
                        },
                    }
                ]
            )
        await asyncio.to_thread(_record_model_invocation, marker)
        if mode == "provider_guard":
            invoke_stream = cast(
                "abc.Callable[..., abc.Iterator[ModelResponse]]",
                Gemini(id="forbidden", api_key="unused").invoke_stream,
            )
            _ = list(invoke_stream(messages))
        if mode == "block":
            await asyncio.to_thread(_wait_for_release, Path(f"{marker}.release"))
        return ModelResponse(content="durable queue process completed")

    @override
    def invoke(self, *_args: Never, **_kwargs: Never) -> ModelResponse:
        return ModelResponse(content="durable queue process completed")

    @override
    async def ainvoke(self, messages: list[Message], **_kwargs: Never) -> ModelResponse:
        return await self._response(messages)

    @override
    def invoke_stream(self, *_args: Never, **_kwargs: Never) -> abc.Iterator[ModelResponse]:
        return iter(())

    @override
    async def ainvoke_stream(
        self,
        messages: list[Message],
        **_kwargs: Never,
    ) -> abc.AsyncIterator[ModelResponse]:
        yield await self._response(messages)

    @override
    def _parse_provider_response(
        self,
        response: ModelResponse,
        **_kwargs: Never,
    ) -> ModelResponse:
        return response

    @override
    def _parse_provider_response_delta(self, response: ModelResponse) -> ModelResponse:
        return response


def _wait_for_release(release: Path) -> None:
    while not release.exists():
        time.sleep(0.05)


def _record_model_invocation(marker: Path) -> None:
    with marker.open("a", encoding="utf-8") as stream:
        _ = stream.write(f"{os.getpid()}\n")


def _forbid_provider_call(*_args: object, **_kwargs: object) -> Never:
    message = "queue process fixtures forbid external provider calls"
    raise InputCheckError(message)


async def _aforbid_provider_call(*_args: object, **_kwargs: object) -> Never:
    return _forbid_provider_call()


async def _aforbid_source_fetch(_urls: Sequence[str]) -> Never:
    message = "queue process fixtures forbid external source fetches"
    raise InputCheckError(message)


async def _reject_parent_run(*_args: object, **_kwargs: object) -> Never:
    message = "exercise permanent parent input rejection"
    raise InputCheckError(message)


@final
class _QueueIntakeModel(Model):
    def __init__(self) -> None:
        super().__init__(id="queue-intake-model", name="Queue intake model", provider="test")
        self.id: str = "queue-intake-model"

    def _response(self) -> ModelResponse:
        return ModelResponse(
            content=json.dumps(
                {
                    "brief": {
                        "idea": "AI receptionist for dental clinics",
                        "target_customer": "Indian dental clinics",
                        "geography": "India",
                        "budget": "INR 50,000",
                        "founder_skills": "Python and product",
                        "goal": "Validate demand in 30 days",
                        "supplied_context": [],
                        "assumptions": [],
                        "open_questions": [],
                        "next_actions": ["Interview five clinic owners."],
                    }
                }
            )
        )

    @override
    def invoke(self, *_args: Never, **_kwargs: Never) -> ModelResponse:
        return self._response()

    @override
    async def ainvoke(self, messages: list[Message], **_kwargs: Never) -> ModelResponse:
        assert messages
        return self._response()

    @override
    def invoke_stream(self, *_args: Never, **_kwargs: Never) -> abc.Iterator[ModelResponse]:
        yield self._response()

    @override
    async def ainvoke_stream(
        self,
        messages: list[Message],
        **_kwargs: Never,
    ) -> abc.AsyncIterator[ModelResponse]:
        assert messages
        yield self._response()

    @override
    def _parse_provider_response(
        self,
        response: ModelResponse,
        **_kwargs: Never,
    ) -> ModelResponse:
        return response

    @override
    def _parse_provider_response_delta(self, response: ModelResponse) -> ModelResponse:
        return response


def _queue_role_catalog(_settings: Settings) -> dict[Role, ConfiguredRole]:
    return {
        role: ConfiguredRole(
            agent_id=f"queue-{role.value}",
            agent=Agent(
                id=f"queue-{role.value}",
                model=_QueueIntakeModel(),
                telemetry=False,
            ),
            capability=ROLE_CAPABILITIES[role],
            instructions="provider-free process fixture",
        )
        for role in Role
    }


@final
class _QueueProcessDb(SamuraiPostgresDb):
    @override
    def accept_company_state(
        self,
        state: CompanyState,
        token: AcceptanceToken,
    ) -> CompanyState:
        accepted = super().accept_company_state(state, token)
        if os.environ["SAMURAI_QUEUE_MODEL_MODE"] == "journey_block_after_commit":
            marker = Path(os.environ["SAMURAI_QUEUE_MODEL_MARKER"])
            _ = marker.write_text(str(os.getpid()), encoding="utf-8")
            _ = threading.Event().wait()
        return accepted


def create_queue_process_app() -> FastAPI:
    """Build the isolated process-test application."""
    settings = Settings.model_validate(
        {
            "database_url": os.environ["SAMURAI_QUEUE_DATABASE_URL"],
            "queue_enabled": True,
            "redis_url": os.environ["SAMURAI_QUEUE_REDIS_URL"],
            "jwt_verification_key": Path(os.environ["SAMURAI_QUEUE_PUBLIC_KEY_FILE"]).read_text(
                encoding="utf-8"
            ),
            "google_api_key": "unused-test-key",
            "os_security_key": "queue-process-test-key-32-bytesx",
        }
    )
    database = _QueueProcessDb(
        id="queue-process",
        db_url=str(settings.database_url),
        db_schema=os.environ["SAMURAI_QUEUE_DB_SCHEMA"],
    )
    catalog_patch = patch.object(
        company_workflow,
        "create_role_catalog",
        new=_queue_role_catalog,
    )
    provider_patch = patch.object(Gemini, "invoke", new=_forbid_provider_call)
    async_provider_patch = patch.object(Gemini, "ainvoke", new=_aforbid_provider_call)
    provider_stream_patch = patch.object(
        Gemini,
        "invoke_stream",
        new=_forbid_provider_call,
    )
    async_provider_stream_patch = patch.object(
        Gemini,
        "ainvoke_stream",
        new=_forbid_provider_call,
    )
    source_fetch_patch = patch.object(
        company_workflow,
        "fetch_sources",
        new=_aforbid_source_fetch,
    )
    run_patch = patch.object(SamuraiParentAgent, "arun", new=_reject_parent_run)
    _ = catalog_patch.start()
    _ = provider_patch.start()
    _ = async_provider_patch.start()
    _ = provider_stream_patch.start()
    _ = async_provider_stream_patch.start()
    _ = source_fetch_patch.start()
    if os.environ["SAMURAI_QUEUE_MODEL_MODE"] == "registration_guard":
        _ = run_patch.start()
    app = create_app(
        db=database,
        settings=settings,
        parent_model_factory=_QueueProcessModel,
    )
    app.state.queue_fixture_patches = (
        catalog_patch,
        provider_patch,
        async_provider_patch,
        provider_stream_patch,
        async_provider_stream_patch,
        source_fetch_patch,
        run_patch,
    )
    return app
