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
    "overview": "Idea",
    "research": "Problem, demand & market",
    "strategy": "Product, technology & resources",
    "verification": "Validation & delivery",
    "sales": "Sales & distribution",
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
            "text": f"You can also explore {AREA_NAMES[checked]} when useful.",
        }
    )


def team_instructions(area: TeamArea) -> str:
    """Focus software-idea mentoring without gating discussion on another aspect."""
    scopes = {
        "overview": "the software idea, its users and the next validation decision",
        "research": "customer problems, demand, market size and existing alternatives",
        "strategy": "software product scope, technology, feasibility, budget and resources",
        "verification": "validation experiments, evidence quality, delivery risks and review",
        "sales": "customer discovery, sales, distribution and reviewable outreach drafts",
    }
    return (
        f"The founder is exploring {AREA_NAMES[area]}: {scopes[area]}. "
        "Read the owned company state before idea-specific guidance. Preserve its brief, "
        "goal, evidence and decisions. Every aspect is independently discussable: missing "
        "research, technology choices or another aspect never blocks mentoring. Explain "
        "assumptions, gaps and useful links to other aspects without requiring completion "
        "or switching. Suggest another area only as an optional founder-controlled choice; "
        "never redirect or start its work automatically. Shared history is context, not "
        "execution permission. Existing workflow stages, evidence prerequisites and action "
        "approval still govern saved work; do not silently create missing upstream work. "
        "Discussion and generated views are not verified outputs. No outreach, publication "
        "or spending is authorized."
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
        return _prerequisite("overview", "Save your idea brief before starting this work.")
    research = latest.get(ArtifactType.RESEARCH)
    if stage in {"strategy", "plan"} and (research is None or research.status != "complete"):
        return _prerequisite(
            "research",
            "Research evidence is needed before shaping the offer. Start with Researcher.",
        )
    if stage == "plan" and ArtifactType.STRATEGY not in latest:
        return "Shape the offer with Strategist before creating a delivery plan."
    return None
