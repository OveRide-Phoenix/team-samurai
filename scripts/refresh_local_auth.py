"""Renew an existing signed local identity without replacing primary AgentOS trust."""

# ruff: noqa: INP001 - standalone Task command, not an importable package.

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from dotenv import dotenv_values, set_key

MIN_RSA_BITS = 2048
LOCAL_SCOPES = ["agents:samurai:read", "agents:samurai:run"]


def _verified_claims(token: str, backend: dict[str, str | None]) -> dict[str, object]:
    claims = None
    for name in ("JWT_VERIFICATION_KEY", "FRONTEND_JWT_VERIFICATION_KEY"):
        key = backend.get(name)
        if not key:
            continue
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                options={
                    "verify_exp": False,
                    "verify_aud": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
            break
        except jwt.InvalidTokenError:
            continue
    if claims is None or not isinstance(claims.get("sub"), str) or not claims["sub"]:
        message = "Existing local token must have a trusted signed identity"
        raise ValueError(message)
    scopes = claims.get("scopes")
    if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
        message = "Local token must have signed scopes"
        raise ValueError(message)
    allowed = set(LOCAL_SCOPES).issubset(scopes) or {"agents:read", "agents:run"}.issubset(scopes)
    if not allowed and "agent_os:admin" not in scopes:
        message = "Existing identity must already be authorized to read and run Samurai"
        raise ValueError(message)
    return claims


def refresh(root: Path) -> None:
    """Renew only a trusted development identity using an owner-only local key."""
    backend_path = root / "backend" / ".env"
    frontend_path = root / "frontend" / ".env.local"
    backend = dotenv_values(backend_path, interpolate=False)
    frontend = dotenv_values(frontend_path, interpolate=False)
    if backend.get("SAMURAI_ENVIRONMENT", "development") != "development":
        message = "Local auth refresh is development-only"
        raise ValueError(message)
    claims = _verified_claims(frontend.get("AGENTOS_USER_TOKEN") or "", backend)
    key_path = root / "frontend" / ".agentos-local.key"
    if key_path.exists():
        private = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        if not isinstance(private, rsa.RSAPrivateKey) or private.key_size < MIN_RSA_BITS:
            message = "Local signing key must be RSA with at least 2048 bits"
            raise ValueError(message)
    else:
        if backend.get("FRONTEND_JWT_VERIFICATION_KEY"):
            message = "Existing frontend trust key has no matching local private key"
            raise ValueError(message)
        private = rsa.generate_private_key(public_exponent=65537, key_size=MIN_RSA_BITS)
    public = (
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
        .strip()
    )
    if (backend.get("FRONTEND_JWT_VERIFICATION_KEY") or "").strip() not in ("", public):
        message = "Existing frontend verification key must be preserved"
        raise ValueError(message)
    now = int(time.time())
    renewed = jwt.encode(
        {**claims, "scopes": LOCAL_SCOPES, "iat": now, "nbf": now, "exp": now + 86400},
        private,
        algorithm="RS256",
    )
    if not key_path.exists():
        with os.fdopen(
            os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
        ) as stream:
            stream.write(
                private.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
    key_path.chmod(0o600)
    set_key(backend_path, "FRONTEND_JWT_VERIFICATION_KEY", public)
    set_key(frontend_path, "AGENTOS_USER_TOKEN", renewed)
    backend_path.chmod(0o600)
    frontend_path.chmod(0o600)


if __name__ == "__main__":
    try:
        refresh(Path(sys.argv[1]).resolve())
    except ValueError, OSError, jwt.PyJWTError:
        message = "Local auth refresh failed; existing identity and trust must be valid."
        raise SystemExit(message) from None
    _ = sys.stdout.write(
        "Local frontend token refreshed for 24 hours; identity, scopes and primary trust "
        "preserved. Restart the backend.\n"
    )
