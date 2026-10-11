from __future__ import annotations

import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

REPOSITORY = Path(__file__).parents[2]
SETUP_SCRIPT = REPOSITORY / "scripts" / "local_setup.py"
TASKFILE = REPOSITORY / "Taskfile.yml"
SOCKET_ADDRESS = TypeAdapter(tuple[str, int])


class _ListedTask(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    name: str


class _TaskListing(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)
    tasks: tuple[_ListedTask, ...]


def _run_setup(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed interpreter and repository-owned script.
        [sys.executable, str(SETUP_SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def _values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", maxsplit=1)
            values[key] = value
    return values


def test_fresh_backend_environment_uses_shared_credentials_and_private_modes(
    tmp_path: Path,
) -> None:
    _ = (tmp_path / ".env.example").write_text("POSTGRES_PASSWORD=\n", encoding="utf-8")
    backend = tmp_path / "backend"
    backend.mkdir()
    database_line = "DATABASE_URL=postgresql+psycopg://samurai:REPLACE_ME@127.0.0.1:54329/samurai"
    _ = (backend / ".env.example").write_text(
        f"OS_SECURITY_KEY=\n{database_line}\nGOOGLE_API_KEY=\n",
        encoding="utf-8",
    )

    result = _run_setup("init-backend", str(tmp_path))

    assert result.returncode == 0
    assert result.stdout == "Created .env and backend/.env.\n"
    assert result.stderr == ""
    root_values = _values(tmp_path / ".env")
    backend_values = _values(backend / ".env")
    password = root_values["POSTGRES_PASSWORD"]
    assert len(password) == 48
    assert password in backend_values["DATABASE_URL"]
    assert len(backend_values["OS_SECURITY_KEY"]) == 64
    assert backend_values["GOOGLE_API_KEY"] == ""
    assert stat.S_IMODE((tmp_path / ".env").stat().st_mode) == 0o600
    assert stat.S_IMODE((backend / ".env").stat().st_mode) == 0o600


def test_repeated_backend_setup_preserves_existing_files(tmp_path: Path) -> None:
    _ = (tmp_path / ".env.example").write_text("POSTGRES_PASSWORD=\n", encoding="utf-8")
    backend = tmp_path / "backend"
    backend.mkdir()
    database_line = "DATABASE_URL=postgresql+psycopg://samurai:REPLACE_ME@127.0.0.1:54329/samurai"
    _ = (backend / ".env.example").write_text(
        f"OS_SECURITY_KEY=\n{database_line}\n",
        encoding="utf-8",
    )
    first = _run_setup("init-backend", str(tmp_path))
    root_before = (tmp_path / ".env").read_bytes()
    backend_before = (backend / ".env").read_bytes()
    root_inode = (tmp_path / ".env").stat().st_ino
    backend_inode = (backend / ".env").stat().st_ino

    second = _run_setup("init-backend", str(tmp_path))

    assert first.returncode == 0
    assert second.returncode == 0
    assert second.stdout == "Existing .env and backend/.env preserved.\n"
    assert (tmp_path / ".env").read_bytes() == root_before
    assert (backend / ".env").read_bytes() == backend_before
    assert (tmp_path / ".env").stat().st_ino == root_inode
    assert (backend / ".env").stat().st_ino == backend_inode


def test_existing_special_character_password_is_url_encoded_without_interpolation(
    tmp_path: Path,
) -> None:
    _ = (tmp_path / ".env").write_text(
        'POSTGRES_PASSWORD="pa:ss@word$literal"\n',
        encoding="utf-8",
    )
    _ = (tmp_path / ".env.example").write_text("POSTGRES_PASSWORD=\n", encoding="utf-8")
    backend = tmp_path / "backend"
    backend.mkdir()
    database_line = "DATABASE_URL=postgresql+psycopg://samurai:REPLACE_ME@127.0.0.1:54329/samurai"
    _ = (backend / ".env.example").write_text(
        f"OS_SECURITY_KEY=\n{database_line}\nGOOGLE_API_KEY=\n",
        encoding="utf-8",
    )

    result = _run_setup("init-backend", str(tmp_path))

    assert result.returncode == 0
    assert result.stdout == "Existing .env preserved; created backend/.env.\n"
    database_url = _values(backend / ".env")["DATABASE_URL"]
    assert "pa%3Ass%40word%24literal" in database_url
    validation = _run_setup("validate", str(tmp_path))
    assert validation.returncode == 0


def test_mismatched_database_credentials_fail_without_secret_output(tmp_path: Path) -> None:
    root_marker = "root-secret-marker"
    backend_marker = "backend-secret-marker"
    _ = (tmp_path / ".env").write_text(
        f"POSTGRES_PASSWORD={root_marker}\n",
        encoding="utf-8",
    )
    backend = tmp_path / "backend"
    backend.mkdir()
    _ = (backend / ".env").write_text(
        "\n".join(
            (
                "OS_SECURITY_KEY=" + "a" * 64,
                f"DATABASE_URL=postgresql+psycopg://samurai:{backend_marker}@127.0.0.1:54329/samurai",
                "",
            )
        ),
        encoding="utf-8",
    )

    result = _run_setup("validate", str(tmp_path))

    assert result.returncode == 2
    assert result.stdout == ""
    assert "root and backend database credentials do not match" in result.stderr
    assert root_marker not in result.stderr
    assert backend_marker not in result.stderr


def test_frontend_setup_preserves_existing_environment(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    _ = (frontend / ".env.example").write_text(
        "BACKEND_URL=http://127.0.0.1:8000/agentos\n",
        encoding="utf-8",
    )
    existing = "BACKEND_URL=http://example.invalid/agentos\n"
    _ = (frontend / ".env").write_text(existing, encoding="utf-8")

    result = _run_setup("init-frontend", str(tmp_path))

    assert result.returncode == 0
    assert result.stdout == "Existing frontend/.env preserved.\n"
    assert (frontend / ".env").read_text(encoding="utf-8") == existing


def test_occupied_port_fails_with_named_diagnostic() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        _, port = SOCKET_ADDRESS.validate_python(listener.getsockname())

        result = _run_setup("check-port", str(port), "backend")

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == f"backend port {port} is already in use\n"


def test_taskfile_lists_local_workflow_without_destructive_database_commands() -> None:
    task_binary = shutil.which("task")
    assert task_binary is not None
    result = subprocess.run(  # noqa: S603 - installed Task binary reads repository Taskfile.
        [task_binary, "--taskfile", str(TASKFILE), "--list", "--json"],
        cwd=REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "NO_COLOR": "1"},
    )

    assert result.returncode == 0
    payload = _TaskListing.model_validate(json.loads(result.stdout))
    names = {task.name for task in payload.tasks}
    assert names == {
        "backend:dev",
        "check",
        "db:logs",
        "db:status",
        "db:stop",
        "db:up",
        "default",
        "frontend:dev",
        "frontend:setup",
        "health",
        "setup",
    }
    taskfile = TASKFILE.read_text(encoding="utf-8")
    assert "podman-compose==1.6.0" in taskfile
    assert "down" not in taskfile
    assert re.search(r"^\s*-\s+podman machine (start|restart)", taskfile, re.MULTILINE) is None
    assert "5432:" not in taskfile


@pytest.mark.parametrize("command", ["init-backend", "init-frontend", "validate"])
def test_setup_rejects_missing_repository_root(command: str, tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    result = _run_setup(command, str(missing))

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == f"repository root does not exist: {missing}\n"
