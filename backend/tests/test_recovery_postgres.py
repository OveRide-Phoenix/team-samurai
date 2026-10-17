from __future__ import annotations

import os
from datetime import UTC, datetime
from multiprocessing import get_context
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from agno.db.base import SessionType
from agno.db.postgres import PostgresDb
from agno.db.schemas.jobs import QueuedJob
from agno.run import RunContext
from agno.run.concurrency import worker_managed_execution
from agno.session.agent import AgentSession
from agno.session.workflow import WorkflowSession
from pydantic import BaseModel, JsonValue, TypeAdapter
from sqlalchemy import MetaData, Table
from sqlalchemy.orm import Session as SqlAlchemySession

from samurai.contracts import (
    ArtifactEnvelope,
    ArtifactType,
    CompanyBrief,
    CompanyState,
    IntakeArtifact,
    ResearchArtifact,
    Role,
    VerificationFinding,
    accept_artifact,
    create_company_state,
)
from samurai.execution_state import (
    WORK_INTENT_METADATA_KEY,
    AcceptanceToken,
    ApprovedStage,
    NormalizedWorkInput,
    SamuraiPostgresDb,
    WorkIntentError,
    WorkIntentInput,
    WorkIntentIssue,
    WorkOperation,
    _terminal_acceptance,  # pyright: ignore[reportPrivateUsage]
)
from samurai.workflow_state import WorkflowContextError, WorkflowContextIssue, save_company_state

if TYPE_CHECKING:
    from collections.abc import Iterator
    from multiprocessing.queues import Queue
    from multiprocessing.synchronize import Barrier

STATE_ADAPTER = TypeAdapter(CompanyState)
TOKEN_ADAPTER = TypeAdapter(AcceptanceToken)
SESSION_DATA_ADAPTER = TypeAdapter(dict[str, JsonValue])


class _ClaimedJob(BaseModel):
    attempt: int


class _StoredJob(BaseModel):
    payload: dict[str, JsonValue] = {}
    status: str = ""


@pytest.fixture
def postgres_url() -> str:
    value = os.environ.get("SAMURAI_TEST_DATABASE_URL")
    if value is None:
        pytest.skip("SAMURAI_TEST_DATABASE_URL is required for PostgreSQL recovery tests")
    return value


@pytest.fixture
def database(postgres_url: str) -> Iterator[SamuraiPostgresDb]:
    schema = f"task4_{uuid4().hex}"
    db = SamuraiPostgresDb(id=schema, db_url=postgres_url, db_schema=schema)
    db.ensure_work_intents_table()
    yield db
    db.close()


def _intent(  # noqa: PLR0913
    *,
    stage: ApprovedStage = ApprovedStage.BRIEF,
    expected_revision: int = 0,
    company_id: UUID | None = None,
    owner_id: str = "founder-1",
    parent_session_id: str = "parent-session",
    child_session_id: str = "child-session",
) -> WorkIntentInput:
    return WorkIntentInput(
        owner_id=owner_id,
        parent_session_id=parent_session_id,
        child_session_id=child_session_id,
        company_id=company_id,
        operation=WorkOperation.JOURNEY,
        stage=stage,
        expected_revision=expected_revision,
        approved_input={"idea": "Clinic assistant", "stage": stage.value},
    )


def _job(run_id: str, intent: WorkIntentInput, *, key: str = "approval-key") -> dict[str, object]:
    return QueuedJob(
        id=run_id,
        component_type="agent",
        component_id="samurai",
        session_id=intent.parent_session_id,
        user_id=intent.owner_id,
        payload={
            "input": "Build my business",
            "kwargs": {"metadata": {WORK_INTENT_METADATA_KEY: intent.model_dump(mode="json")}},
        },
        max_attempts=2,
        idempotency_key=key,
    ).to_dict()


def _normalized(intent: WorkIntentInput) -> NormalizedWorkInput:
    approved = intent.approved_input
    assert isinstance(approved, dict)
    return NormalizedWorkInput(
        operation=intent.operation,
        stage=intent.stage,
        expected_revision=intent.expected_revision,
        arguments=approved,
    )


