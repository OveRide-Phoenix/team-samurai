"""Contract boundary scenarios kept together for lineage coverage. # noqa: SIZE_OK."""

from datetime import UTC, datetime
from typing import Literal, get_args
from uuid import UUID, uuid4

import pytest
from pydantic import HttpUrl, TypeAdapter, ValidationError

from samurai.contracts import (
    AnalysisArtifact,
    ArtifactEnvelope,
    ArtifactType,
    AspectStartingPoint,
    Assumption,
    CompanyBrief,
    CompanyMismatchError,
    CompanyState,
    FounderKnownFact,
    FounderMetricInput,
    FounderTruth,
    FrameworkReference,
    IdeaAnalysis,
    IntakeArtifact,
    InvalidArtifactTransitionError,
    MeasuredResult,
    OfferDiagnostic,
    ResearchArtifact,
    Role,
    SessionMismatchError,
    SourceAdjudication,
    SourcedClaim,
    SourceReference,
    StaleRevisionError,
    StrategyArtifact,
    VerificationFinding,
    accept_artifact,
    create_company_state,
)

NOW = datetime(2026, 10, 11, tzinfo=UTC)


def test_initial_analysis_is_bounded_unverified_and_backwards_compatible() -> None:
    point = {
        "checkpoint_id": "minimum-product",
        "answer": "Test one booking flow.",
        "basis": "inferred",
    }
    analysis = IdeaAnalysis.model_validate(
        {"summary": "Demand is untested.", "starting_points": [point]}
    )
    artifact = IntakeArtifact(brief=_brief(), idea_analysis=analysis)
    assert IntakeArtifact.model_validate_json(artifact.model_dump_json()).idea_analysis == analysis
    assert "idea_analysis" not in IntakeArtifact(brief=_brief()).model_dump(mode="json")
    checkpoint_ids = TypeAdapter(tuple[str, ...]).validate_python(
        get_args(AspectStartingPoint.model_fields["checkpoint_id"].annotation)
    )
    points = [{**point, "checkpoint_id": checkpoint_id} for checkpoint_id in checkpoint_ids]
    assert (
        len(
            IdeaAnalysis.model_validate(
                {"summary": "Draft", "starting_points": points}
            ).starting_points
        )
        == 18
    )
    with pytest.raises(ValidationError, match="unique"):
        _ = IdeaAnalysis.model_validate({"summary": "Draft", "starting_points": [*points, point]})
    for points in (
        [point, point],
        [{**point, "checkpoint_id": "unknown"}],
        [{**point, "basis": "verified"}],
        [{**point, "answer": "x" * 2001}],
    ):
        with pytest.raises(ValidationError):
            _ = IdeaAnalysis.model_validate({"summary": "Draft", "starting_points": points})


def _brief() -> CompanyBrief:
    return CompanyBrief(
        idea="Dental receptionist",
        target_customer="Indian dental clinics",
        geography="India",
        budget="INR 50000",
        founder_skills="Python",
        goal="Validate in 30 days",
        supplied_context=["Founder proposes an AI receptionist"],
        assumptions=["Clinics may pay for missed-call handling"],
        open_questions=["Which clinics feel this pain most?"],
        next_actions=["Interview five clinic owners"],
    )


def test_founder_truth_legacy_default_and_provenance_round_trip() -> None:
    # Given a legacy Intake payload and one exact reviewed framework reference.
    legacy = IntakeArtifact.model_validate({"brief": _brief().model_dump(mode="json")})
    revision = "07ea968338cff2ba67ff245671765ea957ce0a0c"
    reference = FrameworkReference(
        id="founder_truth",
        version="1.0.0",
        source_repository="gvkhosla/founder-skills",
        source_revision=revision,
        source_url=HttpUrl(f"https://github.com/gvkhosla/founder-skills/tree/{revision}"),
        license="MIT",
        attribution="Adapted from Founder Skills by Geet Khosla.",
        allowed_roles=(Role.INTAKE, Role.STRATEGIST, Role.VERIFIER),
        sha256="ba206825fb8ebd15cf911397e55628ff8b5aacf28cbb02b65d20c978bc31e0bb",
        review_date="2026-10-15",
    )

    # When a new Intake artifact is serialized and restored.
    truth = FounderTruth(
        known=(
            FounderKnownFact(
                text="Python",
                basis="founder_context",
                context_key="founder_skills",
            ),
        ),
        believed=("Clinics lose bookings from missed calls.",),
        hoped=("A clinic will pay for a pilot.",),
        evidence_gaps=("No retained willingness-to-pay evidence.",),
        bottleneck="Validate a painful missed-call workflow.",
        next_decision="Choose whether to interview clinic owners first.",
    )
    restored = IntakeArtifact.model_validate_json(
        IntakeArtifact(
            brief=_brief(), founder_truth=truth, frameworks=(reference,)
        ).model_dump_json()
    )

    # Then legacy input stays loadable and new truth/provenance round-trip exactly.
    assert legacy.founder_truth == FounderTruth()
    assert legacy.frameworks == ()
    assert restored.founder_truth == truth
    assert restored.frameworks == (reference,)


