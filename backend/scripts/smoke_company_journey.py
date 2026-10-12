"""Run one sanitized live Gemini company-journey smoke check."""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, cast, override
from uuid import uuid4

import anyio
from agno.db.sqlite import SqliteDb
from agno.run.workflow import WorkflowCompletedEvent, WorkflowRunEvent
from agno.utils.log import set_log_level_to_error

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from samurai.company_workflow import CompanyJourneyRequest, create_company_workflow
from samurai.config import Settings
from samurai.contracts import (
    ArtifactEnvelope,
    ArtifactType,
    CompanyState,
    ResearchArtifact,
    WorkflowResult,
)

if TYPE_CHECKING:
    from agno.run.workflow import StepCompletedEvent
    from pydantic import JsonValue


class SmokeError(Exception):
    """Report a live journey that does not satisfy the verified lineage boundary."""

    @override
    def __str__(self) -> str:
        return "live company journey did not produce complete ordered lineage"


class SmokeArguments(argparse.Namespace):
    """Validated command arguments for one bounded live smoke run."""

    idea: str = ""
    customer: str = ""
    geography: str = ""
    budget: str = ""
    skills: str = ""
    goal: str = ""
    timeout_seconds: float = 420


def _arguments() -> SmokeArguments:
    parser = argparse.ArgumentParser()
    for name in ("idea", "customer", "geography", "budget", "skills", "goal"):
        _ = parser.add_argument(f"--{name}", required=True)
    _ = parser.add_argument("--timeout-seconds", type=float, default=420)
    return parser.parse_args(namespace=SmokeArguments())


def _artifact_record(artifact: ArtifactEnvelope) -> JsonValue:
    return {
        "type": artifact.artifact_type,
        "artifact_id": str(artifact.artifact_id),
        "revision": artifact.revision,
        "input_revision": artifact.input_revision,
        "status": artifact.status,
        "findings": [finding.model_dump(mode="json") for finding in artifact.verification_findings],
        "source_count": len(artifact.sources),
        "source_urls": [str(source.url) for source in artifact.sources],
        "claim_count": len(artifact.claims),
        "claim_verification": [claim.verification_status for claim in artifact.claims],
        "conflicts": list(ResearchArtifact.model_validate(artifact.payload).conflicts)
        if artifact.artifact_type == ArtifactType.RESEARCH
        else [],
    }


def _write_json(path: Path, payload: JsonValue) -> None:
    _ = path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


async def run_smoke(arguments: SmokeArguments) -> None:
    """Run one bounded journey and retain sanitized progress evidence."""
    _ = set_log_level_to_error()
    settings = Settings.model_validate(
        {
            "os_security_key": os.environ.get("OS_SECURITY_KEY", ""),
            "database_url": os.environ.get("DATABASE_URL", ""),
            "google_api_key": os.environ.get("GOOGLE_API_KEY", ""),
            "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        }
    )
    evidence_dir = Path(__file__).parents[1] / ".omo" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    run_token = str(uuid4())
    database_path = evidence_dir / f"task-6-company-smoke-{run_token}.db"
    progress_path = evidence_dir / f"task-6-company-smoke-{run_token}-progress.json"
    workflow = create_company_workflow(SqliteDb(db_file=str(database_path)), settings)
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
    progress: list[JsonValue] = [{"event": "workflow_started", "step": None}]
    completed_steps: list[str] = []
    _write_json(progress_path, progress)
    completed: WorkflowCompletedEvent | None = None
    try:
        with redirect_stdout(StringIO()):
            with anyio.fail_after(arguments.timeout_seconds):
                events = workflow.arun(
                    request,
                    stream=True,
                    stream_events=True,
                    user_id="live-smoke-founder",
                    session_id="live-smoke-child",
                    session_state=session_state,
                    dependencies={
                        "trusted_parent_session_id": "live-smoke-parent",
                        "trusted_user_id": "live-smoke-founder",
                        "child_session_id": "live-smoke-child",
                    },
                )
                async for event in events:
                    if event.event == WorkflowRunEvent.step_completed.value:
                        step_event = cast("StepCompletedEvent", event)
                        step_name = step_event.step_name
                        progress.append({"event": event.event, "step": step_name})
                        if step_name is not None:
                            completed_steps.append(step_name)
                        _write_json(progress_path, progress)
                    if event.event == WorkflowRunEvent.workflow_completed.value:
                        completed = cast("WorkflowCompletedEvent", event)
    except TimeoutError:
        state_data = session_state.get("company")
        state = CompanyState.model_validate(state_data) if state_data is not None else None
        _ = sys.stdout.write(
            json.dumps(
                {
                    "outcome": "incomplete",
                    "reason": "workflow_timeout",
                    "timeout_seconds": arguments.timeout_seconds,
                    "steps": completed_steps,
                    "artifacts": [_artifact_record(artifact) for artifact in state.artifacts]
                    if state is not None
                    else [],
                    "database_path": str(database_path),
                    "progress_path": str(progress_path),
                },
                indent=2,
            )
            + "\n"
        )
        raise SmokeError from None
    if completed is None:
        raise SmokeError
    result = WorkflowResult.model_validate(completed.content)
    expected_types = ["intake", "research", "strategy", "product_plan", "verification"]
    artifacts = list(result.artifacts)
    step_names = [step.step_name or "" for step in completed.step_results]
    terminal = (
        result.outcome in {"verified", "needs_rework"}
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
                "artifacts": [_artifact_record(artifact) for artifact in artifacts],
                "database_path": str(database_path),
                "progress_path": str(progress_path),
            },
            indent=2,
        )
        + "\n"
    )
    if not terminal:
        raise SmokeError


if __name__ == "__main__":
    anyio.run(run_smoke, _arguments())
