"""Pure deterministic low, base, and high scenario arithmetic."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field

from samurai.scenario_contracts import (
    PROVENANCE,
    RESULT_LABELS,
    ConstraintOperator,
    ScenarioAssumption,
    ScenarioContract,
    ScenarioDefinition,
    ScenarioLabel,
    normalized_decimal,
    sha256,
)


class ScenarioPoint(ScenarioContract):
    """One deterministic value at a day in the requested horizon."""

    day: int
    value: Decimal


class MetricTrajectory(ScenarioContract):
    """Baseline and horizon endpoint for one metric."""

    metric: str
    unit: str
    points: tuple[ScenarioPoint, ScenarioPoint]


class ScenarioTrajectory(ScenarioContract):
    """Every projected metric under one assumption label."""

    label: ScenarioLabel
    metrics: tuple[MetricTrajectory, ...]


class ScenarioFormula(ScenarioContract):
    """Machine-readable arithmetic and its exact baseline input."""

    metric: str
    expression: Literal["end = baseline * (1 + delta_percent / 100)"]
    baseline_input: Decimal
    assumption: str | None


class ScenarioSensitivity(ScenarioContract):
    """One assumption ranked by its declared percentage range."""

    assumption: str
    target_metric: str
    delta_range_percent: Decimal


class ConstraintFinding(ScenarioContract):
    """One trajectory's deterministic constraint comparison."""

    constraint: str
    label: ScenarioLabel
    metric: str
    operator: ConstraintOperator
    threshold: Decimal
    actual: Decimal
    unit: str
    violated: bool


class ScenarioResultPayload(ScenarioContract):
    """Hashable synthetic analysis without execution identity."""

    provenance: Literal["synthetic_scenario_not_validation"] = PROVENANCE
    company_revision: int
    company_state_sha256: str
    input_sha256: str
    horizon_days: int
    assumptions: tuple[ScenarioAssumption, ...]
    trajectories: tuple[ScenarioTrajectory, ScenarioTrajectory, ScenarioTrajectory]
    formulas: tuple[ScenarioFormula, ...]
    sensitivity: tuple[ScenarioSensitivity, ...]
    constraint_findings: tuple[ConstraintFinding, ...]


class ScenarioResult(ScenarioResultPayload):
    """One content-hashed synthetic result across all three labels."""

    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _delta(assumption: ScenarioAssumption, label: ScenarioLabel) -> Decimal:
    return {
        "low": assumption.low_delta_percent,
        "base": assumption.base_delta_percent,
        "high": assumption.high_delta_percent,
    }[label]


def _trajectory(
    definition: ScenarioDefinition,
    assumption_by_metric: dict[str, ScenarioAssumption],
    label: ScenarioLabel,
) -> ScenarioTrajectory:
    return ScenarioTrajectory(
        label=label,
        metrics=tuple(
            MetricTrajectory(
                metric=metric.name,
                unit=metric.unit,
                points=(
                    ScenarioPoint(day=0, value=metric.value),
                    ScenarioPoint(
                        day=definition.horizon_days,
                        value=normalized_decimal(
                            metric.value
                            * (
                                Decimal(1)
                                + _delta(assumption_by_metric[metric.name], label) / Decimal(100)
                            )
                        )
                        if metric.name in assumption_by_metric
                        else metric.value,
                    ),
                ),
            )
            for metric in definition.baseline_metrics
        ),
    )


def analyze(definition: ScenarioDefinition) -> ScenarioResult:
    """Compute one deterministic three-trajectory result with visible arithmetic."""
    assumption_by_metric = {item.target_metric: item for item in definition.assumptions}
    trajectories = (
        _trajectory(definition, assumption_by_metric, "low"),
        _trajectory(definition, assumption_by_metric, "base"),
        _trajectory(definition, assumption_by_metric, "high"),
    )
    formulas = tuple(
        ScenarioFormula(
            metric=metric.name,
            expression="end = baseline * (1 + delta_percent / 100)",
            baseline_input=metric.value,
            assumption=(
                assumption_by_metric[metric.name].name
                if metric.name in assumption_by_metric
                else None
            ),
        )
        for metric in definition.baseline_metrics
    )
    sensitivity = tuple(
        ScenarioSensitivity(
            assumption=item.name,
            target_metric=item.target_metric,
            delta_range_percent=normalized_decimal(
                item.high_delta_percent - item.low_delta_percent
            ),
        )
        for item in sorted(
            definition.assumptions,
            key=lambda item: (
                -(item.high_delta_percent - item.low_delta_percent),
                item.name,
            ),
        )
    )
    values = {
        (trajectory.label, metric.metric): metric.points[-1].value
        for trajectory in trajectories
        for metric in trajectory.metrics
    }
    findings = tuple(
        ConstraintFinding(
            constraint=constraint.name,
            label=label,
            metric=constraint.metric,
            operator=constraint.operator,
            threshold=constraint.threshold,
            actual=values[(label, constraint.metric)],
            unit=constraint.unit,
            violated=(
                values[(label, constraint.metric)] < constraint.threshold
                if constraint.operator == "minimum"
                else values[(label, constraint.metric)] > constraint.threshold
            ),
        )
        for constraint in definition.constraints
        for label in RESULT_LABELS
    )
    payload = ScenarioResultPayload(
        company_revision=definition.company_revision,
        company_state_sha256=definition.company_state_sha256,
        input_sha256=definition.input_sha256,
        horizon_days=definition.horizon_days,
        assumptions=definition.assumptions,
        trajectories=trajectories,
        formulas=formulas,
        sensitivity=sensitivity,
        constraint_findings=findings,
    )
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
        result_sha256=sha256(payload),
    )
