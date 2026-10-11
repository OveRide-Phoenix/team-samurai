import pytest
from agno.os.routers.workflows.schema import WorkflowResponse
from agno.os.schema import ConfigResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from samurai import app


def test_discovery_rejects_request_without_bearer_key() -> None:
    # Given a configured local AgentOS instance.
    with TestClient(app.create_app()) as client:
        # When discovery is requested without authentication.
        response = client.get("/config")
    # Then private runtime configuration is not exposed.
    assert response.status_code == 401


def test_discovery_accepts_configured_bearer_key() -> None:
    # Given the service's configured key.
    settings = app.Settings.model_validate({})
    with TestClient(app.create_app()) as client:
        # When discovery uses the matching bearer key.
        response = client.get(
            "/config",
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
        config = ConfigResponse.model_validate_json(client.get("/config", headers=headers).content)
        detail = WorkflowResponse.model_validate_json(
            client.get("/workflows/company-foundation", headers=headers).content,
        )
        cors = client.options(
            "/config",
            headers={
                "Origin": "https://os.agno.com",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert config.agents == []
    assert config.workflows[0].id == "company-foundation"
    assert config.chat is not None
    assert len(config.chat.quick_prompts["company-foundation"]) == 3
    assert detail.workflow_agent is True
    assert detail.steps is not None
    assert len(detail.steps) == 2
    assert cors.headers["access-control-allow-origin"] == "https://os.agno.com"