def test_founder_truth_rejects_contradictory_categories() -> None:
    # Given one statement classified as both known and believed.
    with pytest.raises(ValidationError, match="truth categories must be disjoint"):
        _ = FounderTruth(
            known=(
                FounderKnownFact(
                    text="Customers will pay.",
                    basis="retained_evidence",
                    evidence_ids=(uuid4(),),
                ),
            ),
            believed=("Customers will pay.",),
        )


def test_offer_diagnostic_rejects_a_forged_framework_authority() -> None:
    reference = FrameworkReference(
        id="founder_truth",
        version="1.0.0",
        source_repository="gvkhosla/founder-skills",
        source_revision="07ea968338cff2ba67ff245671765ea957ce0a0c",
        source_url=HttpUrl(
            "https://github.com/gvkhosla/founder-skills/tree/07ea968338cff2ba67ff245671765ea957ce0a0c"
        ),
        license="MIT",
        attribution="Founder truth.",
        allowed_roles=(Role.INTAKE, Role.STRATEGIST),
        sha256="ba206825fb8ebd15cf911397e55628ff8b5aacf28cbb02b65d20c978bc31e0bb",
        review_date="2026-10-15",
    )
    with pytest.raises(ValidationError, match="offer diagnostics require"):
        _ = OfferDiagnostic(
            market="Clinics",
            painful_problem="Missed calls",
            purchasing_power_assumption=Assumption(assumption_id=uuid4(), text="Budget unknown"),
            draft_offer="A pilot",
            evidence_needed=("Retained willingness-to-pay evidence.",),
            framework=reference,
        )
    assert (
        StrategyArtifact.model_validate(
            {
                "ideal_customer_profile": "Clinics",
                "positioning": "Handle missed calls",
                "offer": "A pilot",
                "pricing_assumptions": [],
            }
        ).offer_diagnostic
        is None
    )


def _artifact(state: CompanyState, *, input_revision: int | None = None) -> ArtifactEnvelope:
    source = SourceReference(
        source_id=uuid4(),
        url=HttpUrl("https://example.com/clinic-study"),
        title="Clinic study",
        retrieved_at=NOW,
        search_query="Indian dental clinic missed calls",
        excerpt="Clinics report missed calls.",
    )
    claim = SourcedClaim(
        claim_id=uuid4(),
        text="Some clinics report missed calls.",
        source_ids=(source.source_id,),
        support_status="mapped",
        support_segments=("Clinics report missed calls.",),
        verification_status="unverified",
    )
    return ArtifactEnvelope(
        artifact_id=uuid4(),
        company_id=state.context.company_id,
        artifact_type=ArtifactType.INTAKE,
        revision=state.current_revision + 1,
        input_revision=state.current_revision if input_revision is None else input_revision,
        producer=Role.INTAKE,
        status="complete",
        payload=IntakeArtifact(brief=_brief()),
        sources=(source,),
        claims=(claim,),
        assumptions=(
            Assumption(
                assumption_id=uuid4(),
                text="Clinics may pay for missed-call handling.",
            ),
        ),
        verification_findings=(
            VerificationFinding(
                code="brief_complete",
                message="Required founder context is present.",
                severity="info",
            ),
        ),
    )