def _state(parent_session_id: str, artifact_id: UUID | None = None) -> CompanyState:
    state = create_company_state(parent_session_id, created_at=datetime(2026, 10, 12, tzinfo=UTC))
    artifact = ArtifactEnvelope(
        artifact_id=artifact_id or uuid4(),
        company_id=state.context.company_id,
        artifact_type=ArtifactType.INTAKE,
        revision=1,
        input_revision=0,
        producer=Role.INTAKE,
        status="complete",
        assumptions=(),
        payload=IntakeArtifact(
            brief=CompanyBrief(
                idea="Clinic assistant",
                target_customer="Clinics",
                geography="India",
                budget="INR 100000",
                founder_skills="Sales",
                goal="Validate demand",
                supplied_context=[],
                assumptions=[],
                open_questions=[],
                next_actions=[],
            )
        ),
        verification_findings=(
            VerificationFinding(
                code="founder_context_retained",
                message="Founder input retained.",
                severity="info",
            ),
        ),
    )
    return accept_artifact(state, artifact, authenticated_session_id=parent_session_id)


def test_research_stage_becomes_terminal_only_after_adjudication() -> None:
    raw_state = _state("parent-session")
    raw = ArtifactEnvelope(
        artifact_id=uuid4(),
        company_id=raw_state.context.company_id,
        artifact_type=ArtifactType.RESEARCH,
        revision=2,
        input_revision=1,
        producer=Role.RESEARCHER,
        status="complete",
        payload=ResearchArtifact(summary="Retained research", conflicts=()),
        assumptions=(),
        verification_findings=(
            VerificationFinding(
                code="research_raw",
                message="Raw research awaits adjudication.",
                severity="info",
            ),
        ),
    )
    raw_state = accept_artifact(
        raw_state,
        raw,
        authenticated_session_id="parent-session",
    )
    adjudicated = ArtifactEnvelope(
        artifact_id=uuid4(),
        company_id=raw_state.context.company_id,
        artifact_type=ArtifactType.RESEARCH,
        revision=3,
        input_revision=2,
        producer=Role.VERIFIER,
        status="complete",
        payload=ResearchArtifact(
            summary="Retained research",
            conflicts=(),
            adjudicated_from_artifact_id=raw.artifact_id,
            adjudicated_from_revision=raw.revision,
        ),
        assumptions=(),
        verification_findings=(
            VerificationFinding(
                code="research_adjudicated",
                message="Research adjudication completed.",
                severity="info",
            ),
        ),
    )
    adjudicated_state = accept_artifact(
        raw_state,
        adjudicated,
        authenticated_session_id="parent-session",
    )

    assert not _terminal_acceptance(
        WorkOperation.JOURNEY,
        ApprovedStage.RESEARCH,
        raw_state,
        0,
    )
    assert _terminal_acceptance(
        WorkOperation.JOURNEY,
        ApprovedStage.RESEARCH,
        adjudicated_state,
        0,
    )


def _prepare(database: SamuraiPostgresDb, run_id: str) -> tuple[WorkIntentInput, AcceptanceToken]:
    intent = _intent()
    _ = database.upsert_session(
        WorkflowSession(
            session_id=intent.child_session_id,
            user_id=intent.owner_id,
            workflow_id="company-journey",
            session_data={"session_state": {}},
        )
    )
    admitted = database.enqueue_job(_job(run_id, intent))
    assert admitted["accepted"] is True
    claimed = database.claim_job("worker-1", lock_grace_seconds=60)
    assert claimed is not None
    with worker_managed_execution(run_id, "worker-1", _ClaimedJob.model_validate(claimed).attempt):
        bound = database.bind_work_intent(run_id, _normalized(intent))
    assert bound.approval == intent
    assert bound.normalized_input == _normalized(intent)
    return bound.approval, bound.token


def _expire_job_lease(database: SamuraiPostgresDb) -> None:
    jobs = Table(
        database.job_table_name,
        MetaData(schema=database.db_schema),
        autoload_with=database.db_engine,
    )
    with SqlAlchemySession(database.db_engine) as session, session.begin():
        _ = session.execute(jobs.update().values(locked_at=0))


