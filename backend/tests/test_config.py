from typing import TYPE_CHECKING, cast

import pytest
from agno.job_queue import RedisCoordination
from pydantic import ValidationError
from sqlalchemy import create_engine

from samurai.config import GCS_STORAGE_DISABLED, Settings, create_queue_config

if TYPE_CHECKING:
    from agno.db.base import BaseDb


def test_cloud_sql_socket_url_passes_host_to_psycopg() -> None:
    # Given a Cloud Run Cloud SQL Unix-socket URL accepted by the settings boundary.
    socket_path = "/cloudsql/project:asia-south1:samurai-postgres"
    settings = Settings.model_validate(
        {
            "database_url": (
                f"postgresql+psycopg://samurai:password@localhost/samurai?host={socket_path}"
            )
        }
    )

    # When SQLAlchemy builds psycopg's connection arguments without connecting.
    engine = create_engine(str(settings.database_url))
    _, connect_kwargs = engine.dialect.create_connect_args(engine.url)

    # Then psycopg receives the Unix socket directory as its host.
    assert connect_kwargs["host"] == socket_path


def test_frontend_key_does_not_replace_required_agno_key() -> None:
    # Given production configured only with the optional frontend verification key.
    # When settings are validated, then the original Agno key remains mandatory.
    with pytest.raises(ValidationError, match="JWT_VERIFICATION_KEY is required"):
        _ = Settings.model_validate(
            {
                "samurai_environment": "production",
                "google_api_key": "unused-test-key",
                "jwt_verification_key": None,
                "frontend_jwt_verification_key": "frontend-public-key",
            }
        )


def test_frontend_verification_key_loads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given the BFF public key supplied through the production environment contract.
    monkeypatch.setenv("FRONTEND_JWT_VERIFICATION_KEY", "frontend-public-key")
    # When settings parse the environment.
    settings = Settings.model_validate({})
    # Then it is available separately from the existing Agno key.
    assert settings.frontend_jwt_verification_key == "frontend-public-key"
    assert settings.jwt_verification_key is None


def test_queue_config_uses_the_bounded_native_contract() -> None:
    settings = Settings.model_validate(
        {
            "queue_enabled": True,
            "redis_url": "redis://127.0.0.1:6379/0",
        }
    )
    store = cast("BaseDb", object())

    queue = create_queue_config(settings, store)

    assert queue is not None
    assert queue.db is store
    assert queue.durable is True
    assert queue.max_concurrency == 2
    assert queue.max_queue_depth == 10
    assert queue.max_attempts == 2
    assert queue.retry_delay_seconds == 30
    assert queue.timeout_seconds == 480
    assert queue.deployment_id == "samurai-development-v1"
    assert queue.lock_grace_seconds == 60
    assert queue.poll_interval == 1
    assert queue.retention_seconds == 86_400
    assert queue.stop_timeout_seconds == 5
    assert isinstance(queue.redis, RedisCoordination)
    assert queue.redis.key_prefix == "samurai:development:v1"


def test_enabled_queue_requires_redis_coordination() -> None:
    with pytest.raises(ValidationError, match="REDIS_URL is required"):
        _ = Settings.model_validate({"queue_enabled": True})


def test_gcs_storage_fails_during_configuration_without_adapter_import() -> None:
    with pytest.raises(ValidationError, match=GCS_STORAGE_DISABLED):
        _ = Settings.model_validate({"storage_backend": "gcs"})


def test_production_guest_access_requires_durable_execution() -> None:
    with pytest.raises(ValidationError, match="production guest access requires the durable queue"):
        _ = Settings.model_validate(
            {
                "samurai_environment": "production",
                "guest_access_enabled": True,
                "jwt_verification_key": "test-key",
                "google_api_key": "unused-test-key",
            }
        )
