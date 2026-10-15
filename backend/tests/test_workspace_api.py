from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import TYPE_CHECKING, Literal, Protocol, cast
from uuid import uuid4

import jwt
import pytest
from agno.run import RunContext
from agno.run.base import RunStatus
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, Table, select
from sqlalchemy.schema import DropSchema

from samurai import parent as parent_module
from samurai.app import create_app
from samurai.company_store import CompanyStore
from samurai.config import Settings
from samurai.contracts import (
    ArtifactEnvelope,
    ArtifactType,
    CompanyBrief,
    CompanyState,
    IntakeArtifact,
    Role,
    VerificationArtifact,
    VerificationFinding,
    accept_artifact,
    create_company_state,
)
from samurai.execution_state import SamuraiPostgresDb
from samurai.schema import FounderPlatformMigrator
from samurai.schema_contracts import canonical_state_hash
from samurai.workspace_api import CompanyView, MemberView, WorkspaceView
from samurai.workspace_directory import WorkspaceDirectory
from tests import test_parent as parent_test_module
from tests.company_store_support import revision_one, store_session

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from agno.models.base import Model

pytest_plugins = ("tests.company_store_support",)


class _CountingModelType(Protocol):
    total_invocations: int

    def __call__(self, *tool_names: str) -> Model: ...


class _HttpResponse(Protocol):
    status_code: int

    def json(self) -> object: ...


@pytest.fixture
def workspace_client(
    postgres_url: str,
) -> Iterator[tuple[TestClient, rsa.RSAPrivateKey, SamuraiPostgresDb]]:
    schema = f"founder_t06_{uuid4().hex}"
    database = SamuraiPostgresDb(id=schema, db_url=postgres_url, db_schema=schema)
    database.ensure_work_intents_table()
    _ = FounderPlatformMigrator(database.db_engine, schema=schema).apply()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    settings = Settings.model_validate({"jwt_verification_key": public_key.decode()})
    with TestClient(create_app(db=database, settings=settings)) as client:
        yield client, private_key, database
    with database.db_engine.begin() as connection:
        _ = connection.execute(DropSchema(schema, cascade=True, if_exists=True))
    database.close()


