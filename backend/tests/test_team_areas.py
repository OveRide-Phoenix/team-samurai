"""Independent mentor aspects preserve ownership and bounded execution."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import anyio
import pytest
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from pydantic import ValidationError

from samurai.config import Settings
from samurai.panels import PANEL_MARKER
from samurai.parent import child_session_id, create_parent_agent
from samurai.team_areas import HANDOFF_MARKER, selected_area
from tests.test_agui import fixture, payload
from tests.test_parent import _run_agent, _ToolSequenceModel  # pyright: ignore[reportPrivateUsage] - deterministic model.

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "props",
    [
        {"team_area": "unknown"},
        {"team_area": "research", "user_id": "other"},
        {"company_id": "foreign"},
        {"team_area": 1},
    ],
)
def test_team_area_cannot_forward_identity_or_unknown_modes(props: dict[str, object]) -> None:
    with pytest.raises((ValueError, ValidationError)):
        _ = selected_area(props)


@pytest.mark.parametrize(
    ("tool", "arguments", "target"),
    [
        ("run_company_journey", {"stage": "strategy"}, "strategy"),
        ("create_launch_drafts", {"kind": "sales"}, "sales"),
        ("analyze_metrics", {}, "overview"),
    ],
)
def test_research_area_refuses_other_workflows_before_child_execution(
    tmp_path: Path,
    tool: str,
    arguments: dict[str, str],
    target: str,
) -> None:
    db = SqliteDb(db_file=str(tmp_path / "scoped.db"))
    args = arguments
    if tool == "run_company_journey":
        args = {
            "idea": "Keep this idea",
            "target_customer": "",
            "geography": "",
            "budget": "",
            "founder_skills": "",
            "goal": "",
            **arguments,
        }
    model = _ToolSequenceModel(tool, arguments={tool: json.dumps(args)})
    agent = create_parent_agent(db, Settings.model_validate({}), model=model, team_area="research")
    run = anyio.run(_run_agent, agent, "Change our pricing", "company")
    assert isinstance(run.content, str)
    assert run.content.startswith(HANDOFF_MARKER)
    assert json.loads(run.content[len(HANDOFF_MARKER) :])["area"] == target
    assert (
        db.get_session(child_session_id("founder", "company"), session_type=SessionType.WORKFLOW)
        is None
    )


def test_http_area_is_retained_in_owned_run_and_foreign_context_stays_blocked(
    tmp_path: Path,
) -> None:
    client, headers, _ = fixture(tmp_path)
    with client:
        response = client.post(
            "/agentos/agents/samurai/agui",
            json=payload(forwardedProps={"team_area": "research"}),
            headers=headers,
        )
        saved = client.get(
            "/agentos/agents/samurai/runs/view-run?session_id=company-1", headers=headers
        )
        forged = client.post(
            "/agentos/agents/samurai/agui",
            json=payload(
                runId="other", forwardedProps={"team_area": "research", "user_id": "other"}
            ),
            headers=headers,
        )
    assert response.status_code == 200
    assert saved.status_code == 200
    assert saved.json()["metadata"]["team_area"] == "research"
    assert forged.status_code == 422


@pytest.mark.parametrize("area", ["overview", "research", "sales", "strategy", "verification"])
def test_aspect_can_read_then_compose_without_upstream_work(tmp_path: Path, area: str) -> None:
    # Given an authenticated mentor conversation with no saved brief or evidence.
    model = _ToolSequenceModel(
        "read_company_state",
        "compose_panel",
        arguments={
            "compose_panel": json.dumps(
                {
                    "panel_key": "working-assumptions",
                    "title": "Working assumptions",
                    "blocks": [{"kind": "text", "text": "Scope and costs are assumptions."}],
                }
            )
        },
    )
    client, headers, db = fixture(tmp_path, model)
    # When the founder discusses an aspect before completing any other aspect.
    with client:
        response = client.post(
            "/agentos/agents/samurai/agui",
            json=payload(forwardedProps={"team_area": area}),
            headers=headers,
        )
    # Then state recall can continue into a draft view without child execution.
    assert response.status_code == 200
    assert PANEL_MARKER in response.text
    assert HANDOFF_MARKER not in response.text
    assert model.calls == 2
    for tool in ("run_company_journey", "create_launch_drafts", "analyze_metrics"):
        assert tool not in model.advertised_tools_json
    assert (
        db.get_session(child_session_id("founder", "company-1"), session_type=SessionType.WORKFLOW)
        is None
    )
