"""Validated runtime configuration and Gemini construction."""

from typing import ClassVar

from agno.models.google import Gemini
from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Parse service credentials and bounded model configuration."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        extra="forbid",
        hide_input_in_errors=True,
    )

    os_security_key: SecretStr = Field(min_length=32)
    database_url: PostgresDsn
    google_api_key: SecretStr = SecretStr("")
    gemini_model: str = Field(default="gemini-3.5-flash-lite", min_length=1)
    gemini_max_input_chars: int = Field(default=20_000, gt=0)
    gemini_max_output_tokens: int = Field(default=4096, gt=0)
    gemini_timeout_seconds: float = Field(default=60, gt=0)
    agent_tool_call_limit: int = Field(default=4, gt=0, le=16)
    jwt_verification_key: str | None = None


def create_model(settings: Settings) -> Gemini:
    """Return a fresh Gemini model for one agent or workflow use."""
    return Gemini(
        id=settings.gemini_model,
        api_key=settings.google_api_key.get_secret_value(),
        max_output_tokens=settings.gemini_max_output_tokens,
        timeout=settings.gemini_timeout_seconds,
    )
