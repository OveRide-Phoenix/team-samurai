from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.schema import DropSchema

from samurai.app import create_app
from samurai.config import Settings
from samurai.execution_state import SamuraiPostgresDb
from samurai.file_api import CleanupView, FileView
from samurai.schema import FounderPlatformMigrator
from samurai.workspace_api import CompanyView, WorkspaceView

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

pytest_plugins = ("tests.company_store_support",)


class _HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def content(self) -> bytes: ...

    @property
    def text(self) -> str: ...

    @property
    def headers(self) -> Mapping[str, str]: ...


@pytest.fixture
def file_client(
    postgres_url: str, tmp_path: Path
) -> Iterator[tuple[TestClient, rsa.RSAPrivateKey, SamuraiPostgresDb]]:
    schema = f"founder_t09_{uuid4().hex}"
    database = SamuraiPostgresDb(id=schema, db_url=postgres_url, db_schema=schema)
    database.ensure_work_intents_table()
    _ = FounderPlatformMigrator(database.db_engine, schema=schema).apply()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    settings = Settings.model_validate(
        {
            "jwt_verification_key": public_key.decode(),
            "storage_root": tmp_path / "objects",
        }
    )
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


def _workspace(client: TestClient, headers: dict[str, str], name: str = "Files") -> UUID:
    response = client.post(
        "/agentos/samurai/workspaces", headers=headers, json={"display_name": name}
    )
    assert response.status_code == 201
    return WorkspaceView.model_validate_json(response.content).workspace_id


def _company(client: TestClient, headers: dict[str, str], workspace_id: UUID) -> UUID:
    response = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/companies",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={},
    )
    assert response.status_code == 201
    return CompanyView.model_validate_json(response.content).company_id


def _upload(  # noqa: PLR0913 - tests vary the complete multipart boundary.
    client: TestClient,
    headers: dict[str, str],
    workspace_id: UUID,
    *,
    name: str = "brief.md",
    content: bytes = b"bounded evidence\n",
    media_type: str = "text/markdown",
    company_id: UUID | None = None,
) -> _HttpResponse:
    data = {} if company_id is None else {"company_id": str(company_id)}
    return client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/files",
        headers=headers,
        data=data,
        files={"file": (name, content, media_type)},
    )


def test_authenticated_file_lifecycle_streams_safe_download(
    file_client: tuple[TestClient, rsa.RSAPrivateKey, SamuraiPostgresDb],
) -> None:
    # Given an owner workspace and a company-bound Markdown file.
    client, private_key, _database = file_client
    owner = _headers(private_key, "owner")
    workspace_id = _workspace(client, owner)
    company_id = _company(client, owner, workspace_id)
    content = b"bounded evidence\n"

    # When the owner uploads, lists, inspects, downloads, and deletes it.
    uploaded = _upload(client, owner, workspace_id, content=content, company_id=company_id)
    assert uploaded.status_code == 201
    uploaded_view = FileView.model_validate_json(uploaded.content)
    file_id = uploaded_view.file_id
    listed = client.get(f"/agentos/samurai/workspaces/{workspace_id}/files", headers=owner)
    metadata = client.get(
        f"/agentos/samurai/workspaces/{workspace_id}/files/{file_id}", headers=owner
    )
    downloaded = client.get(
        f"/agentos/samurai/workspaces/{workspace_id}/files/{file_id}/download",
        headers=owner,
    )
    deleted = client.delete(
        f"/agentos/samurai/workspaces/{workspace_id}/files/{file_id}", headers=owner
    )
    unavailable = client.get(
        f"/agentos/samurai/workspaces/{workspace_id}/files/{file_id}/download",
        headers=owner,
    )

    # Then only public metadata is returned and the ready bytes have exact safe headers.
    expected_hash = sha256(content).hexdigest()
    assert listed.status_code == metadata.status_code == downloaded.status_code == 200
    assert TypeAdapter(list[FileView]).validate_json(listed.content) == [uploaded_view]
    assert FileView.model_validate_json(metadata.content) == uploaded_view
    assert uploaded_view.company_id == company_id
    assert uploaded_view.content_sha256 == expected_hash
    assert "storage_key" not in uploaded.text
    assert downloaded.content == content
    assert downloaded.headers["content-length"] == str(len(content))
    assert downloaded.headers["x-content-sha256"] == expected_hash
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert deleted.status_code == 204
    assert unavailable.status_code == 404