def _headers(private_key: rsa.RSAPrivateKey, subject: str) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": subject,
            "scopes": ["agents:samurai:read", "agents:samurai:run"],
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _company_headers(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def test_public_snapshot_includes_sanitized_framework_metadata() -> None:
    state = create_company_state(
        "snapshot-session",
        created_at=datetime(2026, 10, 15, tzinfo=UTC),
    )

    snapshot = WorkspaceDirectory._public_snapshot(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        state
    )

    assert tuple(item.id for item in snapshot.summary.frameworks) == (
        "founder_truth",
        "offer_diagnostic",
    )
    assert all(
        "resource" not in item.model_dump(mode="json") for item in snapshot.summary.frameworks
    )


def test_public_snapshot_does_not_promote_legacy_brief_action_to_founder_decision() -> None:
    initial = create_company_state(
        "legacy-snapshot",
        created_at=datetime(2026, 10, 15, tzinfo=UTC),
    )
    state = accept_artifact(
        initial,
        ArtifactEnvelope(
            artifact_id=uuid4(),
            company_id=initial.context.company_id,
            artifact_type=ArtifactType.INTAKE,
            revision=1,
            input_revision=0,
            producer=Role.INTAKE,
            status="complete",
            payload=IntakeArtifact(
                brief=CompanyBrief(
                    idea="Legacy clinic assistant",
                    target_customer="Clinics",
                    geography="India",
                    budget="INR 50000",
                    founder_skills="Python",
                    goal="Validate demand",
                    supplied_context=[],
                    assumptions=[],
                    open_questions=[],
                    next_actions=["Model-authored legacy action"],
                )
            ),
            assumptions=(),
            verification_findings=(
                VerificationFinding(code="legacy", message="Legacy artifact", severity="info"),
            ),
        ),
        authenticated_session_id="legacy-snapshot",
    )

    snapshot = WorkspaceDirectory._public_snapshot(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        state
    )

    assert snapshot.summary.next_decision is None


def test_members_share_workspace_without_sharing_actor_sessions(
    workspace_client: tuple[TestClient, rsa.RSAPrivateKey, SamuraiPostgresDb],
) -> None:
    # Given principal A creates a workspace and reserves its first company.
    client, private_key, database = workspace_client
    owner = _headers(private_key, "principal-a")
    editor = _headers(private_key, "principal-b")
    workspace_response = client.post(
        "/agentos/samurai/workspaces",
        headers=owner,
        json={"display_name": "Acme Test"},
    )
    assert workspace_response.status_code == 201
    workspace = WorkspaceView.model_validate(cast("object", workspace_response.json()))
    workspace_id = workspace.workspace_id
    first = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/companies",
        headers=_company_headers(owner),
        json={},
    )
    assert first.status_code == 201
    first_view = CompanyView.model_validate(cast("object", first.json()))
    added = client.put(
        f"/agentos/samurai/workspaces/{workspace_id}/members/principal-b",
        headers=owner,
        json={"role": "editor"},
    )
    assert added.status_code == 200
    assert added.json()["authorization_epoch"] == 1

    # When B lists the shared workspace and reserves a second company.
    listed = client.get("/agentos/samurai/workspaces", headers=editor)
    second = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/companies",
        headers=_company_headers(editor),
        json={},
    )
    companies_for_a = client.get(
        f"/agentos/samurai/workspaces/{workspace_id}/companies",
        headers=owner,
    )
    companies_for_b = client.get(
        f"/agentos/samurai/workspaces/{workspace_id}/companies",
        headers=editor,
    )
    opened_for_b = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/companies/{first.json()['company_id']}/open",
        headers=editor,
        json={},
    )
    reopened_for_b = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/companies/{first.json()['company_id']}/open",
        headers=editor,
        json={},
    )

    # Then both see the directory but only their own actor-native session binding.
    assert listed.status_code == 200
    listed_workspaces = [
        WorkspaceView.model_validate(item) for item in cast("list[object]", listed.json())
    ]
    assert listed_workspaces == [
        workspace.model_copy(update={"role": "editor", "authorization_epoch": 1})
    ]
    assert second.status_code == 201
    second_view = CompanyView.model_validate(cast("object", second.json()))
    assert first_view.company_id != second_view.company_id
    assert companies_for_a.status_code == companies_for_b.status_code == 200
    company_views_a = [
        CompanyView.model_validate(item) for item in cast("list[object]", companies_for_a.json())
    ]
    company_views_b = [
        CompanyView.model_validate(item) for item in cast("list[object]", companies_for_b.json())
    ]
    assert {item.company_id for item in company_views_a} == {
        first_view.company_id,
        second_view.company_id,
    }
    assert (
        next(
            item for item in company_views_a if item.company_id == second_view.company_id
        ).parent_session_id
        is None
    )
    assert (
        next(
            item for item in company_views_b if item.company_id == first_view.company_id
        ).parent_session_id
        is None
    )
    assert opened_for_b.status_code == reopened_for_b.status_code == 200
    opened_view = CompanyView.model_validate(cast("object", opened_for_b.json()))
    reopened_view = CompanyView.model_validate(cast("object", reopened_for_b.json()))
    assert opened_view == reopened_view
    assert opened_view.snapshot is not None
    assert opened_view.snapshot.summary.company_id == first_view.company_id
    assert first_view.parent_session_id is not None
    assert first_view.parent_session_id not in opened_for_b.text
    assert opened_view.parent_session_id != first_view.parent_session_id
    assert opened_view.child_session_id != first_view.child_session_id
    assert opened_view.parent_session_id is not None
    assert opened_view.child_session_id is not None
    child_state = cast(
        "Callable[[SamuraiPostgresDb, RunContext], tuple[str, CompanyState | None]]",
        getattr(parent_module, "_" + "child_state"),
    )
    child_id, canonical = child_state(
        database,
        RunContext(
            run_id="provider-free-handshake",
            session_id=opened_view.parent_session_id,
            user_id="principal-b",
            session_state={},
        ),
    )
    assert child_id == opened_view.child_session_id
    assert canonical is not None
    assert canonical.context.company_id == opened_view.company_id


