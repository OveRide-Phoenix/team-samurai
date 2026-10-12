from __future__ import annotations

import hashlib
import json
import os
import subprocess
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Self, cast
from uuid import UUID, uuid4

import httpx
import pytest

from scripts import verify_readiness as readiness
from scripts.verify_readiness import (
    CaseResult,
    CaseStatus,
    ReadinessResult,
    RunnerError,
    build_result,
    load_environment,
    probe_local_endpoints,
    run,
    run_browser_evidence,
    run_contract_fixtures,
    run_domain_fixtures,
    run_http_journeys,
    run_post_commit_recovery,
    run_process_recovery,
    run_queue_safety_cases,
    run_target_pair_journey,
    run_terminal_browser_evidence,
    validate_disposable_services,
    validate_local_url,
    verify_provider_guard,
    write_result,
)
from tests.test_queue_process import (
    _company_state,  # pyright: ignore[reportPrivateUsage]
    _free_port,  # pyright: ignore[reportPrivateUsage]
    _wait_for_receipt,  # pyright: ignore[reportPrivateUsage]
    start_test_process,
    stop_test_process,
)

if TYPE_CHECKING:
    from samurai.execution_state import WorkReceipt
    from scripts.verify_readiness import _Arguments  # pyright: ignore[reportPrivateUsage]

pytest_plugins = ("tests.test_queue_process",)


@pytest.mark.parametrize(
    "url",
    [
        "https://samurai.example/agentos",
        "http://10.0.0.8:8000/agentos",
        "http://user@127.0.0.1:8000/agentos",
        "file:///tmp/samurai",
    ],
)
def test_local_mode_rejects_non_loopback_or_credentialed_urls(url: str) -> None:
    with pytest.raises(RunnerError, match="loopback HTTP URL"):
        _ = validate_local_url(url)


def test_result_cannot_report_missing_cases_as_passed(tmp_path: Path) -> None:
    result = build_result(
        required_cases=("process_recovery", "staged_journey"),
        cases=(
            CaseResult(
                name="process_recovery",
                status=CaseStatus.PASSED,
                observable="fresh subprocess exited zero",
                artifact="process-recovery.log",
            ),
        ),
    )

    write_result(result, tmp_path)

    payload = ReadinessResult.model_validate_json(
        (tmp_path / "result.json").read_text(encoding="utf-8")
    )
    assert payload.status is CaseStatus.BLOCKED
    assert payload.cases["staged_journey"].status is CaseStatus.BLOCKED
    assert payload.cases["staged_journey"].observable == "case was not executed"


def test_local_endpoint_probe_uses_both_supplied_urls_without_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[tuple[str, bool]] = []

    def fake_get(
        url: str,
        *,
        headers: dict[str, str] | None = None,
        follow_redirects: bool,
        timeout: int,
        trust_env: bool,
    ) -> httpx.Response:
        assert timeout == 5
        assert not trust_env
        requested.append((url, follow_redirects))
        if url.endswith("/api/agentos/connection"):
            assert headers == {"x-samurai-client": "1"}
            return httpx.Response(401)
        if "/work-receipts/" in url:
            assert headers is None
            return httpx.Response(403)
        assert headers is None
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "get", fake_get)
    result = probe_local_endpoints(
        "http://127.0.0.1:8123/agentos",
        "http://localhost:4567",
    )

    assert result.status is CaseStatus.PASSED
    submission_id = "00000000-0000-4000-8000-000000000010"
    receipt_probe = (
        f"http://127.0.0.1:8123/agentos/work-receipts/{submission_id}?session_id=task10-probe"
    )
    assert requested == [
        ("http://127.0.0.1:8123/agentos/health", False),
        ("http://localhost:4567/healthz", False),
        (receipt_probe, False),
        ("http://localhost:4567/api/agentos/connection", False),
    ]