def _accept_in_process(
    payload: tuple[str, str, str, str],
    barrier: Barrier,
    results: Queue[str],
) -> None:
    database_url, schema, state_json, token_json = payload
    database = SamuraiPostgresDb(
        id=f"process-{os.getpid()}",
        db_url=database_url,
        db_schema=schema,
        create_schema=False,
    )
    state = STATE_ADAPTER.validate_json(state_json)
    token = TOKEN_ADAPTER.validate_json(token_json)
    with worker_managed_execution(token.parent_run_id, token.worker_id, token.attempt):
        _ = barrier.wait()
        try:
            accepted = database.accept_company_state(state, token)
        except WorkIntentError as error:
            results.put(error.issue.value)
        else:
            results.put(str(accepted.artifacts[-1].artifact_id))
    database.close()


def _cancel_in_process(
    payload: tuple[str, str, str],
    barrier: Barrier,
    results: Queue[str],
) -> None:
    database_url, schema, token_json = payload
    database = SamuraiPostgresDb(
        id=f"cancel-{os.getpid()}",
        db_url=database_url,
        db_schema=schema,
        create_schema=False,
    )
    token = TOKEN_ADAPTER.validate_json(token_json)
    _ = barrier.wait()
    cancelled = database.complete_job(
        token.parent_run_id,
        token.worker_id,
        token.attempt,
        "cancelled",
    )
    results.put(f"cancelled:{cancelled}")
    database.close()


def _accept_then_exit(
    database_url: str,
    schema: str,
    state_json: str,
    token_json: str,
) -> None:
    database = SamuraiPostgresDb(
        id=f"crash-{os.getpid()}",
        db_url=database_url,
        db_schema=schema,
        create_schema=False,
    )
    state = STATE_ADAPTER.validate_json(state_json)
    token = TOKEN_ADAPTER.validate_json(token_json)
    with worker_managed_execution(token.parent_run_id, token.worker_id, token.attempt):
        _ = database.accept_company_state(state, token)
    os._exit(17)


def _stale_upsert_in_process(
    payload: tuple[str, str, str, str, str],
) -> None:
    database_url, schema, session_id, owner_id, session_data_json = payload
    database = SamuraiPostgresDb(
        id=f"stale-upsert-{os.getpid()}",
        db_url=database_url,
        db_schema=schema,
        create_schema=False,
    )
    _ = database.upsert_session(
        WorkflowSession(
            session_id=session_id,
            user_id=owner_id,
            workflow_id="company-journey",
            session_data=SESSION_DATA_ADAPTER.validate_json(session_data_json),
        )
    )
    database.close()


def test_acceptance_native_enqueue_atomically_admits_intent_and_job(
    database: SamuraiPostgresDb,
) -> None:
    # Given a native queue job carrying trusted work approval.
    intent = _intent()
    job = _job("run-admission", intent)

    # When the native Postgres enqueue seam accepts it.
    result = database.enqueue_job(job)

    # Then the job is durable and the trusted envelope is not replayed to the model.
    stored = database.get_job("run-admission")
    assert result["accepted"] is True
    assert stored is not None
    assert WORK_INTENT_METADATA_KEY not in str(_StoredJob.model_validate(stored).payload)


def test_work_receipt_is_scoped_to_owner_session_and_submission(
    database: SamuraiPostgresDb,
) -> None:
    # Given a durable ticket keyed by the founder's persisted submission UUID.
    intent = _intent()
    submission_id = uuid4()
    assert (
        database.enqueue_job(_job("run-receipt", intent, key=str(submission_id)))["accepted"]
        is True
    )

    # When receipt lookup uses the authenticated owner, session, and submission UUID.
    receipt = database.get_work_receipt(
        intent.owner_id,
        intent.parent_session_id,
        submission_id,
    )

    # Then it exposes only sanitized lifecycle data and hides the ticket cross-owner/session.
    assert receipt is not None
    assert receipt.run_id == "run-receipt"
    assert receipt.status == "PENDING"
    assert receipt.attempt == 0
    assert receipt.max_attempts == 2
    assert receipt.failure_reason is None
    assert database.get_work_receipt("other", intent.parent_session_id, submission_id) is None
    assert database.get_work_receipt(intent.owner_id, "other", submission_id) is None


