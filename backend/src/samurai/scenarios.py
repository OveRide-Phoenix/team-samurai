"""Transactional persistence for deterministic synthetic scenarios."""

# allow: SIZE_OK — one store owns authorization, baseline fencing, and atomic result rows.

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Final, final
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, JsonValue
from sqlalchemy import text

from samurai.company_store_queries import valid_schema
from samurai.scenario_contracts import (
    PROVENANCE,
    RESULT_LABELS,
    ScenarioCancelledError,
    ScenarioCreate,
    ScenarioDefinition,
    ScenarioIssue,
    ScenarioLabel,
    ScenarioStoreError,
    canonical_json,
    sha256,
)
from samurai.scenario_math import ScenarioResult, ScenarioResultPayload, analyze

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy import Engine
    from sqlalchemy.engine import Connection
    from sqlalchemy.sql.elements import TextClause

BASELINE_QUERY: Final = """SELECT m.role, c.current_revision, c.state_sha256
FROM "{schema}".samurai_workspace_memberships m
JOIN "{schema}".samurai_companies c ON c.workspace_id=m.workspace_id
WHERE m.workspace_id=:workspace_id AND m.user_id=:actor_id AND m.active
AND c.company_id=:company_id"""
BASELINE_LOCK_QUERY: Final = BASELINE_QUERY + " FOR UPDATE OF m, c"
MAX_SCENARIO_DEFINITIONS: Final = 50
SCENARIO_QUERY: Final = """SELECT scenario_id, workspace_id, company_id, created_by,
company_revision, input_sha256, inputs FROM "{schema}".samurai_scenarios
WHERE scenario_id=:scenario_id AND workspace_id=:workspace_id AND company_id=:company_id"""
SCENARIO_LOCK_QUERY: Final = SCENARIO_QUERY + " FOR UPDATE"


class _ScenarioRow(BaseModel):
    scenario_id: UUID
    workspace_id: UUID
    company_id: UUID
    created_by: str
    company_revision: int
    input_sha256: str
    inputs: dict[str, JsonValue]


class _ResultRow(BaseModel):
    label: ScenarioLabel
    result: dict[str, JsonValue]
    result_sha256: str


class _BaselineRow(BaseModel):
    role: str
    current_revision: int
    state_sha256: str


