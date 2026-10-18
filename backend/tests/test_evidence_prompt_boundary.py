from typing import cast

from agno.db.sqlite import SqliteDb

from samurai.agents import create_role_catalog
from samurai.config import Settings
from samurai.parent import create_parent_agent


def test_founder_context_boundary_is_present_without_loading_optional_skill() -> None:
    settings = Settings.model_validate({})
    parent = create_parent_agent(SqliteDb(), settings)
    assert parent.name == "Proofseed"
    assert parent.id == "samurai"
    instructions = cast("list[str]", parent.instructions)
    parent_prompt = "\n".join(instructions)
    assert '"Founder-provided context", never "Verified facts"' in parent_prompt
    for role in create_role_catalog(settings).values():
        assert '"Founder-provided context", never\n"Verified facts"' in role.instructions