def test_company_quota_is_http_conflict_and_request_validation_stays_unprocessable(
    workspace_client: tuple[TestClient, rsa.RSAPrivateKey, SamuraiPostgresDb],
) -> None:
    # Given an authenticated workspace with all ten company slots committed.
    client, private_key, _database = workspace_client
    owner = _headers(private_key, "quota-owner")
    workspace = WorkspaceView.model_validate(
        client.post(
            "/agentos/samurai/workspaces",
            headers=owner,
            json={"display_name": "HTTP quota"},
        ).json()
    )
    endpoint = f"/agentos/samurai/workspaces/{workspace.workspace_id}/companies"
    missing_key = client.post(endpoint, headers=owner, json={})
    malformed_key = client.post(
        endpoint, headers={**owner, "Idempotency-Key": "not-a-uuid"}, json={}
    )
    assert all(
        client.post(endpoint, headers=_company_headers(owner), json={}).status_code == 201
        for _ in range(10)
    )

    # When another valid reservation and an invalid request cross the API boundary.
    exceeded = client.post(endpoint, headers=_company_headers(owner), json={})
    invalid = client.post(endpoint, headers=_company_headers(owner), json={"unexpected": True})

    # Then the domain conflict survives transaction unwind while validation remains distinct.
    assert missing_key.status_code == malformed_key.status_code == 422
    assert exceeded.status_code == 409
    assert exceeded.json() == {"detail": "workspace quota exceeded"}
    assert invalid.status_code == 422


