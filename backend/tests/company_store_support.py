from __future__ import annotations

import os
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from agno.db.schemas.jobs import QueuedJob
from agno.run.concurrency import worker_managed_execution
from agno.session.workflow import WorkflowSession
from pydantic import BaseModel
from sqlalchemy import MetaData, Table
from sqlalchemy.schema import DropSchema

from samurai.company_store import CompanyStore
from samurai.contracts import (
    ArtifactEnvelope,
    ArtifactType,
    CompanyBrief,
    CompanyState,
    IntakeArtifact,
    Role,
    VerificationFinding,
    accept_artifact,
)
from samurai.execution_state import (
    AcceptanceToken,
    ApprovedStage,
    NormalizedWorkInput,
    SamuraiPostgresDb,
    WorkIntentInput,
    WorkOperation,
)
from samurai.schema import FounderPlatformMigrator

if TYPE_CHECKING:
    from collections.abc import Iterator

    from samurai.company_store_contracts import CompanyAccess


class ClaimedJob(BaseModel):
    attempt: int


def intent(access: CompanyAccess, actor_id: str, parent: str, child: str) -> WorkIntentInput:
    return WorkIntentInput(
        owner_id=actor_id,
        parent_session_id=parent,
        child_session_id=child,
        workspace_id=access.workspace_id,
        authorization_epoch=access.authorization_epoch,
        company_id=access.state.context.company_id,
        operation=WorkOperation.JOURNEY,
        stage=ApprovedStage.BRIEF,
        expected_revision=0,
        approved_input={"idea": "Clinic assistant"},
    )


def job(run_id: str, approval: WorkIntentInput) -> dict[str, object]:
    return QueuedJob(
        id=run_id,
        component_type="agent",
        component_id="samurai",
        session_id=approval.parent_session_id,
        user_id=approval.owner_id,
        payload={"input": "Build", "kwargs": {}},
        max_attempts=2,
        idempotency_key=run_id,
    ).to_dict()


def revision_one(access: CompanyAccess) -> CompanyState:
    artifact = ArtifactEnvelope(
        artifact_id=uuid4(),
        company_id=access.state.context.company_id,
        artifact_type=ArtifactType.INTAKE,
        revision=1,
        input_revision=0,
        producer=Role.INTAKE,
        status="complete",
        payload=IntakeArtifact(
            brief=CompanyBrief(
                idea="Clinic assistant",
                target_customer=None,
                geography=None,
                budget=None,
                founder_skills=None,
                goal=None,
                supplied_context=[],
                assumptions=[],
                open_questions=[],
                next_actions=[],
            )
        ),
        assumptions=(),
        verification_findings=(
            VerificationFinding(code="needs_input", message="Synthetic test", severity="warning"),
        ),
    )
    return accept_artifact(
        access.state,
        artifact,
        authenticated_session_id=access.state.context.authenticated_session_id,
    )


def store_session(database: SamuraiPostgresDb, actor_id: str, access: CompanyAccess) -> None:
    _ = database.upsert_session(
        WorkflowSession(
            session_id=access.child_session_id,
            user_id=actor_id,
            workflow_id="company-journey",
            session_data={"session_state": {"company": access.state.model_dump(mode="json")}},
        )
    )


def bound_attempt(
    database: SamuraiPostgresDb,
    access: CompanyAccess,
    actor_id: str,
    run_id: str,
) -> AcceptanceToken:
    approval = intent(
        access,
        actor_id,
        access.parent_session_id,
        access.child_session_id,
    )
    assert database.enqueue_work_job(job(run_id, approval), approval)["accepted"] is True
    claimed = ClaimedJob.model_validate(database.claim_job(f"worker-{actor_id}", 30))
    with worker_managed_execution(run_id, f"worker-{actor_id}", claimed.attempt):
        return database.bind_work_intent(
            run_id,
            NormalizedWorkInput(
                operation=approval.operation,
                stage=approval.stage,
                expected_revision=0,
                arguments={"idea": "Clinic assistant"},
            ),
        ).token


@pytest.fixture
def postgres_url() -> str:
    value = os.environ.get("SAMURAI_TEST_DATABASE_URL")
    if value is None:
        pytest.skip("SAMURAI_TEST_DATABASE_URL is required for company store tests")
    return value


@pytest.fixture
def company_store(postgres_url: str) -> Iterator[tuple[CompanyStore, SamuraiPostgresDb, UUID]]:
    schema = f"founder_t05_{uuid4().hex}"
    database = SamuraiPostgresDb(id=schema, db_url=postgres_url, db_schema=schema)
    database.ensure_work_intents_table()
    _ = FounderPlatformMigrator(database.db_engine, schema=schema).apply()
    workspace_id = uuid4()
    metadata = MetaData(schema=schema)
    workspaces = Table("samurai_workspaces", metadata, autoload_with=database.db_engine)
    memberships = Table(
        "samurai_workspace_memberships",
        metadata,
        autoload_with=database.db_engine,
    )
    with database.db_engine.begin() as connection:
        _ = connection.execute(
            workspaces.insert().values(
                workspace_id=workspace_id,
                workspace_kind="shared",
                display_name="Acme Test",
                created_at=1,
                updated_at=1,
            )
        )
        _ = connection.execute(
            memberships.insert(),
            [
                {
                    "workspace_id": workspace_id,
                    "user_id": actor_id,
                    "role": role,
                    "authorization_epoch": 1,
                    "active": True,
                    "created_at": 1,
                    "updated_at": 1,
                }
                for actor_id, role in (
                    ("owner", "owner"),
                    ("editor", "editor"),
                    ("viewer", "viewer"),
                )
            ],
        )
    yield CompanyStore(database.db_engine, schema=schema), database, workspace_id
    with database.db_engine.begin() as connection:
        _ = connection.execute(DropSchema(schema, cascade=True, if_exists=True))
    database.close()