def test_target_pair_journey_binds_supplied_bff_backend_and_canonical_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected_company_id = uuid4()
    run_ids = iter((uuid4(), uuid4()))
    stages: list[tuple[str, str, UUID | None, int]] = []

    class FakeClient:
        def __init__(self, **options: object) -> None:
            assert options["headers"] == {
                "x-samurai-client": "1",
                "origin": "http://127.0.0.1:4173",
                "x-goog-iap-jwt-assertion": "task10-local-assertion",
            }

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def get(self, url: str) -> httpx.Response:
            assert url == "http://127.0.0.1:4173/api/agentos/connection"
            return httpx.Response(
                200,
                json={
                    "backend": "http://127.0.0.1:8000",
                    "configured": True,
                    "auth": "jwt",
                    "storageNamespace": hashlib.sha256(b"iap:task10-local").hexdigest(),
                },
                request=httpx.Request("GET", url),
            )

    def fake_submit(
        _client: httpx.Client,
        frontend_url: str,
        _session_id: str,
        *,
        stage: str,
        company_id: UUID | None,
        revision: int,
    ) -> readiness._TargetReceipt:  # pyright: ignore[reportPrivateUsage]
        stages.append((frontend_url, stage, company_id, revision))
        return readiness._TargetReceipt(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
            status="COMPLETED",
            run_id=next(run_ids),
            company_id=company_id or expected_company_id,
            revision=revision + 1,
        )

    def fake_canonical(
        database_url: str,
        schema: str,
        owner_id: str,
        session_id: str,
    ) -> tuple[UUID, int, list[str], list[str]]:
        assert database_url.endswith("/samurai_task10")
        assert schema == "task6_queue_task10target_unit"
        assert owner_id == "iap:task10-local"
        assert session_id.startswith("task10-target-")
        return expected_company_id, 2, ["intake", "research"], ["complete", "complete"]

    monkeypatch.setattr(httpx, "Client", FakeClient)
    monkeypatch.setattr(readiness, "_submit_target_stage", fake_submit)
    monkeypatch.setattr(readiness, "_canonical_target_state", fake_canonical)

    result = run_target_pair_journey(
        tmp_path,
        "http://127.0.0.1:8000/agentos",
        "http://127.0.0.1:4173",
        {
            "SAMURAI_TEST_DATABASE_URL": (
                "postgresql://owner:secret@127.0.0.1:54329/samurai_task10"
            ),
            "SAMURAI_TEST_TARGET_SCHEMA": "task6_queue_task10target_unit",
            "SAMURAI_TEST_BFF_OWNER": "iap:task10-local",
            "SAMURAI_TEST_IAP_ASSERTION": "task10-local-assertion",
        },
    )

    assert result.status is CaseStatus.PASSED
    assert stages == [
        ("http://127.0.0.1:4173", "brief", None, 0),
        ("http://127.0.0.1:4173", "research", expected_company_id, 1),
    ]
    evidence = cast(
        "dict[str, object]",
        json.loads((tmp_path / "target-pair-journey.json").read_text(encoding="utf-8")),
    )
    assert evidence["bff_backend_resolves_to_supplied_base_url"] is True
    assert evidence["canonical"] == {
        "company_id": str(expected_company_id),
        "revision": 2,
        "artifact_types": ["intake", "research"],
        "artifact_statuses": ["complete", "complete"],
    }


