from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import jwt
import pytest
from agno.db.sqlite import SqliteDb
from agno.run.agent import RunOutput
from agno.session.agent import AgentSession
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


@pytest.mark.parametrize("signer", ["agno", "frontend"])
def test_both_signers_preserve_owner_isolation_and_minimal_scopes(
    signer: str,
    tmp_path: Path,
) -> None:
    # Given two independent real RS256 keys and an owner-bound stored run.
    keys = {
        name: rsa.generate_private_key(public_exponent=65537, key_size=2048)
        for name in ("agno", "frontend")
    }
    public_keys = {
        name: key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
        for name, key in keys.items()
    }
    settings = Settings.model_validate(
        {
            "jwt_verification_key": public_keys["agno"],
            "frontend_jwt_verification_key": public_keys["frontend"],
            "google_api_key": "unused-test-key",
        }
    )
    db = SqliteDb(db_file=str(tmp_path / "dual-trust.db"))
    _ = db.upsert_session(
        AgentSession(
            session_id="owner-session",
            agent_id="samurai",
            user_id="iap:owner",
        )
    )
    db.upsert_run(
        RunOutput(
            run_id="owner-run",
            agent_id="samurai",
            session_id="owner-session",
            user_id="iap:owner",
            content="owner-only content",
        ),
        session_id="owner-session",
        user_id="iap:owner",
    )
    tokens = {
        subject: jwt.encode(
            {
                **({"iss": "samurai-frontend", "aud": "samurai"} if signer == "frontend" else {}),
                "sub": subject,
                "scopes": ["agents:samurai:read", "agents:samurai:run"],
                "exp": datetime.now(UTC) + timedelta(minutes=5),
            },
            keys[signer],
            algorithm="RS256",
        )
        for subject in ("iap:owner", "iap:other")
    }
    # When authenticated users request the same run with the minimal frontend scopes.
    with TestClient(create_app(db=db, settings=settings)) as client:
        owner = {"Authorization": f"Bearer {tokens['iap:owner']}"}
        other = {"Authorization": f"Bearer {tokens['iap:other']}"}
        path = "/agentos/agents/samurai/runs/owner-run"
        params = {"session_id": "owner-session"}
        read = client.get(path, params=params, headers=owner)
        other_read = client.get(path, params=params, headers=other)
        other_cancel = client.post(f"{path}/cancel", params=params, headers=other)
        cancel = client.post(f"{path}/cancel", params=params, headers=owner)
        admin = client.get("/agentos/config", headers=owner)
        # Missing message reaches route validation, proving run scope authorization.
        run = client.post("/agentos/agents/samurai/runs", headers=owner)
    # Then both signers have the same scoped access without gaining admin or other owners.
    assert read.status_code == 200
    assert "owner-only content" in read.text
    assert other_read.status_code == other_cancel.status_code == 404
    assert cancel.status_code == 200
    assert admin.status_code == 403
    assert run.status_code == 422


@pytest.mark.parametrize("invalid_kind", ["expired", "untrusted"])
def test_frontend_invalid_token_is_rejected(invalid_kind: str, tmp_path: Path) -> None:
    # Given an expired trusted token or a token signed by an unknown key.
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    settings = Settings.model_validate(
        {
            "jwt_verification_key": public_key,
            "frontend_jwt_verification_key": public_key,
        }
    )
    signing_key = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if invalid_kind == "untrusted"
        else key
    )
    token = jwt.encode(
        {
            "sub": "iap:owner",
            "scopes": ["config:read"],
            "exp": datetime.now(UTC) + timedelta(minutes=-5 if invalid_kind == "expired" else 5),
        },
        signing_key,
        algorithm="RS256",
    )
    # When the invalid credential reaches the actual AgentOS middleware.
    with TestClient(
        create_app(db=SqliteDb(db_file=str(tmp_path / "invalid.db")), settings=settings)
    ) as client:
        response = client.get("/agentos/config", headers={"Authorization": f"Bearer {token}"})
    # Then it is rejected before accessing the route.
    assert response.status_code == 401
