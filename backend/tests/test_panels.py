from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, cast

import pytest
from agno.db.sqlite import SqliteDb
from agno.utils.gemini import format_function_definitions
from google.genai.types import GenerateContentConfig, Tool

from samurai.config import Settings, create_model
from samurai.parent import create_parent_agent
from tests.test_parent import _ToolSequenceModel  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from agno.run.agent import RunOutput

from agno.run import RunContext
from pydantic import ValidationError

from samurai.panels import (
    COMPOSE_PARAMETERS,
    PANEL_MARKER,
    CustomPanel,
    DeclarativePanel,
    compose_panel,
    create_custom_panel,
    presentation_tools,
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
        {"type": "text", "content": "Wrong fields"},
        {"kind": "text", "title": "Not a text field", "text": "Hypothesis"},
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


def test_gemini_receives_the_compose_block_catalog() -> None:
    tool = format_function_definitions(
        [{"type": "function", "function": presentation_tools()[0].to_dict()}]
    )
    assert tool is not None
    assert tool.function_declarations
    declaration = tool.function_declarations[0]
    assert declaration.description
    assert declaration.parameters is not None
    assert declaration.parameters.properties is not None
    blocks = declaration.parameters.properties["blocks"]
    assert blocks.items is not None
    assert blocks.items.any_of
    expected = {
        "text": {"kind", "text"},
        "metric": {"kind", "label", "value", "detail"},
        "list": {"kind", "title", "items"},
        "table": {"kind", "columns", "rows"},
    }
    assert len(blocks.items.any_of) == len(expected)
    for block in blocks.items.any_of:
        assert block.properties is not None
        tags = block.properties["kind"].enum
        assert tags
        assert len(tags) == 1
        assert set(block.properties) == expected[tags[0]]
        assert set(block.required or []) == expected[tags[0]]


def test_gemini_preserves_strict_panel_json_schema_and_optional_text() -> None:
    model = create_model(Settings.model_validate({}))
    params = model.get_request_params(
        tools=[{"type": "function", "function": presentation_tools()[0].to_dict()}],
        tool_choice="validated",
    )
    config = params["config"]
    assert isinstance(config, GenerateContentConfig)
    assert config.tool_config is not None
    assert config.tool_config.function_calling_config is not None
    assert config.tool_config.function_calling_config.mode == "VALIDATED"
    tools = cast("list[object] | None", config.tools)
    assert tools
    tool = tools[0]
    assert isinstance(tool, Tool)
    assert tool.function_declarations
    declaration = tool.function_declarations[0]
    assert declaration.parameters is None
    assert cast("object", declaration.parameters_json_schema) == COMPOSE_PARAMETERS
