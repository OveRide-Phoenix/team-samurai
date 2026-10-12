"""Verify an isolated PostgreSQL backup and restore without provider calls."""

# allow: SIZE_OK — task-scoped operator CLI; split if an executable cloud provider is added.

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, override
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg import sql
from pydantic import TypeAdapter

if TYPE_CHECKING:
    from collections.abc import Mapping

TARGET_PREFIX: Final = "samurai_recovery_"
type Mode = Literal["local", "cloud"]
type EvidenceValue = bool | int | float | str | dict[str, str | int] | dict[str, int]
TABLE_ROWS: Final = TypeAdapter(list[tuple[str]])
COUNT_ROW: Final = TypeAdapter(tuple[int])
LINEAGE_ROWS: Final = TypeAdapter(list[tuple[list[str], int, int, list[str]]])


@dataclass(frozen=True, slots=True)
class _RecoveryError(Exception):
    """A safe operator-facing recovery refusal without database credentials."""

    reason: _Failure

    @override
    def __str__(self) -> str:
        return self.reason


class _Failure(StrEnum):
    MISSING_URL = "required database URL environment variable is unset"
    INVALID_URL = "invalid PostgreSQL URL in environment variable"
    MISSING_USER = "database user is missing from environment variable"
    TARGET_PREFIX = "target database must start with samurai_recovery_"
    SAME_DATABASE = "source and target databases must be different"
    INVENTORY = "database inventory failed"
    REQUIRED_TABLES = "recovery assertions require agno_sessions and samurai_work_intents"
    ASSERTIONS = "ownership and lineage assertions failed"
    TOOL = "required PostgreSQL 18 tool is unavailable"
    TOOL_FAILED = "PostgreSQL backup or restore tool failed"
    TARGET_NOT_EMPTY = "target recovery database must be empty"
    RESTORE_INVALID = "restored row count, ownership, or lineage assertion failed"
    CLOUD_BLOCKED = "cloud execution is blocked until approved task 11"


@dataclass(frozen=True, slots=True)
class _DatabaseIdentity:
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)
    url: str = field(repr=False)
    sslmode: str | None = None

    @property
    def safe_record(self) -> dict[str, str | int]:
        return {"host": self.host, "port": self.port, "database": self.database}

    @property
    def canonical(self) -> tuple[str, int, str]:
        return (self.host.casefold(), self.port, self.database)

    def process_environment(self) -> dict[str, str]:
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PGHOST": self.host,
            "PGPORT": str(self.port),
            "PGDATABASE": self.database,
            "PGUSER": self.user,
            "PGPASSWORD": self.password,
        }
        if self.sslmode is not None:
            environment["PGSSLMODE"] = self.sslmode
        return environment


@dataclass(frozen=True, slots=True)
class _Snapshot:
    row_counts: dict[str, int]
    accepted_intents: int
    invalid_ownership: int
    invalid_lineage: int


class _RecoveryArguments(argparse.Namespace):
    mode: Mode = "local"
    source_env: str = ""
    target_env: str = ""
    evidence_dir: Path = Path()
    dry_run: bool = False


def _arguments() -> _RecoveryArguments:
    parser = argparse.ArgumentParser(
        description="Back up and restore only to an isolated samurai_recovery_ database.",
    )
    _ = parser.add_argument("--mode", choices=("local", "cloud"), required=True)
    _ = parser.add_argument(
        "--source-env", required=True, help="Environment variable with source URL"
    )
    _ = parser.add_argument(
        "--target-env", required=True, help="Environment variable with target URL"
    )
    _ = parser.add_argument("--evidence-dir", required=True, type=Path)
    _ = parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate identities and write a plan; this is never completion proof",
    )
    return parser.parse_args(namespace=_RecoveryArguments())


def _identity(environment_name: str) -> _DatabaseIdentity:
    value = os.environ.get(environment_name)
    if not value:
        raise _RecoveryError(_Failure.MISSING_URL)
    normalized = value.replace("postgresql+psycopg://", "postgresql://", 1)
    try:
        parsed = urlsplit(normalized)
        port = parsed.port or 5432
    except ValueError as error:
        raise _RecoveryError(_Failure.INVALID_URL) from error
    database = unquote(parsed.path.removeprefix("/"))
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or not database:
        raise _RecoveryError(_Failure.INVALID_URL)
    if parsed.username is None:
        raise _RecoveryError(_Failure.MISSING_USER)
    query = dict(
        partition.split("=", maxsplit=1)
        for partition in parsed.query.split("&")
        if "=" in partition
    )
    return _DatabaseIdentity(
        host=parsed.hostname,
        port=port,
        database=database,
        user=unquote(parsed.username),
        password=unquote(parsed.password or ""),
        url=normalized,
        sslmode=query.get("sslmode"),
    )


