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


def _fake_gcloud(tmp_path: Path, scenario: str = "pitr") -> tuple[Path, dict[str, str]]:
    executable = tmp_path / "gcloud"
    _ = executable.write_text(
        f"""#!{sys.executable}
import json
import os
import sys
from pathlib import Path

arguments = sys.argv[1:]
log = Path(os.environ["FAKE_GCLOUD_LOG"])
with log.open("a", encoding="utf-8") as output:
    _ = output.write(json.dumps(arguments) + "\\n")
scenario = os.environ["FAKE_GCLOUD_SCENARIO"]
state = Path(os.environ["FAKE_GCLOUD_STATE"])
source = "samurai-postgres"
target = "samurai-recovery-drill-test"
if arguments[:3] == ["sql", "instances", "describe"]:
    if arguments[3] == source:
        print(json.dumps({{
            "name": source,
            "region": "asia-south1",
            "settings": {{"backupConfiguration": {{
                "pointInTimeRecoveryEnabled": scenario != "backup"
            }}}},
        }}))
    elif state.exists():
        print(json.dumps({{"name": target, "region": "asia-south1"}}))
    else:
        raise SystemExit(1)
elif arguments[:3] == ["sql", "instances", "list"]:
    print(json.dumps([{{"name": target}}] if state.exists() or scenario == "target_exists" else []))
elif arguments[:3] == ["sql", "instances", "clone"]:
    state.write_text("created", encoding="utf-8")
    if scenario == "create_fail":
        raise SystemExit(1)
elif arguments[:3] == ["sql", "backups", "list"]:
    print(json.dumps([{{
        "id": "123456789",
        "endTime": "2026-10-12T00:00:00Z",
        "status": "SUCCESSFUL",
    }}]))
elif arguments[:3] == ["sql", "backups", "restore"]:
    state.write_text("created", encoding="utf-8")
elif arguments[:3] == ["sql", "instances", "delete"]:
    if scenario == "delete_fail":
        raise SystemExit(1)
    state.unlink(missing_ok=True)
else:
    raise SystemExit(64)
""",
        encoding="utf-8",
    )
    _ = executable.chmod(0o700)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
        "FAKE_GCLOUD_LOG": str(tmp_path / "gcloud.jsonl"),
        "FAKE_GCLOUD_SCENARIO": scenario,
        "FAKE_GCLOUD_STATE": str(tmp_path / "target-created"),
    }
    return executable, environment


def _run_cloud(
    tmp_path: Path,
    *,
    scenario: str = "pitr",
    dry_run: bool = False,
    execute: bool = False,
    overrides: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    _, environment = _fake_gcloud(tmp_path, scenario)
    values = {
        "project": "samurai-ai-company-2026",
        "region": "asia-south1",
        "source-instance": "samurai-postgres",
        "target-prefix": "samurai-recovery-drill-",
        "target-instance": "samurai-recovery-drill-test",
        "point-in-time": "2026-10-12T00:00:00Z",
        **(overrides or {}),
    }
    arguments = [
        sys.executable,
        str(SCRIPT),
        "--mode",
        "cloud",
        "--evidence-dir",
        str(tmp_path / "evidence"),
    ]
    for option, value in values.items():
        arguments.extend((f"--{option}", value))
    if dry_run:
        arguments.append("--dry-run")
    if execute:
        arguments.append("--execute-cloud-restore")
    result = subprocess.run(  # noqa: S603 - fixed interpreter and fake gcloud PATH.
        arguments,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    log_path = tmp_path / "gcloud.jsonl"
    calls = (
        [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        if log_path.exists()
        else []
    )
    return result, calls


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
    for option in (
        "--mode",
        "--source-env",
        "--target-env",
        "--evidence-dir",
        "--dry-run",
        "--project",
        "--region",
        "--source-instance",
        "--target-prefix",
        "--target-instance",
        "--point-in-time",
        "--execute-cloud-restore",
    ):
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


def test_cloud_mode_requires_explicit_execution_gate(tmp_path: Path) -> None:
    # Given a guarded cloud restore plan without its explicit mutation gate.
    # When cloud execution is requested without dry-run.
    result, calls = _run_cloud(tmp_path)

    # Then it creates a blocked plan before invoking gcloud.
    assert result.returncode == 2
    evidence = EVIDENCE.validate_json((tmp_path / "evidence" / "restore.json").read_bytes())
    assert evidence["status"] == "blocked"
    assert evidence["completion_proof"] is False
    assert evidence["cloud_mutation_attempted"] is False
    assert calls == []


def test_cloud_dry_run_discovers_source_and_absent_target_without_mutation(
    tmp_path: Path,
) -> None:
    # Given an exact approved boundary and a fake PITR-capable source.
    # When cloud dry-run performs read-only discovery.
    result, calls = _run_cloud(tmp_path, dry_run=True)

    # Then source and target guards pass without clone, restore, or delete calls.
    assert result.returncode == 0
    evidence = EVIDENCE.validate_json((tmp_path / "evidence" / "restore.json").read_bytes())
    assert evidence["status"] == "planned"
    assert evidence["source_discovered"] is True
    assert evidence["target_absence_verified"] is True
    assert evidence["recovery_method"] == "pitr"
    assert evidence["completion_proof"] is False
    mutation_commands = (["sql", "instances", "clone"], ["sql", "instances", "delete"])
    assert all(call[:3] not in mutation_commands for call in calls)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"project": "other-project"}, "cloud project is outside the approved boundary"),
        ({"region": "us-central1"}, "cloud region is outside the approved boundary"),
        ({"target-prefix": "unsafe-"}, "cloud target prefix is outside the approved boundary"),
        ({"target-instance": "samurai-postgres"}, "cloud source and target must be different"),
        ({"point-in-time": "not-a-time"}, "point-in-time is required"),
    ],
)
def test_cloud_boundary_refuses_before_gcloud(
    tmp_path: Path,
    overrides: dict[str, str],
    message: str,
) -> None:
    # Given a cloud identity outside one exact safety boundary.
    # When dry-run validates it.
    result, calls = _run_cloud(tmp_path, dry_run=True, overrides=overrides)

    # Then the request fails before any provider command.
    assert result.returncode == 2
    assert message in result.stderr
    assert calls == []


