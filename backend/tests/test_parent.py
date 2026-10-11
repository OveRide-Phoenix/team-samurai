from __future__ import annotations

from typing import TYPE_CHECKING, cast
from uuid import UUID

from agno.db.sqlite import SqliteDb
from agno.tools.function import Function

from samurai.config import Settings
from samurai.parent import (
    PARENT_AGENT_ID,
    child_session_id,
    create_parent_agent,
)

if TYPE_CHECKING:
    import pathlib


def test_parent_exposes_only_four_bounded_business_tools(tmp_path: pathlib.Path) -> None:
    agent = create_parent_agent(
        SqliteDb(db_file=str(tmp_path / "parent.db")),
        Settings.model_validate({}),
    )

    assert agent.id == PARENT_AGENT_ID
    assert agent.tool_call_limit == Settings.model_validate({}).agent_tool_call_limit
    raw_tools = cast("object", agent.tools)
    assert isinstance(raw_tools, list)
    tools = cast("list[object]", raw_tools)
    assert {tool.name for tool in tools if isinstance(tool, Function)} == {
        "run_company_journey",
        "create_launch_drafts",
        "analyze_metrics",
        "read_company_state",
    }
    assert agent.skills is not None
    assert {tool.name for tool in agent.skills.get_tools()} == {
        "get_skill_instructions",
        "get_skill_reference",
    }
    assert all(tool.stop_after_tool_call for tool in agent.skills.get_tools())


def test_child_session_is_deterministic_and_scoped_to_trusted_owner() -> None:
    first = child_session_id("founder-a", "parent-session")

    assert UUID(first)
    assert first == child_session_id("founder-a", "parent-session")
    assert first != child_session_id("founder-b", "parent-session")
    assert first != child_session_id("founder-a", "other-parent-session")
    assert child_session_id("a:b", "c") != child_session_id("a", "b:c")