def _research_artifact(state: CompanyState) -> ArtifactEnvelope:
    source = SourceReference(
        source_id=uuid4(),
        url=HttpUrl("https://example.com/clinic-study"),
        title="Clinic study",
        retrieved_at=NOW,
        search_query="Indian dental clinic missed calls",
        excerpt="Clinics report missed calls and want a reliable callback process.",
    )
    claim = SourcedClaim(
        claim_id=uuid4(),
        text="Some clinics report missed calls.",
        source_ids=(source.source_id,),
        support_status="mapped",
        support_segments=("Clinics report missed calls.",),
        verification_status="unverified",
    )
    return ArtifactEnvelope(
        artifact_id=uuid4(),
        company_id=state.context.company_id,
        artifact_type=ArtifactType.RESEARCH,
        revision=state.current_revision + 1,
        input_revision=state.current_revision,
        producer=Role.RESEARCHER,
        status="needs_rework",
        payload=ResearchArtifact(
            summary="Clinic demand still needs source adjudication.",
            conflicts=("Pricing evidence is inconsistent.",),
        ),
        sources=(source,),
        claims=(claim,),
        assumptions=(),
        verification_findings=(
            VerificationFinding(
                code="source_review_pending",
                message="Retained research requires source adjudication.",
                severity="warning",
            ),
        ),
    )


def _adjudicated_research(raw: ArtifactEnvelope) -> ArtifactEnvelope:
    source = raw.sources[0]
    claim = raw.claims[0]
    assert isinstance(raw.payload, ResearchArtifact)
    decision = SourceAdjudication(
        research_artifact_id=raw.artifact_id,
        research_revision=raw.revision,
        claim_id=claim.claim_id,
        claim_text=claim.text,
        source_id=source.source_id,
        source_url=source.url,
        attempted_at=datetime(2026, 10, 12, tzinfo=UTC),
        fetched_at=datetime(2026, 10, 12, 0, 0, 1, tzinfo=UTC),
        final_url=source.url,
        content_sha256="a" * 64,
        media_type="text/html",
        evidence_quote="Clinics report missed calls",
        verdict="supported",
        rationale="The retained quote directly supports the claim.",
    )
    payload = raw.payload.model_copy(
        update={
            "adjudicated_from_artifact_id": raw.artifact_id,
            "adjudicated_from_revision": raw.revision,
            "adjudications": (decision,),
        }
    )
    claims = tuple(
        item.model_copy(update={"verification_status": "supported"})
        if item.claim_id == claim.claim_id
        else item
        for item in raw.claims
    )
    return raw.model_copy(
        update={
            "artifact_id": uuid4(),
            "revision": raw.revision + 1,
            "input_revision": raw.revision,
            "producer": Role.VERIFIER,
            "acceptance_status": "pending",
            "payload": payload,
            "claims": claims,
        }
    )


def _adjudication_from(artifact: ArtifactEnvelope) -> SourceAdjudication:
    assert isinstance(artifact.payload, ResearchArtifact)
    assert len(artifact.payload.adjudications) == 1
    return artifact.payload.adjudications[0]


def _forged_adjudications(
    case: str, decision: SourceAdjudication
) -> tuple[SourceAdjudication, ...]:
    if case == "duplicate_pair":
        return (decision, decision)
    if case == "missing_pair":
        return ()
    updates: dict[str, dict[str, object]] = {
        "altered_claim": {"claim_text": "Altered claim text."},
        "altered_source": {"source_url": HttpUrl("https://example.com/altered")},
        "unknown_pair": {"claim_id": uuid4()},
        "quote_not_retained": {"evidence_quote": "This text was not retained."},
        "malformed_hash": {"content_sha256": "not-a-sha"},
        "malformed_final_url": {"final_url": "not-a-url"},
        "inaccessible_with_fetched_fields": {
            "verdict": "inaccessible",
            "evidence_quote": "",
        },
        "insufficient_without_fetched_fields": {
            "verdict": "insufficient",
            "evidence_quote": "",
            "fetched_at": None,
            "final_url": None,
            "content_sha256": None,
            "media_type": None,
        },
    }
    return (decision.model_copy(update=updates[case]),)


