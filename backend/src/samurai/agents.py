"""Typed construction for Samurai's internal role agents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from agno.agent import Agent
from agno.skills import LocalSkills, Skills

from samurai.config import Settings, create_model
from samurai.contracts import (
    AnalysisArtifact,
    ArtifactType,
    BuilderDraftArtifact,
    IntakeArtifact,
    MarketingDraftArtifact,
    ProductPlanArtifact,
    Role,
    RoleCapability,
    SalesDraftArtifact,
    StrategyArtifact,
    VerificationArtifact,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pydantic import BaseModel

RESOURCES: Final = Path(__file__).parent
FOUNDER_FACING_AGENT_IDS: Final = frozenset({"samurai"})
SKILL_TOOL_NAMES: Final = (
    "get_skill_instructions",
    "get_skill_reference",
    "get_skill_script",
)
RESEARCH_TOOL_NAMES: Final = ("google_search",)
PRELOADED_SKILL_ROLES: Final = frozenset(
    {Role.INTAKE, Role.STRATEGIST, Role.PRODUCT_MANAGER, Role.VERIFIER}
)


@dataclass(frozen=True, slots=True)
class _RoleSpec:
    role: Role
    name: str
    output_schema: type[BaseModel] | None
    capability_status: Literal["active", "draft_only", "requires_metrics"]
    output_artifact: ArtifactType

    @property
    def agent_id(self) -> str:
        return f"samurai-{self.role.value.replace('_', '-')}"


@dataclass(frozen=True, slots=True)
class ConfiguredRole:
    """One internal role agent paired with its declared capability."""

    agent_id: str
    agent: Agent
    capability: RoleCapability
    instructions: str


ROLE_SPECS: Final = (
    _RoleSpec(Role.INTAKE, "Intake", IntakeArtifact, "active", ArtifactType.INTAKE),
    _RoleSpec(
        Role.RESEARCHER,
        "Researcher",
        None,
        "active",
        ArtifactType.RESEARCH,
    ),
    _RoleSpec(
        Role.STRATEGIST,
        "Strategist",
        StrategyArtifact,
        "active",
        ArtifactType.STRATEGY,
    ),
    _RoleSpec(
        Role.PRODUCT_MANAGER,
        "Product Manager",
        ProductPlanArtifact,
        "active",
        ArtifactType.PRODUCT_PLAN,
    ),
    _RoleSpec(
        Role.BUILDER,
        "Builder",
        BuilderDraftArtifact,
        "draft_only",
        ArtifactType.BUILDER_DRAFT,
    ),
    _RoleSpec(
        Role.MARKETER,
        "Marketer",
        MarketingDraftArtifact,
        "draft_only",
        ArtifactType.MARKETING_DRAFT,
    ),
    _RoleSpec(
        Role.SALES,
        "Sales",
        SalesDraftArtifact,
        "draft_only",
        ArtifactType.SALES_DRAFT,
    ),
    _RoleSpec(
        Role.ANALYST,
        "Analyst",
        AnalysisArtifact,
        "requires_metrics",
        ArtifactType.ANALYSIS,
    ),
    _RoleSpec(
        Role.VERIFIER,
        "Verifier",
        VerificationArtifact,
        "active",
        ArtifactType.VERIFICATION,
    ),
)


def _capability(spec: _RoleSpec) -> RoleCapability:
    tools = SKILL_TOOL_NAMES
    if spec.role is Role.RESEARCHER:
        tools = RESEARCH_TOOL_NAMES
    elif spec.role in PRELOADED_SKILL_ROLES:
        tools = ()
    return RoleCapability(
        role=spec.role,
        status=spec.capability_status,
        output_artifact=spec.output_artifact,
        tools=tools,
    )


ROLE_CAPABILITIES: Final[Mapping[Role, RoleCapability]] = MappingProxyType(
    {spec.role: _capability(spec) for spec in ROLE_SPECS}
)


def _read_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _role_instructions(role: Role) -> str:
    prompts = RESOURCES / "prompts"
    return "\n\n".join(
        (
            _read_prompt(prompts / "shared" / "evidence.md"),
            _read_prompt(prompts / "shared" / "actions.md"),
            _read_prompt(prompts / "roles" / f"{role.value}.md"),
        )
    )


def _skills() -> Skills:
    skills = RESOURCES / "skills"
    return Skills(
        loaders=[
            LocalSkills(str(skills / "evidence-discipline"), validate=True),
            LocalSkills(str(skills / "action-boundaries"), validate=True),
        ]
    )


def _preloaded_skill_instructions(skills: Skills) -> str:
    return "\n\n".join(
        f"## Validated skill: {skill.name}\n{skill.instructions}"
        for skill in skills.get_all_skills()
    )


def create_role_catalog(settings: Settings) -> Mapping[Role, ConfiguredRole]:
    """Build all internal role bases with independent models and validated skills."""
    catalog: dict[Role, ConfiguredRole] = {}
    for spec in ROLE_SPECS:
        instructions = _role_instructions(spec.role)
        runtime_skills: Skills | None = None
        if spec.role is not Role.RESEARCHER:
            validated_skills = _skills()
            if spec.role in PRELOADED_SKILL_ROLES:
                instructions = "\n\n".join(
                    (instructions, _preloaded_skill_instructions(validated_skills))
                )
            else:
                runtime_skills = validated_skills
        model = create_model(settings)
        model.search = spec.role is Role.RESEARCHER
        catalog[spec.role] = ConfiguredRole(
            agent_id=spec.agent_id,
            agent=Agent(
                id=spec.agent_id,
                name=spec.name,
                model=model,
                skills=runtime_skills,
                instructions=instructions,
                output_schema=spec.output_schema,
                tool_call_limit=settings.agent_tool_call_limit,
                telemetry=False,
            ),
            capability=ROLE_CAPABILITIES[spec.role],
            instructions=instructions,
        )
    return catalog