def test_cloud_existing_target_refuses_before_mutation(tmp_path: Path) -> None:
    # Given discovery returns the exact requested target as existing.
    # When cloud execution reaches the absence guard.
    result, calls = _run_cloud(tmp_path, scenario="target_exists", execute=True)

    # Then no create or delete command runs.
    assert result.returncode == 2
    assert "cloud target already exists" in result.stderr
    mutation_commands = (["sql", "instances", "clone"], ["sql", "instances", "delete"])
    assert all(call[:3] not in mutation_commands for call in calls)


@pytest.mark.parametrize(
    ("scenario", "expected_method", "create_command"),
    [
        ("pitr", "pitr", ["sql", "instances", "clone"]),
        ("backup", "backup", ["sql", "backups", "restore"]),
    ],
)
def test_cloud_mock_execution_creates_and_cleans_isolated_target(
    tmp_path: Path,
    scenario: str,
    expected_method: str,
    create_command: list[str],
) -> None:
    # Given approved fake discovery for PITR or backup recovery.
    # When the explicit cloud execution gate is present.
    result, calls = _run_cloud(tmp_path, scenario=scenario, execute=True)

    # Then the isolated target is created, observed, deleted, and never called drill proof.
    assert result.returncode == 0
    evidence = EVIDENCE.validate_json((tmp_path / "evidence" / "restore.json").read_bytes())
    assert evidence["status"] == "prepared_and_cleaned"
    assert evidence["recovery_method"] == expected_method
    assert evidence["cloud_mutation_attempted"] is True
    assert evidence["cleanup_succeeded"] is True
    assert evidence["completion_proof"] is False
    assert any(call[:3] == create_command for call in calls)
    assert any(call[:3] == ["sql", "instances", "delete"] for call in calls)


@pytest.mark.parametrize("scenario", ["create_fail", "delete_fail"])
def test_cloud_failure_records_guarded_cleanup_result(tmp_path: Path, scenario: str) -> None:
    # Given a fake create or delete failure after the mutation gate.
    # When cloud preparation executes.
    result, calls = _run_cloud(tmp_path, scenario=scenario, execute=True)

    # Then the receipt stays incomplete and records the cleanup outcome without raw output.
    assert result.returncode == 2
    evidence = EVIDENCE.validate_json((tmp_path / "evidence" / "restore.json").read_bytes())
    assert evidence["status"] == "failed"
    assert evidence["completion_proof"] is False
    assert evidence["cleanup_succeeded"] is (scenario == "create_fail")
    assert "fake" not in json.dumps(evidence)
    assert any(call[:3] == ["sql", "instances", "delete"] for call in calls)