def test_valid_source_adjudication_preserves_raw_research_and_round_trips() -> None:
    # Given an accepted raw Research revision and a complete source adjudication revision.
    initial = create_company_state("session-1", created_at=NOW)
    raw = _research_artifact(initial)
    state = accept_artifact(initial, raw, authenticated_session_id="session-1")
    raw_json = state.artifacts[0].model_dump_json()
    adjudicated = _adjudicated_research(state.artifacts[0])

    # When the adjudicated Research revision enters canonical history and is serialized.
    updated = accept_artifact(state, adjudicated, authenticated_session_id="session-1")
    restored = CompanyState.model_validate_json(updated.model_dump_json())

    # Then raw bytes remain immutable and the full bound adjudication remains durable.
    assert restored.artifacts[0].model_dump_json() == raw_json
    assert restored.current_revision == 2
    assert restored.artifacts[1].payload == adjudicated.payload


def test_legacy_research_defaults_to_an_unadjudicated_payload() -> None:
    # Given a pre-adjudication Research payload at the persistence boundary.
    legacy = ResearchArtifact.model_validate({"summary": "Research is retained.", "conflicts": []})

    # When the existing JSON shape is parsed without new fields.
    restored = ResearchArtifact.model_validate_json(legacy.model_dump_json())

    # Then its additive adjudication fields remain empty defaults.
    assert restored.adjudicated_from_artifact_id is None
    assert restored.adjudicated_from_revision is None
    assert restored.adjudications == ()


@pytest.mark.parametrize(
    ("verdict", "claim_status"),
    [
        ("supported", "unverified"),
        ("contradicted", "supported"),
        ("insufficient", "supported"),
        ("inaccessible", "supported"),
    ],
)
def test_rejects_claim_status_that_disagrees_with_source_adjudications(
    verdict: Literal["supported", "contradicted", "insufficient", "inaccessible"],
    claim_status: Literal["unverified", "supported", "contradicted"],
) -> None:
    # Given a complete adjudication whose retained claim status contradicts its verdict.
    initial = create_company_state("session-1", created_at=NOW)
    state = accept_artifact(
        initial, _research_artifact(initial), authenticated_session_id="session-1"
    )
    adjudicated = _adjudicated_research(state.artifacts[0])
    base_decision = _adjudication_from(adjudicated)
    inaccessible = verdict == "inaccessible"
    decision = base_decision.model_copy(
        update={
            "verdict": verdict,
            "evidence_quote": (
                "" if verdict in {"insufficient", "inaccessible"} else "Clinics report missed calls"
            ),
            "fetched_at": None if inaccessible else base_decision.fetched_at,
            "final_url": None if inaccessible else base_decision.final_url,
            "content_sha256": None if inaccessible else base_decision.content_sha256,
            "media_type": None if inaccessible else base_decision.media_type,
        }
    )
    assert isinstance(adjudicated.payload, ResearchArtifact)
    candidate = adjudicated.model_copy(
        update={
            "claims": (
                adjudicated.claims[0].model_copy(update={"verification_status": claim_status}),
            ),
            "payload": adjudicated.payload.model_copy(update={"adjudications": (decision,)}),
        }
    )

    # When the forged status enters the shared acceptance transition.
    with pytest.raises(
        InvalidArtifactTransitionError,
        match="claim verification status must match its source adjudication verdicts",
    ):
        _ = accept_artifact(state, candidate, authenticated_session_id="session-1")

    # Then the accepted raw research stays the only canonical revision.
    assert state.current_revision == 1


@pytest.mark.parametrize(
    "case",
    [
        "altered_claim",
        "altered_source",
        "duplicate_pair",
        "missing_pair",
        "unknown_pair",
        "quote_not_retained",
        "malformed_hash",
        "malformed_final_url",
        "inaccessible_with_fetched_fields",
        "insufficient_without_fetched_fields",
    ],
)
def test_rejects_adjudication_with_forged_or_incomplete_bindings(case: str) -> None:
    # Given a valid raw Research revision and one pending adjudication payload.
    initial = create_company_state("session-1", created_at=NOW)
    state = accept_artifact(
        initial, _research_artifact(initial), authenticated_session_id="session-1"
    )
    adjudicated = _adjudicated_research(state.artifacts[0])
    decision = _adjudication_from(adjudicated)
    assert isinstance(adjudicated.payload, ResearchArtifact)
    candidate = adjudicated.model_copy(
        update={
            "payload": adjudicated.payload.model_copy(
                update={"adjudications": _forged_adjudications(case, decision)}
            )
        }
    )

    # When malformed or inconsistent adjudication data crosses the artifact boundary.
    if case == "malformed_final_url":
        with pytest.warns(UserWarning, match="Pydantic serializer"):
            candidate_json = candidate.model_dump_json()
    else:
        candidate_json = candidate.model_dump_json()
    with pytest.raises(ValidationError):
        _ = ArtifactEnvelope.model_validate_json(candidate_json)

    # Then the accepted raw state remains byte-for-byte unchanged.
    assert state.current_revision == 1