def test_company_reservation_idempotency_reuses_original_and_rejects_changed_workspace(
    workspace_client: tuple[TestClient, rsa.RSAPrivateKey, SamuraiPostgresDb],
) -> None:
    # Given two writable workspaces and one UUID idempotency key.
    client, private_key, database = workspace_client
    owner = _headers(private_key, "idempotent-owner")
    workspace_ids = tuple(
        WorkspaceView.model_validate(
            client.post(
                "/agentos/samurai/workspaces",
                headers=owner,
                json={"display_name": f"Idempotency {index}"},
            ).json()
        ).workspace_id
        for index in range(2)
    )
    key = str(uuid4())
    headers = {**owner, "Idempotency-Key": key}

    # When concurrent identical and changed-workspace retries reuse that key.
    barrier = Barrier(2)

    def reserve() -> _HttpResponse:
        _ = barrier.wait()
        return client.post(
            f"/agentos/samurai/workspaces/{workspace_ids[0]}/companies",
            headers=headers,
            json={},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (executor.submit(reserve), executor.submit(reserve))
        first, identical = (future.result() for future in futures)
    changed = client.post(
        f"/agentos/samurai/workspaces/{workspace_ids[1]}/companies", headers=headers, json={}
    )
    second_owner_headers = _headers(private_key, "idempotent-second-owner")
    assert (
        client.put(
            f"/agentos/samurai/workspaces/{workspace_ids[0]}/members/idempotent-second-owner",
            headers=owner,
            json={"role": "owner"},
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/agentos/samurai/workspaces/{workspace_ids[0]}/members/idempotent-owner",
            headers=second_owner_headers,
            json={"role": "viewer"},
        ).status_code
        == 200
    )
    demoted_replay = client.post(
        f"/agentos/samurai/workspaces/{workspace_ids[0]}/companies", headers=headers, json={}
    )

    # Then the original company and reservation are reused while changed scope conflicts.
    assert first.status_code == identical.status_code == 201
    assert first.json() == identical.json()
    assert changed.status_code == 409
    assert changed.json() == {"detail": "idempotency key was reused for another workspace"}
    assert demoted_replay.status_code == 403
    quotas = Table(
        "samurai_workspace_quotas",
        MetaData(schema=database.db_schema),
        autoload_with=database.db_engine,
    )
    with database.db_engine.connect() as connection:
        counts = tuple(
            connection.execute(
                select(quotas.c.company_count)
                .where(quotas.c.workspace_id.in_(workspace_ids))
                .order_by(quotas.c.workspace_id)
            ).scalars()
        )
    assert sorted(counts) == [0, 1]


def test_editor_native_run_uses_actor_binding_and_viewer_is_denied(
    workspace_client: tuple[TestClient, rsa.RSAPrivateKey, SamuraiPostgresDb],
) -> None:
    client, private_key, database = workspace_client
    owner = _headers(private_key, "native-owner")
    editor = _headers(private_key, "native-editor")
    viewer = _headers(private_key, "native-viewer")
    workspace = WorkspaceView.model_validate(
        client.post(
            "/agentos/samurai/workspaces", headers=owner, json={"display_name": "Native run"}
        ).json()
    )
    workspace_id = workspace.workspace_id
    company = CompanyView.model_validate(
        client.post(
            f"/agentos/samurai/workspaces/{workspace_id}/companies",
            headers=_company_headers(owner),
            json={},
        ).json()
    )
    for subject, role in (("native-editor", "editor"), ("native-viewer", "viewer")):
        added = client.put(
            f"/agentos/samurai/workspaces/{workspace_id}/members/{subject}",
            headers=owner,
            json={"role": role},
        )
        assert added.status_code == 200
    opened_editor = CompanyView.model_validate(
        client.post(
            f"/agentos/samurai/workspaces/{workspace_id}/companies/{company.company_id}/open",
            headers=editor,
            json={},
        ).json()
    )
    opened_viewer = CompanyView.model_validate(
        client.post(
            f"/agentos/samurai/workspaces/{workspace_id}/companies/{company.company_id}/open",
            headers=viewer,
            json={},
        ).json()
    )
    assert opened_editor.parent_session_id is not None
    assert opened_viewer.parent_session_id is not None
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    settings = Settings.model_validate({"jwt_verification_key": public_key.decode()})
    model_type = cast("_CountingModelType", getattr(parent_test_module, "_" + "ToolSequenceModel"))
    model_type.total_invocations = 0
    models: list[Model] = []

    def model_factory() -> Model:
        model = model_type("read_company_state")
        models.append(model)
        return model

    with TestClient(
        create_app(
            db=database,
            settings=settings,
            parent_model_factory=model_factory,
        )
    ) as run_client:
        editor_run = run_client.post(
            "/agentos/agents/samurai/runs",
            headers=editor,
            data={
                "message": "Read the bound company without a provider call.",
                "session_id": opened_editor.parent_session_id,
                "stream": "false",
            },
        )
        viewer_run = run_client.post(
            "/agentos/agents/samurai/runs",
            headers=viewer,
            data={
                "message": "Attempt a viewer run.",
                "session_id": opened_viewer.parent_session_id,
                "stream": "false",
            },
        )
        removed = client.delete(
            f"/agentos/samurai/workspaces/{workspace_id}/members/native-viewer",
            headers=owner,
        )
        assert removed.status_code == 204
        revoked_run = run_client.post(
            "/agentos/agents/samurai/runs",
            headers=viewer,
            data={
                "message": "Attempt a revoked-member run.",
                "session_id": opened_viewer.parent_session_id,
                "stream": "false",
            },
        )

    assert editor_run.status_code == 200
    editor_payload = cast("dict[str, object]", editor_run.json())
    viewer_payload = cast("dict[str, object]", viewer_run.json())
    revoked_payload = cast("dict[str, object]", revoked_run.json())
    assert editor_payload["status"] == RunStatus.completed.value
    assert editor_payload["session_id"] == opened_editor.parent_session_id
    editor_summary = parent_module.CompanyStateSummary.model_validate_json(
        cast("str", editor_payload["content"])
    )
    assert editor_summary.company_id == company.company_id
    assert editor_summary.revision == 0
    assert editor_summary.artifact_count == 0
    assert viewer_run.status_code == revoked_run.status_code == 200
    assert viewer_payload["status"] == revoked_payload["status"] == RunStatus.error.value
    assert len(models) == 1
    assert model_type.total_invocations == 1


def test_membership_permissions_last_owner_and_identity_fields_fail_closed(
    workspace_client: tuple[TestClient, rsa.RSAPrivateKey, SamuraiPostgresDb],
) -> None:
    # Given A owns a workspace and adds B as a viewer.
    client, private_key, database = workspace_client
    owner = _headers(private_key, "opaque-owner")
    viewer = _headers(private_key, "opaque-viewer")
    created = client.post(
        "/agentos/samurai/workspaces",
        headers={**owner, "x-user-id": "forged-owner"},
        json={"display_name": "Private workspace"},
    )
    assert created.status_code == 201
    workspace_id = WorkspaceView.model_validate(cast("object", created.json())).workspace_id
    added = client.put(
        f"/agentos/samurai/workspaces/{workspace_id}/members/opaque-viewer",
        headers=owner,
        json={"role": "viewer"},
    )
    assert added.status_code == 200

    # When viewer/identity-forgery/last-owner operations are attempted.
    viewer_member = client.put(
        f"/agentos/samurai/workspaces/{workspace_id}/members/another-user",
        headers=viewer,
        json={"role": "editor"},
    )
    viewer_company = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/companies",
        headers=_company_headers(viewer),
        json={},
    )
    foreign_response = client.post(
        "/agentos/samurai/workspaces",
        headers=viewer,
        json={"display_name": "Viewer owned"},
    )
    foreign_workspace = WorkspaceView.model_validate(
        cast("object", foreign_response.json())
    ).workspace_id
    owner_company = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/companies",
        headers=_company_headers(owner),
        json={},
    )
    owner_company_view = CompanyView.model_validate(cast("object", owner_company.json()))
    viewer_open = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/companies/{owner_company_view.company_id}/open",
        headers=viewer,
        json={},
    )
    mismatched_open = client.post(
        f"/agentos/samurai/workspaces/{foreign_workspace}/companies/{owner_company_view.company_id}/open",
        headers=viewer,
        json={},
    )
    forged_body = client.put(
        f"/agentos/samurai/workspaces/{workspace_id}/members/opaque-viewer",
        headers=owner,
        json={"role": "editor", "owner_id": "forged-owner"},
    )
    forged_company = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/companies",
        headers=_company_headers(owner),
        json={"user_id": "opaque-viewer"},
    )
    last_owner = client.delete(
        f"/agentos/samurai/workspaces/{workspace_id}/members/opaque-owner",
        headers=owner,
    )

    # Then each fails before membership or company mutation.
    assert viewer_member.status_code == viewer_company.status_code == 403
    assert viewer_open.status_code == 200
    assert owner_company_view.parent_session_id is not None
    assert owner_company_view.parent_session_id not in viewer_open.text
    assert mismatched_open.status_code == 404
    assert forged_body.status_code == forged_company.status_code == 422
    assert last_owner.status_code == 409
    metadata = MetaData(schema=database.db_schema)
    memberships = Table("samurai_workspace_memberships", metadata, autoload_with=database.db_engine)
    companies = Table("samurai_companies", metadata, autoload_with=database.db_engine)
    with database.db_engine.connect() as connection:
        rows = connection.execute(
            select(
                memberships.c.user_id,
                memberships.c.role,
                memberships.c.authorization_epoch,
                memberships.c.active,
            )
            .where(memberships.c.workspace_id == workspace_id)
            .order_by(memberships.c.user_id)
        ).all()
        company_count = len(connection.execute(select(companies.c.company_id)).all())
    assert rows == [
        ("opaque-owner", "owner", 1, True),
        ("opaque-viewer", "viewer", 1, True),
    ]
    assert company_count == 1


