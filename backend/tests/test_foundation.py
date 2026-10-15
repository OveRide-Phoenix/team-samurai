import pytest
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.workflow import Step, StepInput
from pydantic import ValidationError

from samurai.config import Settings
from samurai.foundation import CompanyBrief, FoundationResult, create_foundation, verify_brief


def test_verified_structure_preserves_unverified_business_claims() -> None:
    # Given a brief with customer demand still untested.
    brief = CompanyBrief(
        idea="Dental receptionist",
        target_customer="Indian dental clinics",
        geography="India",
        budget=None,
        founder_skills=None,
        goal=None,
        supplied_context=["Founder proposes an AI receptionist"],
        assumptions=["Clinics may pay for missed-call handling"],
        open_questions=["What is the budget?"],
        next_actions=["Interview five clinic owners"],
    )
    # When the deterministic verifier processes the draft.
    result = verify_brief(StepInput(previous_step_content=brief))
    # Then schema checks cannot promote market assumptions into evidence.
    assert isinstance(result.content, FoundationResult)
    assert result.content.evidence_status == "unverified"
    assert result.content.missing_context == ["budget", "founder_skills", "goal"]
    assert result.content.brief == brief


def test_verifier_rejects_missing_brief() -> None:
    # Given no usable output from the draft step.
    # When verification runs, then it must fail rather than invent a result.
    with pytest.raises(ValidationError):
        _ = verify_brief(StepInput(previous_step_content=None))


def test_foundation_preloads_the_explicit_reviewed_skill_allowlist() -> None:
    workflow = create_foundation(SqliteDb(db_file=":memory:"), Settings.model_validate({}))
    steps = workflow.steps
    assert isinstance(steps, list)
    draft_step = steps[0]
    assert isinstance(draft_step, Step)
    brief_agent = draft_step.agent
    assert isinstance(brief_agent, Agent)
    instructions: object = brief_agent.instructions  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    assert isinstance(instructions, str)

    assert brief_agent.skills is None
    assert "## Validated skill: company-intake" in instructions
