import re
from typing import Never, cast

import pytest
from agno.agent import Agent
from pydantic import BaseModel, ValidationError

from samurai.agents import (
    FOUNDER_FACING_AGENT_IDS,
    ROLE_CAPABILITIES,
    SKILL_TOOL_NAMES,
    create_role_catalog,
)
from samurai.config import Settings, create_model
from samurai.contracts import Role
from samurai.frameworks import MANIFEST_INVALID, FrameworkValidationError


def test_role_catalog_builds_nine_typed_agents_with_fresh_models() -> None:
    # Given valid local model settings.
    settings = Settings.model_validate({})

    # When the complete role catalog is constructed twice.
    first = create_role_catalog(settings)
    second = create_role_catalog(settings)

    # Then every role has its own model, typed output, bounded skill tools, and prompt blocks.
    assert tuple(first) == tuple(Role)
    assert len({id(role.agent.model) for role in first.values()}) == len(Role)
    assert all(first[role].agent.model is not second[role].agent.model for role in Role)
    preloaded_skill_roles = {
        Role.INTAKE,
        Role.STRATEGIST,
        Role.PRODUCT_MANAGER,
        Role.VERIFIER,
    }
    for role, configured in first.items():
        assert isinstance(configured.agent, Agent)
        if role is Role.RESEARCHER:
            assert configured.agent.output_schema is None
            assert configured.agent.skills is None
            assert configured.capability.tools == ("google_search",)
        elif role in preloaded_skill_roles:
            assert configured.agent.skills is None
            assert configured.capability.tools == ()
            assert "Founder statements belong in supplied_context" in configured.instructions
            assert "Drafting content or configuration does not authorize" in configured.instructions
        else:
            assert isinstance(configured.agent.output_schema, type)
            assert issubclass(configured.agent.output_schema, BaseModel)
            assert configured.agent.skills is not None
            assert configured.agent.skills.get_skill_names() == [
                "evidence-discipline",
                "action-boundaries",
            ]
            assert (
                tuple(tool.name for tool in configured.agent.skills.get_tools()) == SKILL_TOOL_NAMES
            )
        assert configured.agent.tool_call_limit == settings.agent_tool_call_limit
        assert configured.capability == ROLE_CAPABILITIES[role]
        assert re.findall(r"<([a-z-]+)(?: [^>]*)?>", configured.instructions) == [
            "evidence-boundary",
            "action-boundary",
            "role",
        ]


def test_intake_and_review_roles_preload_only_their_reviewed_frameworks() -> None:
    catalog = create_role_catalog(Settings.model_validate({}))

    assert "## Validated skill: company-intake" in catalog[Role.INTAKE].instructions
    assert "## Founder framework: founder_truth@1.0.0" in catalog[Role.INTAKE].instructions
    assert "## Founder framework: offer_diagnostic@1.0.0" not in catalog[Role.INTAKE].instructions
    assert "## Founder framework: founder_truth@1.0.0" in catalog[Role.STRATEGIST].instructions
    assert "## Founder framework: offer_diagnostic@1.0.0" in catalog[Role.STRATEGIST].instructions
    assert "## Founder framework: founder_truth@1.0.0" in catalog[Role.VERIFIER].instructions
    assert "## Founder framework: offer_diagnostic@1.0.0" in catalog[Role.VERIFIER].instructions
    no_tool_roles = (Role.INTAKE, Role.STRATEGIST, Role.VERIFIER)
    assert all(catalog[role].agent.skills is None for role in no_tool_roles)


def test_invalid_frameworks_fail_before_model_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a framework boundary failure and an observable model factory.
    model_calls = 0

    def reject_frameworks() -> Never:
        raise FrameworkValidationError(MANIFEST_INVALID)

    def count_model_calls(_settings: Settings) -> Never:
        nonlocal model_calls
        model_calls += 1
        message = "model construction must not start"
        raise AssertionError(message)

    monkeypatch.setattr("samurai.agents.load_framework_catalog", reject_frameworks)
    monkeypatch.setattr("samurai.agents.create_model", count_model_calls)

    # When role construction starts, then it fails before constructing any model.
    with pytest.raises(FrameworkValidationError, match="manifest_invalid"):
        _ = create_role_catalog(Settings.model_validate({}))
    assert model_calls == 0


def test_role_catalog_reports_honest_capability_states() -> None:
    assert {role: capability.status for role, capability in ROLE_CAPABILITIES.items()} == {
        Role.INTAKE: "active",
        Role.RESEARCHER: "active",
        Role.STRATEGIST: "active",
        Role.PRODUCT_MANAGER: "active",
        Role.BUILDER: "draft_only",
        Role.MARKETER: "draft_only",
        Role.SALES: "draft_only",
        Role.ANALYST: "requires_metrics",
        Role.VERIFIER: "active",
    }


def test_analyst_model_only_owns_findings_and_recommendations() -> None:
    analyst = create_role_catalog(Settings.model_validate({}))[Role.ANALYST].agent
    output_schema = analyst.output_schema

    assert isinstance(output_schema, type)
    assert issubclass(output_schema, BaseModel)
    schema = output_schema.model_json_schema()
    properties = cast("dict[str, object]", schema["properties"])
    assert tuple(properties) == ("findings", "recommendations")
    assert schema["required"] == ["findings", "recommendations"]
    assert schema["additionalProperties"] is False


def test_model_factory_applies_budgets_to_each_fresh_model() -> None:
    settings = Settings.model_validate({})

    first = create_model(settings)
    second = create_model(settings)

    assert first is not second
    assert first.id == settings.gemini_model
    assert first.max_output_tokens == settings.gemini_max_output_tokens
    assert first.timeout == settings.gemini_timeout_seconds
    assert settings.gemini_max_input_chars == 20_000


def test_specialists_are_ineligible_for_founder_facing_registration() -> None:
    specialist_ids = {
        configured.agent_id
        for configured in create_role_catalog(Settings.model_validate({})).values()
    }

    assert frozenset({"samurai"}) == FOUNDER_FACING_AGENT_IDS
    assert specialist_ids.isdisjoint(FOUNDER_FACING_AGENT_IDS)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("gemini_max_input_chars", 0),
        ("gemini_max_output_tokens", 0),
        ("gemini_timeout_seconds", 0),
        ("agent_tool_call_limit", 0),
        ("agent_tool_call_limit", 17),
    ],
)
def test_invalid_model_budget_fails_without_revealing_secrets(
    field: str,
    value: int,
) -> None:
    # Given one invalid runtime budget and a secret that must stay redacted.
    redacted_value = "private-key-material-0000000000000000"

    # When settings parse the invalid boundary, then validation fails without the secret value.
    with pytest.raises(ValidationError) as raised:
        _ = Settings.model_validate({"os_security_key": redacted_value, field: value})

    assert redacted_value not in str(raised.value)
