"""Validated immutable inputs and failures for synthetic scenarios."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum, unique
from typing import Annotated, ClassVar, Final, Literal, override
from uuid import UUID  # noqa: TC003 - Pydantic resolves UUID fields at runtime.

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

PROVENANCE: Final = "synthetic_scenario_not_validation"
ScenarioLabel = Literal["low", "base", "high"]
RESULT_LABELS: Final[tuple[ScenarioLabel, ScenarioLabel, ScenarioLabel]] = (
    "low",
    "base",
    "high",
)
ConstraintOperator = Literal["minimum", "maximum"]
type MetricValue = Annotated[
    Decimal,
    Field(ge=0, le=1_000_000_000, max_digits=18, decimal_places=6, allow_inf_nan=False),
]
type DeltaPercent = Annotated[
    Decimal,
    Field(ge=-100, le=1000, max_digits=10, decimal_places=6, allow_inf_nan=False),
]


def _normalized_text(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        code = "scenario_blank_text"
        raise PydanticCustomError(code, "scenario text fields cannot be blank")
    return normalized


def _normalized_name(value: str) -> str:
    return _normalized_text(value).casefold().replace(" ", "_")


def normalized_decimal(value: Decimal) -> Decimal:
    """Return one canonical finite Decimal representation."""
    return Decimal(0) if value == 0 else value.normalize()


class ScenarioContract(BaseModel):
    """Reject unknown fields and prevent mutation across scenario contracts."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class ScenarioMetric(ScenarioContract):
    """One founder-supplied non-negative baseline metric."""

    name: str = Field(min_length=1, max_length=80)
    value: MetricValue
    unit: str = Field(min_length=1, max_length=40)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        return _normalized_name(value)

    @field_validator("unit")
    @classmethod
    def _normalize_unit(cls, value: str) -> str:
        return _normalized_name(value)

    @field_validator("value")
    @classmethod
    def _normalize_value(cls, value: Decimal) -> Decimal:
        return normalized_decimal(value)


class ScenarioAssumption(ScenarioContract):
    """One explicit relative change across the three scenario labels."""

    name: str = Field(min_length=1, max_length=80)
    target_metric: str = Field(min_length=1, max_length=80)
    low_delta_percent: DeltaPercent
    base_delta_percent: DeltaPercent
    high_delta_percent: DeltaPercent

    @field_validator("name", "target_metric")
    @classmethod
    def _normalize_names(cls, value: str) -> str:
        return _normalized_name(value)

    @field_validator("low_delta_percent", "base_delta_percent", "high_delta_percent")
    @classmethod
    def _normalize_deltas(cls, value: Decimal) -> Decimal:
        return normalized_decimal(value)

    @model_validator(mode="after")
    def ordered_deltas(self) -> ScenarioAssumption:
        """Require conservative-to-optimistic ordering."""
        if not self.low_delta_percent <= self.base_delta_percent <= self.high_delta_percent:
            code = "scenario_delta_order"
            raise PydanticCustomError(code, "assumption deltas must be ordered low, base, high")
        return self


class ScenarioConstraint(ScenarioContract):
    """One minimum or maximum applied to every trajectory."""

    name: str = Field(min_length=1, max_length=80)
    metric: str = Field(min_length=1, max_length=80)
    operator: ConstraintOperator
    threshold: MetricValue
    unit: str = Field(min_length=1, max_length=40)

    @field_validator("name", "metric")
    @classmethod
    def _normalize_names(cls, value: str) -> str:
        return _normalized_name(value)

    @field_validator("unit")
    @classmethod
    def _normalize_unit(cls, value: str) -> str:
        return _normalized_name(value)

    @field_validator("threshold")
    @classmethod
    def _normalize_threshold(cls, value: Decimal) -> Decimal:
        return normalized_decimal(value)


class ScenarioCreate(ScenarioContract):
    """Normalized founder inputs pinned to one canonical company baseline."""

    title: str = Field(min_length=1, max_length=200)
    company_revision: int = Field(ge=0)
    company_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    horizon_days: int = Field(ge=1, le=365)
    baseline_metrics: tuple[ScenarioMetric, ...] = Field(min_length=1, max_length=20)
    assumptions: tuple[ScenarioAssumption, ...] = Field(min_length=1, max_length=10)
    constraints: tuple[ScenarioConstraint, ...] = Field(min_length=1, max_length=10)

    @field_validator("title")
    @classmethod
    def _normalize_title(cls, value: str) -> str:
        return _normalized_text(value)

    @model_validator(mode="after")
    def validate_references(self) -> ScenarioCreate:
        """Bind assumptions and constraints to unique compatible metrics."""
        metrics = {item.name: item for item in self.baseline_metrics}
        if len(metrics) != len(self.baseline_metrics):
            code = "scenario_metric_name"
            raise PydanticCustomError(code, "baseline metric names must be unique")
        assumption_names = {item.name for item in self.assumptions}
        targets = {item.target_metric for item in self.assumptions}
        if len(assumption_names) != len(self.assumptions) or len(targets) != len(self.assumptions):
            code = "scenario_assumption_name"
            raise PydanticCustomError(code, "assumption names and target metrics must be unique")
        if not targets <= metrics.keys():
            code = "scenario_assumption_target"
            raise PydanticCustomError(code, "assumptions must target baseline metrics")
        constraint_names = {item.name for item in self.constraints}
        if len(constraint_names) != len(self.constraints):
            code = "scenario_constraint_name"
            raise PydanticCustomError(code, "constraint names must be unique")
        for constraint in self.constraints:
            metric = metrics.get(constraint.metric)
            if metric is None or metric.unit != constraint.unit:
                code = "scenario_constraint_metric"
                raise PydanticCustomError(
                    code,
                    "constraints must reference a baseline metric with the same unit",
                )
        return self


class ScenarioDefinition(ScenarioCreate):
    """One immutable, scope-bound normalized scenario definition."""

    scenario_id: UUID
    workspace_id: UUID
    company_id: UUID
    created_by: str
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@unique
class ScenarioIssue(StrEnum):
    """Stable scenario failures safe for the HTTP boundary."""

    INVALID_SCHEMA = "invalid scenario schema"
    PERMISSION_DENIED = "active workspace editor membership is required"
    NOT_FOUND = "scenario was not found"
    STALE_BASELINE = "scenario baseline no longer matches canonical company state"
    CHANGED_IDEMPOTENCY = "idempotency key was reused with changed scenario inputs"
    CORRUPT_RESULT = "persisted scenario result is incomplete"


@dataclass(slots=True)
class ScenarioStoreError(Exception):
    """Reject one unsafe scenario store operation."""

    issue: ScenarioIssue

    @override
    def __str__(self) -> str:
        return self.issue.value


@dataclass(slots=True)
class ScenarioCancelledError(Exception):
    """Roll back all scenario label rows when execution is cancelled."""

    scenario_id: UUID

    @override
    def __str__(self) -> str:
        return "scenario run was cancelled"


def canonical_json(model: BaseModel) -> str:
    """Serialize one validated contract using canonical JSON ordering."""
    return json.dumps(
        model.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256(model: BaseModel) -> str:
    """Hash the canonical JSON representation of one contract."""
    return hashlib.sha256(canonical_json(model).encode()).hexdigest()