def test_rejects_adjudication_for_a_nonlatest_or_replayed_raw_revision() -> None:
    # Given a raw Research revision followed by its accepted adjudication.
    initial = create_company_state("session-1", created_at=NOW)
    raw_state = accept_artifact(
        initial, _research_artifact(initial), authenticated_session_id="session-1"
    )
    adjudicated = _adjudicated_research(raw_state.artifacts[0])
    state = accept_artifact(raw_state, adjudicated, authenticated_session_id="session-1")
    replay = _adjudicated_research(raw_state.artifacts[0]).model_copy(
        update={"revision": state.current_revision + 1, "input_revision": state.current_revision}
    )

    # When the old raw revision is proposed for adjudication again.
    with pytest.raises(InvalidArtifactTransitionError):
        _ = accept_artifact(
            state,
            replay,
            authenticated_session_id="session-1",
        )

    # Then canonical history remains at the first adjudication only.
    assert state.current_revision == 2


@pytest.mark.parametrize("case", ["stale_reference", "rewritten_summary", "rewritten_conflicts"])
def test_rejects_adjudication_that_does_not_preserve_the_referenced_raw_research(
    case: str,
) -> None:
    # Given a pending adjudication derived from one accepted raw Research revision.
    initial = create_company_state("session-1", created_at=NOW)
    state = accept_artifact(
        initial, _research_artifact(initial), authenticated_session_id="session-1"
    )
    adjudicated = _adjudicated_research(state.artifacts[0])
    assert isinstance(adjudicated.payload, ResearchArtifact)
    payload_update: dict[str, object]
    if case == "stale_reference":
        decision = _adjudication_from(adjudicated).model_copy(update={"research_revision": 99})
        payload_update = {"adjudicated_from_revision": 99, "adjudications": (decision,)}
    elif case == "rewritten_summary":
        payload_update = {"summary": "This attempts to rewrite the raw research."}
    else:
        payload_update = {"conflicts": ()}
    candidate = adjudicated.model_copy(
        update={"payload": adjudicated.payload.model_copy(update=payload_update)}
    )

    # When the structurally valid revision attempts to enter canonical history.
    with pytest.raises(InvalidArtifactTransitionError):
        _ = accept_artifact(
            state,
            candidate,
            authenticated_session_id="session-1",
        )

    # Then no raw Research artifact is rewritten or replaced.
    assert state.current_revision == 1


def test_accepts_current_revision_and_preserves_evidence_categories() -> None:
    # Given a new authenticated session and a verified artifact at its current revision.
    state = create_company_state("session-1", created_at=NOW)
    artifact = _artifact(state)

    # When the deterministic state transition accepts the artifact.
    updated = accept_artifact(state, artifact, authenticated_session_id="session-1")

    # Then the revision advances exactly once and evidence categories stay distinct.
    assert updated.current_revision == 1
    assert updated.artifacts[0].artifact_id == artifact.artifact_id
    assert updated.artifacts[0].acceptance_status == "accepted"
    assert updated.artifacts[0].claims[0].verification_status == "unverified"
    assert updated.artifacts[0].assumptions[0].text.startswith("Clinics may")


@pytest.mark.parametrize(
    "status", ["needs_input", "draft_only", "based_on_founder_supplied_metrics"]
)
def test_accepts_nonfactual_status_without_promoting_evidence(status: str) -> None:
    # Given a nonfactual artifact status accepted only as a structural transition.
    state = create_company_state("session-1", created_at=NOW)
    raw = _artifact(state).model_dump(mode="json")
    raw["status"] = status
    artifact = ArtifactEnvelope.model_validate(raw)

    # When it enters canonical state, then workflow and evidence status remain honest.
    updated = accept_artifact(state, artifact, authenticated_session_id="session-1")

    assert updated.artifacts[0].status == status
    assert updated.artifacts[0].claims[0].verification_status == "unverified"


