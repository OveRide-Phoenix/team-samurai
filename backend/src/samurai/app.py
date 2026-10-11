"""Application factory for the local AgentOS bootstrap."""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from agno.db.postgres import PostgresDb
from agno.os import AgentOS
from agno.os.authz import Authorization
from agno.os.config import AgentOSConfig, ChatConfig
from agno.os.settings import AgnoAPISettings
from agno.workflow import WorkflowFactory
from fastapi import FastAPI

from samurai.config import Settings
from samurai.foundation import (
    STARTER_PROMPTS,
    WORKFLOW_DESCRIPTION,
    WORKFLOW_ID,
    WORKFLOW_NAME,
    create_foundation,
)

__all__ = ["Settings"]

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from agno.factory import RequestContext
    from agno.workflow import Workflow


def create_foundation_workflow(db: PostgresDb, settings: Settings) -> Workflow:
    """Build one request-scoped workflow with a fresh Gemini model."""
    return create_foundation(db, settings)


def _create_foundation_factory(db: PostgresDb, settings: Settings) -> WorkflowFactory:
    def build_foundation(_context: RequestContext) -> Workflow:
        return create_foundation_workflow(db, settings)

    return WorkflowFactory(
        id=WORKFLOW_ID,
        name=WORKFLOW_NAME,
        description=WORKFLOW_DESCRIPTION,
        db=db,
        factory=build_foundation,
    )


def create_app() -> FastAPI:
    """Build a local secured runtime; registration does not invoke Gemini."""
    settings = Settings.model_validate({})
    db = PostgresDb(id="samurai", db_url=str(settings.database_url))
    api_key = settings.google_api_key.get_secret_value()

    runtime = AgentOS(
        id="samurai",
        name="AI Idea to Company",
        db=db,
        workflows=[_create_foundation_factory(db, settings)] if api_key else [],
        config=AgentOSConfig(chat=ChatConfig(quick_prompts={WORKFLOW_ID: STARTER_PROMPTS})),
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
        tracing=True,
        telemetry=False,
    ).get_app()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        # Mounted apps do not receive startup/shutdown automatically.
        async with runtime.router.lifespan_context(runtime):
            yield

    app = FastAPI(title="Samurai API", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.mount("/agentos", runtime, name="agentos")
    return app