def test_viewer_reads_only_ready_files_and_cannot_mutate(
    file_client: tuple[TestClient, rsa.RSAPrivateKey, SamuraiPostgresDb],
) -> None:
    # Given an owner file shared with a viewer and an editor.
    client, private_key, database = file_client
    owner = _headers(private_key, "owner")
    viewer = _headers(private_key, "viewer")
    editor = _headers(private_key, "editor")
    workspace_id = _workspace(client, owner)
    for subject, role in (("viewer", "viewer"), ("editor", "editor")):
        response = client.put(
            f"/agentos/samurai/workspaces/{workspace_id}/members/{subject}",
            headers=owner,
            json={"role": role},
        )
        assert response.status_code == 200
    uploaded = _upload(client, editor, workspace_id, name="shared.txt", media_type="text/plain")
    assert uploaded.status_code == 201
    file_id = FileView.model_validate_json(uploaded.content).file_id

    # When the viewer lists/downloads and attempts both mutations.
    listed = client.get(f"/agentos/samurai/workspaces/{workspace_id}/files", headers=viewer)
    downloaded = client.get(
        f"/agentos/samurai/workspaces/{workspace_id}/files/{file_id}/download",
        headers=viewer,
    )
    denied_upload = _upload(client, viewer, workspace_id)
    denied_delete = client.delete(
        f"/agentos/samurai/workspaces/{workspace_id}/files/{file_id}", headers=viewer
    )

    with database.db_engine.begin() as connection:
        quarantine_statement = text(
            f"""UPDATE "{database.db_schema}".samurai_files
            SET state = 'quarantined' WHERE file_id = :file_id"""  # noqa: S608 - UUID-derived schema fixture.
        )
        _ = connection.execute(quarantine_statement, {"file_id": file_id})
    hidden = client.get(f"/agentos/samurai/workspaces/{workspace_id}/files", headers=viewer)
    blocked = client.get(
        f"/agentos/samurai/workspaces/{workspace_id}/files/{file_id}/download",
        headers=viewer,
    )
    owner_blocked = client.get(
        f"/agentos/samurai/workspaces/{workspace_id}/files/{file_id}/download",
        headers=owner,
    )
    assert (
        client.delete(
            f"/agentos/samurai/workspaces/{workspace_id}/members/viewer", headers=owner
        ).status_code
        == 204
    )
    revoked = client.get(f"/agentos/samurai/workspaces/{workspace_id}/files", headers=viewer)

    # Then ready reads work while writes fail without changing the file.
    assert listed.status_code == downloaded.status_code == 200
    assert len(TypeAdapter(list[FileView]).validate_json(listed.content)) == 1
    assert denied_upload.status_code == denied_delete.status_code == 403
    assert hidden.status_code == 200
    assert TypeAdapter(list[FileView]).validate_json(hidden.content) == []
    assert blocked.status_code == 404
    assert owner_blocked.status_code == 409, owner_blocked.text
    assert revoked.status_code == 403
    assert (
        client.get(
            f"/agentos/samurai/workspaces/{workspace_id}/files/{file_id}", headers=owner
        ).status_code
        == 200
    )