def test_rejects_model_claim_of_prior_state_acceptance() -> None:
    # Given an untrusted artifact that claims the code-owned acceptance decision.
    state = create_company_state("session-1", created_at=NOW)
    forged = _artifact(state).model_copy(update={"acceptance_status": "accepted"})

    # When it reaches the transition, then the forged decision is rejected.
    with pytest.raises(InvalidArtifactTransitionError):
        _ = accept_artifact(state, forged, authenticated_session_id="session-1")


def test_rejects_stale_revision_without_mutation() -> None:
    # Given canonical state already advanced by one accepted artifact.
    initial = create_company_state("session-1", created_at=NOW)
    state = accept_artifact(initial, _artifact(initial), authenticated_session_id="session-1")
    before = state.model_dump_json()
    stale = _artifact(state, input_revision=0)

    # When a stale output is offered, then the exact typed error is raised.
    with pytest.raises(StaleRevisionError) as raised:
        _ = accept_artifact(state, stale, authenticated_session_id="session-1")

    assert raised.value.expected_revision == 1
    assert raised.value.received_revision == 0
    assert state.model_dump_json() == before


def test_rejects_artifact_from_another_company() -> None:
    # Given an artifact whose company ID was replaced after creation.
    state = create_company_state("session-1", created_at=NOW)
    artifact = _artifact(state).model_copy(update={"company_id": uuid4()})

    # When it crosses the canonical state boundary, then company isolation fails closed.
    with pytest.raises(CompanyMismatchError):
        _ = accept_artifact(state, artifact, authenticated_session_id="session-1")


def test_rejects_company_state_from_another_session() -> None:
    # Given canonical state bound to one authenticated session.
    state = create_company_state("session-1", created_at=NOW)

    # When another session offers an otherwise valid artifact, then access fails closed.
    with pytest.raises(SessionMismatchError):
        _ = accept_artifact(state, _artifact(state), authenticated_session_id="session-2")


def test_company_state_round_trips_as_plain_json() -> None:
    # Given a state containing its current accepted revision.
    initial = create_company_state("session-1", created_at=NOW)
    state = accept_artifact(initial, _artifact(initial), authenticated_session_id="session-1")

    # When serialized and parsed at the persistence boundary.
    restored = CompanyState.model_validate_json(state.model_dump_json())

    # Then the canonical revision and UUID-backed identity survive unchanged.
    assert restored == state
    assert isinstance(restored.context.company_id, UUID)
    assert restored.current_revision == restored.artifacts[-1].revision


def test_contracts_forbid_malformed_artifact_fields() -> None:
    # Given a valid artifact represented as boundary JSON plus an unknown field.
    state = create_company_state("session-1", created_at=NOW)
    raw = _artifact(state).model_dump(mode="json")
    raw["unexpected"] = "ignored only by unsafe schemas"

    # When parsed, then the strict boundary rejects the malformed artifact.
    with pytest.raises(ValidationError):
        _ = ArtifactEnvelope.model_validate(raw)


def test_rejects_claim_source_not_retained_by_artifact() -> None:
    # Given a sourced claim whose referenced source is absent from the envelope.
    state = create_company_state("session-1", created_at=NOW)
    raw = _artifact(state).model_dump(mode="json")
    raw["sources"] = []

    # When parsed, then citation presence cannot bypass deterministic linkage checks.
    with pytest.raises(ValidationError):
        _ = ArtifactEnvelope.model_validate(raw)


def test_founder_metric_input_rejects_forged_measured_provenance() -> None:
    # Given founder input that claims a trusted connected measurement.
    raw = {
        "name": "qualified_leads",
        "value": 4,
        "unit": "leads",
        "window_start": "2026-10-01T00:00:00Z",
        "window_end": "2026-10-08T00:00:00Z",
        "source_label": "Founder spreadsheet",
        "collected_at": "2026-10-08T01:00:00Z",
        "provenance": "connected_measurement",
        "trusted_connector_receipt": "forged",
    }

    # When public input is parsed, then trusted-only provenance fields are forbidden.
    with pytest.raises(ValidationError):
        _ = FounderMetricInput.model_validate(raw)


