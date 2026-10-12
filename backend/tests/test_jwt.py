from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import jwt
import pytest
from agno.db.sqlite import SqliteDb
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import ValidationError

from samurai.app import create_app
from samurai.config import Settings

if TYPE_CHECKING:
    from pathlib import Path


def test_jwt_mode_rejects_shared_key_and_accepts_signed_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    monkeypatch.setenv("JWT_VERIFICATION_KEY", public_key.decode())
    token = jwt.encode(
        {
            "sub": "local-test-founder",
            "scopes": ["config:read"],
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )
    with TestClient(create_app(db=SqliteDb(db_file=str(tmp_path / "jwt.db")))) as client:
        assert client.get("/agentos/config").status_code == 401
        assert (
            client.get(
                "/agentos/config",
                headers={"Authorization": "Bearer test-key-0000000000000000000000000000"},
            ).status_code
            == 401
        )
        assert (
            client.get(
                "/agentos/config",
                headers={"Authorization": f"Bearer {token}"},
            ).status_code
            == 200
        )


def test_production_settings_reject_missing_jwt_verification_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given production mode with a Gemini key but no public JWT verification key.
    monkeypatch.setenv("SAMURAI_ENVIRONMENT", "production")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-gemini-key")
    monkeypatch.delenv("JWT_VERIFICATION_KEY", raising=False)

    # When settings are loaded at process startup.
    # Then the process refuses the insecure configuration.
    with pytest.raises(ValidationError, match="JWT_VERIFICATION_KEY"):
        _ = Settings.model_validate({})


def test_production_settings_reject_blank_jwt_verification_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given production mode with a Gemini key and a blank JWT verification key.
    monkeypatch.setenv("SAMURAI_ENVIRONMENT", "production")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-gemini-key")
    monkeypatch.setenv("JWT_VERIFICATION_KEY", "  ")

    # When settings are loaded at process startup.
    # Then the process refuses the insecure configuration.
    with pytest.raises(ValidationError, match="JWT_VERIFICATION_KEY"):
        _ = Settings.model_validate({})


def test_production_settings_reject_missing_gemini_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given production mode with a JWT verification key but no Gemini API key.
    monkeypatch.setenv("SAMURAI_ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_VERIFICATION_KEY", "test-public-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "")

    # When settings are loaded at process startup.
    # Then the process refuses the incomplete configuration.
    with pytest.raises(ValidationError, match="GOOGLE_API_KEY"):
        _ = Settings.model_validate({})
