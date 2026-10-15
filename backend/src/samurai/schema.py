"""Apply ordered founder-platform migrations to an existing Agno schema."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, final
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Engine, text

from samurai.quota import WorkspaceQuota
from samurai.schema_contracts import (
    LegacyCompany,
    LegacyMigrationError,
    LegacyMigrationIssue,
    LegacyRow,
    MigrationReceipt,
    canonical_state_hash,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection
    from sqlalchemy.sql.elements import TextClause

MIGRATIONS_DIR: Final = Path(__file__).with_name("migrations")
MIGRATION_NAME: Final = "0001_founder_platform"
MIGRATION_NAMES: Final = (
    MIGRATION_NAME,
    "0002_knowledge_provenance",
    "0003_learning_sharing",
    "0004_schedule_leases",
)
SCHEMA_NAME: Final = re.compile(r"^[a-z_][a-z0-9_]*$")
MIGRATION_FILE: Final = re.compile(r"^(?P<version>\d{4})_[a-z0-9_]+\.sql$")
UUID_LIST_ADAPTER = TypeAdapter(list[UUID])


@final
class FounderPlatformMigrator:
    """Validate, lock, migrate, and backfill one database transaction."""

    def __init__(self, engine: Engine, *, schema: str) -> None:
        """Bind a validated schema identifier without opening a transaction."""
        if SCHEMA_NAME.fullmatch(schema) is None:
            raise LegacyMigrationError(LegacyMigrationIssue.INVALID_SCHEMA)
        self._engine = engine
        self._schema = schema

    def inventory(self) -> MigrationReceipt:
        """Read and validate legacy state without database writes."""
        with self._engine.connect() as connection, connection.begin():
            _ = connection.execute(text("SET TRANSACTION READ ONLY"))
            return self._receipt(self._legacy_companies(connection, lock=False), status="planned")

    def apply(self) -> MigrationReceipt:
        """Apply ordered DDL and exact legacy backfill atomically."""
        with self._engine.connect() as connection, connection.begin():
            _ = connection.execute(self._sql('LOCK TABLE "{{schema}}".agno_sessions IN SHARE MODE'))
            companies = self._legacy_companies(connection, lock=True)
            for version, source, digest in self._migrations():
                if not self._migration_applied(connection, version):
                    _ = connection.exec_driver_sql(source.replace("{{schema}}", self._schema))
                    _ = connection.execute(
                        self._sql(
                            """INSERT INTO "{{schema}}".samurai_schema_migrations
                            (version, source_sha256, applied_at, receipt)
                            VALUES (:version, :digest,
                            EXTRACT(EPOCH FROM clock_timestamp())::bigint, '{}'::jsonb)"""
                        ),
                        {"version": version, "digest": digest},
                    )
            self._lock_quota_workspaces(connection, companies)
            self._backfill(connection, companies)
            self._reconcile_quotas(connection)
            receipt = self._receipt(companies, status="applied")
            _ = connection.execute(
                self._sql(
                    """UPDATE "{{schema}}".samurai_schema_migrations
                    SET receipt = CAST(:receipt AS jsonb) WHERE version = :version"""
                ),
                {
                    "receipt": json.dumps(receipt.as_json(), separators=(",", ":")),
                    "version": MIGRATION_NAME,
                },
            )
            return receipt

    def _sql(self, source: str) -> TextClause:
        return text(source.replace("{{schema}}", self._schema))

    def _migrations(self) -> tuple[tuple[str, str, str], ...]:
        migrations: list[tuple[str, str, str]] = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if MIGRATION_FILE.fullmatch(path.name) is None:
                raise LegacyMigrationError(LegacyMigrationIssue.INVALID_FILENAME)
            source = path.read_text(encoding="utf-8")
            migrations.append((path.stem, source, hashlib.sha256(source.encode()).hexdigest()))
        if tuple(version for version, _, _ in migrations) != MIGRATION_NAMES:
            raise LegacyMigrationError(LegacyMigrationIssue.INVALID_ORDER)
        return tuple(migrations)

    def _migration_applied(self, connection: Connection, version: str) -> bool:
        table_name = connection.execute(
            text("SELECT to_regclass(:table_name)"),
            {"table_name": f"{self._schema}.samurai_schema_migrations"},
        ).scalar_one_or_none()
        if table_name is None:
            return False
        source_hash = connection.execute(
            self._sql(
                """SELECT source_sha256 FROM "{{schema}}".samurai_schema_migrations
                WHERE version = :version"""
            ),
            {"version": version},
        ).scalar_one_or_none()
        if source_hash is None:
            return False
        expected = next(digest for name, _, digest in self._migrations() if name == version)
        if source_hash != expected:
            raise LegacyMigrationError(LegacyMigrationIssue.SOURCE_DRIFT)
        return True

    def _legacy_companies(self, connection: Connection, *, lock: bool) -> tuple[LegacyCompany, ...]:
        query = """SELECT session_id, user_id, session_data, created_at, updated_at
        FROM "{{schema}}".agno_sessions
        WHERE session_type = 'workflow'
        AND session_data #> '{session_state,company}' IS NOT NULL
        ORDER BY session_id"""
        if lock:
            query = f"{query} FOR SHARE"
        rows = connection.execute(self._sql(query)).mappings()
        companies = tuple(self._parse_legacy(row) for row in rows)
        ids = [company.state.context.company_id for company in companies]
        if len(ids) != len(set(ids)):
            raise LegacyMigrationError(LegacyMigrationIssue.DUPLICATE_COMPANY)
        return companies

    def _parse_legacy(self, row: object) -> LegacyCompany:
        try:
            parsed = LegacyRow.model_validate(row)
        except ValidationError as error:
            raise LegacyMigrationError(LegacyMigrationIssue.INVALID_LINEAGE) from error
        if parsed.user_id is None or not parsed.user_id.strip():
            raise LegacyMigrationError(LegacyMigrationIssue.MISSING_OWNER)
        state = parsed.session_data.session_state.company
        return LegacyCompany(
            owner_id=parsed.user_id,
            child_session_id=parsed.session_id,
            parent_session_id=state.context.authenticated_session_id,
            created_at=parsed.created_at,
            updated_at=parsed.updated_at or parsed.created_at,
            state=state,
            state_sha256=canonical_state_hash(state),
        )

    def _receipt(self, companies: tuple[LegacyCompany, ...], *, status: str) -> MigrationReceipt:
        return MigrationReceipt(
            status=status,
            owners=len({company.owner_id for company in companies}),
            companies=len(companies),
            revisions=sum(company.state.current_revision for company in companies),
            state_sha256=tuple(sorted(company.state_sha256 for company in companies)),
            migration_versions=tuple(version for version, _, _ in self._migrations()),
        )

    def _backfill(self, connection: Connection, companies: tuple[LegacyCompany, ...]) -> None:
        by_owner: dict[str, list[LegacyCompany]] = {}
        for company in companies:
            by_owner.setdefault(company.owner_id, []).append(company)
        for owner_id, owned in by_owner.items():
            workspace_id = uuid5(NAMESPACE_URL, f"samurai:{owner_id}:personal-workspace")
            parameters = {
                "workspace_id": workspace_id,
                "owner_id": owner_id,
                "created_at": min(company.created_at for company in owned),
                "updated_at": max(company.updated_at for company in owned),
            }
            statements = (
                """INSERT INTO "{{schema}}".samurai_workspaces
                    (workspace_id, workspace_kind, display_name, created_at, updated_at)
                    VALUES (:workspace_id, 'personal', 'Personal workspace',
                    :created_at, :updated_at)
                    ON CONFLICT (workspace_id) DO NOTHING""",
                """INSERT INTO "{{schema}}".samurai_workspace_memberships
                    (workspace_id, user_id, role, authorization_epoch, active,
                    created_at, updated_at)
                    VALUES (:workspace_id, :owner_id, 'owner', 1, true, :created_at, :updated_at)
                    ON CONFLICT (workspace_id, user_id) DO NOTHING""",
                """INSERT INTO "{{schema}}".samurai_workspace_quotas
                    (workspace_id, updated_at) VALUES (:workspace_id, :updated_at)
                    ON CONFLICT (workspace_id) DO NOTHING""",
            )
            for statement in statements:
                _ = connection.execute(self._sql(statement), parameters)
            for company in owned:
                self._backfill_company(connection, workspace_id, company)

    def _lock_quota_workspaces(
        self, connection: Connection, companies: tuple[LegacyCompany, ...]
    ) -> None:
        workspace_ids = set(
            UUID_LIST_ADAPTER.validate_python(
                connection.execute(
                    self._sql('SELECT workspace_id FROM "{{schema}}".samurai_workspaces')
                )
                .scalars()
                .all()
            )
        )
        workspace_ids.update(
            uuid5(NAMESPACE_URL, f"samurai:{company.owner_id}:personal-workspace")
            for company in companies
        )
        quota = WorkspaceQuota(self._schema)
        for workspace_id in sorted(workspace_ids):
            quota.lock(connection, workspace_id)

    def _backfill_company(
        self, connection: Connection, workspace_id: UUID, company: LegacyCompany
    ) -> None:
        parameters = {
            "company_id": company.state.context.company_id,
            "workspace_id": workspace_id,
            "state": json.dumps(company.state.model_dump(mode="json"), separators=(",", ":")),
            "state_sha256": company.state_sha256,
            "revision": company.state.current_revision,
            "owner_id": company.owner_id,
            "child_session_id": company.child_session_id,
            "parent_session_id": company.parent_session_id,
            "created_at": company.created_at,
            "updated_at": company.updated_at,
        }
        statements = (
            """INSERT INTO "{{schema}}".samurai_companies
                (company_id, workspace_id, canonical_state, state_sha256, current_revision,
                legacy_owner_id, legacy_session_id, legacy_parent_session_id,
                created_at, updated_at)
                VALUES (:company_id, :workspace_id, CAST(:state AS jsonb), :state_sha256, :revision,
                :owner_id, :child_session_id, :parent_session_id, :created_at, :updated_at)
                ON CONFLICT (company_id) DO NOTHING""",
            """INSERT INTO "{{schema}}".samurai_company_actor_bindings
                (company_id, user_id, parent_session_id, child_session_id, created_at, updated_at)
                VALUES (:company_id, :owner_id, :parent_session_id, :child_session_id,
                :created_at, :updated_at) ON CONFLICT (company_id, user_id) DO NOTHING""",
        )
        for statement in statements:
            _ = connection.execute(self._sql(statement), parameters)
        matches = TypeAdapter(int).validate_python(
            connection.execute(
                self._sql(
                    """SELECT count(*) FROM "{{schema}}".samurai_companies
                WHERE company_id = :company_id AND workspace_id = :workspace_id
                AND canonical_state = CAST(:state AS jsonb) AND state_sha256 = :state_sha256
                AND current_revision = :revision AND legacy_owner_id = :owner_id
                AND legacy_session_id = :child_session_id
                AND legacy_parent_session_id = :parent_session_id
                AND created_at = :created_at"""
                ),
                parameters,
            ).scalar_one()
        )
        if matches != 1:
            raise LegacyMigrationError(LegacyMigrationIssue.COMPANY_CONFLICT)

    def _reconcile_quotas(self, connection: Connection) -> None:
        timestamp = int(datetime.now(UTC).timestamp())
        _ = connection.execute(
            self._sql(
                """INSERT INTO "{{schema}}".samurai_workspace_quotas
                (workspace_id, updated_at)
                SELECT workspace_id, :timestamp FROM "{{schema}}".samurai_workspaces
                ON CONFLICT (workspace_id) DO NOTHING"""
            ),
            {"timestamp": timestamp},
        )
        intents_table = connection.execute(
            text("SELECT to_regclass(:table_name)"),
            {"table_name": f"{self._schema}.samurai_work_intents"},
        ).scalar_one_or_none()
        if intents_table is not None:
            _ = connection.execute(
                self._sql(
                    """UPDATE "{{schema}}".samurai_workspace_quotas q SET
                    active_job_count = (SELECT count(*)
                    FROM "{{schema}}".samurai_work_intents i
                    WHERE i.workspace_id = q.workspace_id AND i.active_job_reserved),
                    updated_at = :timestamp"""
                ),
                {"timestamp": timestamp},
            )
        _ = connection.execute(
            self._sql(
                """UPDATE "{{schema}}".samurai_workspace_quotas q SET
                company_count = (SELECT count(*) FROM "{{schema}}".samurai_companies c
                    WHERE c.workspace_id = q.workspace_id),
                member_count = (SELECT count(*) FROM "{{schema}}".samurai_workspace_memberships m
                    WHERE m.workspace_id = q.workspace_id AND m.active),
                file_count = (SELECT count(*) FROM "{{schema}}".samurai_files f
                    WHERE f.workspace_id = q.workspace_id
                    AND f.state IN ('quarantined', 'ready')),
                stored_bytes = COALESCE((SELECT sum(f.byte_size)
                    FROM "{{schema}}".samurai_files f WHERE f.workspace_id = q.workspace_id
                    AND f.state IN ('quarantined', 'ready')), 0),
                schedule_count = (SELECT count(*) FROM "{{schema}}".samurai_schedules s
                    WHERE s.workspace_id = q.workspace_id AND s.enabled),
                knowledge_chunk_count = (SELECT count(*)
                    FROM "{{schema}}".samurai_knowledge_chunks k
                    WHERE k.workspace_id = q.workspace_id),
                updated_at = :timestamp"""
            ),
            {"timestamp": timestamp},
        )
