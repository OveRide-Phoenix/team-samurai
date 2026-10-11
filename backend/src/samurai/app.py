"""Application factory for the local AgentOS bootstrap."""

from typing import TYPE_CHECKING, ClassVar

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.google import Gemini
from agno.os import AgentOS
from agno.os.settings import AgnoAPISettings
from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

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


def create_app() -> FastAPI:
    """Build a local secured runtime; registration does not invoke Gemini."""
    settings = Settings.model_validate({})
    db = PostgresDb(id="samurai", db_url=str(settings.database_url))
    api_key = settings.google_api_key.get_secret_value()
    return AgentOS(
        id="samurai",
        name="AI Idea to Company",
        db=db,
        agents=[
            Agent(
                id="researcher",
                name="Researcher",
                model=Gemini(id=settings.gemini_model, api_key=api_key),
                db=db,
                instructions=[
                    "Separate supplied evidence from assumptions.",
                    "Search and verification tools are not connected yet;",
                    "do not claim live research or invent citations.",
                ],
                telemetry=False,
            ),
        ]
        if api_key
        else [],
        settings=AgnoAPISettings(os_security_key=settings.os_security_key.get_secret_value()),
        cors_allowed_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
        auto_provision_dbs=False,
        telemetry=False,
    ).get_app()
