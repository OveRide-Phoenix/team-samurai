"""Public prerequisite form contract; no founder data or credentials."""

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict


class IntakeQuestion(BaseModel):
    """A required input supported by the company journey."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    id: Literal["idea", "customer", "location", "budget", "founderSkills", "goal"]
    label: str
    placeholder: str
    multiline: bool = False


class IntakePage(BaseModel):
    """One page in the founder flow."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    title: str
    questions: tuple[IntakeQuestion, ...]


INTAKE_PAGES = (
    IntakePage(
        title="What do you want to build?",
        questions=(
            IntakeQuestion(
                id="idea",
                label="Business idea",
                placeholder="The problem you want to solve, and how.",
                multiline=True,
            ),
        ),
    ),
    IntakePage(
        title="Who is it for?",
        questions=(
            IntakeQuestion(
                id="customer",
                label="Your first customers",
                placeholder="For example, independent dental clinics",
            ),
            IntakeQuestion(
                id="location",
                label="Where will you start?",
                placeholder="City, country or online market",
            ),
        ),
    ),
    IntakePage(
        title="What are you working with?",
        questions=(
            IntakeQuestion(
                id="budget",
                label="Starting budget",
                placeholder="Amount and currency, or no budget yet",
            ),
            IntakeQuestion(
                id="founderSkills",
                label="Your skills and resources",
                placeholder="What can you deliver yourself, and where do you need help?",
                multiline=True,
            ),
            IntakeQuestion(
                id="goal",
                label="Your first milestone",
                placeholder="What would progress look like in 30 days?",
                multiline=True,
            ),
        ),
    ),
)
