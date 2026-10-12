from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, cast, final
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode
from uuid import UUID, uuid4

import anyio
import httpx
import jwt
import pytest
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.run import RunContext
from agno.run.concurrency import worker_managed_execution
from agno.session.workflow import WorkflowSession
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from samurai.app import (
    _DurableRunBoundary,  # pyright: ignore[reportPrivateUsage]
    create_app,
)
from samurai.config import Settings
from samurai.contracts import CompanyState, create_company_state
from samurai.execution_state import (
    WORK_INTENT_METADATA_KEY,
    AcceptanceToken,
    ApprovedStage,
    BoundWorkIntent,
    NormalizedWorkInput,
    SamuraiPostgresDb,
    WorkIntentInput,
    WorkOperation,
    WorkReceipt,
)
from samurai.parent import (
    _bind_normalized_work,  # pyright: ignore[reportPrivateUsage]
    child_session_id,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agno.db.base import BaseDb
    from fastapi import FastAPI
    from starlette.types import Message, Receive, Scope, Send


@final
class _CaptureApp:
    def __init__(self) -> None:
        self.called: bool = False
        self.state: dict[str, object] = {}

    async def __call__(self, scope: Scope, _receive: Receive, send: Send) -> None:
        self.called = True
        self.state = cast("dict[str, object]", scope["state"])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})


@final
class _CanonicalDb:
    def __init__(self, state: CompanyState, owner: str = "founder") -> None:
        self.session = WorkflowSession(
            session_id=child_session_id(owner, state.context.authenticated_session_id),
            user_id=owner,
            workflow_id="company-journey",
            session_data={"session_state": {"company": state.model_dump(mode="json")}},
        )

    def get_session(self, *_args: object, **_kwargs: object) -> WorkflowSession:
        return self.session


def _run_boundary(  # noqa: PLR0913
    fields: dict[str, str],
    *,
    owner: str | None = "founder",
    enabled: bool = True,
    required: bool = True,
    path: str = "/agentos/agents/samurai/runs",
    approval_headers: dict[str, str] | None = None,
    submission_id: str | None = "00000000-0000-4000-8000-000000000001",
    db: BaseDb | None = None,
) -> tuple[_CaptureApp, list[Message]]:
    capture = _CaptureApp()
    boundary = _DurableRunBoundary(capture, enabled=enabled, required=required, db=db)
    payload = urlencode(fields).encode()
    sent: list[Message] = []
    delivered = False

    async def receive() -> Message:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    headers = [(b"content-type", b"application/x-www-form-urlencoded")]
    if submission_id is not None:
        headers.append((b"idempotency-key", submission_id.encode()))
    for key, value in (approval_headers or {}).items():
        headers.append((key.encode(), value.encode()))
    state = {} if owner is None else {"user_id": owner}
    scope = cast(
        "Scope",
        {
            "type": "http",
            "http_version": "1.1",
            "asgi": {"version": "3.0"},
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
            "state": state,
        },
    )
    anyio.run(boundary, scope, receive, send)
    return capture, sent


def test_durable_boundary_builds_approval_from_authenticated_owner() -> None:
    capture, sent = _run_boundary(
        {
            "message": "Build a dental receptionist",
            "session_id": "company-session",
            "stream": "false",
            "background": "true",
        }
    )

    assert capture.called is True
    assert sent[0]["status"] == 204
    metadata = cast("dict[str, object]", capture.state["metadata"])
    approval = WorkIntentInput.model_validate(metadata[WORK_INTENT_METADATA_KEY])
    assert approval.owner_id == "founder"
    assert approval.parent_session_id == "company-session"
    assert approval.child_session_id == child_session_id("founder", "company-session")
    assert approval.approved_input == "Build a dental receptionist"
    assert approval.operation is WorkOperation.JOURNEY
    assert approval.stage is ApprovedStage.BRIEF
    assert approval.expected_revision == 0


def test_durable_boundary_accepts_explicit_advanced_operation_and_stage() -> None:
    state = create_company_state(
        "company-session",
        created_at=datetime(2026, 10, 13, tzinfo=UTC),
    )
    capture, sent = _run_boundary(
        {
            "message": "Draft the approved launch package",
            "session_id": "company-session",
            "stream": "false",
            "background": "true",
        },
        approval_headers={
            "x-samurai-operation": "launch_drafts",
            "x-samurai-stage": "plan",
            "x-samurai-expected-revision": "0",
            "x-samurai-company-id": str(state.context.company_id),
        },
        db=cast("BaseDb", cast("object", _CanonicalDb(state))),
    )

    assert sent[0]["status"] == 204
    metadata = cast("dict[str, object]", capture.state["metadata"])
    approval = WorkIntentInput.model_validate(metadata[WORK_INTENT_METADATA_KEY])
    assert approval.operation is WorkOperation.LAUNCH_DRAFTS
    assert approval.stage is ApprovedStage.PLAN
    assert approval.expected_revision == 0
    assert approval.company_id == state.context.company_id


