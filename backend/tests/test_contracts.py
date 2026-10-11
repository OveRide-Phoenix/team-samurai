from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

import pytest
from pydantic import HttpUrl, ValidationError

from samurai.contracts import (
    ArtifactEnvelope,
    ArtifactType,
    Assumption,
    CompanyBrief,
    CompanyMismatchError,
    CompanyState,
    FounderMetricInput,
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