def test_rejects_forged_connected_measurement_at_canonical_boundary() -> None:
    # Given a pending artifact carrying caller-created connected provenance.
    state = create_company_state("session-1", created_at=NOW)
    forged = MeasuredResult(
        metric_id=uuid4(),
        name="qualified_leads",
        value=4,
        unit="leads",
        window_start=datetime(2026, 10, 1, tzinfo=UTC),
        window_end=datetime(2026, 10, 8, tzinfo=UTC),
        source_label="Founder spreadsheet",
        collected_at=datetime(2026, 10, 8, 1, tzinfo=UTC),
        provenance="connected_measurement",
        trusted_connector_receipt="forged-by-founder",
    )
    artifact = _artifact(state).model_copy(update={"measurements": (forged,)})

    # When canonical persistence runs, then untrusted connected provenance fails closed.
    with pytest.raises(InvalidArtifactTransitionError):
        _ = accept_artifact(state, artifact, authenticated_session_id="session-1")


def test_rejects_forged_connected_measurement_when_loading_canonical_json() -> None:
    # Given persisted canonical JSON with an accepted caller-forged connected measurement.
    state = create_company_state("session-1", created_at=NOW)
    forged = MeasuredResult(
        metric_id=uuid4(),
        name="qualified_leads",
        value=4,
        unit="leads",
        window_start=datetime(2026, 10, 1, tzinfo=UTC),
        window_end=datetime(2026, 10, 8, tzinfo=UTC),
        source_label="Founder spreadsheet",
        collected_at=datetime(2026, 10, 8, 1, tzinfo=UTC),
        provenance="connected_measurement",
        trusted_connector_receipt="forged-by-founder",
    )
    artifact = _artifact(state).model_copy(
        update={"acceptance_status": "accepted", "measurements": (forged,)}
    )
    raw = {
        "context": state.context.model_dump(mode="json"),
        "current_revision": 1,
        "artifacts": [artifact.model_dump(mode="json")],
    }

    # When restored through the typed boundary, then canonical validation fails closed.
    with pytest.raises(ValidationError):
        _ = CompanyState.model_validate(raw)


@pytest.mark.parametrize(
    ("provenance", "status"),
    [
        ("founder_supplied", "based_on_founder_supplied_metrics"),
        ("demo_fixture", "requires_metrics"),
    ],
)
def test_preserves_untrusted_metric_labels(
    provenance: Literal["founder_supplied", "demo_fixture"], status: str
) -> None:
    # Given a measurement explicitly labelled as untrusted input.
    state = create_company_state("session-1", created_at=NOW)
    measurement = MeasuredResult(
        metric_id=uuid4(),
        name="qualified_leads",
        value=4,
        unit="leads",
        window_start=datetime(2026, 10, 1, tzinfo=UTC),
        window_end=datetime(2026, 10, 8, tzinfo=UTC),
        source_label="Founder spreadsheet",
        collected_at=datetime(2026, 10, 8, 1, tzinfo=UTC),
        provenance=provenance,
    )
    artifact = _artifact(state).model_copy(
        update={"measurements": (measurement,), "status": status}
    )

    # When accepted structurally, then canonical state retains the untrusted label.
    updated = accept_artifact(state, artifact, authenticated_session_id="session-1")

    assert updated.artifacts[0].measurements[0].provenance == provenance
    assert updated.artifacts[0].status == status


def test_rejects_connected_analysis_basis_without_measurements() -> None:
    # Given a pending analysis that claims connected evidence using an arbitrary metric ID.
    state = create_company_state("session-1", created_at=NOW)
    artifact = _artifact(state).model_copy(
        update={
            "artifact_type": ArtifactType.ANALYSIS,
            "producer": Role.ANALYST,
            "payload": AnalysisArtifact(
                metric_ids=(uuid4(),),
                findings=("Conversion improved",),
                recommendations=("Continue",),
                basis="connected_measurements",
            ),
        }
    )

    # When canonical acceptance runs, then the unsupported promotion fails closed.
    with pytest.raises(InvalidArtifactTransitionError):
        _ = accept_artifact(state, artifact, authenticated_session_id="session-1")


