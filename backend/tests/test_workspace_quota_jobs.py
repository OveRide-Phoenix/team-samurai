from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import TYPE_CHECKING

import pytest
from agno.db.schemas.jobs import QueuedJob
from agno.run.concurrency import worker_managed_execution
from pydantic import BaseModel, TypeAdapter
from sqlalchemy import MetaData, Table, func, select

from samurai.company_store_contracts import WorkspaceRole
from samurai.execution_state import (
    WORK_INTENT_METADATA_KEY,
    ApprovedStage,
    NormalizedWorkInput,
    SamuraiPostgresDb,
    WorkIntentError,
    WorkIntentInput,
    WorkIntentIssue,
    WorkOperation,
)
from samurai.workspace_directory import WorkspaceDirectory

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

pytest_plugins = ("tests.test_workspace_quota",)
INT_ADAPTER = TypeAdapter(int)


class _ClaimedJob(BaseModel):
    id: str
    attempt: int


def _intent(workspace_id: UUID, company_id: UUID, suffix: str) -> WorkIntentInput:
    return WorkIntentInput(
        owner_id="owner",
        parent_session_id=f"parent-{suffix}",
        child_session_id=f"child-{suffix}",
        workspace_id=workspace_id,
        authorization_epoch=1,
        company_id=company_id,
        operation=WorkOperation.JOURNEY,
        stage=ApprovedStage.BRIEF,
        expected_revision=0,
        approved_input={"idea": f"idea-{suffix}"},
    )


def _job(run_id: str, intent: WorkIntentInput, key: str) -> dict[str, object]:
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


def _active_job_count(database: SamuraiPostgresDb, workspace_id: UUID) -> int:
    quotas = Table(
        "samurai_workspace_quotas",
        MetaData(schema=database.db_schema),
        autoload_with=database.db_engine,
    )
    with database.db_engine.connect() as connection:
        return INT_ADAPTER.validate_python(
            connection.execute(
                select(quotas.c.active_job_count).where(quotas.c.workspace_id == workspace_id)
            ).scalar_one()
        )


def _outcome(operation: Callable[[], object]) -> str:
    try:
        _ = operation()
    except WorkIntentError as error:
        return error.issue.value
    return "accepted"


def test_four_synchronized_work_admissions_commit_only_three_active_jobs(
    quota_database: SamuraiPostgresDb,
) -> None:
    # Given four distinct companies in one shared workspace.
    directory = WorkspaceDirectory(quota_database)
    workspace_id = directory.create_workspace("owner", "Job boundary").workspace_id
    intents = tuple(
        _intent(workspace_id, directory.create_company("owner", workspace_id).company_id, str(i))
        for i in range(4)
    )
    barrier = Barrier(4)

    def admit(index: int) -> str:
        _ = barrier.wait()
        intent = intents[index]
        return _outcome(
            lambda: quota_database.enqueue_work_job(
                _job(f"quota-run-{index}", intent, f"quota-key-{index}"), intent
            )
        )

    # When all four native job admissions race.
    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = tuple(executor.map(admit, range(4)))

    # Then three job/intent rows own capacity and the excess admission conflicts.
    assert outcomes.count("accepted") == 3
    assert outcomes.count(WorkIntentIssue.WORKSPACE_QUOTA.value) == 1
    intents_table = Table(
        quota_database.work_intent_table_name,
        MetaData(schema=quota_database.db_schema),
        autoload_with=quota_database.db_engine,
    )
    with quota_database.db_engine.connect() as connection:
        reservations = connection.execute(
            select(func.count())
            .select_from(intents_table)
            .where(
                intents_table.c.workspace_id == workspace_id,
                intents_table.c.active_job_reserved,
            )
        ).scalar_one()
    assert _active_job_count(quota_database, workspace_id) == reservations == 3
    for index in range(4):
        if quota_database.get_job(f"quota-run-{index}") is not None:
            assert quota_database.cancel_job(f"quota-run-{index}")
    assert _active_job_count(quota_database, workspace_id) == 0


