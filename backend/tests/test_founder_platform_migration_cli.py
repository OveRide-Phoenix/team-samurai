from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "migrate_founder_platform.py"


def _run_cli(
    *arguments: str, environment: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed interpreter and repository-owned script.
        [sys.executable, str(SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_cli_help_exposes_guarded_interface() -> None:
    # Given the repository-owned migration CLI.
    arguments = ("--help",)

    # When its help is requested.
    result = _run_cli(*arguments)

    # Then every guarded input is documented.
    assert result.returncode == 0
    assert {"--database-url-env", "--schema", "--receipt", "--dry-run"} <= set(
        result.stdout.split()
    )


@pytest.mark.parametrize(
    ("variable", "value", "error"),
    [
        ("MISSING_MIGRATION_URL", None, "database URL environment variable is unset"),
        (
            "BROKEN_MIGRATION_URL",
            "postgresql+psycopg://owner:secret-sentinel@127.0.0.1:1/missing",
            "database operation failed",
        ),
    ],
)
def test_cli_refusal_is_redacted(
    tmp_path: Path, variable: str, value: str | None, error: str
) -> None:
    # Given a missing URL or a driver failure containing a secret sentinel.
    environment = {**os.environ}
    if value is None:
        _ = environment.pop(variable, None)
    else:
        environment[variable] = value
    receipt = tmp_path / "receipt.json"

    # When migration setup is refused.
    result = _run_cli(
        "--database-url-env",
        variable,
        "--receipt",
        str(receipt),
        environment=environment,
    )

    # Then only the fixed safe category is emitted and no receipt or secret leaks.
    assert result.returncode == 2
    assert result.stderr == f"migration refused: {error}\n"
    assert "secret-sentinel" not in result.stdout + result.stderr
    assert not receipt.exists()
