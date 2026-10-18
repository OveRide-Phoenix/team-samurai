from __future__ import annotations

import json
from typing import TYPE_CHECKING, Never

import anyio
import pytest
from agno.db.sqlite import SqliteDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus

from samurai.config import Settings
from samurai.panels import PANEL_MARKER, DeclarativePanel
from samurai.parent import create_parent_agent
from tests.test_parent import ToolSequenceModel

if TYPE_CHECKING:
    from pathlib import Path

    from agno.models.message import Message
    from agno.models.response import ModelResponse


def panel_arguments(*, corrected: bool) -> str:
    return json.dumps(
        {
            "panel_key": "validation-budget",
            "title": "Validation budget estimates",
            "blocks": [
                {
                    "kind": "table",
                    "columns": ["Item", "Estimated INR", "Free alternative", "Assumption"],
                    "rows": (
                        [["Travel", "3500", "Walk", "Managers are reachable"]]
                        if corrected
                        else ["Travel", "3500", "Walk", "Managers are reachable"]
                    ),
                },
                {
                    "kind": "list",
                    "title": "Safeguards",
                    ("items" if corrected else '"items'): ["No software spend before interviews"],
                },
            ],
        }
    )


@pytest.mark.parametrize("stream", [False, True])
def test_malformed_panel_is_corrected_within_the_same_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, stream: bool
) -> None:
    original = ToolSequenceModel.ainvoke

    async def respond(
        current: ToolSequenceModel,
        messages: list[Message],
        **kwargs: Never,
    ) -> ModelResponse:
        current.arguments["compose_panel"] = panel_arguments(corrected=current.calls > 0)
        if current.calls:
            assert any(message.tool_call_error for message in messages)
        return await original(current, messages, **kwargs)

    monkeypatch.setattr(ToolSequenceModel, "ainvoke", respond)
    model = ToolSequenceModel("compose_panel", "compose_panel")
    agent = create_parent_agent(
        SqliteDb(db_file=str(tmp_path / "panel-repair.db")),
        Settings.model_validate({}),
        model=model,
    )

    async def scenario() -> RunOutput:
        if stream:
            events = [
                event
                async for event in agent.arun(
                    "Show a draft validation budget",
                    user_id="founder",
                    session_id="panel-repair",
                    stream=True,
                    stream_events=True,
                    yield_run_output=True,
                )
            ]
            outputs = [event for event in events if isinstance(event, RunOutput)]
            assert len(outputs) == 1
            return outputs[0]
        return await agent.arun(
            "Show a draft validation budget",
            user_id="founder",
            session_id="panel-repair",
            stream=False,
        )

    output = anyio.run(scenario)
    assert output.status == RunStatus.completed
    assert model.calls == 2
    assert isinstance(output.content, str)
    panel = DeclarativePanel.model_validate_json(output.content.removeprefix(PANEL_MARKER))
    assert panel.blocks[0].kind == "table"
    assert panel.blocks[0].rows == [["Travel", "3500", "Walk", "Managers are reachable"]]
    assert output.tools
    assert len(output.tools) == 2
    assert output.tools[0].tool_call_error
    assert not output.tools[0].stop_after_tool_call
    assert not output.tools[1].tool_call_error
    assert output.tools[1].stop_after_tool_call


def test_repeated_invalid_panels_still_stop_at_the_existing_model_budget(tmp_path: Path) -> None:
    settings = Settings.model_validate({"agent_tool_call_limit": 2})
    model = ToolSequenceModel(
        "compose_panel", repeat=True, arguments={"compose_panel": panel_arguments(corrected=False)}
    )
    agent = create_parent_agent(
        SqliteDb(db_file=str(tmp_path / "panel-budget.db")), settings, model=model
    )

    async def scenario() -> RunOutput:
        return await agent.arun(
            "Show a draft budget", user_id="founder", session_id="panel-budget", stream=False
        )

    output = anyio.run(scenario)
    assert output.status == RunStatus.error
    assert model.calls == settings.agent_tool_call_limit + 1


def test_unrepaired_panel_error_is_not_reported_as_success(tmp_path: Path) -> None:
    model = ToolSequenceModel(
        "compose_panel", arguments={"compose_panel": panel_arguments(corrected=False)}
    )
    agent = create_parent_agent(
        SqliteDb(db_file=str(tmp_path / "unrepaired-panel.db")),
        Settings.model_validate({}),
        model=model,
    )

    async def scenario() -> RunOutput:
        return await agent.arun(
            "Show a draft budget", user_id="founder", session_id="panel-error", stream=False
        )

    output = anyio.run(scenario)
    assert model.calls == 2
    assert output.status == RunStatus.error
