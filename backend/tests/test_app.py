from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.os.routers.agents.schema import AgentResponse
from agno.os.schema import ConfigResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from samurai import app
from samurai.parent import create_parent_agent

if TYPE_CHECKING:
    import pathlib


def test_discovery_rejects_request_without_bearer_key(tmp_path: pathlib.Path) -> None:
    # Given a configured local AgentOS instance.
    with TestClient(
        app.create_app(db=SqliteDb(db_file=str(tmp_path / "unauthorized.db")))
    ) as client:
        # When discovery is requested without authentication.
        response = client.get("/agentos/config")
    # Then private runtime configuration is not exposed.
    assert response.status_code == 401


def test_discovery_accepts_configured_bearer_key(tmp_path: pathlib.Path) -> None:
    # Given the service's configured key.
    settings = app.Settings.model_validate({})
    with TestClient(app.create_app(db=SqliteDb(db_file=str(tmp_path / "authorized.db")))) as client:
        # When discovery uses the matching bearer key.
        response = client.get(
            "/agentos/config",
            headers={
                "Authorization": f"Bearer {settings.os_security_key.get_secret_value()}",
            },
        )
    # Then AgentOS discovery succeeds without a paid model call.
    assert response.status_code == 200


def test_startup_rejects_empty_service_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OS_SECURITY_KEY", "")
    with pytest.raises(ValidationError):
        _ = app.create_app()


def test_config_exposes_only_samurai_parent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "not-a-real-key")
    settings = app.Settings.model_validate({})
    application = app.create_app(
        db=SqliteDb(db_file=str(tmp_path / "discovery.db")),
        settings=settings,
    )
    with TestClient(application) as client:
        headers = {"Authorization": f"Bearer {settings.os_security_key.get_secret_value()}"}
        config = ConfigResponse.model_validate_json(
            client.get("/agentos/config", headers=headers).content
        )
        detail = AgentResponse.model_validate_json(
            client.get("/agentos/agents/samurai", headers=headers).content,
        )
        cors = client.options(
            "/agentos/config",
            headers={
                "Origin": "https://os.agno.com",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert [agent.id for agent in config.agents] == ["samurai"]
    assert config.workflows == []
    assert config.chat is not None
    assert config.chat.quick_prompts["samurai"] == [
        (
            "Build my business: describe the idea, customer, geography, budget, founder skills, "
            "and goal."
        ),
        "Continue my company plan using the context and decisions already retained.",
        "Create reviewable Builder, Marketer, and Sales drafts from my verified plan.",
        "Analyze these provenance-labelled business metrics and recommend what to improve.",
    ]
    assert detail.is_factory is True
    assert cors.headers["access-control-allow-origin"] == "https://os.agno.com"


def test_parent_factory_creates_fresh_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a model-enabled parent factory.
    monkeypatch.setenv("GOOGLE_API_KEY", "not-a-real-key")
    settings = app.Settings.model_validate({})
    db = PostgresDb(id="samurai", db_url=str(settings.database_url))
    # When two independent parent requests are resolved.
    first = create_parent_agent(db, settings)
    second = create_parent_agent(db, settings)
    # Then neither request can inherit mutable Gemini state from the other.
    assert first.model is not second.model


def test_agentos_mount_keeps_root_routes_separate(tmp_path: pathlib.Path) -> None:
    # Given the mounted runtime and a future parent-owned route.
    application = app.create_app(db=SqliteDb(db_file=str(tmp_path / "mount.db")))

    @application.get("/product-health")
    def product_health() -> str:
        return "ok"

    # When requests address the parent and AgentOS namespaces.
    with TestClient(application) as client:
        parent = client.get("/product-health")
        health = client.get("/agentos/health")
        root_config = client.get("/config")
        schema = client.get("/agentos/openapi.json")
    # Then AgentOS auth and routes remain inside their mount.
    assert parent.status_code == 200
    assert health.status_code == 200
    assert root_config.status_code == 404
    assert schema.status_code == 200
    assert schema.json()["servers"] == [{"url": "/agentos"}]