def test_same_submission_uuid_is_independent_for_two_owners(
    database: SamuraiPostgresDb,
) -> None:
    submission_id = uuid4()
    first = _intent(
        owner_id="founder-a",
        parent_session_id="session-a",
        child_session_id="child-a",
    )
    second = _intent(
        owner_id="founder-b",
        parent_session_id="session-b",
        child_session_id="child-b",
    )

    assert (
        database.enqueue_job(_job("run-owner-a", first, key=str(submission_id)))["accepted"] is True
    )
    assert (
        database.enqueue_job(_job("run-owner-b", second, key=str(submission_id)))["accepted"]
        is True
    )

    first_receipt = database.get_work_receipt(
        first.owner_id,
        first.parent_session_id,
        submission_id,
    )
    second_receipt = database.get_work_receipt(
        second.owner_id,
        second.parent_session_id,
        submission_id,
    )
    assert first_receipt is not None
    assert second_receipt is not None
    assert first_receipt.run_id == "run-owner-a"
    assert second_receipt.run_id == "run-owner-b"
    assert (
        database.get_work_receipt(
            first.owner_id,
            second.parent_session_id,
            submission_id,
        )
        is None
    )
    assert (
        database.get_work_receipt(
            second.owner_id,
            first.parent_session_id,
            submission_id,
        )
        is None
    )


def test_acceptance_native_enqueue_rejects_missing_trusted_approval(
    database: SamuraiPostgresDb,
) -> None:
    # Given a native job whose trusted approval envelope is absent.
    intent = _intent()
    job = _job("run-missing-approval", intent)
    payload = job["payload"]
    assert isinstance(payload, dict)
    payload["kwargs"] = {}

    # When the native queue seam receives the unbound job.
    with pytest.raises(WorkIntentError) as raised:
        _ = database.enqueue_job(job)

    # Then admission fails closed without creating a queue ticket.
    assert raised.value.issue is WorkIntentIssue.MISSING_APPROVAL
    assert database.get_job("run-missing-approval") is None


def test_acceptance_changed_stage_retry_is_rejected_before_second_job(
    database: SamuraiPostgresDb,
) -> None:
    # Given an admitted brief-stage request.
    _ = database.enqueue_job(_job("run-original", _intent()))

    # When the same idempotency key is reused with a changed stage.
    with pytest.raises(WorkIntentError) as raised:
        _ = database.enqueue_job(_job("run-changed", _intent(stage=ApprovedStage.RESEARCH)))

    # Then immutable approval rejects the retry and no second ticket exists.
    assert raised.value.issue is WorkIntentIssue.CHANGED_APPROVAL
    assert database.get_job("run-changed") is None


def test_acceptance_duplicate_same_stage_returns_retained_artifact(
    database: SamuraiPostgresDb,
) -> None:
    # Given one running approved attempt that has accepted an intake artifact.
    _, token = _prepare(database, "run-duplicate")
    first = _state(token.parent_session_id)
    with worker_managed_execution(token.parent_run_id, token.worker_id, token.attempt):
        accepted = database.accept_company_state(first, token)

        # When the same attempt repeats acceptance with a different generated artifact.
        duplicate = database.accept_company_state(_state(token.parent_session_id), token)

    # Then the committed artifact and revision are reused.
    assert duplicate.artifacts[-1].artifact_id == accepted.artifacts[-1].artifact_id
    assert duplicate.current_revision == 1


def test_acceptance_old_stage_artifact_does_not_complete_new_intent(
    database: SamuraiPostgresDb,
) -> None:
    # Given a company that reached brief before a new brief-scoped intent was admitted.
    prior = _state("parent-session")
    intent = _intent(expected_revision=1, company_id=prior.context.company_id)
    _ = database.upsert_session(
        WorkflowSession(
            session_id=intent.child_session_id,
            user_id=intent.owner_id,
            workflow_id="company-journey",
            session_data={"session_state": {"company": prior.model_dump(mode="json")}},
        )
    )
    assert database.enqueue_job(_job("run-old-stage", intent))["accepted"] is True
    claimed = database.claim_job("worker-1", lock_grace_seconds=60)
    assert claimed is not None
    with worker_managed_execution(
        "run-old-stage", "worker-1", _ClaimedJob.model_validate(claimed).attempt
    ):
        token = database.bind_work_intent("run-old-stage", _normalized(intent)).token
        _ = database.accept_company_state(prior, token)

    # When another write is requested while the new intent produced no new brief artifact.
    retry = _job("run-after-old-stage", intent, key="second-approval-key")
    with pytest.raises(WorkIntentError) as raised:
        _ = database.enqueue_job(retry)

    # Then the old artifact did not terminalize the new active intent.
    assert raised.value.issue is WorkIntentIssue.ACTIVE_WORK


