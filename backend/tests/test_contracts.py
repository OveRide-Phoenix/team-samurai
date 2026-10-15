"""Contract boundary scenarios kept together for lineage coverage. # noqa: SIZE_OK."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

import pytest
from pydantic import HttpUrl, ValidationError

from samurai.contracts import (
    AnalysisArtifact,
    ArtifactEnvelope,
    ArtifactType,
    Assumption,
    CompanyBrief,
    CompanyMismatchError,
    CompanyState,
    FounderKnownFact,
    FounderMetricInput,
    FounderTruth,
    FrameworkReference,
    IntakeArtifact,
    InvalidArtifactTransitionError,
    MeasuredResult,
    Role,
    SessionMismatchError,
    SourcedClaim,
    SourceReference,
    StaleRevisionError,
    VerificationFinding,
    accept_artifact,
    create_company_state,
)

NOW = datetime(2026, 10, 11, tzinfo=UTC)


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
