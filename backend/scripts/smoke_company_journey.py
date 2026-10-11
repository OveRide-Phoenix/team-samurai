"""Run one sanitized live Gemini company-journey smoke check."""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, override

import anyio
from agno.db.sqlite import SqliteDb
from agno.utils.log import set_log_level_to_error
from agno.workflow import StepOutput

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from samurai.company_workflow import CompanyJourneyRequest, create_company_workflow
from samurai.config import Settings
from samurai.contracts import WorkflowResult

if TYPE_CHECKING:
    from pydantic import JsonValue


class SmokeError(Exception):
    """Report a live journey that does not satisfy the verified lineage boundary."""

    @override
    def __str__(self) -> str:
        return "live company journey did not produce complete ordered lineage"


class _Arguments(argparse.Namespace):
    idea: str = ""
    customer: str = ""
    geography: str = ""
    budget: str = ""
    skills: str = ""
    goal: str = ""


def _arguments() -> _Arguments:
    parser = argparse.ArgumentParser()
    for name in ("idea", "customer", "geography", "budget", "skills", "goal"):
        _ = parser.add_argument(f"--{name}", required=True)
    return parser.parse_args(namespace=_Arguments())


async def _run(arguments: _Arguments) -> None:
    _ = set_log_level_to_error()
    settings = Settings.model_validate(
        {
            "os_security_key": os.environ.get("OS_SECURITY_KEY", ""),
            "database_url": os.environ.get("DATABASE_URL", ""),
            "google_api_key": os.environ.get("GOOGLE_API_KEY", ""),
            "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
        }
    )
    with TemporaryDirectory(prefix="samurai-company-smoke-") as directory:
        workflow = create_company_workflow(
            SqliteDb(db_file=str(Path(directory) / "journey.db")), settings
        )
        session_state: dict[str, JsonValue] = {}
        request = CompanyJourneyRequest(
            company_id=None,
            expected_revision=0,
            idea=arguments.idea,
            target_customer=arguments.customer,
            geography=arguments.geography,
            budget=arguments.budget,
            founder_skills=arguments.skills,
            goal=arguments.goal,
        )
        with redirect_stdout(StringIO()):
            output = await workflow.arun(
                request,
                stream=False,
                user_id="live-smoke-founder",
                session_id="live-smoke-child",
                session_state=session_state,
                dependencies={
                    "trusted_parent_session_id": "live-smoke-parent",
                    "trusted_user_id": "live-smoke-founder",
                    "child_session_id": "live-smoke-child",
                },
            )
    result = WorkflowResult.model_validate(output.content)
    expected_types = ["intake", "research", "strategy", "product_plan", "verification"]
    artifacts = list(result.artifacts)
    step_names: list[str] = []
    for step in output.step_results or ():
        if not isinstance(step, StepOutput):
            raise SmokeError
        step_names.append(step.step_name or "")
    complete = (
        result.outcome == "verified"
        and [artifact.artifact_type for artifact in artifacts] == expected_types
        and [artifact.revision for artifact in artifacts] == [1, 2, 3, 4, 5]
        and [artifact.input_revision for artifact in artifacts] == [0, 1, 2, 3, 4]
        and all(
            claim.verification_status == "unverified"
            for artifact in artifacts
            for claim in artifact.claims
        )
    )
    _ = sys.stdout.write(
        json.dumps(
            {
                "outcome": result.outcome,
                "company_id": str(result.company_id),
                "revision": result.revision,
                "steps": step_names,
                "artifacts": [
                    {
                        "type": artifact.artifact_type,
                        "revision": artifact.revision,
                        "input_revision": artifact.input_revision,
                        "status": artifact.status,
                        "source_count": len(artifact.sources),
                        "claim_count": len(artifact.claims),
                        "claim_verification": [
                            claim.verification_status for claim in artifact.claims
                        ],
                    }
                    for artifact in artifacts
                ],
            },
            indent=2,
        )
        + "\n"
    )
    if not complete:
        raise SmokeError


if __name__ == "__main__":
    anyio.run(_run, _arguments())
