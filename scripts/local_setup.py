# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = ["python-dotenv==1.2.4"]
# ///
# ─── How to run ───
# python3 scripts/local_setup.py init-backend /path/to/repository

"""Create and validate private local developer configuration."""

from __future__ import annotations

import os
import secrets
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, override
from urllib.parse import quote, unquote, urlsplit

from dotenv import dotenv_values

if TYPE_CHECKING:
    from collections.abc import Sequence


MIN_SERVICE_KEY_CHARS: Final = 32
MIN_PORT: Final = 1
MAX_PORT: Final = 65_535
REDIS_LABEL: Final = "redis"


@dataclass(frozen=True, slots=True)
class SetupError(Exception):
    """Describe one safe, user-actionable setup failure."""

    message: str

    @override
    def __str__(self) -> str:
        """Return the sanitized diagnostic."""
        return self.message


def _missing_root_error(raw_path: str) -> SetupError:
    return SetupError(f"repository root does not exist: {raw_path}")


def _missing_environment_error(relative_path: str) -> SetupError:
    return SetupError(f"missing local environment file: {relative_path}")


def _missing_key_error(relative_path: str, key: str) -> SetupError:
    return SetupError(f"{relative_path} is missing required key {key}")


def _invalid_template_error(key: str) -> SetupError:
    return SetupError(f"environment template must define {key} exactly once")


def _invalid_port_error(label: str) -> SetupError:
    return SetupError(f"invalid {label} port")


def _occupied_port_error(label: str, port: int) -> SetupError:
    return SetupError(f"{label} port {port} is already in use")


DATABASE_PASSWORD_MISSING: Final = SetupError("backend/.env DATABASE_URL has no password")
SHORT_SERVICE_KEY: Final = SetupError(
    "backend/.env OS_SECURITY_KEY must contain at least 32 characters"
)
DATABASE_MISMATCH: Final = SetupError("root and backend database credentials do not match")
QUEUE_REDIS_MISSING: Final = SetupError(
    "backend/.env REDIS_URL is required when QUEUE_ENABLED=true"
)
USAGE_ERROR: Final = SetupError("usage: local_setup.py COMMAND ARGUMENTS")


def _repository(raw_path: str) -> Path:
    root = Path(raw_path).resolve()
    if not root.is_dir():
        raise _missing_root_error(raw_path)
    return root


def _environment(path: Path) -> dict[str, str]:
    if not path.is_file():
        relative_path = str(path.relative_to(path.parents[1]))
        raise _missing_environment_error(relative_path)
    return {
        key: value
        for key, value in dotenv_values(path, interpolate=False).items()
        if value is not None
    }


def _required(values: dict[str, str], key: str, relative_path: str) -> str:
    value = values.get(key, "")
    if not value:
        raise _missing_key_error(relative_path, key)
    return value


def _database_password(database_url: str) -> str:
    password = urlsplit(database_url).password
    if password is None:
        raise DATABASE_PASSWORD_MISSING
    return unquote(password)


def _local_redis_url(root_values: dict[str, str]) -> str | None:
    raw_port = root_values.get("REDIS_PORT")
    if raw_port is None:
        return None
    try:
        port = int(raw_port)
    except ValueError as error:
        raise _invalid_port_error(REDIS_LABEL) from error
    if not MIN_PORT <= port <= MAX_PORT:
        raise _invalid_port_error(REDIS_LABEL)
    return f"redis://127.0.0.1:{port}/0"


def _replace_assignment(template: str, key: str, value: str) -> str:
    prefix = f"{key}="
    lines = template.splitlines()
    replacements = sum(line.startswith(prefix) for line in lines)
    if replacements != 1:
        raise _invalid_template_error(key)
    rendered = [f"{prefix}{value}" if line.startswith(prefix) else line for line in lines]
    return "\n".join(rendered) + "\n"


def _create_private(path: Path, content: str) -> bool:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        _ = stream.write(content)
    return True