def test_membership_updates_advance_authorization_epoch_and_protect_final_owner(
    workspace_client: tuple[TestClient, rsa.RSAPrivateKey, SamuraiPostgresDb],
) -> None:
    # Given A owns a workspace with B as another owner.
    client, private_key, _database = workspace_client
    owner = _headers(private_key, "owner-a")
    created = client.post(
        "/agentos/samurai/workspaces", headers=owner, json={"display_name": "Shared"}
    )
    workspace_id = WorkspaceView.model_validate(cast("object", created.json())).workspace_id
    first = client.put(
        f"/agentos/samurai/workspaces/{workspace_id}/members/owner-b",
        headers=owner,
        json={"role": "owner"},
    )

    # When B is changed to editor, removed, and reactivated as viewer.
    editor = client.put(
        f"/agentos/samurai/workspaces/{workspace_id}/members/owner-b",
        headers=owner,
        json={"role": "editor"},
    )
    removed = client.delete(
        f"/agentos/samurai/workspaces/{workspace_id}/members/owner-b", headers=owner
    )
    reactivated = client.put(
        f"/agentos/samurai/workspaces/{workspace_id}/members/owner-b",
        headers=owner,
        json={"role": "viewer"},
    )
    final_owner = client.put(
        f"/agentos/samurai/workspaces/{workspace_id}/members/owner-a",
        headers=owner,
        json={"role": "editor"},
    )

    # Then every authorization change advances the epoch and sole-owner demotion is blocked.
    first_view = MemberView.model_validate(cast("object", first.json()))
    editor_view = MemberView.model_validate(cast("object", editor.json()))
    reactivated_view = MemberView.model_validate(cast("object", reactivated.json()))
    assert first_view.authorization_epoch == 1
    assert editor_view.authorization_epoch == 2
    assert removed.status_code == 204
    assert reactivated_view.authorization_epoch == 4
    assert final_owner.status_code == 409