@final
class ScenarioStore:
    """Persist immutable scenario definitions and atomic deterministic results."""

    def __init__(self, engine: Engine, *, schema: str) -> None:
        """Bind the store to one validated founder-platform schema."""
        if not valid_schema(schema):
            raise ScenarioStoreError(ScenarioIssue.INVALID_SCHEMA)
        self._engine = engine
        self._schema = schema

    def create(
        self,
        actor_id: str,
        workspace_id: UUID,
        company_id: UUID,
        idempotency_key: UUID,
        inputs: ScenarioCreate,
    ) -> tuple[ScenarioDefinition, bool]:
        """Create or replay one normalized definition under current authority."""
        scenario_id = uuid5(
            NAMESPACE_URL,
            f"samurai-scenario:{workspace_id}:{company_id}:{actor_id}:{idempotency_key}",
        )
        input_sha256 = sha256(inputs)
        with self._engine.begin() as connection:
            _ = self._baseline(connection, actor_id, workspace_id, company_id, inputs, lock=True)
            row = self._scenario_row(connection, scenario_id, workspace_id, company_id, lock=True)
            if row is not None:
                if row.input_sha256 != input_sha256:
                    raise ScenarioStoreError(ScenarioIssue.CHANGED_IDEMPOTENCY)
                return self._definition(row), False
            definition = ScenarioDefinition(
                title=inputs.title,
                company_revision=inputs.company_revision,
                company_state_sha256=inputs.company_state_sha256,
                horizon_days=inputs.horizon_days,
                baseline_metrics=inputs.baseline_metrics,
                assumptions=inputs.assumptions,
                constraints=inputs.constraints,
                scenario_id=scenario_id,
                workspace_id=workspace_id,
                company_id=company_id,
                created_by=actor_id,
                input_sha256=input_sha256,
            )
            _ = connection.execute(
                self._sql(
                    """INSERT INTO "{schema}".samurai_scenarios
                    (scenario_id, workspace_id, company_id, created_by, company_revision,
                    input_sha256, inputs, created_at) VALUES
                    (:scenario_id, :workspace_id, :company_id, :created_by, :company_revision,
                    :input_sha256, CAST(:inputs AS jsonb), :created_at)"""
                ),
                {
                    "scenario_id": scenario_id,
                    "workspace_id": workspace_id,
                    "company_id": company_id,
                    "created_by": actor_id,
                    "company_revision": inputs.company_revision,
                    "input_sha256": input_sha256,
                    "inputs": canonical_json(inputs),
                    "created_at": int(time.time()),
                },
            )
            return definition, True

    def get(
        self, actor_id: str, workspace_id: UUID, company_id: UUID, scenario_id: UUID
    ) -> ScenarioDefinition:
        """Read one definition through current workspace membership."""
        with self._engine.connect() as connection:
            _ = self._admit(connection, actor_id, workspace_id, company_id, writable=False)
            row = self._scenario_row(connection, scenario_id, workspace_id, company_id, lock=False)
        if row is None:
            raise ScenarioStoreError(ScenarioIssue.NOT_FOUND)
        return self._definition(row)

    def list(
        self, actor_id: str, workspace_id: UUID, company_id: UUID
    ) -> tuple[ScenarioDefinition, ...]:
        """Read a bounded newest-first definition collection under current membership."""
        with self._engine.connect() as connection:
            _ = self._admit(connection, actor_id, workspace_id, company_id, writable=False)
            rows = tuple(
                _ScenarioRow.model_validate(row)
                for row in connection.execute(
                    self._sql(
                        """SELECT scenario_id, workspace_id, company_id, created_by,
                        company_revision, input_sha256, inputs FROM "{schema}".samurai_scenarios
                        WHERE workspace_id=:workspace_id AND company_id=:company_id
                        ORDER BY created_at DESC, scenario_id DESC LIMIT :limit"""
                    ),
                    {
                        "workspace_id": workspace_id,
                        "company_id": company_id,
                        "limit": MAX_SCENARIO_DEFINITIONS,
                    },
                ).mappings()
            )
        return tuple(self._definition(row) for row in rows)

    def run(  # noqa: PLR0913 - all arguments are independent persistence fences.
        self,
        actor_id: str,
        workspace_id: UUID,
        company_id: UUID,
        scenario_id: UUID,
        idempotency_key: UUID,
        *,
        cancelled: Callable[[ScenarioLabel], bool] | None = None,
    ) -> tuple[ScenarioResult, bool]:
        """Compute and atomically persist all three deterministic labels."""
        with self._engine.begin() as connection:
            return self.run_in_transaction(
                connection,
                actor_id,
                workspace_id,
                company_id,
                scenario_id,
                idempotency_key,
                cancelled=cancelled,
            )

    def run_in_transaction(  # noqa: PLR0913, PLR0917 - transaction owns all fences.
        self,
        connection: Connection,
        actor_id: str,
        workspace_id: UUID,
        company_id: UUID,
        scenario_id: UUID,
        idempotency_key: UUID,
        *,
        cancelled: Callable[[ScenarioLabel], bool] | None = None,
    ) -> tuple[ScenarioResult, bool]:
        """Run using a caller-owned transaction so scheduler locks stay atomic."""
        row = self._scenario_row(connection, scenario_id, workspace_id, company_id, lock=False)
        if row is None:
            raise ScenarioStoreError(ScenarioIssue.NOT_FOUND)
        definition = self._definition(row)
        _ = self._baseline(
            connection,
            actor_id,
            workspace_id,
            company_id,
            definition,
            lock=True,
        )
        row = self._scenario_row(connection, scenario_id, workspace_id, company_id, lock=True)
        if row is None or row.input_sha256 != definition.input_sha256:
            raise ScenarioStoreError(ScenarioIssue.NOT_FOUND)
        existing = self._result(connection, scenario_id)
        if existing is not None:
            return existing, False
        run_id = uuid5(
            NAMESPACE_URL,
            f"samurai-scenario-run:{scenario_id}:{actor_id}:{idempotency_key}",
        )
        result = analyze(definition)
        payload = canonical_json(
            ScenarioResultPayload.model_validate(result.model_dump(exclude={"result_sha256"}))
        )
        for trajectory in result.trajectories:
            if cancelled is not None and cancelled(trajectory.label):
                raise ScenarioCancelledError(scenario_id)
            _ = connection.execute(
                self._sql(
                    """INSERT INTO "{schema}".samurai_scenario_runs
                    (run_id, scenario_id, label, result, result_sha256, provenance, created_at)
                    VALUES (:run_id, :scenario_id, :label, CAST(:result AS jsonb),
                    :result_sha256, :provenance, :created_at)"""
                ),
                {
                    "run_id": uuid5(NAMESPACE_URL, f"{run_id}:{trajectory.label}"),
                    "scenario_id": scenario_id,
                    "label": trajectory.label,
                    "result": payload,
                    "result_sha256": result.result_sha256,
                    "provenance": PROVENANCE,
                    "created_at": int(time.time()),
                },
            )
        return result, True

    def get_result(
        self, actor_id: str, workspace_id: UUID, company_id: UUID, scenario_id: UUID
    ) -> ScenarioResult:
        """Read one complete result through current workspace membership."""
        with self._engine.connect() as connection:
            _ = self._admit(connection, actor_id, workspace_id, company_id, writable=False)
            if (
                self._scenario_row(connection, scenario_id, workspace_id, company_id, lock=False)
                is None
            ):
                raise ScenarioStoreError(ScenarioIssue.NOT_FOUND)
            result = self._result(connection, scenario_id)
        if result is None:
            raise ScenarioStoreError(ScenarioIssue.NOT_FOUND)
        return result

    def _baseline(  # noqa: PLR0913 - transaction and four baseline fences are required.
        self,
        connection: Connection,
        actor_id: str,
        workspace_id: UUID,
        company_id: UUID,
        inputs: ScenarioCreate,
        *,
        lock: bool,
    ) -> None:
        row = self._admit(connection, actor_id, workspace_id, company_id, writable=True, lock=lock)
        if (
            row.current_revision != inputs.company_revision
            or row.state_sha256 != inputs.company_state_sha256
        ):
            raise ScenarioStoreError(ScenarioIssue.STALE_BASELINE)

    def _admit(  # noqa: PLR0913 - transaction and scope fields stay explicit.
        self,
        connection: Connection,
        actor_id: str,
        workspace_id: UUID,
        company_id: UUID,
        *,
        writable: bool,
        lock: bool = False,
    ) -> _BaselineRow:
        query = BASELINE_LOCK_QUERY if lock else BASELINE_QUERY
        raw = (
            connection.execute(
                self._sql(query),
                {
                    "workspace_id": workspace_id,
                    "actor_id": actor_id,
                    "company_id": company_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        if raw is None:
            raise ScenarioStoreError(ScenarioIssue.PERMISSION_DENIED)
        row = _BaselineRow.model_validate(raw)
        if writable and row.role == "viewer":
            raise ScenarioStoreError(ScenarioIssue.PERMISSION_DENIED)
        return row

    def _scenario_row(
        self,
        connection: Connection,
        scenario_id: UUID,
        workspace_id: UUID,
        company_id: UUID,
        *,
        lock: bool,
    ) -> _ScenarioRow | None:
        query = SCENARIO_LOCK_QUERY if lock else SCENARIO_QUERY
        raw = (
            connection.execute(
                self._sql(query),
                {
                    "scenario_id": scenario_id,
                    "workspace_id": workspace_id,
                    "company_id": company_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        return None if raw is None else _ScenarioRow.model_validate(raw)

    @staticmethod
    def _definition(row: _ScenarioRow) -> ScenarioDefinition:
        inputs = ScenarioCreate.model_validate(row.inputs)
        if sha256(inputs) != row.input_sha256:
            raise ScenarioStoreError(ScenarioIssue.CORRUPT_RESULT)
        return ScenarioDefinition(
            title=inputs.title,
            company_revision=inputs.company_revision,
            company_state_sha256=inputs.company_state_sha256,
            horizon_days=inputs.horizon_days,
            baseline_metrics=inputs.baseline_metrics,
            assumptions=inputs.assumptions,
            constraints=inputs.constraints,
            scenario_id=row.scenario_id,
            workspace_id=row.workspace_id,
            company_id=row.company_id,
            created_by=row.created_by,
            input_sha256=row.input_sha256,
        )

    def _result(self, connection: Connection, scenario_id: UUID) -> ScenarioResult | None:
        rows = tuple(
            _ResultRow.model_validate(row)
            for row in connection.execute(
                self._sql(
                    """SELECT label, result, result_sha256 FROM
                    "{schema}".samurai_scenario_runs WHERE scenario_id=:scenario_id
                    ORDER BY CASE label WHEN 'low' THEN 1 WHEN 'base' THEN 2 ELSE 3 END"""
                ),
                {"scenario_id": scenario_id},
            ).mappings()
        )
        if not rows:
            return None
        if len(rows) != len(RESULT_LABELS) or tuple(row.label for row in rows) != RESULT_LABELS:
            raise ScenarioStoreError(ScenarioIssue.CORRUPT_RESULT)
        payload = ScenarioResultPayload.model_validate(rows[0].result)
        digest = sha256(payload)
        if any(row.result != rows[0].result or row.result_sha256 != digest for row in rows):
            raise ScenarioStoreError(ScenarioIssue.CORRUPT_RESULT)
        return ScenarioResult(
            provenance=payload.provenance,
            company_revision=payload.company_revision,
            company_state_sha256=payload.company_state_sha256,
            input_sha256=payload.input_sha256,
            horizon_days=payload.horizon_days,
            assumptions=payload.assumptions,
            trajectories=payload.trajectories,
            formulas=payload.formulas,
            sensitivity=payload.sensitivity,
            constraint_findings=payload.constraint_findings,
            result_sha256=digest,
        )

    def _sql(self, source: str) -> TextClause:
        return text(source.format(schema=self._schema))
