import pytest
from agno.workflow import StepInput
from pydantic import ValidationError

from samurai.foundation import CompanyBrief, FoundationResult, verify_brief


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