def test_concurrent_company_opens_reuse_one_actor_binding(
    workspace_client: tuple[TestClient, rsa.RSAPrivateKey, SamuraiPostgresDb],
) -> None:
    client, private_key, database = workspace_client
    owner = _headers(private_key, "open-owner")
    workspace_response = client.post(
        "/agentos/samurai/workspaces", headers=owner, json={"display_name": "Concurrent"}
    )
    workspace_id = WorkspaceView.model_validate(
        cast("object", workspace_response.json())
    ).workspace_id
    company_response = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/companies",
        headers=_company_headers(owner),
        json={},
    )
    company_id = CompanyView.model_validate(cast("object", company_response.json())).company_id
    added = client.put(
        f"/agentos/samurai/workspaces/{workspace_id}/members/concurrent-viewer",
        headers=owner,
        json={"role": "viewer"},
    )
    assert added.status_code == 200
    directory = WorkspaceDirectory(database)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(directory.open_company, "concurrent-viewer", workspace_id, company_id)
            for _index in range(2)
        ]
        opened = [future.result() for future in futures]

    assert opened[0].parent_session_id == opened[1].parent_session_id
    assert opened[0].child_session_id == opened[1].child_session_id
    metadata = MetaData(schema=database.db_schema)
    bindings = Table("samurai_company_actor_bindings", metadata, autoload_with=database.db_engine)
    with database.db_engine.connect() as connection:
        rows = connection.execute(
            select(bindings.c.parent_session_id).where(
                bindings.c.company_id == company_id,
                bindings.c.user_id == "concurrent-viewer",
            )
        ).all()
    assert rows == [(opened[0].parent_session_id,)]


def test_concurrent_owner_removals_retain_one_active_owner(
    workspace_client: tuple[TestClient, rsa.RSAPrivateKey, SamuraiPostgresDb],
) -> None:
    client, private_key, database = workspace_client
    owner = _headers(private_key, "owner-one")
    workspace_response = client.post(
        "/agentos/samurai/workspaces", headers=owner, json={"display_name": "Owners"}
    )
    workspace_id = WorkspaceView.model_validate(
        cast("object", workspace_response.json())
    ).workspace_id
    added = client.put(
        f"/agentos/samurai/workspaces/{workspace_id}/members/owner-two",
        headers=owner,
        json={"role": "owner"},
    )
    assert added.status_code == 200
    directory = WorkspaceDirectory(database)

    def remove(actor_id: str, target_id: str) -> int:
        try:
            directory.delete_member(actor_id, workspace_id, target_id)
        except HTTPException as error:
            return error.status_code
        return 204

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(remove, "owner-one", "owner-two")
        second = executor.submit(remove, "owner-two", "owner-one")
        statuses = {first.result(), second.result()}

    assert 204 in statuses
    assert statuses <= {204, 403, 409}
    metadata = MetaData(schema=database.db_schema)
    memberships = Table("samurai_workspace_memberships", metadata, autoload_with=database.db_engine)
    with database.db_engine.connect() as connection:
        active_owners = connection.execute(
            select(memberships.c.user_id).where(
                memberships.c.workspace_id == workspace_id,
                memberships.c.role == "owner",
                memberships.c.active,
            )
        ).all()
    assert len(active_owners) == 1


