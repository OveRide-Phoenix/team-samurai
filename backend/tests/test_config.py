import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine

from samurai.config import Settings


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