def test_work_admission_retries_are_idempotent_and_rollback_insert_failure(
    quota_database: SamuraiPostgresDb,
) -> None:
    # Given one shared job admitted with a stable idempotency key.
    directory = WorkspaceDirectory(quota_database)
    workspace_id = directory.create_workspace("owner", "Job retries").workspace_id
    company_id = directory.create_company("owner", workspace_id).company_id
    intent = _intent(workspace_id, company_id, "retry")
    job = _job("retry-original", intent, "stable-key")
    assert quota_database.enqueue_work_job(job, intent)["accepted"] is True

    # When identical and changed payloads reuse the key.
    identical = quota_database.enqueue_work_job(_job("retry-copy", intent, "stable-key"), intent)
    changed = intent.model_copy(update={"approved_input": {"idea": "changed"}})
    with pytest.raises(WorkIntentError) as rejected:
        _ = quota_database.enqueue_work_job(_job("retry-changed", changed, "stable-key"), changed)

    # Then only the original owns capacity and transaction failures do not leak it.
    assert identical["accepted"] is False
    assert identical["reason"] == "duplicate"
    assert rejected.value.issue is WorkIntentIssue.CHANGED_APPROVAL
    assert _active_job_count(quota_database, workspace_id) == 1
    second_workspace = directory.create_workspace("owner", "Insert rollback").workspace_id
    second_company = directory.create_company("owner", second_workspace).company_id
    second_intent = _intent(second_workspace, second_company, "collision")
    with pytest.raises(WorkIntentError) as collision:
        _ = quota_database.enqueue_work_job(
            _job("retry-original", second_intent, "other-key"), second_intent
        )
    assert collision.value.issue is WorkIntentIssue.ACTIVE_WORK
    assert _active_job_count(quota_database, second_workspace) == 0


def test_all_terminal_paths_release_once_while_retry_and_pause_retain_capacity(
    quota_database: SamuraiPostgresDb,
) -> None:
    # Given one company reused across sequential native job lifecycles.
    directory = WorkspaceDirectory(quota_database)
    workspace_id = directory.create_workspace("owner", "Job lifecycle").workspace_id
    company_id = directory.create_company("owner", workspace_id).company_id

    def admit(suffix: str) -> None:
        intent = _intent(workspace_id, company_id, suffix)
        result = quota_database.enqueue_work_job(
            _job(f"lifecycle-{suffix}", intent, f"lifecycle-key-{suffix}"), intent
        )
        assert result["accepted"] is True
        assert _active_job_count(quota_database, workspace_id) == 1

    # When cancellation, completion, exhausted retry, paused settlement, and sweep run.
    admit("cancel")
    assert quota_database.cancel_job("lifecycle-cancel")
    assert not quota_database.cancel_job("lifecycle-cancel")
    assert _active_job_count(quota_database, workspace_id) == 0

    admit("complete")
    claimed = _ClaimedJob.model_validate(quota_database.claim_job("worker-complete"))
    assert quota_database.complete_job(claimed.id, "worker-complete", claimed.attempt, "completed")
    assert _active_job_count(quota_database, workspace_id) == 0

    admit("retry")
    first = _ClaimedJob.model_validate(quota_database.claim_job("worker-retry-1"))
    assert (
        quota_database.retry_or_fail_job(
            first.id, "worker-retry-1", first.attempt, "transient", retry_delay_seconds=0
        )
        == "queued"
    )
    assert _active_job_count(quota_database, workspace_id) == 1
    second = _ClaimedJob.model_validate(quota_database.claim_job("worker-retry-2"))
    assert (
        quota_database.retry_or_fail_job(
            second.id, "worker-retry-2", second.attempt, "exhausted", retry_delay_seconds=0
        )
        == "failed"
    )
    assert _active_job_count(quota_database, workspace_id) == 0

    admit("paused")
    paused = _ClaimedJob.model_validate(quota_database.claim_job("worker-paused"))
    assert quota_database.complete_job(paused.id, "worker-paused", paused.attempt, "paused")
    assert _active_job_count(quota_database, workspace_id) == 1
    assert quota_database.settle_paused_job(paused.id, "failed", "stopped")
    assert _active_job_count(quota_database, workspace_id) == 0

    admit("swept")
    swept = _ClaimedJob.model_validate(quota_database.claim_job("worker-swept"))
    assert quota_database.settle_swept_job(swept.id, "worker-swept", "failed", "expired")
    assert _active_job_count(quota_database, workspace_id) == 0