@pytest.mark.parametrize(
    ("reported_backend", "storage_namespace"),
    [
        (
            "http://127.0.0.1:9999",
            hashlib.sha256(b"iap:task10-local").hexdigest(),
        ),
        ("http://127.0.0.1:8000", hashlib.sha256(b"another-owner").hexdigest()),
    ],
)
def test_target_pair_journey_rejects_unbound_bff_before_submission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reported_backend: str,
    storage_namespace: str,
) -> None:
    class FakeClient:
        def __init__(self, **_options: object) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def get(self, url: str) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "backend": reported_backend,
                    "configured": True,
                    "auth": "jwt",
                    "storageNamespace": storage_namespace,
                },
                request=httpx.Request("GET", url),
            )

    def unexpected_submission(*_args: object, **_kwargs: object) -> None:
        pytest.fail("a BFF bound to another backend must fail before submission")

    monkeypatch.setattr(httpx, "Client", FakeClient)
    monkeypatch.setattr(readiness, "_submit_target_stage", unexpected_submission)

    result = run_target_pair_journey(
        tmp_path,
        "http://127.0.0.1:8000/agentos",
        "http://127.0.0.1:4173",
        {
            "SAMURAI_TEST_DATABASE_URL": (
                "postgresql://owner:secret@127.0.0.1:54329/samurai_task10"
            ),
            "SAMURAI_TEST_TARGET_SCHEMA": "task6_queue_task10target_unit",
            "SAMURAI_TEST_BFF_OWNER": "iap:task10-local",
            "SAMURAI_TEST_IAP_ASSERTION": "task10-local-assertion",
        },
    )

    assert result.status is CaseStatus.FAILED
    evidence = cast(
        "dict[str, object]",
        json.loads((tmp_path / "target-pair-journey.json").read_text(encoding="utf-8")),
    )
    assert evidence["bff_backend_resolves_to_supplied_base_url"] is False


def test_provider_guard_fails_closed_and_counts_detected_access(tmp_path: Path) -> None:
    _ = (tmp_path / "process.log").write_text(
        "Error from Gemini API: invalid fixture key",
        encoding="utf-8",
    )

    guard = verify_provider_guard(tmp_path)
    result = build_result(("provider_guard",), (guard,))

    assert guard.status is CaseStatus.FAILED
    assert result.status is CaseStatus.FAILED
    assert result.provider_calls == 1


