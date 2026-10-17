"""Public prerequisite form contract; no founder data or credentials."""

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict


class IntakeQuestion(BaseModel):
    """A required input supported by the existing software-idea journey."""

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
        title="What software idea do you want to explore?",
        questions=(
            IntakeQuestion(
                id="idea",
                label="Software idea",
                placeholder="An app, website or enhancement, and the problem it could solve.",
                multiline=True,
            ),
        ),
    ),
    IntakePage(
        title="Who is it for?",
        questions=(
            IntakeQuestion(
                id="customer",
                label="Your first users or customers",
                placeholder="For example, clinic staff who miss appointment calls",
            ),
            IntakeQuestion(
                id="location",
                label="Where will you start?",
                placeholder="Your first users: city, country or online market",
            ),
        ),
    ),
    IntakePage(
        title="What are you working with?",
        questions=(
            IntakeQuestion(
                id="budget",
                label="Budget for testing and building",
                placeholder="Amount and currency, or no budget yet",
            ),
            IntakeQuestion(
                id="founderSkills",
                label="Your skills and resources",
                placeholder="Your skills, available time, existing tools and help you need",
                multiline=True,
            ),
            IntakeQuestion(
                id="goal",
                label="Your next validation milestone",
                placeholder="What do you want to learn or test about this idea in 30 days?",
                multiline=True,
            ),
        ),
    ),
)