def test_file_boundary_rejects_wrong_scope_fields_types_and_size(
    file_client: tuple[TestClient, rsa.RSAPrivateKey, SamuraiPostgresDb],
) -> None:
    # Given two isolated workspaces and one company in the second workspace.
    client, private_key, database = file_client
    owner = _headers(private_key, "owner")
    other = _headers(private_key, "other")
    workspace_id = _workspace(client, owner, "Owner")
    other_workspace_id = _workspace(client, other, "Other")
    other_company_id = _company(client, other, other_workspace_id)
    uploaded = _upload(client, owner, workspace_id)
    assert uploaded.status_code == 201
    file_id = FileView.model_validate_json(uploaded.content).file_id

    # When callers cross scope or send malformed, spoofed, traversal, and oversized input.
    cross_workspace = client.get(
        f"/agentos/samurai/workspaces/{other_workspace_id}/files/{file_id}", headers=owner
    )
    wrong_company = _upload(client, owner, workspace_id, company_id=other_company_id)
    unknown = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/files",
        headers=owner,
        data={"user_id": "forged"},
        files={"file": ("brief.md", b"safe", "text/markdown")},
    )
    traversal = _upload(client, owner, workspace_id, name="../brief.md")
    spoofed_type = _upload(client, owner, workspace_id, media_type="application/pdf")
    oversized = _upload(client, owner, workspace_id, content=b"x" * (10 * 1024 * 1024 + 1))
    duplicate = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/files",
        headers=owner,
        files=[
            ("file", ("one.txt", b"one", "text/plain")),
            ("file", ("two.txt", b"two", "text/plain")),
        ],
    )
    malformed = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/files",
        headers={**owner, "Content-Type": "multipart/form-data; boundary=broken"},
        content=b"not multipart",
    )
    boundary = "samurai-t09-boundary"
    prefix = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        'filename="large.txt"\r\nContent-Type: text/plain\r\n\r\n'
    ).encode()

    def chunked_body() -> Iterator[bytes]:
        yield prefix
        for _ in range(11):
            yield b"x" * (1024 * 1024)
        yield f"\r\n--{boundary}--\r\n".encode()

    chunked_oversized = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/files",
        headers={
            **owner,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Transfer-Encoding": "chunked",
        },
        content=chunked_body(),
    )

    # Then no existence or internal storage detail leaks and quota reflects only the first file.
    assert cross_workspace.status_code in {403, 404}
    assert wrong_company.status_code == 404
    assert unknown.status_code == 400
    assert traversal.status_code == 422
    assert spoofed_type.status_code == 422
    assert oversized.status_code == 413
    assert duplicate.status_code == malformed.status_code == 400
    assert chunked_oversized.status_code == 413
    with database.db_engine.connect() as connection:
        quota_statement = text(
            f"""SELECT file_count, stored_bytes
            FROM "{database.db_schema}".samurai_workspace_quotas
            WHERE workspace_id = :workspace_id"""  # noqa: S608 - UUID-derived schema fixture.
        )
        usage = connection.execute(
            quota_statement,
            {"workspace_id": workspace_id},
        ).one()
    assert usage == (1, len(b"bounded evidence\n"))
    assert "storage" not in cross_workspace.text.casefold()


def test_owner_cleanup_is_strictly_workspace_scoped(
    file_client: tuple[TestClient, rsa.RSAPrivateKey, SamuraiPostgresDb],
) -> None:
    # Given an owner, an editor, and aged quarantines in two workspaces.
    client, private_key, database = file_client
    owner = _headers(private_key, "owner")
    editor = _headers(private_key, "editor")
    other = _headers(private_key, "other")
    workspace_id = _workspace(client, owner, "Owner")
    other_workspace_id = _workspace(client, other, "Other")
    assert (
        client.put(
            f"/agentos/samurai/workspaces/{workspace_id}/members/editor",
            headers=owner,
            json={"role": "editor"},
        ).status_code
        == 200
    )
    target_files = (
        _upload(client, owner, workspace_id, name="owner.txt", media_type="text/plain"),
        _upload(client, other, other_workspace_id, name="other.txt", media_type="text/plain"),
    )
    for uploaded in target_files:
        assert uploaded.status_code == 201
        file_id = FileView.model_validate_json(uploaded.content).file_id
        with database.db_engine.begin() as connection:
            age_statement = text(
                f"""UPDATE "{database.db_schema}".samurai_files
                SET state = 'quarantined', updated_at = 0
                WHERE file_id = :file_id"""  # noqa: S608 - UUID-derived schema fixture.
            )
            _ = connection.execute(
                age_statement,
                {"file_id": file_id},
            )

    # When the editor is denied and the owner cleans only their workspace.
    denied = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/files/cleanup", headers=editor
    )
    query_denied = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/files/cleanup?now=2147483648",
        headers=owner,
    )
    cleaned = client.post(
        f"/agentos/samurai/workspaces/{workspace_id}/files/cleanup", headers=owner
    )

    # Then only the selected workspace changes state.
    assert denied.status_code == 403
    assert query_denied.status_code == 400
    assert cleaned.status_code == 200
    assert CleanupView.model_validate_json(cleaned.content).quarantines_rejected == 1
    with database.db_engine.connect() as connection:
        state_statement = text(
            f"""SELECT workspace_id, state
            FROM "{database.db_schema}".samurai_files
            ORDER BY workspace_id"""  # noqa: S608 - UUID-derived schema fixture.
        )
        states = dict(connection.execute(state_statement).all())
    assert states[workspace_id] == "rejected"
    assert states[other_workspace_id] == "quarantined"