def test_workflow_save_uses_trusted_native_worker_identity(
    database: SamuraiPostgresDb,
) -> None:
    # Given a claimed work intent and the exact server-bound acceptance identity.
    intent, token = _prepare(database, "run-workflow-save")
    context = RunContext(
        run_id="child-run",
        session_id=intent.child_session_id,
        user_id=intent.owner_id,
        dependencies={
            "trusted_parent_session_id": intent.parent_session_id,
            "trusted_user_id": intent.owner_id,
            "child_session_id": intent.child_session_id,
            "parent_run_id": token.parent_run_id,
            "worker_id": token.worker_id,
            "attempt": token.attempt,
            "fingerprint": token.fingerprint,
        },
        session_state={},
    )

    # When a workflow save reaches the PostgreSQL acceptance boundary.
    with worker_managed_execution(token.parent_run_id, token.worker_id, token.attempt):
        accepted = save_company_state(_state(intent.parent_session_id), context, db=database)

    # Then the canonical state and in-memory workflow view contain the same revision.
    assert accepted.current_revision == 1
    assert context.session_state is not None
    assert CompanyState.model_validate(context.session_state["company"]) == accepted


def test_first_tool_binding_rejects_changed_normalized_arguments(
    database: SamuraiPostgresDb,
) -> None:
    # Given a first tool invocation already bound to normalized approved arguments.
    intent, token = _prepare(database, "run-bound-input")

    # When the same attempt proposes different normalized arguments.
    with (
        worker_managed_execution(token.parent_run_id, token.worker_id, token.attempt),
        pytest.raises(WorkIntentError) as raised,
    ):
        _ = database.bind_work_intent(
            token.parent_run_id,
            NormalizedWorkInput(
                operation=intent.operation,
                stage=intent.stage,
                expected_revision=intent.expected_revision,
                arguments={"idea": "Different idea"},
            ),
        )

    # Then the immutable first-tool binding rejects the changed input.
    assert raised.value.issue is WorkIntentIssue.CHANGED_APPROVAL
    with worker_managed_execution(token.parent_run_id, token.worker_id, token.attempt):
        retry = database.bind_work_intent(token.parent_run_id)
    assert retry.normalized_input == _normalized(intent)


def test_first_tool_binding_rejects_scope_broadening_before_initial_bind(
    database: SamuraiPostgresDb,
) -> None:
    # Given a brief-scoped approval whose native job has been claimed.
    intent = _intent()
    _ = database.upsert_session(
        WorkflowSession(
            session_id=intent.child_session_id,
            user_id=intent.owner_id,
            workflow_id="company-journey",
            session_data={"session_state": {}},
        )
    )
    assert database.enqueue_job(_job("run-first-mismatch", intent))["accepted"] is True
    claimed = database.claim_job("worker-1", lock_grace_seconds=60)
    assert claimed is not None

    # When the first tool invocation tries to broaden the approved stage.
    with (
        worker_managed_execution(
            "run-first-mismatch", "worker-1", _ClaimedJob.model_validate(claimed).attempt
        ),
        pytest.raises(WorkIntentError) as raised,
    ):
        _ = database.bind_work_intent(
            "run-first-mismatch",
            NormalizedWorkInput(
                operation=WorkOperation.JOURNEY,
                stage=ApprovedStage.PLAN,
                expected_revision=0,
                arguments={"idea": "Clinic assistant"},
            ),
        )

    # Then the broadened first bind is rejected and the approved bind remains available.
    assert raised.value.issue is WorkIntentIssue.CHANGED_APPROVAL
    with worker_managed_execution(
        "run-first-mismatch", "worker-1", _ClaimedJob.model_validate(claimed).attempt
    ):
        bound = database.bind_work_intent("run-first-mismatch", _normalized(intent))
    assert bound.approval.stage is ApprovedStage.BRIEF


