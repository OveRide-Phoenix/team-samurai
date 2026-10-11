from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import jwt
from agno.db.sqlite import SqliteDb
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from samurai.app import create_app

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


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
