from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Never, final, override

from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse

from samurai import company_workflow
from samurai.app import create_app
from samurai.config import Settings
from samurai.execution_state import SamuraiPostgresDb
from tests.test_company_workflow import (
    _catalog,  # pyright: ignore[reportPrivateUsage]
    _complete_research,  # pyright: ignore[reportPrivateUsage]
    _supporting_fetch,  # pyright: ignore[reportPrivateUsage]
    _unmapped_research_result,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from collections import abc
    from collections.abc import Mapping

    from agno.models.message import Message
    from fastapi import FastAPI

    from samurai.agents import ConfiguredRole
    from samurai.contracts import CompanyBrief, Role
    from samurai.research import ResearchAgent, ResearchResult


@final
class _ReadinessParentModel(Model):
    def __init__(self) -> None:
        super().__init__(id="readiness-parent", name="Readiness parent", provider="test")
        self.id: str = "readiness-parent"
        self.calls: int = 0

    @staticmethod
    def _requested_stage(messages: list[Message] | None) -> str:
        configured = os.environ["SAMURAI_READINESS_STAGE"]
        if configured != "dynamic" or not messages:
            return configured
        content = messages[-1].content
        prompt = content.lower() if isinstance(content, str) else ""
        if 'stage="brief"' in prompt:
            return "brief"
        if "research our market" in prompt:
            return "research"
        if "create our strategy" in prompt:
            return "strategy"
        if "product and delivery plan" in prompt:
            return "plan"
        return "brief"

    def _response(self, messages: list[Message] | None = None) -> ModelResponse:
        self.calls += 1
        if self.calls > 1:
            return ModelResponse(content="provider-free readiness stage completed")
        arguments = {
            "idea": "AI receptionist for dental clinics",
            "target_customer": "Independent Indian dental clinics",
            "geography": "India",
            "budget": "INR 50,000",
            "founder_skills": "Python and Next.js",
            "goal": "Validate demand in 30 days",
            "stage": self._requested_stage(messages),
        }
        return ModelResponse(
            tool_calls=[
                {
                    "id": "journey-tool",
                    "type": "function",
                    "function": {
                        "name": "run_company_journey",
                        "arguments": json.dumps(arguments),
                    },
                }
            ]
        )

    @override
    def invoke(self, *_args: Never, **_kwargs: Never) -> ModelResponse:
        return self._response()

    @override
    async def ainvoke(self, messages: list[Message], **_kwargs: Never) -> ModelResponse:
        assert messages
        return self._response(messages)

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
        yield self._response(messages)

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


async def _unsupported_research(
    _agent: ResearchAgent,
    _brief: CompanyBrief,
    *,
    max_sources: int = 5,
) -> ResearchResult:
    assert max_sources == 5
    return _unmapped_research_result()


def create_readiness_process_app() -> FastAPI:
    """Build the isolated staged-journey process application."""
    catalog, _models = _catalog()

    def role_catalog(_settings: Settings) -> Mapping[Role, ConfiguredRole]:
        return catalog

    company_workflow.create_role_catalog = role_catalog  # pyright: ignore[reportPrivateLocalImportUsage]
    company_workflow.fetch_sources = _supporting_fetch  # pyright: ignore[reportPrivateLocalImportUsage]
    company_workflow.run_research = (  # pyright: ignore[reportPrivateLocalImportUsage]
        _unsupported_research
        if os.environ["SAMURAI_READINESS_RESEARCH_MODE"] == "unsupported"
        else _complete_research
    )
    settings = Settings.model_validate(
        {
            "database_url": os.environ["SAMURAI_QUEUE_DATABASE_URL"],
            "queue_enabled": True,
            "redis_url": os.environ["SAMURAI_QUEUE_REDIS_URL"],
            "jwt_verification_key": Path(os.environ["SAMURAI_QUEUE_PUBLIC_KEY_FILE"]).read_text(
                encoding="utf-8"
            ),
            "google_api_key": "unused-test-key",
            "os_security_key": "x" * 32,
            "samurai_environment": os.environ.get(
                "SAMURAI_READINESS_ENVIRONMENT",
                "development",
            ),
        }
    )
    database = SamuraiPostgresDb(
        id="readiness-process",
        db_url=str(settings.database_url),
        db_schema=os.environ["SAMURAI_QUEUE_DB_SCHEMA"],
    )
    return create_app(
        db=database,
        settings=settings,
        parent_model_factory=_ReadinessParentModel,
    )


def create_readiness_health_app() -> FastAPI:
    """Build the provider-free health fixture without shared service state."""
    settings = Settings.model_validate(
        {
            "database_url": "postgresql://unused:unused@127.0.0.1:1/samurai_task10_health",
            "queue_enabled": False,
            "jwt_verification_key": Path(os.environ["SAMURAI_QUEUE_PUBLIC_KEY_FILE"]).read_text(
                encoding="utf-8"
            ),
            "google_api_key": "unused-test-key",
            "os_security_key": "x" * 32,
        }
    )
    return create_app(
        db=SqliteDb(db_file=os.environ["SAMURAI_READINESS_HEALTH_DB"]),
        settings=settings,
        parent_model_factory=_ReadinessParentModel,
    )