def test_workflow_save_rejects_postgres_without_worker_identity(
    database: SamuraiPostgresDb,
) -> None:
    # Given trusted session identity without a native worker attempt binding.
    intent, _ = _prepare(database, "run-workflow-unbound")
    context = RunContext(
        run_id="child-run",
        session_id=intent.child_session_id,
        user_id=intent.owner_id,
        dependencies={
            "trusted_parent_session_id": intent.parent_session_id,
            "trusted_user_id": intent.owner_id,
            "child_session_id": intent.child_session_id,
        },
        session_state={},
    )

    # When the workflow attempts a PostgreSQL save.
    with pytest.raises(WorkflowContextError) as raised:
        _ = save_company_state(_state(intent.parent_session_id), context, db=database)

    # Then the missing server-bound ownership fails closed.
    assert raised.value.issue is WorkflowContextIssue.INVALID_DEPENDENCIES


def test_workflow_save_rejects_plain_postgres_adapter_before_mutation() -> None:
    # Given a live-shaped workflow context and an unfenced native Postgres adapter.
    context = RunContext(
        run_id="child-run",
        session_id="child-session",
        user_id="founder-1",
        dependencies={
            "trusted_parent_session_id": "parent-session",
            "trusted_user_id": "founder-1",
            "child_session_id": "child-session",
        },
        session_state={},
    )
    database = PostgresDb(
        id="unfenced",
        db_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
        create_schema=False,
    )

    # When canonical company state is offered to the unfenced adapter.
    with pytest.raises(WorkflowContextError) as raised:
        _ = save_company_state(_state("parent-session"), context, db=database)
    database.close()

    # Then the boundary fails before session state can be mutated.
    assert raised.value.issue is WorkflowContextIssue.INVALID_DEPENDENCIES
    assert context.session_state == {}


def test_acceptance_two_process_race_fences_stale_lease_after_successor_claim(
    database: SamuraiPostgresDb,
    postgres_url: str,
) -> None:
    # Given worker one prepared state before its lease was reclaimed by worker two.
    intent, stale_token = _prepare(database, "run-race")
    _expire_job_lease(database)
    successor = database.claim_job("worker-2", lock_grace_seconds=1)
    assert successor is not None
    with worker_managed_execution(
        "run-race", "worker-2", _ClaimedJob.model_validate(successor).attempt
    ):
        winner_token = database.bind_work_intent("run-race").token
    stale_state = _state(intent.parent_session_id)
    winner_state = _state(intent.parent_session_id)
    context = get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = (
        context.Process(
            target=_accept_in_process,
            args=(
                (
                    postgres_url,
                    database.db_schema,
                    stale_state.model_dump_json(),
                    stale_token.model_dump_json(),
                ),
                barrier,
                results,
            ),
        ),
        context.Process(
            target=_accept_in_process,
            args=(
                (
                    postgres_url,
                    database.db_schema,
                    winner_state.model_dump_json(),
                    winner_token.model_dump_json(),
                ),
                barrier,
                results,
            ),
        ),
    )

    # When both OS processes cross the acceptance barrier together.
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)

    # Then only the successor artifact commits and the stale attempt is fenced.
    outcomes = {results.get(timeout=2), results.get(timeout=2)}
    assert all(process.exitcode == 0 for process in processes)
    assert outcomes == {
        WorkIntentIssue.STALE_WORKER.value,
        str(winner_state.artifacts[-1].artifact_id),
    }
    child = database.get_session(
        intent.child_session_id,
        session_type=SessionType.WORKFLOW,
        user_id=intent.owner_id,
    )
    assert isinstance(child, WorkflowSession)
    assert child.session_data is not None
    retained = CompanyState.model_validate(child.session_data["session_state"]["company"])
    assert retained.artifacts[-1].artifact_id == winner_state.artifacts[-1].artifact_id


def test_acceptance_crash_after_commit_rehydrates_binding_and_reuses_artifact(
    database: SamuraiPostgresDb,
    postgres_url: str,
) -> None:
    # Given a claimed attempt and a child process that exits immediately after commit.
    intent, token = _prepare(database, "run-crash")
    committed = _state(intent.parent_session_id)
    context = get_context("spawn")
    process = context.Process(
        target=_accept_then_exit,
        args=(
            postgres_url,
            database.db_schema,
            committed.model_dump_json(),
            token.model_dump_json(),
        ),
    )

    # When the worker dies after the database transaction but before acknowledgement.
    process.start()
    process.join(timeout=15)

    # Then the binding and artifact remain committed and a reclaimed retry reuses them.
    assert process.exitcode == 17
    binding = database.get_parent_binding("run-crash", intent.owner_id)
    assert binding is not None
    assert binding.current_revision == 1
    _expire_job_lease(database)
    successor = database.claim_job("worker-2", lock_grace_seconds=1)
    assert successor is not None
    with worker_managed_execution(
        "run-crash", "worker-2", _ClaimedJob.model_validate(successor).attempt
    ):
        retry_token = database.bind_work_intent("run-crash").token
        retried = database.accept_company_state(_state(intent.parent_session_id), retry_token)
    assert retried.artifacts[-1].artifact_id == committed.artifacts[-1].artifact_id