def test_accepted_artifact_state_does_not_release_active_company_fence(
    quota_database: SamuraiPostgresDb,
) -> None:
    # Given an active shared job whose artifact intent reached accepted state.
    directory = WorkspaceDirectory(quota_database)
    workspace_id = directory.create_workspace("owner", "Artifact fence").workspace_id
    company_id = directory.create_company("owner", workspace_id).company_id
    first = _intent(workspace_id, company_id, "artifact")
    assert (
        quota_database.enqueue_work_job(_job("artifact-first", first, "artifact-key-first"), first)[
            "accepted"
        ]
        is True
    )
    intents = Table(
        quota_database.work_intent_table_name,
        MetaData(schema=quota_database.db_schema),
        autoload_with=quota_database.db_engine,
    )
    with quota_database.db_engine.begin() as connection:
        _ = connection.execute(
            intents.update().where(intents.c.job_id == "artifact-first").values(state="accepted")
        )

    # When distinct work tries to enter before and after native completion.
    second = _intent(workspace_id, company_id, "artifact-next")
    with pytest.raises(WorkIntentError) as active:
        _ = quota_database.enqueue_work_job(
            _job("artifact-blocked", second, "artifact-key-blocked"), second
        )
    assert quota_database.cancel_job("artifact-first")
    admitted = quota_database.enqueue_work_job(
        _job("artifact-after", second, "artifact-key-after"), second
    )

    # Then the durable reservation flag fences accepted artifacts until the job is terminal.
    assert active.value.issue is WorkIntentIssue.ACTIVE_WORK
    assert admitted["accepted"] is True


def test_dispatch_revalidates_membership_epoch_and_terminal_cleanup_releases(
    quota_database: SamuraiPostgresDb,
) -> None:
    # Given an editor-authorized job admitted before the editor is revoked.
    directory = WorkspaceDirectory(quota_database)
    workspace_id = directory.create_workspace("owner", "Dispatch epoch").workspace_id
    company_id = directory.create_company("owner", workspace_id).company_id
    _ = directory.put_member("owner", workspace_id, "editor", WorkspaceRole.EDITOR)
    intent = _intent(workspace_id, company_id, "epoch").model_copy(update={"owner_id": "editor"})
    assert (
        quota_database.enqueue_work_job(_job("epoch-job", intent, "epoch-key"), intent)["accepted"]
        is True
    )
    directory.delete_member("owner", workspace_id, "editor")
    claimed = _ClaimedJob.model_validate(quota_database.claim_job("epoch-worker"))

    # When dispatch binds the claimed attempt against the persisted epoch.
    with (
        worker_managed_execution(claimed.id, "epoch-worker", claimed.attempt),
        pytest.raises(WorkIntentError) as revoked,
    ):
        _ = quota_database.bind_work_intent(
            claimed.id,
            NormalizedWorkInput(
                operation=intent.operation,
                stage=intent.stage,
                expected_revision=intent.expected_revision,
                arguments={"idea": "idea-epoch"},
            ),
        )

    # Then dispatch fails closed and terminal failure releases the reserved slot.
    assert revoked.value.issue is WorkIntentIssue.AUTHORIZATION_CHANGED
    assert quota_database.complete_job(
        claimed.id, "epoch-worker", claimed.attempt, "failed", "authorization changed"
    )
    assert _active_job_count(quota_database, workspace_id) == 0
