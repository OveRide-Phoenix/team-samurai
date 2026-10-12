"""Validated runtime configuration and Gemini construction."""

from __future__ import annotations

from math import ceil
from typing import TYPE_CHECKING, ClassVar, Final, Literal, Self

from agno.job_queue import QueueConfig, RedisCoordination
from agno.models.google import Gemini
from pydantic import Field, PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from agno.db.base import BaseDb

PRODUCTION_JWT_KEY_REQUIRED: Final = "JWT_VERIFICATION_KEY is required in production"
PRODUCTION_GEMINI_KEY_REQUIRED: Final = "GOOGLE_API_KEY is required in production"
QUEUE_REDIS_REQUIRED: Final = "REDIS_URL is required when the durable queue is enabled"


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
    gemini_model: str = Field(default="gemini-3.5-flash-lite", min_length=1)
    gemini_max_input_chars: int = Field(default=20_000, gt=0)
    gemini_max_output_tokens: int = Field(default=4096, gt=0)
    gemini_timeout_seconds: float = Field(default=60, gt=0)
    agent_tool_call_limit: int = Field(default=4, gt=0, le=16)
    queue_enabled: bool = False
    redis_url: SecretStr | None = None
    jwt_verification_key: str | None = None
    frontend_jwt_verification_key: str | None = None

    @model_validator(mode="after")
    def _require_production_credentials(self) -> Self:
        if self.queue_enabled and (
            self.redis_url is None or not self.redis_url.get_secret_value().strip()
        ):
            raise ValueError(QUEUE_REDIS_REQUIRED)
        match self.samurai_environment:
            case "development":
                return self
            case "production":
                if not self.jwt_verification_key or not self.jwt_verification_key.strip():
                    raise ValueError(PRODUCTION_JWT_KEY_REQUIRED)
                if not self.google_api_key.get_secret_value().strip():
                    raise ValueError(PRODUCTION_GEMINI_KEY_REQUIRED)
                return self


def create_queue_config(settings: Settings, store: BaseDb) -> QueueConfig | None:
    """Build the bounded native queue configuration when enabled."""
    if not settings.queue_enabled:
        return None
    if settings.redis_url is None:
        raise ValueError(QUEUE_REDIS_REQUIRED)
    environment = settings.samurai_environment
    return QueueConfig(
        max_concurrency=2,
        redis=RedisCoordination(
            url=settings.redis_url.get_secret_value(),
            key_prefix=f"samurai:{environment}:v1",
        ),
        durable=True,
        db=store,
        max_queue_depth=10,
        max_attempts=2,
        retry_delay_seconds=30,
        timeout_seconds=ceil(settings.gemini_timeout_seconds * 7 + 60),
        deployment_id=f"samurai-{environment}-v1",
        lock_grace_seconds=60,
        poll_interval=1,
        retention_seconds=86_400,
        stop_timeout_seconds=5,
    )


def create_model(settings: Settings) -> Gemini:
    """Return a fresh Gemini model for one agent or workflow use."""
    return Gemini(
        id=settings.gemini_model,
        api_key=settings.google_api_key.get_secret_value(),
        max_output_tokens=settings.gemini_max_output_tokens,
        timeout=settings.gemini_timeout_seconds,
    )