def test_acceptance_stale_agno_upsert_cannot_replace_fenced_company(
    database: SamuraiPostgresDb,
    postgres_url: str,
) -> None:
    # Given committed canonical state and a stale in-memory Agno workflow session.
    intent, token = _prepare(database, "run-upsert")
    committed = _state(intent.parent_session_id)
    with worker_managed_execution(token.parent_run_id, token.worker_id, token.attempt):
        _ = database.accept_company_state(committed, token)
    stale = WorkflowSession(
        session_id=intent.child_session_id,
        user_id=intent.owner_id,
        workflow_id="company-journey",
        session_data={"session_state": {}},
    )

    # When another OS process later performs Agno's native stale upsert.
    assert stale.session_data is not None
    process = get_context("spawn").Process(
        target=_stale_upsert_in_process,
        args=(
            (
                postgres_url,
                database.db_schema,
                intent.child_session_id,
                intent.owner_id,
                SESSION_DATA_ADAPTER.dump_json(stale.session_data).decode(),
            ),
        ),
    )
    process.start()
    process.join(timeout=15)
    assert process.exitcode == 0

    # Then the protected company revision and artifact remain canonical.
    child = database.get_session(
        intent.child_session_id,
        session_type=SessionType.WORKFLOW,
        user_id=intent.owner_id,
    )
    assert isinstance(child, WorkflowSession)
    assert child.session_data is not None
    retained = CompanyState.model_validate(child.session_data["session_state"]["company"])
    assert retained == committed


def test_terminal_retry_keeps_scope_active_until_exhausted_failure(
    database: SamuraiPostgresDb,
) -> None:
    # Given a first failed attempt with one native retry remaining.
    intent, token = _prepare(database, "run-retry-lifecycle")
    assert (
        database.retry_or_fail_job(
            token.parent_run_id,
            token.worker_id,
            token.attempt,
            "transient",
            retry_delay_seconds=0,
        )
        == "queued"
    )

    # When distinct work tries to enter before and after the retry is exhausted.
    with pytest.raises(WorkIntentError) as raised:
        _ = database.enqueue_job(_job("run-blocked-retry", intent, key="blocked-key"))
    assert raised.value.issue is WorkIntentIssue.ACTIVE_WORK
    claimed = database.claim_job("worker-2", lock_grace_seconds=60)
    assert claimed is not None
    with worker_managed_execution(
        token.parent_run_id, "worker-2", _ClaimedJob.model_validate(claimed).attempt
    ):
        retry = database.bind_work_intent(token.parent_run_id)
    assert (
        database.retry_or_fail_job(
            token.parent_run_id,
            retry.token.worker_id,
            retry.token.attempt,
            "exhausted",
            retry_delay_seconds=0,
        )
        == "failed"
    )

    # Then queued retry retained exclusivity and terminal failure released it.
    admitted = database.enqueue_job(_job("run-after-failure", intent, key="after-failure-key"))
    assert admitted["accepted"] is True