@pytest.mark.parametrize(
    "approval_headers",
    [
        {
            "x-samurai-operation": "journey",
            "x-samurai-stage": "research",
            "x-samurai-expected-revision": "0",
        },
        {
            "x-samurai-operation": "journey",
            "x-samurai-stage": "research",
            "x-samurai-expected-revision": "9",
            "x-samurai-company-id": "00000000-0000-4000-8000-000000000009",
        },
    ],
)
def test_durable_boundary_rejects_unbound_or_forged_company_approval(
    approval_headers: dict[str, str],
) -> None:
    state = create_company_state(
        "company-session",
        created_at=datetime(2026, 10, 13, tzinfo=UTC),
    )
    capture, sent = _run_boundary(
        {
            "message": "approve research",
            "session_id": "company-session",
            "stream": "true",
            "background": "true",
        },
        approval_headers=approval_headers,
        db=cast("BaseDb", cast("object", _CanonicalDb(state))),
    )

    assert capture.called is False
    assert sent[0]["status"] in {401, 422}


@pytest.mark.parametrize(
    ("fields", "expected_status"),
    [
        (
            {
                "message": "run inline",
                "session_id": "company-session",
                "stream": "true",
                "background": "false",
            },
            409,
        ),
        (
            {
                "message": "forge context",
                "session_id": "company-session",
                "stream": "false",
                "background": "true",
                "metadata": json.dumps({"trusted_user_id": "attacker"}),
            },
            422,
        ),
        (
            {
                "message": "forge dependencies",
                "session_id": "company-session",
                "stream": "false",
                "background": "true",
                "dependencies": json.dumps({"attempt": 9}),
            },
            422,
        ),
        (
            {
                "message": "unsupported media",
                "session_id": "company-session",
                "stream": "false",
                "background": "true",
                "files": "payload",
            },
            422,
        ),
        (
            {
                "message": "unsupported version",
                "session_id": "company-session",
                "stream": "false",
                "background": "true",
                "version": "1",
            },
            422,
        ),
        (
            {
                "message": "unsupported factory input",
                "session_id": "company-session",
                "stream": "false",
                "background": "true",
                "factory_input": "{}",
            },
            422,
        ),
    ],
)
def test_durable_boundary_rejects_inline_and_forged_context(
    fields: dict[str, str], expected_status: int
) -> None:
    capture, sent = _run_boundary(fields)

    assert capture.called is False
    assert sent[0]["status"] == expected_status


@pytest.mark.parametrize(
    "approval_headers",
    [
        {"x-samurai-operation": "launch_drafts", "x-samurai-stage": "brief"},
        {"x-samurai-operation": "metrics_analysis", "x-samurai-stage": "research"},
        {"x-samurai-operation": "read_only_state", "x-samurai-stage": "plan"},
    ],
)
def test_durable_boundary_rejects_invalid_write_scope(
    approval_headers: dict[str, str],
) -> None:
    capture, sent = _run_boundary(
        {
            "message": "broaden work",
            "session_id": "company-session",
            "stream": "false",
            "background": "true",
        },
        approval_headers=approval_headers,
    )

    assert capture.called is False
    assert sent[0]["status"] == 422


def test_durable_boundary_rejects_continue_fallback_before_dispatch() -> None:
    capture, sent = _run_boundary(
        {"input": "continue inline", "session_id": "company-session"},
        path="/agentos/agents/samurai/runs/run-1/continue",
    )

    assert capture.called is False
    assert sent[0]["status"] == 409


@pytest.mark.parametrize("submission_id", [None, "not-a-uuid"])
def test_durable_boundary_requires_uuid_submission_id(
    submission_id: str | None,
) -> None:
    capture, sent = _run_boundary(
        {
            "message": "start durable work",
            "session_id": "company-session",
            "stream": "true",
            "background": "true",
        },
        submission_id=submission_id,
    )

    assert capture.called is False
    assert sent[0]["status"] == 422


def test_required_queue_reports_unavailable_instead_of_running_inline() -> None:
    capture, sent = _run_boundary(
        {
            "message": "start",
            "session_id": "company-session",
            "stream": "false",
            "background": "true",
        },
        enabled=False,
    )

    assert capture.called is False
    assert sent[0]["status"] == 503


