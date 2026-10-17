from __future__ import annotations

import asyncio
import json
import os
import re
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

from samurai import company_workflow, parent
from samurai.agents import ROLE_CAPABILITIES, ConfiguredRole
from samurai.app import create_app
from samurai.company_store import CompanyStore
from samurai.config import Settings
from samurai.contracts import (
    AnalysisDraft,
    BuilderDraftArtifact,
    CompanyState,
    MarketingDraftArtifact,
    Role,
    SalesDraftArtifact,
)
from samurai.execution_state import AcceptanceToken, SamuraiPostgresDb
from samurai.parent import SamuraiParentAgent
from samurai.parent import _child_state as _native_child_state  # pyright: ignore[reportPrivateUsage]
from samurai.schema import FounderPlatformMigrator

# Reuse accepted native-workflow fixtures rather than duplicating evidence construction.
from tests.test_company_workflow import (
    _catalog,  # pyright: ignore[reportPrivateUsage]
    _complete_request,  # pyright: ignore[reportPrivateUsage]
    _complete_research,  # pyright: ignore[reportPrivateUsage]
    _supporting_fetch,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from collections import abc
    from collections.abc import Sequence

    from agno.db.base import BaseDb
    from agno.models.message import Message
    from agno.run import RunContext
    from fastapi import FastAPI


def _traced_child_state(database: BaseDb, context: RunContext) -> tuple[str, CompanyState | None]:
    try:
        return _native_child_state(database, context)
    except parent.ParentContextError as error:
        state = context.session_state or {}
        access = (
            CompanyStore(database.db_engine, schema=database.db_schema).read_for_actor(
                context.user_id or "", context.session_id or ""
            )
            if isinstance(database, SamuraiPostgresDb)
            else None
        )
        proof = {
            "issue": error.issue,
            "run_id": context.run_id,
            "supplied_binding": {
                key: state[key] for key in parent.PARENT_BINDING_KEYS if key in state
            },
            "unexpected_keys": sorted(
                state.keys() - parent.PARENT_BINDING_KEYS - parent.AGNO_SESSION_KEYS
            ),
            "framework_matches": {
                key: state.get(key, expected) == expected
                for key, expected in {
                    "current_user_id": context.user_id,
                    "current_session_id": context.session_id,
                    "current_run_id": context.run_id,
                }.items()
            },
            "canonical_binding": None
            if access is None
            else {
                "child_session_id": access.child_session_id,
                "company_id": str(access.state.context.company_id),
                "current_revision": access.state.current_revision,
            },
        }
        marker = Path(os.environ["SAMURAI_QUEUE_MODEL_MARKER"])
        _ = marker.with_suffix(".binding.json").write_text(
            json.dumps(proof, default=str), encoding="utf-8"
        )
        raise


def _browser_request(message: str) -> dict[str, object] | None:
    stage = re.search(r'stage=["\']?(brief|research|strategy|plan|verify)', message)
    kind = re.search(r"kind=(sales|builder|marketer)", message)
    if stage:
        arguments = _complete_request().model_dump(
            include={
                "idea",
                "target_customer",
                "geography",
                "budget",
                "founder_skills",
                "goal",
            }
        )
        if stage[1] == "brief" and "\n{" in message:
            arguments.update(
                cast("dict[str, object]", json.loads(message[message.index("\n{") + 1 :]))
            )
        budget = re.search(r"(?:new|updated) budget:\s*(INR\s*\d+)", message, re.IGNORECASE)
        if budget:
            arguments["budget"] = budget[1]
        request: dict[str, object] = {
            "tool": "run_company_journey",
            "arguments": {**arguments, "stage": stage[1]},
        }
    elif message.startswith("Please review this result I recorded."):
        fields = dict(line.split(": ", 1) for line in message.splitlines() if ": " in line)
        value, _, unit = fields["Result"].partition(" ")
        request = {
            "tool": "analyze_metrics",
            "arguments": {
                "measurements": [
                    {
                        "name": fields["Measurement"],
                        "value": float(value),
                        "unit": unit,
                        "source_label": fields["Source"],
                        "window_start": fields["From"].split()[0] + "T00:00:00Z",
                        "window_end": fields["Until"].split()[0] + "T00:00:00Z",
                        "collected_at": fields["Recorded at"],
                    }
                ],
            },
        }
    elif kind:
        request = {
            "tool": "create_launch_drafts",
            "arguments": {"kind": kind[1], "action": "draft"},
        }
    else:
        return None
    return request


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
        if mode == "stream_failure":
            await asyncio.to_thread(_record_model_invocation, marker)
            message = "provider-free-stream-failure"
            raise TimeoutError(message)
        if mode in {"journey_full", "journey_browser"} and self.calls == 1:
            message = next(
                message.get_content_string()
                for message in reversed(messages)
                if message.role == "user"
            )
            if mode == "journey_browser":
                request = _browser_request(message)
                if request is None:
                    return ModelResponse(
                        content="Provider-free fixture: choose a company action to continue."
                    )
            else:
                request = cast("dict[str, object]", json.loads(message))
            return ModelResponse(
                tool_calls=[
                    {
                        "id": "full-journey-tool",
                        "type": "function",
                        "function": {
                            "name": request["tool"],
                            "arguments": json.dumps(request["arguments"]),
                        },
                    }
                ]
            )
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
    def __init__(self, payload: str | None = None) -> None:
        super().__init__(id="queue-intake-model", name="Queue intake model", provider="test")
        self.id: str = "queue-intake-model"
        self.payload: str | None = payload

    def _response(self) -> ModelResponse:
        if self.payload is not None:
            return ModelResponse(content=self.payload)
        return ModelResponse(
            content=json.dumps(
                {
                    "founder_truth": {},
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
                    },
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
            "storage_root": os.environ.get("SAMURAI_QUEUE_STORAGE_ROOT", ".samurai-storage"),
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
    if os.environ.get("SAMURAI_QUEUE_CANONICAL") == "1":
        database.ensure_work_intents_table()
        _ = FounderPlatformMigrator(database.db_engine, schema=database.db_schema).apply()
    full_journey = os.environ["SAMURAI_QUEUE_MODEL_MODE"] in {"journey_full", "journey_browser"}
    if full_journey:
        _ = patch.object(parent, "_child_state", new=_traced_child_state).start()
        # Reuse the native workflow's deterministic evidence fixtures, never public fetches.

        def full_catalog(_settings: Settings) -> dict[Role, ConfiguredRole]:
            catalog, _ = _catalog()
            drafts = {
                Role.ANALYST: AnalysisDraft(
                    findings=("Founder reports twelve qualified leads.",),
                    recommendations=("Review the measured funnel with the founder.",),
                ),
                Role.SALES: SalesDraftArtifact(
                    prospect_criteria=("Independent clinic with missed-call pain",),
                    outreach=("Review a discovery conversation draft.",),
                    scripts=("Ask about current call handling.",),
                    objection_handling=("Founder controls the pilot.",),
                ),
                Role.BUILDER: BuilderDraftArtifact(
                    architecture=("Company-scoped API",),
                    database_schema=("Company records",),
                    apis=("GET /company",),
                    user_interface=("Founder review",),
                    deployment_configuration=("Draft only",),
                ),
                Role.MARKETER: MarketingDraftArtifact(
                    landing_page="Review your missed-call workflow.",
                    ads=("Review draft",),
                    social_posts=("Review draft",),
                    emails=("Review draft",),
                ),
            }
            return {
                **catalog,
                **{
                    role: ConfiguredRole(
                        agent_id=f"queue-{role.value}",
                        agent=Agent(
                            id=f"queue-{role.value}",
                            model=_QueueIntakeModel(payload.model_dump_json()),
                            output_schema=type(payload),
                            telemetry=False,
                        ),
                        capability=ROLE_CAPABILITIES[role],
                        instructions="provider-free draft fixture",
                    )
                    for role, payload in drafts.items()
                },
            }

        _ = patch.object(company_workflow, "run_research", new=_complete_research).start()
        _ = patch.object(parent, "create_role_catalog", new=full_catalog).start()
    else:
        full_catalog = _queue_role_catalog
    catalog_patch = patch.object(
        company_workflow,
        "create_role_catalog",
        new=full_catalog,
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
        new=_supporting_fetch if full_journey else _aforbid_source_fetch,
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