def _validated_identities(
    arguments: _RecoveryArguments,
) -> tuple[_DatabaseIdentity, _DatabaseIdentity]:
    source = _identity(arguments.source_env)
    target = _identity(arguments.target_env)
    if not target.database.startswith(TARGET_PREFIX):
        raise _RecoveryError(_Failure.TARGET_PREFIX)
    if source.canonical == target.canonical:
        raise _RecoveryError(_Failure.SAME_DATABASE)
    return source, target


def validate_lineage(
    recorded_ids: list[str], revision_window: tuple[int, int], retained_ids: list[str]
) -> bool:
    """Match accepted work IDs to its canonical child-session revision slice."""
    expected_revision, accepted_revision = revision_window
    return (
        len(retained_ids) >= accepted_revision
        and recorded_ids == retained_ids[expected_revision:accepted_revision]
    )


def _table_counts(database: _DatabaseIdentity) -> dict[str, int]:
    counts: dict[str, int] = {}
    try:
        with psycopg.connect(database.url) as connection, connection.cursor() as cursor:
            inventory_query = (
                "SELECT tablename FROM pg_catalog.pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename"
            )
            _ = cursor.execute(inventory_query)
            for (table_name,) in TABLE_ROWS.validate_python(cursor.fetchall()):
                _ = cursor.execute(
                    sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table_name))
                )
                row = cursor.fetchone()
                if row is None:
                    raise _RecoveryError(_Failure.INVENTORY)
                counts[table_name] = COUNT_ROW.validate_python(row)[0]
    except psycopg.Error as error:
        raise _RecoveryError(_Failure.INVENTORY) from error
    return counts


def _snapshot(database: _DatabaseIdentity) -> _Snapshot:
    counts = _table_counts(database)
    required = {"agno_sessions", "samurai_work_intents"}
    if not required.issubset(counts):
        raise _RecoveryError(_Failure.REQUIRED_TABLES)
    try:
        with psycopg.connect(database.url) as connection, connection.cursor() as cursor:
            _ = cursor.execute(
                "SELECT count(*) FROM samurai_work_intents WHERE accepted_revision IS NOT NULL"
            )
            accepted_row = cursor.fetchone()
            ownership_query = (
                "SELECT count(*) FROM samurai_work_intents i LEFT JOIN agno_sessions s "
                "ON s.session_id = i.child_session_id WHERE i.accepted_revision IS NOT NULL "
                "AND (s.session_id IS NULL OR s.user_id <> i.owner_id)"
            )
            _ = cursor.execute(ownership_query)
            ownership_row = cursor.fetchone()
            lineage_query = """
                SELECT i.accepted_artifact_ids, i.expected_revision, i.accepted_revision,
                       COALESCE(
                           jsonb_agg(
                               a.value ->> 'artifact_id'
                               ORDER BY (a.value ->> 'revision')::bigint
                           )
                               FILTER (WHERE a.value IS NOT NULL),
                           '[]'::jsonb
                       ) AS retained_artifact_ids
                FROM samurai_work_intents i
                LEFT JOIN agno_sessions s ON s.session_id = i.child_session_id
                LEFT JOIN LATERAL jsonb_array_elements(
                    COALESCE(s.session_data #> '{session_state,company,artifacts}', '[]'::jsonb)
                ) WITH ORDINALITY AS a(value, ordinality) ON TRUE
                WHERE i.accepted_revision IS NOT NULL
                GROUP BY i.logical_work_id, i.accepted_artifact_ids,
                         i.expected_revision, i.accepted_revision
                """
            _ = cursor.execute(lineage_query)
            lineage_rows = LINEAGE_ROWS.validate_python(cursor.fetchall())
    except psycopg.Error as error:
        raise _RecoveryError(_Failure.ASSERTIONS) from error
    if accepted_row is None or ownership_row is None:
        raise _RecoveryError(_Failure.ASSERTIONS)
    return _Snapshot(
        row_counts=counts,
        accepted_intents=COUNT_ROW.validate_python(accepted_row)[0],
        invalid_ownership=COUNT_ROW.validate_python(ownership_row)[0],
        invalid_lineage=sum(
            not validate_lineage(recorded, (expected, accepted), retained)
            for recorded, expected, accepted, retained in lineage_rows
        ),
    )


