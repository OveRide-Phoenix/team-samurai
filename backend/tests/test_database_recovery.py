from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import JsonValue, TypeAdapter

from scripts.verify_database_recovery import validate_lineage

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_database_recovery.py"
EVIDENCE = TypeAdapter(dict[str, JsonValue])


def _run(
    tmp_path: Path,
    *,
    mode: str = "local",
    source: str = "postgresql://source-user:source-secret@127.0.0.1:5432/samurai_source",
    target: str = ("postgresql://target-user:target-secret@127.0.0.1:5432/samurai_recovery_target"),
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "SAMURAI_RECOVERY_SOURCE_URL": source,
        "SAMURAI_RECOVERY_TARGET_URL": target,
    }
    arguments = [
        sys.executable,
        str(SCRIPT),
        "--mode",
        mode,
        "--source-env",
        "SAMURAI_RECOVERY_SOURCE_URL",
        "--target-env",
        "SAMURAI_RECOVERY_TARGET_URL",
        "--evidence-dir",
        str(tmp_path),
    ]
    if dry_run:
        arguments.append("--dry-run")
    return subprocess.run(  # noqa: S603 - fixed interpreter and repository-owned script.
        arguments,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_help_describes_safe_local_recovery_contract() -> None:
    # Given the provider-free recovery CLI.
    # When an operator asks for help.
    result = subprocess.run(  # noqa: S603 - fixed interpreter and repository-owned script.
        [sys.executable, str(SCRIPT), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    # Then the explicit identities, mode, evidence, and plan-only switch are documented.
    assert result.returncode == 0
    for option in ("--mode", "--source-env", "--target-env", "--evidence-dir", "--dry-run"):
        assert option in result.stdout


def test_same_database_is_rejected_before_evidence_or_secret_output(tmp_path: Path) -> None:
    # Given source and target env vars resolving to the same database.
    database_url = "postgresql://samurai:same-target-secret@127.0.0.1:5432/samurai_recovery_same"
    # When recovery is requested.
    result = _run(tmp_path, source=database_url, target=database_url)

    # Then it fails before a restore or completion artifact and never prints the credential.
    assert result.returncode == 2
    assert "source and target databases must be different" in result.stderr
    assert "same-target-secret" not in result.stdout + result.stderr
    assert not (tmp_path / "restore.json").exists()


def test_target_without_recovery_prefix_is_rejected(tmp_path: Path) -> None:
    # Given a target identity that could be an application or production database.
    # When recovery is requested.
    result = _run(
        tmp_path,
        target="postgresql://target:production-secret@127.0.0.1:5432/production",
    )

    # Then the target prefix guard fails closed without exposing the credential.
    assert result.returncode == 2
    assert "target database must start with samurai_recovery_" in result.stderr
    assert "production-secret" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "source",
    [
        "postgresql://source-user:source-secret@127.0.0.1:not-a-port/samurai_source",
        "postgresql://source-user:source-secret@[broken/samurai_source",
    ],
)
def test_malformed_source_url_is_sanitized(source: str, tmp_path: Path) -> None:
    # Given a malformed database URL containing a credential marker.
    # When recovery parses the untrusted environment boundary.
    result = _run(tmp_path, source=source)

    # Then it fails with the sanitized refusal contract before writing evidence.
    assert result.returncode == 2
    assert (
        result.stderr
        == "recovery verification refused: invalid PostgreSQL URL in environment variable\n"
    )
    assert "source-secret" not in result.stdout + result.stderr
    assert not (tmp_path / "restore.json").exists()


def test_matching_count_bogus_artifact_id_is_invalid_lineage() -> None:
    # Given recorded IDs with the expected count but one ID absent from retained child state.
    # When restored lineage is compared with the database-joined child artifacts.
    valid = validate_lineage(
        recorded_ids=["artifact-2", "bogus-artifact"],
        revision_window=(1, 3),
        retained_ids=["artifact-1", "artifact-2", "artifact-3"],
    )

    # Then count equality cannot hide the broken artifact lineage.
    assert valid is False


def test_earlier_accepted_window_remains_valid_after_child_progress() -> None:
    # Given an accepted first-stage intent and a child session that later reached revision three.
    # When restored lineage compares the original acceptance window with retained history.
    valid = validate_lineage(
        recorded_ids=["artifact-1"],
        revision_window=(0, 1),
        retained_ids=["artifact-1", "artifact-2", "artifact-3"],
    )

    # Then later canonical artifacts do not invalidate the earlier accepted intent.
    assert valid is True


def test_dry_run_records_plan_without_completion_proof(tmp_path: Path) -> None:
    # Given distinct disposable database identities.
    # When a local dry run is requested without reachable databases or PostgreSQL tools.
    result = _run(tmp_path, dry_run=True)

    # Then it records only a sanitized plan and explicitly withholds completion proof.
    assert result.returncode == 0
    evidence = EVIDENCE.validate_json((tmp_path / "restore.json").read_bytes())
    assert evidence["status"] == "planned"
    assert evidence["completion_proof"] is False
    assert evidence["mode"] == "local"
    serialized = json.dumps(evidence)
    assert "source-secret" not in serialized
    assert "target-secret" not in serialized


def test_cloud_mode_is_inert_even_without_dry_run(tmp_path: Path) -> None:
    # Given the cloud branch before task 11 authorization.
    # When an execution is requested.
    result = _run(tmp_path, mode="cloud")

    # Then it creates a sanitized blocked plan and performs no cloud mutation.
    assert result.returncode == 2
    evidence = EVIDENCE.validate_json((tmp_path / "restore.json").read_bytes())
    assert evidence["status"] == "blocked"
    assert evidence["completion_proof"] is False
    assert evidence["cloud_mutation_attempted"] is False
    assert "task 11" in result.stderr
