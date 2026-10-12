"""Guarded Cloud SQL recovery preparation for the database recovery CLI."""

# allow: SIZE_OK — one atomic Cloud SQL validation, create, observation, and cleanup state machine.

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Final, Literal, override

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    field_validator,
)

if TYPE_CHECKING:
    from pathlib import Path

APPROVED_PROJECT: Final = "samurai-ai-company-2026"
APPROVED_REGION: Final = "asia-south1"
APPROVED_TARGET_PREFIX: Final = "samurai-recovery-drill-"
INSTANCE_NAME: Final = re.compile(r"[a-z][a-z0-9-]{0,96}[a-z0-9]")


class _Failure(StrEnum):
    PROJECT = "cloud project is outside the approved boundary"
    REGION = "cloud region is outside the approved boundary"
    PREFIX = "cloud target prefix is outside the approved boundary"
    SOURCE = "cloud source instance is required"
    TARGET = "cloud target must use the approved recovery prefix"
    SAME = "cloud source and target must be different"
    GATE = "cloud execution requires --execute-cloud-restore or --dry-run"
    CONFLICTING_GATES = "cloud dry-run and execution gate cannot be combined"
    TOOL = "gcloud CLI is unavailable"
    PROVIDER = "cloud recovery command failed"
    SOURCE_MISMATCH = "cloud source discovery did not match the requested boundary"
    TARGET_EXISTS = "cloud target already exists"
    BACKUP = "no successful Cloud SQL backup was discovered"
    PITR_TIME = "point-in-time is required when source PITR is enabled"
    TARGET_OBSERVATION = "created cloud target could not be observed"
    CLEANUP = "cloud target cleanup failed"


@dataclass(frozen=True, slots=True)
class CloudRecoveryError(Exception):
    """A sanitized cloud preparation failure."""

    reason: _Failure

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class CloudRecoveryArguments:
    """Explicit Cloud SQL recovery boundary."""

    project: str
    region: str
    source_instance: str
    target_prefix: str
    target_instance: str
    point_in_time: str
    evidence_dir: Path
    dry_run: bool
    execute: bool


