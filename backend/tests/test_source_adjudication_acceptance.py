from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import anyio
from agno.run.concurrency import worker_managed_execution

from samurai.company_store import CompanyStore
from samurai.company_store_contracts import CompanyAccess, CompanyReservation
from samurai.company_workflow import CompanyJourneyRequest, create_company_workflow
from samurai.config import Settings
from samurai.contracts import CompanyState, ResearchArtifact, Role, StrategyArtifact
from samurai.execution_state import (
    AcceptanceToken,
    ApprovedStage,
    NormalizedWorkInput,
    SamuraiPostgresDb,
    WorkIntentInput,
    WorkOperation,
)
from tests.company_store_support import ClaimedJob, job, store_session
from tests.test_parent import (
    StaticRoleModel,
    deterministic_catalog,
    ordinary_mapped_research,
    supporting_source_fetch,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    import pytest
    from agno.workflow import Workflow
    from pydantic import JsonValue

    from samurai.agents import ConfiguredRole
    from samurai.source_fetch import SourceFetchResult


pytest_plugins = ("tests.company_store_support",)


def _bound_attempt(
    database: SamuraiPostgresDb,
    owner: CompanyAccess,
    *,
    stage: ApprovedStage,
    expected_revision: int,
    run_id: str,
) -> AcceptanceToken:
    approved_input: dict[str, JsonValue] = {
        "idea": "AI receptionist for Indian dental clinics",
        "target_customer": "Independent Indian dental clinics",
        "geography": "India",
        "budget": "INR 50000",
        "founder_skills": "Python and Next.js",
        "goal": "Validate demand in 30 days",
    }
    approval = WorkIntentInput(
        owner_id="owner",
        parent_session_id=owner.parent_session_id,
        child_session_id=owner.child_session_id,
        workspace_id=owner.workspace_id,
        authorization_epoch=owner.authorization_epoch,
        company_id=owner.state.context.company_id,
        operation=WorkOperation.JOURNEY,
        stage=stage,
        expected_revision=expected_revision,
        approved_input=approved_input,
    )
    worker_id = f"worker-{stage.value}"
    assert database.enqueue_work_job(job(run_id, approval), approval)["accepted"] is True
    claimed = ClaimedJob.model_validate(database.claim_job(worker_id, 30))
    with worker_managed_execution(run_id, worker_id, claimed.attempt):
        return database.bind_work_intent(
            run_id,
            NormalizedWorkInput(
                operation=approval.operation,
                stage=approval.stage,
                expected_revision=approval.expected_revision,
                arguments=approved_input,
            ),
        ).token


def _model_calls(catalog: Mapping[Role, ConfiguredRole]) -> int:
    return sum(
        cast("StaticRoleModel", configured.agent.model).calls for configured in catalog.values()
    )


def _assessment_calls(catalog: Mapping[Role, ConfiguredRole]) -> int:
    return cast("StaticRoleModel", catalog[Role.VERIFIER].agent.model).assessment_calls


def _fresh_readback(
    database: SamuraiPostgresDb,
    postgres_url: str,
    accepted: CompanyState,
) -> None:
    fresh_database = SamuraiPostgresDb(
        id="source-adjudication-fresh-read",
        db_url=postgres_url,
        db_schema=database.db_schema,
        create_schema=False,
    )
    try:
        fresh_store = CompanyStore(fresh_database.db_engine, schema=database.db_schema)
        readback = fresh_store.read_for_actor("owner", "owner-parent")
        assert readback is not None
        assert readback.state == accepted
        assert fresh_store.read_for_actor("foreign", "owner-parent") is None
        assert fresh_store.read_for_actor("owner", "foreign-parent") is None
    finally:
        fresh_database.close()


def _assert_source_gated_offer(accepted: CompanyState) -> None:
    assert [artifact.revision for artifact in accepted.artifacts] == [1, 2, 3, 4, 5, 6]
    raw, adjudicated = accepted.artifacts[1:3]
    payload = ResearchArtifact.model_validate(adjudicated.payload)
    assert raw.claims[0].verification_status == "unverified"
    assert payload.adjudicated_from_artifact_id == raw.artifact_id
    assert payload.adjudicated_from_revision == raw.revision
    decision = payload.adjudications[0]
    assert decision.verdict == "supported"
    assert decision.claim_text == raw.claims[0].text == decision.evidence_quote
    assert decision.content_sha256 is not None
    assert decision.final_url == raw.sources[0].url
    strategy = StrategyArtifact.model_validate(accepted.artifacts[3].payload)
    assert accepted.artifacts[3].status == "draft_only"
    assert strategy.offer_diagnostic is not None


def test_postgres_workflow_retry_reuses_accepted_source_adjudication(
    company_store: tuple[CompanyStore, SamuraiPostgresDb, UUID],
    postgres_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, database, workspace_id = company_store
    owner = store.reserve(
        CompanyReservation(
            workspace_id=workspace_id,
            actor_id="owner",
            parent_session_id="owner-parent",
            child_session_id="owner-child",
            created_at=datetime(2026, 10, 15, tzinfo=UTC),
        )
    )
    store_session(database, "owner", owner)
    catalog = deterministic_catalog()
    fetch_calls: list[tuple[str, ...]] = []

    def catalog_factory(_settings: Settings) -> dict[Role, ConfiguredRole]:
        return catalog

    async def counted_source_fetch(urls: Sequence[str]) -> tuple[SourceFetchResult, ...]:
        fetch_calls.append(tuple(urls))
        return await supporting_source_fetch(urls)

    monkeypatch.setattr("samurai.company_workflow.create_role_catalog", catalog_factory)
    monkeypatch.setattr("samurai.company_workflow.run_research", ordinary_mapped_research)
    monkeypatch.setattr("samurai.company_workflow.fetch_sources", counted_source_fetch)
    research_workflow = create_company_workflow(
        database, Settings.model_validate({}), stage="research"
    )
    session_state = {"company": owner.state.model_dump(mode="json")}
    request = CompanyJourneyRequest(
        company_id=owner.state.context.company_id,
        expected_revision=0,
        idea="AI receptionist for Indian dental clinics",
        target_customer="Independent Indian dental clinics",
        geography="India",
        budget="INR 50000",
        founder_skills="Python and Next.js",
        goal="Validate demand in 30 days",
    )
    research_token = _bound_attempt(
        database,
        owner,
        stage=ApprovedStage.RESEARCH,
        expected_revision=0,
        run_id="source-adjudication-pg-research",
    )

    async def run_journey(
        workflow: Workflow,
        journey_request: CompanyJourneyRequest,
        token: AcceptanceToken,
    ) -> None:
        _ = await workflow.arun(
            journey_request,
            user_id="owner",
            session_id="owner-child",
            session_state=session_state,
            dependencies={
                "trusted_parent_session_id": "owner-parent",
                "trusted_user_id": "owner",
                "child_session_id": "owner-child",
                "parent_run_id": token.parent_run_id,
                "worker_id": token.worker_id,
                "attempt": token.attempt,
                "fingerprint": token.fingerprint,
            },
        )

    with worker_managed_execution(
        research_token.parent_run_id, research_token.worker_id, research_token.attempt
    ):
        anyio.run(run_journey, research_workflow, request, research_token)

    accepted_research = CompanyState.model_validate(session_state["company"])
    assert accepted_research.current_revision == 3
    _fresh_readback(database, postgres_url, accepted_research)
    initial_fetch_calls = tuple(fetch_calls)
    research_model_calls = _model_calls(catalog)
    research_assessment_calls = _assessment_calls(catalog)
    assert database.complete_job(
        research_token.parent_run_id,
        research_token.worker_id,
        research_token.attempt,
        "completed",
    )

    plan_token = _bound_attempt(
        database,
        owner,
        stage=ApprovedStage.PLAN,
        expected_revision=accepted_research.current_revision,
        run_id="source-adjudication-pg-plan",
    )
    plan_workflow = create_company_workflow(database, Settings.model_validate({}))
    plan_request = request.model_copy(update={"expected_revision": 3})
    with worker_managed_execution(
        plan_token.parent_run_id, plan_token.worker_id, plan_token.attempt
    ):
        anyio.run(run_journey, plan_workflow, plan_request, plan_token)

    accepted = CompanyState.model_validate(session_state["company"])
    initial_model_calls = _model_calls(catalog)
    assert _assessment_calls(catalog) == research_assessment_calls
    retry = plan_request.model_copy(update={"expected_revision": accepted.current_revision})
    with worker_managed_execution(
        plan_token.parent_run_id, plan_token.worker_id, plan_token.attempt
    ):
        anyio.run(run_journey, plan_workflow, retry, plan_token)

    assert tuple(fetch_calls) == initial_fetch_calls
    assert len(initial_fetch_calls) == 1
    assert research_model_calls == 2
    assert research_assessment_calls == 1
    assert _model_calls(catalog) == initial_model_calls
    assert _assessment_calls(catalog) == research_assessment_calls
    assert initial_model_calls == 5
    assert CompanyState.model_validate(session_state["company"]) == accepted

    _fresh_readback(database, postgres_url, accepted)
    _assert_source_gated_offer(accepted)
