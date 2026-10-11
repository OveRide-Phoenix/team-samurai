import pytest
from agno.db.postgres import PostgresDb
from agno.os.routers.workflows.schema import WorkflowResponse
from agno.os.schema import ConfigResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from samurai import app


def test_discovery_rejects_request_without_bearer_key() -> None:
    # Given a configured local AgentOS instance.
    with TestClient(app.create_app()) as client:
        # When discovery is requested without authentication.
        response = client.get("/agentos/config")
    # Then private runtime configuration is not exposed.
    assert response.status_code == 401


def test_discovery_accepts_configured_bearer_key() -> None:
    # Given the service's configured key.
    settings = app.Settings.model_validate({})
    with TestClient(app.create_app()) as client:
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


def test_config_exposes_conversational_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "not-a-real-key")
    settings = app.Settings.model_validate({})
    with TestClient(app.create_app()) as client:
        headers = {"Authorization": f"Bearer {settings.os_security_key.get_secret_value()}"}
        config = ConfigResponse.model_validate_json(
            client.get("/agentos/config", headers=headers).content
        )
        detail = WorkflowResponse.model_validate_json(
            client.get("/agentos/workflows/company-foundation", headers=headers).content,
        )
        cors = client.options(
            "/agentos/config",
            headers={
                "Origin": "https://os.agno.com",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert config.agents == []
    assert config.workflows[0].id == "company-foundation"
    assert config.chat is not None
    assert len(config.chat.quick_prompts["company-foundation"]) == 3
    assert detail.is_factory is True
    assert cors.headers["access-control-allow-origin"] == "https://os.agno.com"


def test_workflow_builder_creates_fresh_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a model-enabled workflow factory.
    monkeypatch.setenv("GOOGLE_API_KEY", "not-a-real-key")
    settings = app.Settings.model_validate({})
    db = PostgresDb(id="samurai", db_url=str(settings.database_url))
    # When two independent workflow requests are resolved.
    first = app.create_foundation_workflow(db, settings)
    second = app.create_foundation_workflow(db, settings)
    # Then neither request can inherit mutable Gemini state from the other.
    assert first.agent is not None
    assert second.agent is not None
    assert first.agent.model is not second.agent.model


def test_agentos_mount_keeps_root_routes_separate() -> None:
    # Given the mounted runtime and a future parent-owned route.
    application = app.create_app()

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
