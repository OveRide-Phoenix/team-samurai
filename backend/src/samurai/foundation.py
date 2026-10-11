"""The company-brief workflow contract and its deterministic evidence boundary."""

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final, Literal

from agno.agent import Agent
from agno.skills import LocalSkills, Skills
from agno.workflow import Step, StepInput, StepOutput, Workflow, WorkflowAgent
from pydantic import BaseModel, ConfigDict

from samurai.contracts import CompanyBrief

__all__ = ["CompanyBrief"]

if TYPE_CHECKING:
    from agno.db.base import BaseDb
    from agno.models.google import Gemini

RESOURCES: Final = Path(__file__).parent
WORKFLOW_ID: Final = "company-foundation"
WORKFLOW_NAME: Final = "Samurai — Build My Business"
WORKFLOW_DESCRIPTION: Final = (
    "Clarify a company idea, preserve assumptions, and identify missing context."
)
STARTER_PROMPTS: Final = [
    "Build my business: an AI receptionist for Indian dental clinics. Start with a company brief.",
    "Help me clarify my customer, budget, skills, and goals before planning my business.",
    "What assumptions and unanswered questions remain in our company brief?",
]


class FoundationResult(BaseModel):
    """Verified structure with a deliberately unverified business-evidence status."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)
    brief: CompanyBrief
    missing_context: list[str]
    evidence_status: Literal["unverified"] = "unverified"
    verification_scope: Literal["schema_and_missing_context"] = "schema_and_missing_context"
    next_stage: Literal["research_and_strategy"] = "research_and_strategy"


def verify_brief(step_input: StepInput) -> StepOutput:
    """Reject invalid drafts; do not promote ungrounded claims to verified evidence."""
    brief = CompanyBrief.model_validate(step_input.previous_step_content)
    context = {
        "target_customer": brief.target_customer,
        "geography": brief.geography,
        "budget": brief.budget,
        "founder_skills": brief.founder_skills,
        "goal": brief.goal,
    }
    return StepOutput(
        content=FoundationResult(
            brief=brief,
            missing_context=[name for name, value in context.items() if not value],
        ),
    )


def create_foundation(db: BaseDb, model: Gemini) -> Workflow:
    """Expose one conversational workflow, with skills owned by its brief step."""
    skills = Skills(loaders=[LocalSkills(str(RESOURCES / "skills"))])
    brief_agent = Agent(
        id="company-brief",
        name="Company Brief",
        model=model,
        skills=skills,
        instructions=(RESOURCES / "prompts" / "brief.md").read_text(encoding="utf-8"),
        output_schema=CompanyBrief,
        tool_call_limit=4,
        telemetry=False,
    )
    main_agent = WorkflowAgent(
        model=replace(model),
        instructions=(RESOURCES / "prompts" / "main.md").read_text(encoding="utf-8"),
        num_history_runs=5,
    )
    main_agent.telemetry = False
    return Workflow(
        id=WORKFLOW_ID,
        name=WORKFLOW_NAME,
        description=WORKFLOW_DESCRIPTION,
        db=db,
        agent=main_agent,
        steps=[
            Step(name="Draft company brief", agent=brief_agent, max_retries=0),
            Step(name="Verify brief structure", executor=verify_brief, max_retries=0),
        ],
        add_workflow_history_to_steps=True,
        num_history_runs=5,
        store_events=True,
        telemetry=False,
    )