def _validate_backend(root: Path) -> None:
    root_values = _environment(root / ".env")
    backend_values = _environment(root / "backend" / ".env")
    root_password = _required(root_values, "POSTGRES_PASSWORD", ".env")
    database_url = _required(backend_values, "DATABASE_URL", "backend/.env")
    service_key = _required(backend_values, "OS_SECURITY_KEY", "backend/.env")
    if len(service_key) < MIN_SERVICE_KEY_CHARS:
        raise SHORT_SERVICE_KEY
    if _database_password(database_url) != root_password:
        raise DATABASE_MISMATCH
    queue_enabled = backend_values.get("QUEUE_ENABLED", "").strip().lower() == "true"
    if queue_enabled and not backend_values.get("REDIS_URL", "").strip():
        raise QUEUE_REDIS_MISSING


def _init_backend(root: Path) -> None:
    root_path = root / ".env"
    backend_path = root / "backend" / ".env"
    root_exists = root_path.exists()
    backend_exists = backend_path.exists()
    if root_exists:
        root_values = _environment(root_path)
        root_password = _required(root_values, "POSTGRES_PASSWORD", ".env")
    elif backend_exists:
        root_values = {}
        database_url = _required(
            _environment(backend_path),
            "DATABASE_URL",
            "backend/.env",
        )
        root_password = _database_password(database_url)
    else:
        root_values = {}
        root_password = secrets.token_hex(24)

    root_template = (root / ".env.example").read_text(encoding="utf-8")
    backend_template = (root / "backend" / ".env.example").read_text(encoding="utf-8")
    root_content = _replace_assignment(root_template, "POSTGRES_PASSWORD", root_password)
    backend_content = _replace_assignment(
        _replace_assignment(backend_template, "OS_SECURITY_KEY", secrets.token_hex(32)),
        "DATABASE_URL",
        f"postgresql+psycopg://samurai:{quote(root_password, safe='')}@127.0.0.1:54329/samurai",
    )
    redis_url = _local_redis_url(root_values)
    if redis_url is not None:
        backend_content = _replace_assignment(backend_content, "REDIS_URL", redis_url)
    root_created = _create_private(root_path, root_content)
    backend_created = _create_private(backend_path, backend_content)
    _validate_backend(root)
    if root_created and backend_created:
        message = "Created .env and backend/.env."
    elif root_created:
        message = "Created .env; existing backend/.env preserved."
    elif backend_created:
        message = "Existing .env preserved; created backend/.env."
    else:
        message = "Existing .env and backend/.env preserved."
    _ = sys.stdout.write(message + "\n")


def _init_frontend(root: Path) -> None:
    path = root / "frontend" / ".env"
    template = (root / "frontend" / ".env.example").read_text(encoding="utf-8")
    message = (
        "Created frontend/.env."
        if _create_private(path, template)
        else "Existing frontend/.env preserved."
    )
    _ = sys.stdout.write(message + "\n")


def _check_port(raw_port: str, label: str) -> None:
    try:
        port = int(raw_port)
    except ValueError as error:
        raise _invalid_port_error(label) from error
    try:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", port))
    except OSError as error:
        raise _occupied_port_error(label, port) from error


def _run(arguments: Sequence[str]) -> None:
    match arguments:
        case ["init-backend", raw_root]:
            _init_backend(_repository(raw_root))
        case ["init-frontend", raw_root]:
            _init_frontend(_repository(raw_root))
        case ["validate", raw_root]:
            _validate_backend(_repository(raw_root))
            _ = sys.stdout.write("Local backend environment is valid.\n")
        case ["check-port", raw_port, label]:
            _check_port(raw_port, label)
        case _:
            raise USAGE_ERROR


def main() -> int:
    """Run the requested setup operation without exposing secret values."""
    try:
        _run(sys.argv[1:])
    except SetupError as error:
        _ = sys.stderr.write(f"{error}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
