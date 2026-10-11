"""Application factory for the local AgentOS bootstrap."""

from typing import TYPE_CHECKING, ClassVar

from agno.db.postgres import PostgresDb
from agno.models.google import Gemini
from agno.os import AgentOS
from agno.os.authz import Authorization
from agno.os.config import AgentOSConfig, ChatConfig
from agno.os.settings import AgnoAPISettings
from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from samurai.foundation import STARTER_PROMPTS, WORKFLOW_ID, create_foundation

if TYPE_CHECKING:
    from fastapi import FastAPI


class Settings(BaseSettings):
    """Parse required service credentials and optional Gemini configuration."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        extra="forbid",
        hide_input_in_errors=True,
    )

    os_security_key: SecretStr = Field(min_length=32)
    database_url: PostgresDsn
    google_api_key: SecretStr = SecretStr("")
    gemini_model: str = Field(default="gemini-3.8-flash", min_length=1)
    jwt_verification_key: str | None = None


def create_app() -> FastAPI:
    """Build a local secured runtime; registration does not invoke Gemini."""
    settings = Settings.model_validate({})
    db = PostgresDb(id="samurai", db_url=str(settings.database_url))
    api_key = settings.google_api_key.get_secret_value()
    return AgentOS(
        id="samurai",
        name="AI Idea to Company",
        db=db,
        workflows=[
            create_foundation(
                db,
                Gemini(
                    id=settings.gemini_model,
                    api_key=api_key,
                    max_output_tokens=4096,
                    timeout=60,
                ),
            ),
        ]
        if api_key
        else [],
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