def test_rejects_connected_analysis_basis_when_loading_canonical_json() -> None:
    # Given accepted canonical JSON that claims connected evidence without retained metrics.
    state = create_company_state("session-1", created_at=NOW)
    artifact = _artifact(state).model_copy(
        update={
            "acceptance_status": "accepted",
            "artifact_type": ArtifactType.ANALYSIS,
            "producer": Role.ANALYST,
            "payload": AnalysisArtifact(
                metric_ids=(uuid4(),),
                findings=("Conversion improved",),
                recommendations=("Continue",),
                basis="connected_measurements",
            ),
        }
    )
    raw = {
        "context": state.context.model_dump(mode="json"),
        "current_revision": 1,
        "artifacts": [artifact.model_dump(mode="json")],
    }

    # When restored through CompanyState, then the unsupported promotion fails closed.
    with pytest.raises(ValidationError):
        _ = CompanyState.model_validate(raw)


def test_accepts_conditional_analysis_linked_to_exact_founder_metrics() -> None:
    # Given conditional analysis linked to one retained founder-supplied metric.
    state = create_company_state("session-1", created_at=NOW)
    metric = MeasuredResult(
        metric_id=uuid4(),
        name="qualified_leads",
        value=4,
        unit="leads",
        window_start=datetime(2026, 10, 1, tzinfo=UTC),
        window_end=datetime(2026, 10, 8, tzinfo=UTC),
        source_label="Founder spreadsheet",
        collected_at=datetime(2026, 10, 8, 1, tzinfo=UTC),
        provenance="founder_supplied",
    )
    raw = _artifact(state).model_dump(mode="json")
    raw.update(
        {
            "artifact_type": ArtifactType.ANALYSIS,
            "producer": Role.ANALYST,
            "status": "based_on_founder_supplied_metrics",
            "measurements": [metric.model_dump(mode="json")],
            "payload": AnalysisArtifact(
                metric_ids=(metric.metric_id,),
                findings=("Four leads were supplied",),
                recommendations=("Verify through a connector before claiming impact",),
                basis="based_on_founder_supplied_metrics",
            ).model_dump(mode="json"),
        }
    )
    artifact = ArtifactEnvelope.model_validate(raw)

    # When accepted and restored, then the exact metric and conditional basis remain intact.
    updated = accept_artifact(state, artifact, authenticated_session_id="session-1")
    restored = CompanyState.model_validate_json(updated.model_dump_json())

    assert restored.artifacts[0].measurements == (metric,)
    assert restored.artifacts[0].payload == artifact.payload


@pytest.mark.parametrize("case", ["unretained_id", "demo_provenance", "complete_status"])
def test_rejects_conditional_analysis_with_inconsistent_metric_evidence(case: str) -> None:
    # Given conditional analysis whose metric linkage, provenance, or status is inconsistent.
    state = create_company_state("session-1", created_at=NOW)
    metric = MeasuredResult(
        metric_id=uuid4(),
        name="qualified_leads",
        value=4,
        unit="leads",
        window_start=datetime(2026, 10, 1, tzinfo=UTC),
        window_end=datetime(2026, 10, 8, tzinfo=UTC),
        source_label="Founder spreadsheet",
        collected_at=datetime(2026, 10, 8, 1, tzinfo=UTC),
        provenance="founder_supplied",
    )
    raw = _artifact(state).model_dump(mode="json")
    raw.update(
        {
            "artifact_type": ArtifactType.ANALYSIS,
            "producer": Role.ANALYST,
            "status": "based_on_founder_supplied_metrics",
            "measurements": [metric.model_dump(mode="json")],
            "payload": AnalysisArtifact(
                metric_ids=(metric.metric_id,),
                findings=("Four leads were supplied",),
                recommendations=("Verify with a connector",),
                basis="based_on_founder_supplied_metrics",
            ).model_dump(mode="json"),
        }
    )
    if case == "unretained_id":
        raw["payload"]["metric_ids"] = [str(uuid4())]
    elif case == "demo_provenance":
        raw["measurements"][0]["provenance"] = "demo_fixture"
    else:
        raw["status"] = "complete"

    # When parsed at the envelope boundary, then the inconsistent evidence is rejected.
    with pytest.raises(ValidationError):
        _ = ArtifactEnvelope.model_validate(raw)