def test_browser_evidence_requires_network_state_screenshot_and_cleanup(tmp_path: Path) -> None:
    task7 = tmp_path / ".omo/evidence/readiness/task-7"
    browser_fixture = tmp_path / ".omo/evidence/readiness/task-10/browser-fixture"
    task7.mkdir(parents=True)
    browser_fixture.mkdir(parents=True)
    session_id, run_id, company_id = uuid4(), uuid4(), uuid4()
    screenshot = task7 / "desktop-research-approval.jpg"
    _ = screenshot.write_bytes(b"browser pixels")
    network = task7 / "task10-approval-network.log"
    network_payload = "".join(
        (
            "POST /agentos/agents/samurai/runs\n",
            "POST /agentos/agents/samurai/runs\n",
            f"GET /agentos/agents/samurai/runs/{run_id}?session_id={session_id}\n",
        )
    )
    _ = network.write_text(
        network_payload,
        encoding="utf-8",
    )
    canonical = browser_fixture / "canonical-state.json"
    _ = canonical.write_text(
        json.dumps(
            {
                "parent_session_id": str(session_id),
                "run_id": str(run_id),
                "company_id": str(company_id),
                "revision": 2,
                "artifact_types": ["intake", "research"],
                "artifact_statuses": ["complete", "complete"],
            }
        ),
        encoding="utf-8",
    )
    cleanup = browser_fixture / "cleanup.json"
    _ = cleanup.write_text(
        json.dumps(
            {
                "port_18008_listener": False,
                "schema_remaining": 0,
                "exact_fixture_cleanup": True,
            }
        ),
        encoding="utf-8",
    )
    manifest = {
        "parent_session_id": str(session_id),
        "final_run_id": str(run_id),
        "company_id": str(company_id),
        "canonical_revision": 2,
        "canonical_artifacts": ["intake:complete", "research:complete"],
        "network": {
            "raw_log": str(network.relative_to(tmp_path)),
            "logical_submission_posts_total": 2,
            "submission_replay_posts_after_reload": 0,
            "final_run_gets_after_reload": 1,
        },
        "browser": {
            "console_warnings_or_errors": [],
            "result_observed": [
                "Research evidence",
                "Research completed",
                "Verify evidence completed",
            ],
            "reload_preserved_result": True,
            "screenshot": str(screenshot.relative_to(tmp_path)),
            "screenshot_sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
        },
        "backend_evidence": {
            "canonical_state": str(canonical.relative_to(tmp_path)),
            "cleanup": str(cleanup.relative_to(tmp_path)),
        },
        "credentials_included": False,
    }
    _ = (task7 / "task10-browser-manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    result = run_browser_evidence(tmp_path)

    assert result.status is CaseStatus.PASSED


def test_terminal_browser_evidence_requires_visible_states_cleanup_and_no_credentials(
    tmp_path: Path,
) -> None:
    task7 = tmp_path / ".omo/evidence/readiness/task-7"
    task6 = tmp_path / ".omo/evidence/readiness/task-6/browser-fixtures"
    fixtures = task7 / "terminal-fixtures"
    task7.mkdir(parents=True)
    task6.mkdir(parents=True)
    fixtures.mkdir()
    source_hashes: dict[str, str] = {}
    for name in (
        "frontend/src/agentos.ts",
        "frontend/src/agentos.test.ts",
        "frontend/server/production.mjs",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(name, encoding="utf-8")
        source_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    cases = [
        {
            "case_id": "expired-iap-visible-no-replay",
            "visible_state": "HTTP 401 JSON: Google authentication required.",
            "http_status": 401,
            "submission_post_count": 0,
            "resume_post_count": 0,
            "upstream_request_count": 0,
            "artifacts": {
                "screenshot": "expired.jpg",
                "dom": "expired.md",
                "browser_network": "expired-browser.log",
                "server_network": "expired-server.log",
                "console": "expired-console.log",
            },
        },
        {
            "case_id": "second-replica-cancel-terminal-reload",
            "visible_state": "Researcher: The backend acknowledged cancellation.",
            "authoritative_receipt": "CANCELLED, attempt 1 of 2",
            "submission_post_count": 0,
            "resume_post_count": 0,
            "receipt_get_count": 1,
            "saved_run_get_count": 1,
            "console_error_count": 0,
            "artifacts": {
                "screenshot": "cancelled.jpg",
                "dom": "cancelled.md",
                "browser_network": "cancelled-browser.log",
                "bff_upstream_network": "cancelled-server.log",
                "console": "cancelled-console.log",
            },
        },
        {
            "case_id": "retry-exhaustion-terminal-reload",
            "visible_state": (
                "Backend status: work stopped after the allowed attempts; "
                "Researcher: The backend run failed."
            ),
            "authoritative_receipt": (
                "ERROR, attempt 2 of 2, sanitized failure_reason="
                "work stopped after the allowed attempts"
            ),
            "submission_post_count": 0,
            "resume_post_count": 0,
            "receipt_get_count": 1,
            "saved_run_get_count": 1,
            "console_error_count": 0,
            "artifacts": {
                "screenshot": "exhausted.jpg",
                "dom": "exhausted.md",
                "browser_network": "exhausted-browser.log",
                "bff_upstream_network": "exhausted-server.log",
                "console": "exhausted-console.log",
            },
        },
    ]
    for case in cases:
        artifacts = cast("dict[str, str]", case["artifacts"])
        for kind, name in artifacts.items():
            path = task7 / name
            if kind == "screenshot":
                _ = path.write_bytes(b"\xff\xd8\xffpixels")
            else:
                _ = path.write_text(str(case["visible_state"]), encoding="utf-8")
    cleanup = task6 / "cleanup.json"
    _ = cleanup.write_text('{"clean":true}', encoding="utf-8")
    for name in ("frontend.log", "bff.log"):
        _ = (task7 / name).write_text("passed", encoding="utf-8")
    for name in ("cancelled-fixture.json", "exhausted-fixture.json", "cleanup.json"):
        _ = (fixtures / name).write_text('{"credentials_included":false}', encoding="utf-8")
    manifest = {
        "source_hashes": source_hashes,
        "cases": cases,
        "regression": {
            "frontend_tests": "93 passed",
            "bff_tests": "46 passed",
            "frontend_check": "frontend.log",
            "bff_check": "bff.log",
        },
        "cleanup": {
            "browser_tabs_closed": True,
            "production_bff_port_4178_closed": True,
            "backend_fixture_cleanup": "../task-6/browser-fixtures/cleanup.json",
            "backend_fixture_cleanup_sha256": hashlib.sha256(cleanup.read_bytes()).hexdigest(),
            "backend_fixture_ports_closed": [18009, 18010],
            "remaining_fixture_schemas": [],
        },
    }
    _ = (task7 / "final-browser-failure-manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    assert run_terminal_browser_evidence(tmp_path).status is CaseStatus.PASSED

    _ = (fixtures / "cancelled-fixture.json").write_text(
        '{"bearer_token":"eyJcredential"}',
        encoding="utf-8",
    )
    assert run_terminal_browser_evidence(tmp_path).status is CaseStatus.FAILED


def test_process_recovery_runs_frozen_task6_node_and_requires_fresh_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[list[str], Path, dict[str, str]]] = []

    def fake_run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        cwd = cast("Path", options["cwd"])
        environment = cast("dict[str, str]", options["env"])
        calls.append((command, cwd, environment))
        artifact = {
            "external_provider_calls": 0,
            "provider_guard": "local deterministic model",
            "recovery": {
                "terminal": {"status": "COMPLETED", "attempt": 2, "max_attempts": 2},
                "run_completed": True,
            },
            "exhaustion": {
                "terminal": {"status": "ERROR", "attempt": 2, "max_attempts": 2},
                "third_model_invocation": False,
            },
        }
        _ = (tmp_path / "recovery.json").write_text(
            json.dumps(artifact),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=("1 passed postgresql://secret@127.0.0.1/db task10-local-assertion"),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_process_recovery(
        tmp_path,
        {
            "SAMURAI_TEST_DATABASE_URL": "postgresql://secret@127.0.0.1/db",
            "SAMURAI_TEST_REDIS_URL": "redis://127.0.0.1:6379/0",
            "SAMURAI_TEST_IAP_ASSERTION": "task10-local-assertion",
        },
    )

    assert result.status is CaseStatus.PASSED
    assert calls[0][0][-1].endswith(
        "test_native_queue_recovers_once_replays_sse_and_exhausts_after_second_kill"
    )
    assert calls[0][1].name == "backend"
    assert "GOOGLE_API_KEY" not in calls[0][2]
    log = (tmp_path / "process-recovery.log").read_text(encoding="utf-8")
    assert "secret" not in log
    assert "task10-local-assertion" not in log
    assert "[REDACTED_SERVICE_URL]" in log
    assert "[REDACTED_TEST_ASSERTION]" in log


def test_process_recovery_blocks_without_disposable_service_urls(tmp_path: Path) -> None:
    result = run_process_recovery(tmp_path, {})

    assert result.status is CaseStatus.BLOCKED
    assert result.observable == "disposable PostgreSQL and Redis URLs are required"


def test_post_commit_recovery_requires_its_own_fresh_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_run(command: list[str], **_options: object) -> subprocess.CompletedProcess[str]:
        proof = {
            "external_provider_calls": 0,
            "provider_guard": "local deterministic model",
            "terminal_receipt": {"status": "COMPLETED", "attempt": 2, "max_attempts": 2},
            "committed_revision": 1,
            "retained_revision": 1,
            "committed_artifact_ids": ["artifact-1"],
            "retained_artifact_ids": ["artifact-1"],
        }
        _ = (tmp_path / "post-commit.json").write_text(json.dumps(proof), encoding="utf-8")
        assert command[-1].endswith(
            "test_native_retry_reuses_child_commit_after_pre_ack_process_kill"
        )
        return subprocess.CompletedProcess(command, 0, stdout="1 passed", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_post_commit_recovery(
        tmp_path,
        {
            "SAMURAI_TEST_DATABASE_URL": "postgresql://secret@127.0.0.1/db",
            "SAMURAI_TEST_REDIS_URL": "redis://127.0.0.1:6379/0",
        },
    )

    assert result.status is CaseStatus.PASSED
    assert result.artifact == "post-commit.json"


def test_ignored_env_maps_service_urls_without_overriding_explicit_values(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    database_line = "SAMURAI_TEST_DATABASE_URL=postgresql://ignored-secret@127.0.0.1/samurai"
    redis_line = "SAMURAI_TEST_REDIS_URL=redis://127.0.0.1:16379/0"
    _ = env_file.write_text(
        f"{database_line}\n{redis_line}\n",
        encoding="utf-8",
    )

    mapped = load_environment(
        {
            "PATH": "/usr/bin",
            "GOOGLE_API_KEY": "must-not-reach-subprocess",
            "DATABASE_URL": "postgresql://ambient-secret@127.0.0.1/production",
            "SAMURAI_TEST_DATABASE_URL": "postgresql://explicit@127.0.0.1/test",
        },
        env_file,
    )

    assert mapped["SAMURAI_TEST_DATABASE_URL"] == "postgresql://explicit@127.0.0.1/test"
    assert mapped["SAMURAI_TEST_REDIS_URL"] == "redis://127.0.0.1:16379/0"
    assert mapped["PATH"] == "/usr/bin"
    assert "GOOGLE_API_KEY" not in mapped
    assert "DATABASE_URL" not in mapped


def test_generic_or_non_disposable_service_urls_are_never_selected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mapped = load_environment(
        {
            "PATH": "/usr/bin",
            "DATABASE_URL": "postgresql://owner:secret@db.example/production",
            "REDIS_URL": "rediss://cache.example/0",
        },
        tmp_path / "missing.env",
    )

    assert "SAMURAI_TEST_DATABASE_URL" not in mapped
    assert "SAMURAI_TEST_REDIS_URL" not in mapped

    def unexpected_network(*_args: object, **_kwargs: object) -> None:
        pytest.fail("invalid service URLs must be rejected before network or subprocess access")

    monkeypatch.setattr(httpx, "get", unexpected_network)
    monkeypatch.setattr(subprocess, "run", unexpected_network)
    arguments = Namespace(
        mode="local",
        base_url="http://127.0.0.1:8000/agentos",
        frontend_url="http://127.0.0.1:4173",
        evidence_dir=tmp_path,
    )
    with pytest.raises(RunnerError, match="disposable loopback test services"):
        _ = run(
            cast("_Arguments", arguments),
            {
                "SAMURAI_TEST_DATABASE_URL": "postgresql://owner:secret@db.example/prod",
                "SAMURAI_TEST_REDIS_URL": "rediss://cache.example/0",
            },
        )


def test_disposable_service_urls_require_loopback_and_test_database_prefix() -> None:
    validate_disposable_services(
        {
            "SAMURAI_TEST_DATABASE_URL": (
                "postgresql+psycopg://owner:secret@127.0.0.1:54329/samurai_task10"
            ),
            "SAMURAI_TEST_REDIS_URL": "redis://127.0.0.1:16379/0",
            "SAMURAI_TEST_TARGET_SCHEMA": "task6_queue_task10target_unit",
            "SAMURAI_TEST_BFF_OWNER": "iap:task10-local",
            "SAMURAI_TEST_IAP_ASSERTION": "task10-local-assertion",
        }
    )


def test_domain_fixtures_run_real_workflow_nodes_without_provider_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_run(command: list[str], **_options: object) -> subprocess.CompletedProcess[str]:
        assert any("approved_stages_resume" in part for part in command)
        assert any("invalid_research_stops" in part for part in command)
        return subprocess.CompletedProcess(command, 0, stdout="4 passed", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    staged, unsupported = run_domain_fixtures(tmp_path, {})

    assert staged.name == "domain_staged_journey"
    assert unsupported.name == "domain_unsupported_research"
    assert staged.status is CaseStatus.PASSED
    assert unsupported.status is CaseStatus.PASSED
    assert staged.artifact == unsupported.artifact == "domain-fixtures.log"


def test_contract_fixtures_cover_iap_and_owner_rejection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_options: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="passed", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    identity, owner = run_contract_fixtures(tmp_path, {})

    assert identity.status is CaseStatus.PASSED
    assert owner.status is CaseStatus.PASSED
    assert calls[0] == ["npm", "--prefix", "frontend", "run", "test:server"]
    assert calls[1][-1].endswith("test_receipt_http_uses_jwt_owner_and_hides_raw_failure")


def test_queue_safety_runner_requires_semantic_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first_run, second_run = uuid4(), uuid4()

    def fake_run(command: list[str], **_options: object) -> subprocess.CompletedProcess[str]:
        receipts = {
            "status": "COMPLETED",
            "attempt": 1,
            "max_attempts": 2,
        }
        payloads = {
            "idempotency.json": {
                "first_status": 202,
                "identical_replay_status": 202,
                "identical_replay_run_id": str(first_run),
                "changed_payload_status": 409,
                "second_status": 202,
                "first_receipt": {**receipts, "run_id": str(first_run)},
                "second_receipt": {**receipts, "run_id": str(second_run)},
                "cross_owner_receipt": None,
                "cross_session_receipt": None,
                "model_invocation_count": 2,
            },
            "cancellation.json": {
                "cancel_http_status": 200,
                "running": {**receipts, "status": "RUNNING", "run_id": str(first_run)},
                "terminal": {**receipts, "status": "CANCELLED", "run_id": str(first_run)},
                "after_replacement": {
                    **receipts,
                    "status": "CANCELLED",
                    "run_id": str(first_run),
                },
                "replacement_model_invoked": False,
                "child_session_created": False,
            },
            "provider-guard.json": {
                "accepted_status": 202,
                "terminal": {"status": "ERROR", "attempt": 2, "max_attempts": 2},
                "attempt_after_settle": 2,
                "external_provider_calls": 0,
            },
        }
        for name, payload in payloads.items():
            _ = (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")
        assert len(command) == 7
        return subprocess.CompletedProcess(command, 0, stdout="3 passed", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    results = run_queue_safety_cases(
        tmp_path,
        {
            "SAMURAI_TEST_DATABASE_URL": "postgresql://owner:secret@127.0.0.1/db",
            "SAMURAI_TEST_REDIS_URL": "redis://127.0.0.1:6379/0",
        },
    )

    assert [result.status for result in results] == [CaseStatus.PASSED] * 3


def test_http_journey_runner_requires_semantic_process_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        environment = cast("dict[str, str]", options["env"])
        evidence = Path(environment["SAMURAI_READINESS_HTTP_EVIDENCE"])
        payload = {
            "external_provider_calls": 0,
            "provider_guard": "local deterministic models",
            "staged": {
                "company_id": str(uuid4()),
                "revisions": [1, 2, 3, 5],
                "artifact_types": [
                    "intake",
                    "research",
                    "strategy",
                    "product_plan",
                    "verification",
                ],
            },
            "unsupported": {
                "company_id": str(uuid4()),
                "revision": 2,
                "artifact_types": ["intake", "research"],
            },
        }
        _ = evidence.write_text(json.dumps(payload), encoding="utf-8")
        assert command[-1].endswith(
            "test_readiness_http_runs_approved_stages_and_unsupported_research"
        )
        return subprocess.CompletedProcess(command, 0, stdout="1 passed", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    staged, unsupported = run_http_journeys(
        tmp_path,
        {
            "SAMURAI_TEST_DATABASE_URL": "postgresql://secret@127.0.0.1/db",
            "SAMURAI_TEST_REDIS_URL": "redis://127.0.0.1:6379/0",
        },
    )

    assert staged.status is CaseStatus.PASSED
    assert unsupported.status is CaseStatus.PASSED
    assert staged.artifact == unsupported.artifact == "http-journeys.json"


@dataclass(frozen=True, slots=True)
class _StageRequest:
    token: str
    session_id: str
    stage: str
    revision: int
    company_id: UUID | None


def _submit_stage(
    port: int,
    request: _StageRequest,
) -> WorkReceipt:
    submission_id = uuid4()
    headers = {
        "Authorization": f"Bearer {request.token}",
        "Idempotency-Key": str(submission_id),
    }
    if request.company_id is not None:
        headers.update(
            {
                "X-Samurai-Operation": "journey",
                "X-Samurai-Stage": request.stage,
                "X-Samurai-Expected-Revision": str(request.revision),
                "X-Samurai-Company-Id": str(request.company_id),
            }
        )
    with (
        httpx.Client(timeout=10) as client,
        client.stream(
            "POST",
            f"http://127.0.0.1:{port}/agentos/agents/samurai/runs",
            headers=headers,
            data={
                "message": f"Approve the {request.stage} stage",
                "session_id": request.session_id,
                "stream": "true",
                "background": "true",
            },
        ) as response,
    ):
        assert response.status_code == 200, response.text
    return _wait_for_receipt(
        port,
        request.token,
        request.session_id,
        submission_id,
        {"COMPLETED"},
    )


def _run_http_stage(
    base_environment: dict[str, str],
    request: _StageRequest,
    research_mode: str,
    tmp_path: Path,
) -> WorkReceipt:
    port = _free_port()
    environment = {
        **base_environment,
        "SAMURAI_READINESS_STAGE": request.stage,
        "SAMURAI_READINESS_RESEARCH_MODE": research_mode,
    }
    process, log = start_test_process(
        port,
        environment,
        tmp_path / f"{request.session_id}-{request.stage}.log",
        factory="tests.readiness_process_app:create_readiness_process_app",
    )
    try:
        return _submit_stage(port, request)
    finally:
        stop_test_process(process, log, kill=False)


def test_readiness_http_runs_approved_stages_and_unsupported_research(
    queue_environment: tuple[dict[str, str], str, str, str],
    tmp_path: Path,
) -> None:
    base_environment, token, database_url, schema = queue_environment
    staged_session = f"staged-{uuid4()}"
    staged_receipt: WorkReceipt | None = None
    staged_revisions: list[int] = []
    for stage in ("brief", "research", "strategy", "plan"):
        revision = 0 if staged_receipt is None else staged_receipt.revision
        assert revision is not None
        staged_receipt = _run_http_stage(
            base_environment,
            _StageRequest(
                token=token,
                session_id=staged_session,
                stage=stage,
                revision=revision,
                company_id=None if staged_receipt is None else staged_receipt.company_id,
            ),
            "supported",
            tmp_path,
        )
        assert staged_receipt.revision is not None
        staged_revisions.append(staged_receipt.revision)
    staged_state = _company_state(database_url, schema, "queue-founder", staged_session)
    assert [artifact.artifact_type for artifact in staged_state.artifacts] == [
        "intake",
        "research",
        "strategy",
        "product_plan",
        "verification",
    ]

    unsupported_session = f"unsupported-{uuid4()}"
    brief = _run_http_stage(
        base_environment,
        _StageRequest(
            token=token,
            session_id=unsupported_session,
            stage="brief",
            revision=0,
            company_id=None,
        ),
        "supported",
        tmp_path,
    )
    assert brief.revision == 1
    unsupported = _run_http_stage(
        base_environment,
        _StageRequest(
            token=token,
            session_id=unsupported_session,
            stage="research",
            revision=brief.revision,
            company_id=brief.company_id,
        ),
        "unsupported",
        tmp_path,
    )
    unsupported_state = _company_state(
        database_url,
        schema,
        "queue-founder",
        unsupported_session,
    )
    assert [artifact.artifact_type for artifact in unsupported_state.artifacts] == [
        "intake",
        "research",
    ]
    evidence_path = os.environ.get("SAMURAI_READINESS_HTTP_EVIDENCE")
    if evidence_path:
        payload = {
            "external_provider_calls": 0,
            "provider_guard": "local deterministic models",
            "staged": {
                "company_id": str(staged_receipt.company_id),
                "revisions": staged_revisions,
                "artifact_types": [artifact.artifact_type for artifact in staged_state.artifacts],
            },
            "unsupported": {
                "company_id": str(unsupported.company_id),
                "revision": unsupported.revision,
                "artifact_types": [
                    artifact.artifact_type for artifact in unsupported_state.artifacts
                ],
            },
        }
        evidence = Path(evidence_path)
        evidence.parent.mkdir(parents=True, exist_ok=True)
        _ = evidence.write_text(json.dumps(payload, indent=2), encoding="utf-8")
