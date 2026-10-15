"""Provider-free platform evaluation runner boundary tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from scripts.run_platform_evals import (
    EvalCounts,
    evaluation_passed,
    read_counts,
    require_loopback_database,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_runner_rejects_non_loopback_database() -> None:
    # Given an environment pointed at a non-local PostgreSQL host.
    environment = {"SAMURAI_TEST_DATABASE_URL": "postgresql://user:secret@db.example/samurai"}

    # When the provider-free runner validates its database boundary.
    validate = require_loopback_database

    # Then it refuses before executing any tests.
    with pytest.raises(ValueError, match="disposable loopback PostgreSQL"):
        validate(environment)


def test_runner_reads_actual_junit_counts(tmp_path: Path) -> None:
    # Given a pytest-shaped JUnit report with one executed test.
    junit = tmp_path / "pytest.xml"
    _ = junit.write_text(
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0" /></testsuites>',
        encoding="utf-8",
    )

    # When the runner parses the executed result.
    counts = read_counts(junit)

    # Then its summary inputs come from the report rather than fixture labels.
    assert (counts.tests, counts.failures, counts.errors, counts.skipped) == (1, 0, 0, 0)


def test_runner_rejects_an_empty_test_selection() -> None:
    # Given a successful pytest exit whose JUnit report executed no tests.
    counts = EvalCounts(tests=0, failures=0, errors=0, skipped=0)

    # When the runner evaluates the acceptance gate.
    passed = evaluation_passed(0, counts)

    # Then an empty selection cannot be reported as a passing evaluation.
    assert not passed
