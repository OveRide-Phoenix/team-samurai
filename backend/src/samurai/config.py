"""Validated runtime configuration and Gemini construction."""

from typing import ClassVar, Final, Literal, Self

from agno.models.google import Gemini
from pydantic import Field, PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCTION_JWT_KEY_REQUIRED: Final = "JWT_VERIFICATION_KEY is required in production"
PRODUCTION_GEMINI_KEY_REQUIRED: Final = "GOOGLE_API_KEY is required in production"


class Settings(BaseSettings):
    """Parse service credentials and bounded model configuration."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        extra="forbid",
        hide_input_in_errors=True,
    )

    os_security_key: SecretStr = Field(min_length=32)
    database_url: PostgresDsn
    samurai_environment: Literal["development", "production"] = "development"
    google_api_key: SecretStr = SecretStr("")
    gemini_model: str = Field(default="gemini-3.8-flash", min_length=1)
    gemini_max_input_chars: int = Field(default=20_000, gt=0)
    gemini_max_output_tokens: int = Field(default=4096, gt=0)
    gemini_timeout_seconds: float = Field(default=60, gt=0)
    agent_tool_call_limit: int = Field(default=4, gt=0, le=16)
    jwt_verification_key: str | None = None

    @model_validator(mode="after")
    def _require_production_credentials(self) -> Self:
        match self.samurai_environment:
            case "development":
                return self
            case "production":
                if not self.jwt_verification_key or not self.jwt_verification_key.strip():
                    raise ValueError(PRODUCTION_JWT_KEY_REQUIRED)
                if not self.google_api_key.get_secret_value().strip():
                    raise ValueError(PRODUCTION_GEMINI_KEY_REQUIRED)
                return self


def create_model(settings: Settings) -> Gemini:
    """Return a fresh Gemini model for one agent or workflow use."""
    return Gemini(
        id=settings.gemini_model,
        api_key=settings.google_api_key.get_secret_value(),
        max_output_tokens=settings.gemini_max_output_tokens,
        timeout=settings.gemini_timeout_seconds,
    )
