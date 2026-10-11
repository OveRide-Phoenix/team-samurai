"""Run one sanitized Gemini Search grounding smoke check."""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import redirect_stdout
from functools import partial
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Literal, override

import anyio
from agno.models.google import Gemini
from agno.utils.log import set_log_level_to_error

if TYPE_CHECKING:
    from agno.run.agent import RunOutput

# ─── How to run ───
# uv run python scripts/smoke_research.py --idea "AI receptionist for Indian dental clinics"

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from samurai.agents import create_role_catalog
from samurai.config import Settings
from samurai.contracts import CompanyBrief, Role
from samurai.research import MAX_SOURCES, ResearchAgent, run_research


class SmokeError(Exception):
    """The live provider returned no usable grounded lineage."""

    @override
    def __str__(self) -> str:
        return "Gemini Search returned no usable claim-to-source lineage"


class _Arguments(argparse.Namespace):
    idea: str = ""
    max_sources: int = 3


class _CapturingAgent:
    def __init__(self, agent: ResearchAgent) -> None:
        self.agent: ResearchAgent = agent
        self.output: RunOutput | None = None

    async def arun(
        self,
        input: str,  # noqa: A002
        *,
        stream: Literal[False] = False,
    ) -> RunOutput:
        self.output = await self.agent.arun(input, stream=stream)
        return self.output


def _arguments() -> _Arguments:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--idea", required=True)
    _ = parser.add_argument("--max-sources", type=int, choices=range(1, MAX_SOURCES + 1), default=3)
    return parser.parse_args(namespace=_Arguments())


async def _run(idea: str, max_sources: int) -> None:
    _ = set_log_level_to_error()
    settings = Settings.model_validate({})
    researcher = create_role_catalog(settings)[Role.RESEARCHER].agent
    if not isinstance(researcher.model, Gemini):
        raise SmokeError
    model = researcher.model
    captured = _CapturingAgent(researcher)
    brief = CompanyBrief(
        idea=idea,
        target_customer=None,
        geography=None,
        budget=None,
        founder_skills=None,
        goal="Find current market evidence",
        supplied_context=[],
        assumptions=[],
        open_questions=[],
        next_actions=[],
    )
    with redirect_stdout(StringIO()):
        result = await run_research(captured, brief, max_sources=max_sources)
    if captured.output is None:
        raise SmokeError
    citations = captured.output.citations
    retained_ids = {source.source_id for source in result.sources}
    usable_lineage = bool(result.sources) and not any(
        not set(claim.source_ids) <= retained_ids for claim in result.claims
    )
    _ = sys.stdout.write(
        json.dumps(
            {
                "status": result.status,
                "request_focus": "current public competitor and pricing evidence as of 2026-10-11",
                "model_id": model.id,
                "search_enabled": model.search,
                "provider_metadata_present": citations is not None and citations.raw is not None,
                "search_queries": [] if citations is None else citations.search_queries or [],
                "citation_count": 0 if citations is None else len(citations.urls or ()),
                "sources": [
                    {
                        "source_id": str(source.source_id),
                        "url": str(source.url),
                        "title": source.title,
                        "retrieved_at": source.retrieved_at.isoformat(),
                    }
                    for source in result.sources
                ],
                "claims": [
                    {
                        "source_ids": [str(source_id) for source_id in claim.source_ids],
                        "support_status": claim.support_status,
                        "verification_status": claim.verification_status,
                    }
                    for claim in result.claims
                ],
                "finding": result.verification_findings[0].message,
            },
            indent=2,
        )
        + "\n"
    )
    if not usable_lineage:
        raise SmokeError


if __name__ == "__main__":
    arguments = _arguments()
    anyio.run(partial(_run, arguments.idea, arguments.max_sources))
