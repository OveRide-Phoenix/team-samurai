from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, cast

import pytest
from agno.db.sqlite import SqliteDb

from samurai.config import Settings
from samurai.parent import create_parent_agent
from tests.test_parent import _ToolSequenceModel  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from agno.run.agent import RunOutput

from agno.run import RunContext
from pydantic import ValidationError

from samurai.panels import (
    PANEL_MARKER,
    CustomPanel,
    DeclarativePanel,
    compose_panel,
    create_custom_panel,
)


def context(user: str = "founder", session: str = "company") -> RunContext:
    return RunContext(run_id="view-run", user_id=user, session_id=session, session_state={})


def test_views_keep_stable_owner_and_company_scoped_ids() -> None:
    first = compose_panel(context(), "pricing", "Pricing", [{"kind": "text", "text": "Hypothesis"}])
    panel = DeclarativePanel.model_validate_json(first.removeprefix(PANEL_MARKER))
    updated = DeclarativePanel.model_validate_json(
        compose_panel(
            context(),
            "pricing",
            "Revised pricing",
            [{"kind": "text", "text": "Updated"}],
        ).removeprefix(PANEL_MARKER)
    )
    other = DeclarativePanel.model_validate_json(
        compose_panel(
            context("other"),
            "pricing",
            "Pricing",
            [{"kind": "text", "text": "Other"}],
        ).removeprefix(PANEL_MARKER)
    )
    another_company = DeclarativePanel.model_validate_json(
        compose_panel(
            context(session="other-company"),
            "pricing",
            "Pricing",
            [{"kind": "text", "text": "Other"}],
        ).removeprefix(PANEL_MARKER)
    )
    assert panel.id == updated.id
    assert len({panel.id, other.id, another_company.id}) == 3
    assert context().session_state == {}


def test_declarative_boundary_rejects_unknown_components_and_ragged_tables() -> None:
    for block in (
        {"kind": "script", "text": "bad"},
        {"kind": "table", "columns": ["A"], "rows": [["A", "B"]]},
    ):
        with pytest.raises(ValidationError):
            _ = DeclarativePanel.model_validate({"id": "p", "title": "Draft", "blocks": [block]})


def test_custom_views_are_bounded_and_cannot_claim_verification() -> None:
    view = CustomPanel.model_validate_json(
        create_custom_panel(
            context(),
            "calculator",
            "Calculator",
            "<button>Calculate</button>",
            javascript="void 0;",
        ).removeprefix(PANEL_MARKER)
    )
    assert "not verified" in view.note
    with pytest.raises(ValidationError):
        _ = CustomPanel.model_validate({**view.model_dump(), "html": "x" * 60001})
    with pytest.raises(ValidationError):
        _ = CustomPanel.model_validate({**view.model_dump(), "note": "Verified results"})
    with pytest.raises(ValueError, match="Authenticated"):
        _ = compose_panel(context(user=""), "key", "Draft", [{"kind": "text", "text": "x"}])


def test_compose_tool_executes_through_real_agno(tmp_path: Path) -> None:
    model = _ToolSequenceModel(
        "compose_panel",
        arguments={
            "compose_panel": json.dumps(
                {
                    "panel_key": "comparison",
                    "title": "Pilot comparison",
                    "blocks": [
                        {"kind": "text", "text": "Working hypothesis"},
                        {"kind": "table", "columns": ["Customer"], "rows": [["Fictional clinic"]]},
                    ],
                }
            )
        },
    )
    agent = create_parent_agent(
        SqliteDb(db_file=str(tmp_path / "panel-run.db")), Settings.model_validate({}), model=model
    )
    run = cast("Callable[..., Awaitable[RunOutput]]", agent.arun)
    output = asyncio.run(
        run("Compose a view", user_id="founder", session_id="panel-company", stream=False)
    )
    assert output.status is not None
    assert output.status.value == "COMPLETED"
    assert isinstance(output.content, str)
    panel = DeclarativePanel.model_validate_json(output.content.removeprefix(PANEL_MARKER))
    assert panel.title == "Pilot comparison"
    assert panel.blocks[1].kind == "table"
