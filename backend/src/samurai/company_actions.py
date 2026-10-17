"""Founder actions derived from canonical state; execution still enforces its guards."""

from __future__ import annotations

from typing import Literal

from samurai.company_workflow import (
    JourneyStage,
    has_critical_contradiction,
    supported_research_claim,
)
from samurai.contracts import (
    ArtifactType,
    CompanyState,
    Contract,
    ResearchArtifact,
    current_artifacts,
)
from samurai.launch_workflows import MissingVerifiedLaunchInputsError, verified_launch_inputs
from samurai.team_areas import TeamArea  # noqa: TC001 - Pydantic resolves this annotation.

type ActionId = Literal[
    "brief", "research", "strategy", "plan", "verify", "sales", "builder", "marketer", "metrics"
]


class CompanyAction(Contract):
    """One bounded operation and its canonical prerequisite decision."""

    id: ActionId
    label: str
    prompt: str
    operation: Literal["journey", "launch_drafts", "metrics_analysis"]
    stage: JourneyStage
    area: TeamArea
    eligible: bool
    blocked_reason: str | None


def company_actions(state: CompanyState) -> tuple[ActionId, tuple[CompanyAction, ...]]:
    """Return the recommended step and visible actions without running any work."""
    latest = current_artifacts(state)
    intake = latest.get(ArtifactType.INTAKE)
    research = latest.get(ArtifactType.RESEARCH)
    strategy = latest.get(ArtifactType.STRATEGY)
    product = latest.get(ArtifactType.PRODUCT_PLAN)
    verification = latest.get(ArtifactType.VERIFICATION)
    brief_ready = intake is not None and intake.status == "complete"
    brief_reason = (
        None if brief_ready else "Complete the company brief and its open questions first."
    )
    evidence_reason = None
    if not brief_ready:
        evidence_reason = brief_reason
    elif research is None:
        evidence_reason = "Research your market first."
    elif (
        research.status != "complete"
        or not ResearchArtifact.model_validate(research.payload).is_adjudicated
    ):
        evidence_reason = "Research needs source review before shaping an offer."
    elif has_critical_contradiction(research):
        evidence_reason = "Resolve conflicting research before shaping an offer."
    elif supported_research_claim(research) is None:
        evidence_reason = "A retained source must support the customer problem first."
    try:
        _ = verified_launch_inputs(state)
        launch_reason = None
    except MissingVerifiedLaunchInputsError:
        launch_reason = "Verify the current offer and delivery plan before preparing launch drafts."
    plan_reason = evidence_reason or ("Shape your offer first." if strategy is None else None)
    verify_reason = (
        "Finish research, the offer and delivery plan first."
        if any(item is None for item in (intake, research, strategy, product))
        else None
    )
    research_retry = research is not None and evidence_reason is not None and brief_ready
    specs: tuple[
        tuple[
            ActionId,
            str,
            str,
            Literal["journey", "launch_drafts", "metrics_analysis"],
            JourneyStage,
            TeamArea,
            str | None,
        ],
        ...,
    ] = (
        (
            "brief",
            "Refine brief" if intake else "Save brief",
            "Prepare my brief using stage=brief. Preserve my inputs and ask for missing context.",
            "journey",
            "brief",
            "overview",
            None,
        ),
        (
            "research",
            "Research again" if research_retry else "Research market",
            "Research again using stage=research. Resolve gaps; stop before shaping the offer."
            if research_retry
            else "Research our market using stage=research. Stop before shaping the offer.",
            "journey",
            "research",
            "research",
            brief_reason
            if not brief_ready
            else "Review the retained research before requesting new work."
            if research and not research_retry
            else None,
        ),
        (
            "strategy",
            "Shape offer",
            "Shape our offer and positioning using stage=strategy. Stop before delivery planning.",
            "journey",
            "strategy",
            "strategy",
            evidence_reason,
        ),
        (
            "plan",
            "Plan delivery",
            "Prepare our delivery plan using stage=plan from the existing research and offer.",
            "journey",
            "plan",
            "strategy",
            plan_reason,
        ),
        (
            "verify",
            "Run verification",
            "Verify existing artifacts using stage=verify. Do not rerun upstream stages.",
            "journey",
            "verify",
            "verification",
            verify_reason,
        ),
        (
            "sales",
            "Prepare sales",
            "Prepare only kind=sales drafts from verified inputs. Do not contact anyone.",
            "launch_drafts",
            "plan",
            "sales",
            launch_reason,
        ),
        (
            "builder",
            "Prepare build draft",
            "Prepare only kind=builder reviewable drafts. Do not deploy or publish.",
            "launch_drafts",
            "plan",
            "overview",
            launch_reason,
        ),
        (
            "marketer",
            "Prepare marketing",
            "Prepare only kind=marketer reviewable drafts. Do not publish, send or spend.",
            "launch_drafts",
            "plan",
            "overview",
            launch_reason,
        ),
        (
            "metrics",
            "Review measurements",
            "Ask for measured values and provenance before analysis. Do not invent measurements.",
            "metrics_analysis",
            "plan",
            "overview",
            None if intake else "Save your company brief first.",
        ),
    )
    actions = tuple(
        CompanyAction(
            id=id_,
            label=label,
            prompt=prompt,
            operation=operation,
            stage=stage,
            area=area,
            eligible=reason is None,
            blocked_reason=reason,
        )
        for id_, label, prompt, operation, stage, area, reason in specs
    )
    next_action: ActionId = (
        "brief"
        if not brief_ready
        else "research"
        if research is None or research_retry
        else "strategy"
        if strategy is None
        else "plan"
        if product is None
        else "verify"
        if verification is None or launch_reason
        else "sales"
    )
    return next_action, actions