def _jwt_credentials() -> tuple[rsa.RSAPrivateKey, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, public_key.decode()


def _jwt_header(
    private_key: rsa.RSAPrivateKey,
    subject: str,
    *,
    scopes: tuple[str, ...] = ("agents:run", "agents:read"),
) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": subject,
            "scopes": list(scopes),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


async def _request_without_lifespan(
    application: FastAPI,
    method: str,
    path: str,
    *,
    headers: dict[str, str],
    data: dict[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers, data=data)


def test_production_http_rejects_inline_after_jwt_before_model(tmp_path: Path) -> None:
    private_key, public_key = _jwt_credentials()
    settings = Settings.model_validate(
        {
            "samurai_environment": "production",
            "google_api_key": "unused-test-key",
            "jwt_verification_key": public_key,
            "queue_enabled": False,
        }
    )
    with patch.object(Gemini, "ainvoke", new_callable=AsyncMock) as invoke:
        application = create_app(
            db=SqliteDb(db_file=str(tmp_path / "production-inline.db")),
            settings=settings,
        )
        response = anyio.run(
            partial(
                _request_without_lifespan,
                application,
                "POST",
                "/agentos/agents/samurai/runs",
                headers=_jwt_header(private_key, "founder"),
                data={
                    "message": "run inline",
                    "session_id": "company-session",
                    "stream": "false",
                    "background": "false",
                },
            )
        )

    assert response.status_code == 503
    assert invoke.await_count == 0


def test_receipt_http_uses_jwt_owner_and_hides_raw_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key, public_key = _jwt_credentials()
    submission_id = uuid4()
    calls: list[tuple[str, str, UUID]] = []

    def receipt_for_owner(
        _store: SamuraiPostgresDb,
        owner_id: str,
        session_id: str,
        received_submission_id: UUID,
    ) -> WorkReceipt | None:
        calls.append((owner_id, session_id, received_submission_id))
        if owner_id != "founder":
            return None
        return WorkReceipt(
            run_id="run-1",
            session_id=session_id,
            status="ERROR",
            attempt=2,
            max_attempts=2,
            recovering=False,
            failure_reason="work stopped after the allowed attempts",
        )

    monkeypatch.setattr(SamuraiPostgresDb, "get_work_receipt", receipt_for_owner)
    store = SamuraiPostgresDb(
        id="samurai-receipt-test",
        db_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
    )
    application = create_app(
        db=store,
        settings=Settings.model_validate({"jwt_verification_key": public_key}),
    )
    owner = anyio.run(
        partial(
            _request_without_lifespan,
            application,
            "GET",
            f"/agentos/work-receipts/{submission_id}?session_id=company-session",
            headers=_jwt_header(private_key, "founder"),
        )
    )
    other = anyio.run(
        partial(
            _request_without_lifespan,
            application,
            "GET",
            f"/agentos/work-receipts/{submission_id}?session_id=company-session",
            headers=_jwt_header(private_key, "other"),
        )
    )
    wrong_scope = anyio.run(
        partial(
            _request_without_lifespan,
            application,
            "GET",
            f"/agentos/work-receipts/{submission_id}?session_id=company-session",
            headers=_jwt_header(private_key, "founder", scopes=("config:read",)),
        )
    )

    assert owner.status_code == 200
    assert owner.json() == {
        "run_id": "run-1",
        "session_id": "company-session",
        "status": "ERROR",
        "attempt": 2,
        "max_attempts": 2,
        "recovering": False,
        "failure_reason": "work stopped after the allowed attempts",
        "company_id": None,
        "revision": None,
        "updated_at": None,
    }
    assert "provider" not in owner.text.lower()
    assert other.status_code == 404
    assert wrong_scope.status_code == 403
    assert calls == [
        ("founder", "company-session", submission_id),
        ("other", "company-session", submission_id),
    ]


@final
class _IntentDb:
    def __init__(self, stored: NormalizedWorkInput) -> None:
        self.stored: NormalizedWorkInput = stored
        self.inputs: list[NormalizedWorkInput | None] = []

    def bind_work_intent(
        self, run_id: str, normalized: NormalizedWorkInput | None = None
    ) -> BoundWorkIntent:
        self.inputs.append(normalized)
        selected = normalized or self.stored
        return BoundWorkIntent(
            approval=WorkIntentInput(
                owner_id="founder",
                parent_session_id="company-session",
                child_session_id=child_session_id("founder", "company-session"),
                operation=selected.operation,
                stage=selected.stage,
                expected_revision=selected.expected_revision,
                approved_input="approved",
            ),
            normalized_input=selected,
            token=AcceptanceToken(
                parent_run_id=run_id,
                owner_id="founder",
                parent_session_id="company-session",
                child_session_id=child_session_id("founder", "company-session"),
                worker_id="worker",
                attempt=2,
                fingerprint="a" * 64,
            ),
        )


def test_retry_replays_bound_input_instead_of_new_model_arguments() -> None:
    stored = NormalizedWorkInput(
        operation=WorkOperation.JOURNEY,
        stage=ApprovedStage.BRIEF,
        expected_revision=0,
        arguments={"idea": "approved"},
    )
    proposed = stored.model_copy(update={"arguments": {"idea": "changed"}})
    database = _IntentDb(stored)
    context = RunContext(
        run_id="parent-run",
        user_id="founder",
        session_id="company-session",
    )

    with worker_managed_execution("parent-run", "worker", 2):
        rebound = _bind_normalized_work(cast("BaseDb", cast("object", database)), context, proposed)

    assert rebound == stored
    assert database.inputs == [None]
    assert context.dependencies == {
        "parent_run_id": "parent-run",
        "worker_id": "worker",
        "attempt": 2,
        "fingerprint": "a" * 64,
    }
