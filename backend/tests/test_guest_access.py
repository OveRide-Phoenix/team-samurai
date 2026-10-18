from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import text

from samurai.app import create_app
from samurai.config import Settings
from samurai.guest_access import admit_guest
from samurai.workspace_api import WorkspaceView

if TYPE_CHECKING:
    from uuid import UUID

    from samurai.company_store import CompanyStore
    from samurai.execution_state import SamuraiPostgresDb

pytest_plugins = ("tests.company_store_support",)


def test_guest_limits_are_atomic_global_and_survive_new_clients(
    company_store: tuple[CompanyStore, SamuraiPostgresDb, UUID],
) -> None:
    _, database, _ = company_store

    def submit(_: int) -> bool:
        return admit_guest(database.db_engine, database.db_schema, "guest:one", ai_run=True)

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(submit, range(20))) == 13
    for index in range(40):
        assert admit_guest(database.db_engine, database.db_schema, f"guest:{index}", ai_run=True)
    assert not admit_guest(database.db_engine, database.db_schema, "guest:new-cookie", ai_run=True)
    assert admit_guest(database.db_engine, database.db_schema, "guest:one", ai_run=False)
    with database.db_engine.begin() as connection:
        _ = connection.execute(
            text(f'UPDATE "{database.db_schema}".samurai_guest_usage SET day = day - 1'),  # noqa: S608 - generated fixture schema.
        )
    assert submit(0)


def test_guest_write_budget_cannot_be_reset_by_new_identity(
    company_store: tuple[CompanyStore, SamuraiPostgresDb, UUID],
) -> None:
    _, database, _ = company_store
    for index in range(300):
        assert admit_guest(database.db_engine, database.db_schema, f"guest:{index}", ai_run=False)
    assert not admit_guest(database.db_engine, database.db_schema, "guest:another", ai_run=False)


def test_guest_authentication_isolation_and_disabled_boundary(
    company_store: tuple[CompanyStore, SamuraiPostgresDb, UUID],
) -> None:
    _, database, _ = company_store
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    settings = Settings.model_validate(
        {"jwt_verification_key": public, "guest_access_enabled": True}
    )

    def headers(subject: str) -> dict[str, str]:
        token = jwt.encode(
            {
                "sub": subject,
                "scopes": ["agents:samurai:read", "agents:samurai:run"],
                "exp": datetime.now(UTC) + timedelta(minutes=5),
            },
            key,
            algorithm="RS256",
        )
        return {"Authorization": f"Bearer {token}"}

    one, two = headers(f"guest:{uuid4()}"), headers(f"guest:{uuid4()}")
    path = "/agentos/samurai/workspaces"
    with TestClient(create_app(db=database, settings=settings)) as client:
        assert client.post(path, json={"display_name": "Guest"}).status_code == 401
        created = client.post(path, headers=one, json={"display_name": "Guest"})
        assert created.status_code == 201
        workspace = WorkspaceView.model_validate(created.json()).workspace_id
        assert client.get(path, headers=two).json() == []
        assert client.get(f"{path}/{workspace}/companies", headers=two).status_code == 403
        assert (
            client.put(
                f"{path}/{workspace}/members/other", headers=one, json={"role": "editor"}
            ).status_code
            == 403
        )
        with database.db_engine.begin() as connection:
            _ = connection.execute(
                text(f'DROP TABLE "{database.db_schema}".samurai_guest_usage'),
            )
        assert client.post(path, headers=one, json={"display_name": "Blocked"}).status_code == 503
    disabled = settings.model_copy(update={"guest_access_enabled": False})
    with TestClient(create_app(db=database, settings=disabled)) as client:
        assert client.get(path, headers=one).status_code == 503
        assert client.get(path, headers=headers("iap:team-user")).status_code == 200