def test_acceptance_and_native_cancellation_serialize_on_job_lock(
    database: SamuraiPostgresDb,
    postgres_url: str,
) -> None:
    # Given acceptance and native cancellation in separate processes at one barrier.
    intent, token = _prepare(database, "run-cancel-race")
    candidate = _state(intent.parent_session_id)
    context = get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = (
        context.Process(
            target=_accept_in_process,
            args=(
                (
                    postgres_url,
                    database.db_schema,
                    candidate.model_dump_json(),
                    token.model_dump_json(),
                ),
                barrier,
                results,
            ),
        ),
        context.Process(
            target=_cancel_in_process,
            args=(
                (postgres_url, database.db_schema, token.model_dump_json()),
                barrier,
                results,
            ),
        ),
    )

    # When both processes attempt the job-row transition concurrently.
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)

    # Then cancellation commits once and acceptance is linearized before or after it.
    outcomes = {results.get(timeout=2), results.get(timeout=2)}
    assert all(process.exitcode == 0 for process in processes)
    assert "cancelled:True" in outcomes
    acceptance = outcomes - {"cancelled:True"}
    assert acceptance in (
        {WorkIntentIssue.CANCELLED.value},
        {str(candidate.artifacts[-1].artifact_id)},
    )
    stored = database.get_job(token.parent_run_id)
    assert stored is not None
    assert _StoredJob.model_validate(stored).status == "cancelled"
    admitted = database.enqueue_job(
        _job("run-after-cancel-race", intent, key="after-cancel-race-key")
    )
    assert admitted["accepted"] is True


def test_acceptance_cancelled_job_cannot_commit_late_state(
    database: SamuraiPostgresDb,
) -> None:
    # Given an acceptance token captured before persisted native cancellation.
    intent, token = _prepare(database, "run-cancelled")
    assert database.complete_job(
        token.parent_run_id,
        token.worker_id,
        token.attempt,
        "cancelled",
    )

    # When the cancelled worker tries to accept a late artifact.
    with (
        worker_managed_execution(token.parent_run_id, token.worker_id, token.attempt),
        pytest.raises(WorkIntentError) as raised,
    ):
        _ = database.accept_company_state(_state(intent.parent_session_id), token)

    # Then the shared job-row lock fences the late acceptance.
    assert raised.value.issue is WorkIntentIssue.CANCELLED


@pytest.mark.parametrize("older_timestamp", [20, 30])
def test_parent_cache_uses_highest_accepted_revision_when_timestamps_tie_or_retry(
    database: SamuraiPostgresDb,
    older_timestamp: int,
) -> None:
    first_intent, first_token = _prepare(database, "binding-first")
    first = _state(first_intent.parent_session_id)
    with worker_managed_execution(
        first_token.parent_run_id, first_token.worker_id, first_token.attempt
    ):
        _ = database.accept_company_state(first, first_token)
    assert database.complete_job(
        first_token.parent_run_id, first_token.worker_id, first_token.attempt, "completed"
    )
    second_intent = _intent(expected_revision=1, company_id=first.context.company_id)
    assert (
        database.enqueue_job(_job("binding-second", second_intent, key="second-binding-key"))[
            "accepted"
        ]
        is True
    )
    claimed = database.claim_job("worker-2", lock_grace_seconds=60)
    assert claimed is not None
    attempt = _ClaimedJob.model_validate(claimed).attempt
    second = accept_artifact(
        first,
        first.artifacts[0].model_copy(
            update={
                "artifact_id": uuid4(),
                "revision": 2,
                "input_revision": 1,
                "acceptance_status": "pending",
            }
        ),
        authenticated_session_id=first_intent.parent_session_id,
    )
    with worker_managed_execution("binding-second", "worker-2", attempt):
        second_token = database.bind_work_intent("binding-second", _normalized(second_intent)).token
        _ = database.accept_company_state(second, second_token)
    intents = Table(
        database.work_intent_table_name,
        MetaData(schema=database.db_schema),
        autoload_with=database.db_engine,
    )
    with database.db_engine.begin() as connection:
        _ = connection.execute(intents.update().values(updated_at=20))
        _ = connection.execute(
            intents.update()
            .where(intents.c.job_id == "binding-first")
            .values(updated_at=older_timestamp)
        )
    stale_binding = database.get_parent_binding("binding-first", first_intent.owner_id)
    assert stale_binding is not None
    _ = database.upsert_session(
        AgentSession(
            session_id=first_intent.parent_session_id,
            user_id=first_intent.owner_id,
            agent_id="samurai",
            created_at=20,
            updated_at=20,
            session_data={"session_state": stale_binding.model_dump(mode="json")},
        )
    )
    restored = database.get_session(
        first_intent.parent_session_id,
        session_type=SessionType.AGENT,
        user_id=first_intent.owner_id,
    )
    assert isinstance(restored, AgentSession)
    assert restored.session_data is not None
    assert restored.session_data["session_state"] == {
        "child_session_id": first_intent.child_session_id,
        "company_id": str(first.context.company_id),
        "current_revision": 2,
    }