class _BackupConfiguration(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    pitr_enabled: bool = Field(default=False, alias="pointInTimeRecoveryEnabled")


class _Settings(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    backup_configuration: _BackupConfiguration = Field(
        default_factory=_BackupConfiguration,
        alias="backupConfiguration",
    )


class _Instance(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: str
    region: str = ""
    settings: _Settings = Field(default_factory=_Settings)


class _Backup(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    backup_id: str = Field(alias="id")
    status: Literal["SUCCESSFUL"]

    @field_validator("backup_id", mode="before")
    @classmethod
    def _stringify_id(cls, value: object) -> str:
        if not isinstance(value, (str, int)):
            raise TypeError
        return str(value)


INSTANCE_ROWS: Final = TypeAdapter(list[_Instance])
BACKUP_ROWS: Final = TypeAdapter(list[_Backup])


def _write(arguments: CloudRecoveryArguments, payload: dict[str, JsonValue]) -> None:
    arguments.evidence_dir.mkdir(parents=True, exist_ok=True)
    _ = (arguments.evidence_dir / "restore.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def _base_receipt(arguments: CloudRecoveryArguments) -> dict[str, JsonValue]:
    return {
        "mode": "cloud",
        "project": arguments.project,
        "region": arguments.region,
        "source_instance": arguments.source_instance,
        "target_instance": arguments.target_instance,
        "completion_proof": False,
        "cloud_mutation_attempted": False,
    }


def _validate_point_in_time(value: str) -> None:
    if not value:
        return
    try:
        point_in_time = datetime.fromisoformat(value)
    except ValueError as error:
        raise CloudRecoveryError(_Failure.PITR_TIME) from error
    if point_in_time.tzinfo is None:
        raise CloudRecoveryError(_Failure.PITR_TIME)


def _validate(arguments: CloudRecoveryArguments) -> None:
    if arguments.project != APPROVED_PROJECT:
        raise CloudRecoveryError(_Failure.PROJECT)
    if arguments.region != APPROVED_REGION:
        raise CloudRecoveryError(_Failure.REGION)
    if arguments.target_prefix != APPROVED_TARGET_PREFIX:
        raise CloudRecoveryError(_Failure.PREFIX)
    if INSTANCE_NAME.fullmatch(arguments.source_instance) is None:
        raise CloudRecoveryError(_Failure.SOURCE)
    if arguments.source_instance == arguments.target_instance:
        raise CloudRecoveryError(_Failure.SAME)
    if (
        not arguments.target_instance.startswith(arguments.target_prefix)
        or arguments.target_instance == arguments.target_prefix
        or INSTANCE_NAME.fullmatch(arguments.target_instance) is None
    ):
        raise CloudRecoveryError(_Failure.TARGET)
    _validate_point_in_time(arguments.point_in_time)
    if arguments.dry_run and arguments.execute:
        raise CloudRecoveryError(_Failure.CONFLICTING_GATES)


def _command(executable: str, options: list[str]) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - resolved gcloud and typed options.
            [executable, *options],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise CloudRecoveryError(_Failure.PROVIDER) from error
    if result.returncode != 0:
        raise CloudRecoveryError(_Failure.PROVIDER)
    return result.stdout


def _discover(
    executable: str,
    arguments: CloudRecoveryArguments,
) -> tuple[_Instance, Literal["pitr", "backup"], str | None]:
    try:
        source = _Instance.model_validate_json(
            _command(
                executable,
                [
                    "sql",
                    "instances",
                    "describe",
                    arguments.source_instance,
                    f"--project={arguments.project}",
                    "--format=json(name,region,settings.backupConfiguration.pointInTimeRecoveryEnabled)",
                ],
            )
        )
    except ValidationError as error:
        raise CloudRecoveryError(_Failure.PROVIDER) from error
    if source.name != arguments.source_instance or source.region != arguments.region:
        raise CloudRecoveryError(_Failure.SOURCE_MISMATCH)
    try:
        existing = INSTANCE_ROWS.validate_json(
            _command(
                executable,
                [
                    "sql",
                    "instances",
                    "list",
                    f"--project={arguments.project}",
                    f"--filter=name=({arguments.target_instance})",
                    "--format=json(name)",
                ],
            )
        )
    except ValidationError as error:
        raise CloudRecoveryError(_Failure.PROVIDER) from error
    if any(item.name == arguments.target_instance for item in existing):
        raise CloudRecoveryError(_Failure.TARGET_EXISTS)
    if source.settings.backup_configuration.pitr_enabled:
        if not arguments.point_in_time:
            raise CloudRecoveryError(_Failure.PITR_TIME)
        return source, "pitr", None
    try:
        backups = BACKUP_ROWS.validate_json(
            _command(
                executable,
                [
                    "sql",
                    "backups",
                    "list",
                    f"--instance={arguments.source_instance}",
                    f"--project={arguments.project}",
                    "--filter=status=SUCCESSFUL",
                    "--sort-by=~endTime",
                    "--limit=1",
                    "--format=json(id,status)",
                ],
            )
        )
    except ValidationError as error:
        raise CloudRecoveryError(_Failure.PROVIDER) from error
    if not backups:
        raise CloudRecoveryError(_Failure.BACKUP)
    return source, "backup", backups[0].backup_id


def _create(
    executable: str,
    arguments: CloudRecoveryArguments,
    method: Literal["pitr", "backup"],
    backup_id: str | None,
) -> None:
    if method == "pitr":
        _ = _command(
            executable,
            [
                "sql",
                "instances",
                "clone",
                arguments.source_instance,
                arguments.target_instance,
                f"--project={arguments.project}",
                f"--point-in-time={arguments.point_in_time}",
                "--quiet",
            ],
        )
        return
    if backup_id is None:
        raise CloudRecoveryError(_Failure.BACKUP)
    _ = _command(
        executable,
        [
            "sql",
            "backups",
            "restore",
            backup_id,
            f"--restore-instance={arguments.target_instance}",
            f"--backup-instance={arguments.source_instance}",
            f"--project={arguments.project}",
            f"--region={arguments.region}",
            "--quiet",
        ],
    )


def _target_exists(executable: str, arguments: CloudRecoveryArguments) -> bool:
    try:
        rows = INSTANCE_ROWS.validate_json(
            _command(
                executable,
                [
                    "sql",
                    "instances",
                    "list",
                    f"--project={arguments.project}",
                    f"--filter=name=({arguments.target_instance})",
                    "--format=json(name)",
                ],
            )
        )
        return any(item.name == arguments.target_instance for item in rows)
    except ValidationError as error:
        raise CloudRecoveryError(_Failure.PROVIDER) from error


def _cleanup(executable: str, arguments: CloudRecoveryArguments) -> None:
    if not _target_exists(executable, arguments):
        return
    _ = _command(
        executable,
        [
            "sql",
            "instances",
            "delete",
            arguments.target_instance,
            f"--project={arguments.project}",
            "--quiet",
        ],
    )


def _observe_target(executable: str, arguments: CloudRecoveryArguments) -> None:
    try:
        target = _Instance.model_validate_json(
            _command(
                executable,
                [
                    "sql",
                    "instances",
                    "describe",
                    arguments.target_instance,
                    f"--project={arguments.project}",
                    "--format=json(name,region)",
                ],
            )
        )
    except ValidationError as error:
        raise CloudRecoveryError(_Failure.TARGET_OBSERVATION) from error
    if target.name != arguments.target_instance or target.region != arguments.region:
        raise CloudRecoveryError(_Failure.TARGET_OBSERVATION)


def run_cloud_recovery(arguments: CloudRecoveryArguments) -> None:
    """Validate or fake-execute the exact approved cloud recovery boundary."""
    _validate(arguments)
    receipt = _base_receipt(arguments)
    if not arguments.dry_run and not arguments.execute:
        receipt["status"] = "blocked"
        _write(arguments, receipt)
        raise CloudRecoveryError(_Failure.GATE)
    executable = shutil.which("gcloud")
    if executable is None:
        raise CloudRecoveryError(_Failure.TOOL)
    _, method, backup_id = _discover(executable, arguments)
    receipt.update(
        {
            "status": "planned",
            "source_discovered": True,
            "target_absence_verified": True,
            "recovery_method": method,
        }
    )
    if arguments.dry_run:
        _write(arguments, receipt)
        return
    receipt["cloud_mutation_attempted"] = True
    failure: CloudRecoveryError | None = None
    cleanup_succeeded = False
    try:
        _create(executable, arguments, method, backup_id)
        _observe_target(executable, arguments)
    except CloudRecoveryError as error:
        failure = error
    finally:
        try:
            _cleanup(executable, arguments)
            cleanup_succeeded = True
        except CloudRecoveryError:
            cleanup_succeeded = False
    receipt["cleanup_succeeded"] = cleanup_succeeded
    receipt["status"] = (
        "prepared_and_cleaned" if failure is None and cleanup_succeeded else "failed"
    )
    _write(arguments, receipt)
    if failure is not None:
        raise failure
    if not cleanup_succeeded:
        raise CloudRecoveryError(_Failure.CLEANUP)
