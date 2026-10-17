"""Local token renewal preserves signed identity, scopes and existing trust."""

from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from dotenv import dotenv_values, set_key

SCRIPT = Path(__file__).parents[2] / "scripts" / "refresh_local_auth.py"


def _setup(root: Path, scopes: list[str] | None = None) -> str:
    (root / "backend").mkdir()
    (root / "frontend").mkdir()
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
        .strip()
    )
    backend = root / "backend" / ".env"
    _ = backend.write_text("GOOGLE_API_KEY='unchanged-test-value'\n")
    _ = set_key(backend, "JWT_VERIFICATION_KEY", public)
    token = jwt.encode(
        {
            "sub": "local-founder",
            "exp": 1,
            "scopes": scopes
            if scopes is not None
            else ["agents:samurai:read", "agents:samurai:run"],
        },
        private,
        algorithm="RS256",
    )
    _ = set_key(root / "frontend" / ".env.local", "AGENTOS_USER_TOKEN", token)
    return public


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed interpreter and repository script.
        [sys.executable, str(SCRIPT), str(root)], capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize(
    "scopes", [["agents:samurai:read", "agents:samurai:run"], ["agent_os:admin", "org:write"]]
)
def test_refresh_retains_identity_primary_trust_and_key_on_repeated_runs(
    tmp_path: Path, scopes: list[str]
) -> None:
    primary = _setup(tmp_path, scopes)
    assert _run(tmp_path).returncode == 0
    key_path = tmp_path / "frontend" / ".agentos-local.key"
    private = key_path.read_bytes()
    assert _run(tmp_path).returncode == 0
    assert key_path.read_bytes() == private
    backend = dotenv_values(tmp_path / "backend" / ".env", interpolate=False)
    frontend = dotenv_values(tmp_path / "frontend" / ".env.local", interpolate=False)
    assert backend["JWT_VERIFICATION_KEY"] == primary
    assert backend["GOOGLE_API_KEY"] == "unchanged-test-value"
    token = frontend["AGENTOS_USER_TOKEN"]
    public = backend["FRONTEND_JWT_VERIFICATION_KEY"]
    assert isinstance(token, str)
    assert isinstance(public, str)
    claims = jwt.decode(token, public, algorithms=["RS256"])
    assert claims["sub"] == "local-founder"
    assert claims["scopes"] == ["agents:samurai:read", "agents:samurai:run"]
    assert claims["exp"] - claims["iat"] == 86400
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "frontend" / ".env.local").stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "failure", ["production", "foreign_trust", "bad_signature", "missing_run_permission"]
)
def test_refresh_refuses_invalid_identity_or_overwriting_existing_trust(
    tmp_path: Path, failure: str
) -> None:
    primary = _setup(
        tmp_path, ["agents:samurai:read"] if failure == "missing_run_permission" else None
    )
    backend = tmp_path / "backend" / ".env"
    frontend = tmp_path / "frontend" / ".env.local"
    if failure == "production":
        _ = set_key(backend, "SAMURAI_ENVIRONMENT", "production")
    elif failure == "foreign_trust":
        _ = set_key(backend, "FRONTEND_JWT_VERIFICATION_KEY", primary)
    elif failure == "bad_signature":
        _ = set_key(frontend, "AGENTOS_USER_TOKEN", "invalid-token")
    before = (backend.read_bytes(), frontend.read_bytes())
    result = _run(tmp_path)
    assert result.returncode != 0
    assert (backend.read_bytes(), frontend.read_bytes()) == before
    assert not (tmp_path / "frontend" / ".agentos-local.key").exists()
    assert "unchanged-test-value" not in result.stdout + result.stderr
