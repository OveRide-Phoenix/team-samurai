"""Run the fixed provider-free platform acceptance suite and record raw evidence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, cast
from urllib.parse import urlsplit

BACKEND_ROOT: Final = Path(__file__).parents[1]
TEST_TARGETS: Final = (
    "tests/test_knowledge.py",
    "tests/test_learning.py",
    "tests/test_schedules.py",
    "tests/test_scenarios.py",
    "tests/test_platform_e2e.py",
)
BEHAVIOR_FILTER: Final = (
    "not fixture_declares_bounded_non_evidentiary_cases "
    "and not eval_fixture_declares_inert_bounded_security_cases"
)
PROVIDER_KEYS: Final = frozenset(
    {"AGNO_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"}
)
LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "::1", "localhost"})


@dataclass(frozen=True, slots=True)
class EvalCounts:
    """Machine-read test counts parsed from pytest's JUnit report."""

    tests: int
    failures: int
    errors: int
    skipped: int


def require_loopback_database(environment: dict[str, str]) -> None:
    """Refuse absent or non-loopback PostgreSQL targets."""
    database_url = environment.get("SAMURAI_TEST_DATABASE_URL", "")
    if urlsplit(database_url).hostname not in LOOPBACK_HOSTS:
        message = "SAMURAI_TEST_DATABASE_URL must name a disposable loopback PostgreSQL database"
        raise ValueError(message)


def read_counts(junit_path: Path) -> EvalCounts:
    """Read execution counts from pytest's generated JUnit artifact."""
    root = ET.parse(junit_path).getroot()  # noqa: S314 - pytest creates this local file.
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    if not suites:
        message = "pytest JUnit artifact has no test suite counts"
        raise ValueError(message)
    return EvalCounts(
        tests=sum(int(suite.attrib["tests"]) for suite in suites),
        failures=sum(int(suite.attrib["failures"]) for suite in suites),
        errors=sum(int(suite.attrib["errors"]) for suite in suites),
        skipped=sum(int(suite.attrib["skipped"]) for suite in suites),
    )


def evaluation_passed(exit_code: int, counts: EvalCounts | None) -> bool:
    """Require a non-empty, fully passing executed test set."""
    return (
        exit_code == 0
        and counts is not None
        and counts.tests > 0
        and counts.failures == 0
        and counts.errors == 0
        and counts.skipped == 0
    )


def _parse_args() -> Path:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
        help="directory that will receive pytest.log, pytest.xml, and summary.json",
    )
    return cast("Path", parser.parse_args().evidence_dir)


def main() -> int:
    """Execute the fixed suite and return a shell-compatible status."""
    evidence_dir = _parse_args().resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    require_loopback_database(environment)
    for key in PROVIDER_KEYS:
        environment[key] = ""
    junit_path = evidence_dir / "pytest.xml"
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and fixed test targets.
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-k",
            BEHAVIOR_FILTER,
            *TEST_TARGETS,
            f"--junitxml={junit_path}",
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    pytest_log = completed.stdout + completed.stderr
    _ = (evidence_dir / "pytest.log").write_text(pytest_log, encoding="utf-8")
    counts = read_counts(junit_path) if junit_path.is_file() else None
    passed = evaluation_passed(completed.returncode, counts)
    summary: dict[str, object] = {
        "status": "passed" if passed else "failed",
        "provider_calls": 0,
        "provider_credentials_forwarded": [],
        "pytest_exit_code": completed.returncode,
        "counts": asdict(counts) if counts is not None else None,
        "selection": BEHAVIOR_FILTER,
        "test_targets": TEST_TARGETS,
        "artifacts": {"pytest_log": "pytest.log", "junit": "pytest.xml"},
    }
    _ = (evidence_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _ = sys.stdout.write(json.dumps(summary, sort_keys=True) + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
