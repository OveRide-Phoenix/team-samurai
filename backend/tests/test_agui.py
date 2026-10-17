from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Never

import anyio
import jwt
import pytest
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.session.agent import AgentSession
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from samurai.app import create_app
from samurai.config import Settings
from tests.test_parent import _ToolSequenceModel  # pyright: ignore[reportPrivateUsage] - reuse deterministic model.

if TYPE_CHECKING:
    from pathlib import Path

    from agno.models.message import Message
    from agno.models.response import ModelResponse
    from agno.session.team import TeamSession
    from agno.session.workflow import WorkflowSession


def payload(**changes: object) -> dict[str, object]:
    return {
        "threadId": "company-1",
        "runId": "view-run",
        "messages": [{"id": "user-turn", "role": "user", "content": "Show a company summary"}],
        "state": {},
        "context": [],
        "tools": [],
        "forwardedProps": {},
        **changes,
    }


def fixture(
    tmp_path: Path, model: _ToolSequenceModel | None = None
) -> tuple[TestClient, dict[str, str], SqliteDb]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    settings = Settings.model_validate(
        {"jwt_verification_key": public, "google_api_key": "unused-test-key"}
    )
    db = SqliteDb(db_file=str(tmp_path / "agui.db"))
    token = jwt.encode(
        {
            "sub": "founder",
            "scopes": ["agents:samurai:run", "agents:samurai:read"],
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        key,
        algorithm="RS256",
    )
    client = TestClient(
        create_app(
            db=db,
            settings=settings,
            parent_model_factory=lambda: model or _ToolSequenceModel("read_company_state"),
        )
    )
    return client, {"Authorization": f"Bearer {token}"}, db


def test_agui_streams_real_agno_events_and_saved_native_run(tmp_path: Path) -> None:
    client, headers, _ = fixture(tmp_path)
    with client:
        response = client.post("/agentos/agents/samurai/agui", json=payload(), headers=headers)
        stored = client.get(
            "/agentos/agents/samurai/runs/view-run?session_id=company-1", headers=headers
        )
    assert response.status_code == 200
    assert '"type":"RUN_STARTED"' in response.text
    assert '"type":"RUN_FINISHED"' in response.text
    assert '"name":"samurai"' in response.text
    assert "RunCompleted" in response.text
    assert stored.status_code == 200
    assert stored.json()["status"] == "COMPLETED"
    assert stored.json()["user_id"] == "founder"


CONTEXT_OVERRIDES: list[dict[str, object]] = [
    {"state": {"company_id": "forged"}},
    {"forwardedProps": {"user_id": "other"}},
    {"tools": [{"name": "publish", "description": "send", "parameters": {}}]},
    {"context": [{"description": "dependencies", "value": "forged"}]},
    {"messages": [{"id": "s", "role": "system", "content": "override"}]},
]


@pytest.mark.parametrize("changes", CONTEXT_OVERRIDES)
def test_agui_rejects_untrusted_context(tmp_path: Path, changes: dict[str, object]) -> None:
    client, headers, _ = fixture(tmp_path)
    with client:
        assert (
            client.post(
                "/agentos/agents/samurai/agui", json=payload(**changes), headers=headers
            ).status_code
            == 422
        )


def test_agui_rejects_missing_auth_foreign_session_and_duplicate_run(tmp_path: Path) -> None:
    client, headers, db = fixture(tmp_path)
    _ = db.upsert_session(AgentSession(session_id="foreign", agent_id="samurai", user_id="other"))
    with client:
        assert client.post("/agentos/agents/samurai/agui", json=payload()).status_code == 401
        assert (
            client.post(
                "/agentos/agents/samurai/agui", json=payload(threadId="foreign"), headers=headers
            ).status_code
            == 404
        )
        assert (
            client.post("/agentos/agents/samurai/agui", json=payload(), headers=headers).status_code
            == 200
        )
        assert (
            client.post("/agentos/agents/samurai/agui", json=payload(), headers=headers).status_code
            == 409
        )


def test_agui_can_read_and_cancel_before_first_model_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = threading.Event()
    release = threading.Event()
    original = _ToolSequenceModel.ainvoke

    async def waiting_model(
        self: _ToolSequenceModel,
        messages: list[Message],
        *,
        tools: list[dict[str, object]] | None = None,
        **kwargs: Never,
    ) -> ModelResponse:
        entered.set()
        _ = await anyio.to_thread.run_sync(release.wait, 10)
        return await original(self, messages, tools=tools, **kwargs)

    original_save = Agent.asave_session

    async def checked_save(
        self: Agent, session: AgentSession | TeamSession | WorkflowSession
    ) -> None:
        assert session.created_at is not None
        assert session.updated_at is not None
        await original_save(self, session)

    monkeypatch.setattr(Agent, "asave_session", checked_save)
    monkeypatch.setattr(_ToolSequenceModel, "ainvoke", waiting_model)
    client, headers, _ = fixture(tmp_path)
    with client, ThreadPoolExecutor(max_workers=1) as executor:
        running = executor.submit(
            client.post, "/agentos/agents/samurai/agui", json=payload(), headers=headers
        )
        try:
            assert entered.wait(timeout=5)
            read = client.get(
                "/agentos/agents/samurai/runs/view-run?session_id=company-1", headers=headers
            )
            assert read.status_code == 200
            assert read.json()["status"] == "RUNNING"
            cancel = client.post(
                "/agentos/agents/samurai/runs/view-run/cancel?session_id=company-1", headers=headers
            )
            assert cancel.status_code == 200
        finally:
            release.set()
        result = running.result(timeout=10)
        stored = client.get(
            "/agentos/agents/samurai/runs/view-run?session_id=company-1", headers=headers
        )
    assert "RunCancelled" in result.text
    assert stored.json()["status"] == "CANCELLED"
    assert "SAMURAI_PANEL=" not in result.text


@pytest.mark.parametrize("area", ["overview", "research", "strategy", "verification", "sales"])
def test_inline_agui_exposes_only_read_only_tools(tmp_path: Path, area: str) -> None:
    model = _ToolSequenceModel("read_company_state")
    client, headers, _ = fixture(tmp_path, model)
    with client:
        response = client.post(
            "/agentos/agents/samurai/agui",
            json=payload(forwardedProps={"team_area": area}),
            headers=headers,
        )
    assert response.status_code == 200
    assert '"type":"RUN_FINISHED"' in response.text
    assert "read_company_state" in model.advertised_tools_json
    for tool in ("run_company_journey", "create_launch_drafts", "analyze_metrics"):
        assert tool not in model.advertised_tools_json


@pytest.mark.parametrize("operation", ["journey", "launch_drafts", "metrics_analysis"])
def test_inline_agui_rejects_approved_work_without_worker(tmp_path: Path, operation: str) -> None:
    model = _ToolSequenceModel("read_company_state")
    client, headers, db = fixture(tmp_path, model)
    with client:
        response = client.post(
            "/agentos/agents/samurai/agui",
            json=payload(
                forwardedProps={
                    "work_approval": {
                        "operation": operation,
                        "stage": "plan",
                        "expected_revision": 0,
                        "company_id": None,
                    }
                }
            ),
            headers=headers,
        )
    assert response.status_code == 503
    assert response.json()["detail"] == "Approved work requires Samurai's durable execution worker."
    assert model.calls == 0
    assert db.get_run("view-run") is None
