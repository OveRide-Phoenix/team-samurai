from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest
from pydantic import JsonValue, TypeAdapter

from samurai.contracts import Role
from samurai.frameworks import (
    FRAMEWORK_MANIFEST,
    FrameworkValidationError,
    load_framework_catalog,
)

if TYPE_CHECKING:
    import pathlib


MANIFEST_ADAPTER = TypeAdapter(dict[str, list[dict[str, JsonValue]]])


def _copied_frameworks(tmp_path: pathlib.Path) -> pathlib.Path:
    target = tmp_path / "frameworks"
    _ = shutil.copytree(FRAMEWORK_MANIFEST.parent, target)
    return target / "manifest.json"


def _manifest_payload(path: pathlib.Path) -> dict[str, list[dict[str, JsonValue]]]:
    return MANIFEST_ADAPTER.validate_json(path.read_bytes())


def _write_manifest(path: pathlib.Path, payload: dict[str, list[dict[str, JsonValue]]]) -> None:
    _ = path.write_text(MANIFEST_ADAPTER.dump_json(payload).decode(), encoding="utf-8")


def test_reviewed_frameworks_are_role_scoped_and_attributed() -> None:
    # Given the committed reviewed manifest.
    catalog = load_framework_catalog()

    # When framework access is projected by role.
    role_ids = {
        role: tuple(resource.metadata.id for resource in catalog.for_role(role)) for role in Role
    }

    # Then only Intake, Strategist, and Verifier receive reviewed text.
    assert role_ids == {
        Role.INTAKE: ("founder_truth",),
        Role.RESEARCHER: (),
        Role.STRATEGIST: ("founder_truth", "offer_diagnostic"),
        Role.PRODUCT_MANAGER: (),
        Role.BUILDER: (),
        Role.MARKETER: (),
        Role.SALES: (),
        Role.ANALYST: (),
        Role.VERIFIER: ("founder_truth", "offer_diagnostic"),
    }
    assert all(resource.text.strip() for resource in catalog.resources)
    assert all(metadata.license == "MIT" for metadata in catalog.metadata)
    assert all(len(metadata.sha256) == 64 for metadata in catalog.metadata)
    assert all(
        tuple(metadata.model_dump(mode="json"))
        == (
            "id",
            "version",
            "source_repository",
            "source_revision",
            "source_url",
            "license",
            "attribution",
            "allowed_roles",
            "sha256",
            "review_date",
        )
        for metadata in catalog.metadata
    )


def test_framework_hash_tamper_fails_closed(tmp_path: pathlib.Path) -> None:
    # Given one altered byte in a reviewed resource.
    manifest = _copied_frameworks(tmp_path)
    resource = manifest.parent / "founder-truth.md"
    _ = resource.write_bytes(resource.read_bytes() + b"x")

    # When the catalog loads, then it rejects the resource before returning text.
    with pytest.raises(FrameworkValidationError, match="resource_hash_mismatch"):
        _ = load_framework_catalog(manifest)


@pytest.mark.parametrize(
    ("field", "value", "expected_issue"),
    [
        ("resource", "../outside.md", "resource_path_invalid"),
        ("permissions", ["network"], "manifest_invalid"),
        ("allowed_roles", ["intruder"], "manifest_invalid"),
        ("allowed_roles", [], "manifest_invalid"),
        ("allowed_roles", ["intake", "intake"], "manifest_invalid"),
    ],
)
def test_hostile_manifest_fails_closed(
    tmp_path: pathlib.Path,
    field: str,
    value: JsonValue,
    expected_issue: str,
) -> None:
    # Given a copied manifest with one hostile field.
    manifest = _copied_frameworks(tmp_path)
    payload = _manifest_payload(manifest)
    entry = payload["frameworks"][0]
    entry[field] = value
    _write_manifest(manifest, payload)

    # When the catalog loads, then strict validation rejects it.
    with pytest.raises(FrameworkValidationError, match=expected_issue):
        _ = load_framework_catalog(manifest)


def test_duplicate_framework_id_fails_closed(tmp_path: pathlib.Path) -> None:
    # Given two manifest entries with the same ID.
    manifest = _copied_frameworks(tmp_path)
    payload = _manifest_payload(manifest)
    payload["frameworks"][1]["id"] = payload["frameworks"][0]["id"]
    _write_manifest(manifest, payload)

    # When the catalog loads, then it rejects the duplicate.
    with pytest.raises(FrameworkValidationError, match="manifest_invalid"):
        _ = load_framework_catalog(manifest)