def _tool(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise _RecoveryError(_Failure.TOOL)
    result = subprocess.run(  # noqa: S603 - resolved fixed PostgreSQL executable.
        [executable, "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or " 18." not in result.stdout:
        raise _RecoveryError(_Failure.TOOL)
    return executable


def _run_tool(executable: str, options: list[str], database: _DatabaseIdentity) -> None:
    result = subprocess.run(  # noqa: S603 - executable passed only from _tool.
        [executable, *options],
        check=False,
        capture_output=True,
        text=True,
        env=database.process_environment(),
    )
    if result.returncode != 0:
        raise _RecoveryError(_Failure.TOOL_FAILED)


def _write_evidence(path: Path, payload: Mapping[str, EvidenceValue]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _ = (path / "restore.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _plan(
    arguments: _RecoveryArguments,
    source: _DatabaseIdentity,
    target: _DatabaseIdentity,
) -> dict[str, EvidenceValue]:
    blocked = arguments.mode == "cloud" and not arguments.dry_run
    return {
        "mode": arguments.mode,
        "status": "blocked" if blocked else "planned",
        "completion_proof": False,
        "cloud_mutation_attempted": False,
        "source": source.safe_record,
        "target": target.safe_record,
    }


def _run_local(
    arguments: _RecoveryArguments,
    source: _DatabaseIdentity,
    target: _DatabaseIdentity,
) -> None:
    source_before = _snapshot(source)
    if _table_counts(target):
        raise _RecoveryError(_Failure.TARGET_NOT_EMPTY)
    pg_dump = _tool("pg_dump")
    pg_restore = _tool("pg_restore")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="samurai-readiness-restore-") as temporary:
        backup = Path(temporary) / "backup.dump"
        _run_tool(
            pg_dump,
            ["--format=custom", "--file", str(backup), "--no-owner", "--no-privileges"],
            source,
        )
        _run_tool(
            pg_restore,
            [
                "--dbname",
                target.database,
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                str(backup),
            ],
            target,
        )
    target_after = _snapshot(target)
    row_counts_match = source_before.row_counts == target_after.row_counts
    ownership_valid = source_before.invalid_ownership == target_after.invalid_ownership == 0
    lineage_valid = (
        source_before.accepted_intents > 0
        and source_before.accepted_intents == target_after.accepted_intents
        and source_before.invalid_lineage == target_after.invalid_lineage == 0
    )
    if not (row_counts_match and ownership_valid and lineage_valid):
        raise _RecoveryError(_Failure.RESTORE_INVALID)
    _write_evidence(
        arguments.evidence_dir,
        {
            "mode": "local",
            "status": "completed",
            "completion_proof": True,
            "cloud_mutation_attempted": False,
            "source": source.safe_record,
            "target": target.safe_record,
            "row_counts": target_after.row_counts,
            "row_counts_match": row_counts_match,
            "ownership_valid": ownership_valid,
            "lineage_valid": lineage_valid,
            "accepted_intents": target_after.accepted_intents,
            "duration_seconds": round(time.monotonic() - started, 3),
            "completed_at": datetime.now(UTC).isoformat(),
        },
    )


def main() -> int:
    """Validate a plan or execute one isolated local backup and restore."""
    arguments = _arguments()
    try:
        source, target = _validated_identities(arguments)
        if arguments.dry_run or arguments.mode == "cloud":
            _write_evidence(arguments.evidence_dir, _plan(arguments, source, target))
            if arguments.mode == "cloud" and not arguments.dry_run:
                _ = sys.stderr.write(f"recovery verification refused: {_Failure.CLOUD_BLOCKED}\n")
                return 2
            return 0
        _run_local(arguments, source, target)
    except (OSError, _RecoveryError) as error:
        _ = sys.stderr.write(f"recovery verification refused: {error}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