@pytest.mark.parametrize("outcome", ["verified", "needs_rework"])
def test_open_projects_populated_company_as_truthful_read_summary(
    workspace_client: tuple[TestClient, rsa.RSAPrivateKey, SamuraiPostgresDb],
    outcome: str,
) -> None:
    client, private_key, database = workspace_client
    owner = _headers(private_key, "summary-owner")
    viewer = _headers(private_key, "summary-viewer")
    workspace_response = client.post(
        "/agentos/samurai/workspaces", headers=owner, json={"display_name": "Summary"}
    )
    workspace_id = WorkspaceView.model_validate(
        cast("object", workspace_response.json())
    ).workspace_id
    company_response = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/companies",
        headers=_company_headers(owner),
        json={},
    )
    company = CompanyView.model_validate(cast("object", company_response.json()))
    assert company.parent_session_id is not None
    store = CompanyStore(database.db_engine, schema=database.db_schema)
    access = store.read_for_actor("summary-owner", company.parent_session_id)
    assert access is not None
    store_session(database, "summary-owner", access)
    first_revision = revision_one(access)
    verification = ArtifactEnvelope(
        artifact_id=uuid4(),
        company_id=company.company_id,
        artifact_type=ArtifactType.VERIFICATION,
        revision=2,
        input_revision=1,
        producer=Role.VERIFIER,
        status="complete" if outcome == "verified" else "needs_rework",
        payload=VerificationArtifact(
            checked_artifact_ids=(first_revision.artifacts[0].artifact_id,),
            outcome=cast("Literal['verified', 'needs_rework']", outcome),
        ),
        assumptions=(),
        verification_findings=(
            VerificationFinding(
                code=f"{outcome}-state", message=f"Persisted {outcome}", severity="warning"
            ),
        ),
    )
    populated = accept_artifact(
        first_revision,
        verification,
        authenticated_session_id=first_revision.context.authenticated_session_id,
    )
    metadata = MetaData(schema=database.db_schema)
    companies = Table("samurai_companies", metadata, autoload_with=database.db_engine)
    with database.db_engine.begin() as connection:
        _ = connection.execute(
            companies.update()
            .where(companies.c.company_id == company.company_id)
            .values(
                canonical_state=populated.model_dump(mode="json"),
                state_sha256=canonical_state_hash(populated),
                current_revision=populated.current_revision,
            )
        )
    added = client.put(
        f"/agentos/samurai/workspaces/{workspace_id}/members/summary-viewer",
        headers=owner,
        json={"role": "viewer"},
    )
    assert added.status_code == 200

    opened = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/companies/{company.company_id}/open",
        headers=viewer,
        json={},
    )

    assert opened.status_code == 200
    view = CompanyView.model_validate(cast("object", opened.json()))
    assert view.snapshot is not None
    assert view.snapshot.summary.revision == 2
    assert view.snapshot.summary.artifact_count == 2
    assert view.snapshot.summary.status == "active"
    assert tuple(item.id for item in view.snapshot.summary.frameworks) == (
        "founder_truth",
        "offer_diagnostic",
    )
    assert all(
        "resource" not in item.model_dump(mode="json") for item in view.snapshot.summary.frameworks
    )
    assert view.snapshot.summary.verification_findings[-1].code == f"{outcome}-state"
    assert len(view.snapshot.artifacts) == 2
    verification_snapshot = view.snapshot.artifacts[-1]
    assert isinstance(verification_snapshot.payload, VerificationArtifact)
    assert verification_snapshot.payload.outcome == outcome
    assert company.parent_session_id not in opened.text
