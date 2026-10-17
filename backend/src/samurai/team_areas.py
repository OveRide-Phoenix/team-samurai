"""Founder-selected team areas narrow execution without changing company ownership."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final, Literal

from pydantic import TypeAdapter

from samurai.contracts import ArtifactType, current_artifacts

if TYPE_CHECKING:
    from samurai.company_workflow import JourneyStage
    from samurai.contracts import CompanyState

type TeamArea = Literal["overview", "research", "strategy", "verification", "sales"]
AREA_ADAPTER: Final = TypeAdapter(TeamArea)
AREA_NAMES: Final = {
    "overview": "Company",
    "research": "Researcher",
    "strategy": "Strategist",
    "verification": "Verifier",
    "sales": "Sales",
}
HANDOFF_MARKER: Final = "SAMURAI_HANDOFF="


def selected_area(props: dict[str, object]) -> TeamArea:
    """Accept only a navigation choice, never identity or execution dependencies."""
    if props and set(props) != {"team_area"}:
        message = "Only a team area may be forwarded"
        raise ValueError(message)
    return AREA_ADAPTER.validate_python(props.get("team_area", "overview"))


def suggest_team_area(area: TeamArea) -> str:
    """Suggest a team switch without switching or starting work for the founder."""
    checked = AREA_ADAPTER.validate_python(area)
    return HANDOFF_MARKER + json.dumps(
        {
            "area": checked,
            "text": f"This belongs with {AREA_NAMES[checked]}. Switch there to continue.",
        }
    )


def team_instructions(area: TeamArea) -> str:
    """Keep the current conversation focused while retaining shared company context."""
    if area == "overview":
        return "Company overview: help the founder choose the next team area."
    scopes = {
        "research": "market research, competitors, customer problems and source evidence",
        "strategy": "positioning, the offer, pricing and product/delivery planning",
        "verification": "existing evidence, conflicting claims, unsupported assumptions and review",
        "sales": "qualified prospects, customer discovery and reviewable sales drafts",
    }
    return (
        f"The founder is in the {AREA_NAMES[area]} team area. Stay within {scopes[area]}. "
        "Read the owned company state before giving company-specific guidance. Preserve its "
        "brief, goal, evidence and decisions. Shared history is context, not permission to "
        "execute a task from another area. If the request belongs to another area, call "
        "suggest_team_area and stop; do not answer or execute that task here. For unrelated "
        "topics, briefly return to this area's business goal. Research uses stage=research; "
        "strategy uses stage=strategy or plan after prerequisites; verification uses stage=verify "
        "on existing artifacts; sales creates only kind=sales drafts. Never create missing "
        "upstream work silently. No outreach, publication or spending is authorized."
    )


def _prerequisite(area: TeamArea, message: str) -> str:
    return HANDOFF_MARKER + json.dumps(
        {
            "area": area,
            "text": message,
            "prerequisite": True,
        }
    )


def journey_handoff(area: TeamArea, stage: JourneyStage, state: CompanyState | None) -> str | None:
    """Refuse another area's execution and missing upstream work before model calls."""
    destinations: dict[JourneyStage, TeamArea] = {
        "brief": "overview",
        "research": "research",
        "strategy": "strategy",
        "plan": "strategy",
        "verify": "verification",
    }
    if area == "overview":
        return None
    if destinations[stage] != area:
        return suggest_team_area(destinations[stage])
    latest = {} if state is None else current_artifacts(state)
    if ArtifactType.INTAKE not in latest:
        return _prerequisite("overview", "Save your company brief before starting this work.")
    research = latest.get(ArtifactType.RESEARCH)
    if stage in {"strategy", "plan"} and (research is None or research.status != "complete"):
        return _prerequisite(
            "research",
            "Research evidence is needed before shaping the offer. Start with Researcher.",
        )
    if stage == "plan" and ArtifactType.STRATEGY not in latest:
        return "Shape the offer with Strategist before creating a delivery plan."
    return None
