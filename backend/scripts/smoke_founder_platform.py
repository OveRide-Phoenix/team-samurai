"""Exercise the private workspace file API over loopback with synthetic JWT actors."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, Never
from urllib.parse import urlsplit

import httpx
import jwt

if TYPE_CHECKING:
    from pydantic import JsonValue


PUBLIC_FILE_FIELDS = {
    "file_id",
    "workspace_id",
    "company_id",
    "state",
    "display_name",
    "media_type",
    "byte_size",
    "content_sha256",
    "created_at",
    "updated_at",
}
FORBIDDEN = 403
NOT_FOUND = 404
CONTENT_TOO_LARGE = 413


class SmokeArguments(argparse.Namespace):
    """Validated inputs for one loopback-only file smoke run."""

    base_url: str = "http://127.0.0.1:8000"
    signing_key: Path = Path()
    evidence: Path = Path()


class SmokeError(RuntimeError):
    """Identify a failed public boundary without including response bodies."""


def _arguments() -> SmokeArguments:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    _ = parser.add_argument("--signing-key", required=True, type=Path)
    _ = parser.add_argument("--evidence", required=True, type=Path)
    return parser.parse_args(namespace=SmokeArguments())


def validate_local_url(value: str) -> str:
    """Accept only uncredentialed loopback HTTP origins."""
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        _fail("base URL must be a loopback HTTP origin")
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        _fail("base URL must be a loopback HTTP origin")
    return value.rstrip("/")


def _headers(signing_key: str, subject: str) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": subject,
            "scopes": ["agents:samurai:read", "agents:samurai:run"],
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        signing_key,
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _expect(response: httpx.Response, status_code: int) -> httpx.Response:
    if response.status_code != status_code:
        message = f"expected HTTP {status_code}, received {response.status_code}"
        raise SmokeError(message)
    return response


def _fail(message: str) -> Never:
    raise SmokeError(message)


def _json(response: httpx.Response) -> dict[str, Any]:
    value = response.json()
    if not isinstance(value, dict):
        _fail("expected a JSON object")
    return value


def _workspace(client: httpx.Client, headers: dict[str, str], name: str) -> str:
    response = _expect(
        client.post("/agentos/samurai/workspaces", headers=headers, json={"display_name": name}),
        201,
    )
    workspace_id = _json(response).get("workspace_id")
    if not isinstance(workspace_id, str):
        _fail("workspace response omitted its identifier")
    return workspace_id


def _write_evidence(path: Path, payload: JsonValue) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_smoke(arguments: SmokeArguments) -> None:  # noqa: C901, PLR0915 - linear HTTP scenario.
    """Verify successful and adversarial file flows against a real loopback server."""
    base_url = validate_local_url(arguments.base_url)
    signing_key = arguments.signing_key.read_text(encoding="utf-8")
    owner = _headers(signing_key, "task9-owner")
    other = _headers(signing_key, "task9-other")
    editor = _headers(signing_key, "task9-editor")
    viewer = _headers(signing_key, "task9-viewer")
    payload = b"# Task 9 loopback evidence\n"
    expected_hash = sha256(payload).hexdigest()
    results: dict[str, JsonValue] = {}

    with httpx.Client(base_url=base_url, timeout=30) as client:
        workspace_id = _workspace(client, owner, "Task 9 Files")
        other_workspace_id = _workspace(client, other, "Task 9 Other")
        for subject, role in (("task9-editor", "editor"), ("task9-viewer", "viewer")):
            _expect(
                client.put(
                    f"/agentos/samurai/workspaces/{workspace_id}/members/{subject}",
                    headers=owner,
                    json={"role": role},
                ),
                200,
            )

        uploaded = _expect(
            client.post(
                f"/agentos/samurai/workspaces/{workspace_id}/files",
                headers=editor,
                files={"file": ("evidence.md", payload, "text/markdown")},
            ),
            201,
        )
        file_record = _json(uploaded)
        if set(file_record) != PUBLIC_FILE_FIELDS:
            _fail("file response fields differ from the public contract")
        file_id = file_record.get("file_id")
        if not isinstance(file_id, str) or file_record.get("content_sha256") != expected_hash:
            _fail("file response identity or hash is invalid")

        listed = _expect(
            client.get(f"/agentos/samurai/workspaces/{workspace_id}/files", headers=viewer),
            200,
        )
        if listed.json() != [file_record]:
            _fail("viewer list did not contain exactly the ready file")
        downloaded = _expect(
            client.get(
                f"/agentos/samurai/workspaces/{workspace_id}/files/{file_id}/download",
                headers=viewer,
            ),
            200,
        )
        if downloaded.content != payload:
            _fail("download bytes differ from uploaded bytes")
        expected_headers = {
            "content-length": str(len(payload)),
            "x-content-sha256": expected_hash,
            "cache-control": "private, no-store",
            "x-content-type-options": "nosniff",
        }
        if any(downloaded.headers.get(key) != value for key, value in expected_headers.items()):
            _fail("download security or integrity headers are invalid")
        if not downloaded.headers.get("content-disposition", "").startswith("attachment;"):
            _fail("download disposition is not an attachment")

        denied_upload = client.post(
            f"/agentos/samurai/workspaces/{workspace_id}/files",
            headers=viewer,
            files={"file": ("denied.txt", b"denied", "text/plain")},
        )
        denied_delete = client.delete(
            f"/agentos/samurai/workspaces/{workspace_id}/files/{file_id}", headers=viewer
        )
        cross_workspace = client.get(
            f"/agentos/samurai/workspaces/{workspace_id}/files/{file_id}", headers=other
        )
        oversized = client.post(
            f"/agentos/samurai/workspaces/{workspace_id}/files",
            headers=owner,
            files={"file": ("large.txt", b"x" * (10 * 1024 * 1024 + 1), "text/plain")},
        )
        if denied_upload.status_code != FORBIDDEN or denied_delete.status_code != FORBIDDEN:
            _fail("viewer mutation was not denied")
        if cross_workspace.status_code not in {FORBIDDEN, NOT_FOUND}:
            _fail("cross-workspace metadata leaked existence")
        if oversized.status_code != CONTENT_TOO_LARGE:
            _fail("oversized multipart upload was not rejected")

        _expect(
            client.delete(
                f"/agentos/samurai/workspaces/{workspace_id}/files/{file_id}", headers=owner
            ),
            204,
        )
        stale_download = client.get(
            f"/agentos/samurai/workspaces/{workspace_id}/files/{file_id}/download",
            headers=owner,
        )
        cleanup = _expect(
            client.post(f"/agentos/samurai/workspaces/{workspace_id}/files/cleanup", headers=owner),
            200,
        )
        cleanup_record = _json(cleanup)
        if stale_download.status_code != NOT_FOUND or any(cleanup_record.values()):
            _fail("deleted bytes remained readable or cleanup was not empty")

        results = {
            "outcome": "passed",
            "workspace_id": workspace_id,
            "isolation_workspace_id": other_workspace_id,
            "file_id": file_id,
            "content_sha256": expected_hash,
            "ready_download": downloaded.status_code,
            "viewer_upload": denied_upload.status_code,
            "viewer_delete": denied_delete.status_code,
            "cross_workspace": cross_workspace.status_code,
            "oversized_upload": oversized.status_code,
            "deleted_download": stale_download.status_code,
            "cleanup": cleanup_record,
        }
    _write_evidence(arguments.evidence, results)
    _ = sys.stdout.write(json.dumps(results, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    run_smoke(_arguments())
