"""Run provider-free readiness checks and record only directly observed results."""

# allow: SIZE_OK — task-scoped acceptance CLI; split if production runtime behavior is added.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final, Literal, override
from urllib.parse import unquote, urlsplit

import httpx
from dotenv import dotenv_values
from pydantic import UUID4, BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

type Mode = Literal["local", "provider"]

BACKEND_SOURCE: Final = Path(__file__).parents[1] / "src"
if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))

TOTAL_ATTEMPTS: Final = 2
HTTP_OK: Final = 200
HTTP_ACCEPTED: Final = 202
HTTP_CONFLICT: Final = 409
HTTP_UNAUTHORIZED: Final = 401
HTTP_FORBIDDEN: Final = 403
HTTP_NOT_FOUND: Final = 404
MIN_REDACTION_LENGTH: Final = 4
MIN_TEST_ASSERTION_LENGTH: Final = 16
PROBE_SUBMISSION_ID: Final = "00000000-0000-4000-8000-000000000010"
SAFE_ENVIRONMENT_KEYS: Final = frozenset(
    {"LANG", "LC_ALL", "PATH", "PYTHONPATH", "TEMP", "TMP", "TMPDIR", "TZ", "VIRTUAL_ENV"}
)
PROCESS_NODE: Final = (
    "tests/test_queue_process.py::"
    "test_native_queue_recovers_once_replays_sse_and_exhausts_after_second_kill"
)
POST_COMMIT_NODE: Final = (
    "tests/test_queue_process.py::test_native_retry_reuses_child_commit_after_pre_ack_process_kill"
)
DOMAIN_NODES: Final = (
    "tests/test_company_workflow.py::test_complete_company_journey_persists_verified_ordered_lineage",
    "tests/test_company_workflow.py::test_approved_stages_resume_the_same_retained_company",
    "tests/test_company_workflow.py::test_invalid_research_stops_before_strategy",
)
OWNER_NODE: Final = (
    "tests/test_queue_runtime.py::test_receipt_http_uses_jwt_owner_and_hides_raw_failure"
)
HTTP_JOURNEY_NODE: Final = (
    "tests/test_verify_readiness.py::"
    "test_readiness_http_runs_approved_stages_and_unsupported_research"
)
QUEUE_SAFETY_NODES: Final = (
    "tests/test_queue_process.py::test_native_http_idempotency_is_scoped_by_owner_and_rejects_changed_payload",
    "tests/test_queue_process.py::test_native_cancel_from_second_replica_reaches_terminal_without_child_artifacts",
    "tests/test_queue_process.py::test_unexpected_provider_stream_fails_locally_before_network",
)
REQUIRED_CASES: Final = (
    "local_endpoints",
    "target_pair_journey",
    "provider_guard",
    "provider_runtime_guard",
    "process_recovery",
    "post_commit_recovery",
    "domain_staged_journey",
    "domain_unsupported_research",
    "staged_journey",
    "unsupported_research",
    "duplicate_submission",
    "cancelled_job",
    "invalid_identity",
    "owner_isolation",
    "receipt_reconnect",
    "browser_reload",
    "browser_terminal_states",
)


class CaseStatus(StrEnum):
    """One directly observed acceptance outcome."""

    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class _Failure(StrEnum):
    LOCAL_URL = "local mode requires a loopback HTTP URL"
    PROVIDER_MODE = "provider mode is refused by this provider-free runner"
    TEST_SERVICES = "local mode requires explicit disposable loopback test services"


class CaseResult(BaseModel):
    """Sanitized result for one required scenario."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    name: str
    status: CaseStatus
    observable: str
    artifact: str | None = None


class ReadinessResult(BaseModel):
    """Compact acceptance record that fails closed for absent cases."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    mode: str = "local-provider-free"
    status: CaseStatus
    provider_calls: int = 0
    cases: dict[str, CaseResult]


class _ReceiptProof(BaseModel):
    status: str
    attempt: int
    max_attempts: int


class _RecoveryLeg(BaseModel):
    terminal: _ReceiptProof
    run_completed: bool


class _ExhaustionLeg(BaseModel):
    terminal: _ReceiptProof
    third_model_invocation: bool


class _RecoveryProof(BaseModel):
    recovery: _RecoveryLeg
    exhaustion: _ExhaustionLeg


class _PostCommitProof(BaseModel):
    external_provider_calls: Literal[0]
    provider_guard: str
    terminal_receipt: _ReceiptProof
    committed_revision: int
    retained_revision: int
    committed_artifact_ids: list[str]
    retained_artifact_ids: list[str]


class _StagedJourneyProof(BaseModel):
    company_id: UUID4
    revisions: list[int]
    artifact_types: list[str]


class _UnsupportedJourneyProof(BaseModel):
    company_id: UUID4
    revision: int
    artifact_types: list[str]


class _HttpJourneyProof(BaseModel):
    external_provider_calls: Literal[0]
    provider_guard: str
    staged: _StagedJourneyProof
    unsupported: _UnsupportedJourneyProof


class _BrowserNetworkProof(BaseModel):
    raw_log: str
    logical_submission_posts_total: int
    submission_replay_posts_after_reload: int
    final_run_gets_after_reload: int


class _BrowserObservationProof(BaseModel):
    console_warnings_or_errors: list[str]
    result_observed: list[str]
    reload_preserved_result: bool
    screenshot: str
    screenshot_sha256: str


class _BrowserBackendEvidence(BaseModel):
    canonical_state: str
    cleanup: str


class _BrowserManifest(BaseModel):
    parent_session_id: UUID4
    final_run_id: UUID4
    company_id: UUID4
    canonical_revision: int
    canonical_artifacts: list[str]
    network: _BrowserNetworkProof
    browser: _BrowserObservationProof
    backend_evidence: _BrowserBackendEvidence
    credentials_included: bool


class _CanonicalBrowserState(BaseModel):
    parent_session_id: UUID4
    run_id: UUID4
    company_id: UUID4
    revision: int
    artifact_types: list[str]
    artifact_statuses: list[str]


class _BrowserCleanupProof(BaseModel):
    port_18008_listener: bool
    schema_remaining: int
    exact_fixture_cleanup: bool


class _TerminalBrowserCase(BaseModel):
    case_id: str
    visible_state: str
    authoritative_receipt: str | None = None
    http_status: int | None = None
    submission_post_count: int
    resume_post_count: int
    receipt_get_count: int = 0
    saved_run_get_count: int = 0
    upstream_request_count: int | None = None
    console_error_count: int = 0
    artifacts: dict[str, str]


class _TerminalBrowserRegression(BaseModel):
    frontend_tests: Literal["93 passed"]
    bff_tests: Literal["46 passed"]
    frontend_check: str
    bff_check: str


class _TerminalBrowserCleanup(BaseModel):
    browser_tabs_closed: Literal[True]
    production_bff_port_4178_closed: Literal[True]
    backend_fixture_cleanup: str
    backend_fixture_cleanup_sha256: str
    backend_fixture_ports_closed: list[int]
    remaining_fixture_schemas: list[str]


class _TerminalBrowserManifest(BaseModel):
    source_hashes: dict[str, str]
    cases: list[_TerminalBrowserCase]
    regression: _TerminalBrowserRegression
    cleanup: _TerminalBrowserCleanup


class _RunReceiptProof(_ReceiptProof):
    run_id: UUID4


class _CancellationProof(BaseModel):
    cancel_http_status: int
    running: _RunReceiptProof
    terminal: _RunReceiptProof
    after_replacement: _RunReceiptProof
    replacement_model_invoked: bool
    child_session_created: bool


class _IdempotencyProof(BaseModel):
    first_status: int
    identical_replay_status: int
    identical_replay_run_id: UUID4
    changed_payload_status: int
    second_status: int
    first_receipt: _RunReceiptProof
    second_receipt: _RunReceiptProof
    cross_owner_receipt: None
    cross_session_receipt: None
    model_invocation_count: int


class _ProviderRuntimeProof(BaseModel):
    accepted_status: int
    terminal: _ReceiptProof
    attempt_after_settle: int
    external_provider_calls: Literal[0]


class _TargetReceipt(BaseModel):
    status: str
    run_id: UUID4
    company_id: UUID4
    revision: int


class _TargetConnection(BaseModel):
    backend: str
    configured: Literal[True]
    auth: Literal["jwt"]
    storage_namespace: str = Field(alias="storageNamespace")


@dataclass(frozen=True, slots=True)
class RunnerError(Exception):
    """A safe refusal that contains no credential values."""

    reason: _Failure

    @override
    def __str__(self) -> str:
        return self.reason


class _Arguments(argparse.Namespace):
    mode: Mode = "local"
    base_url: str = ""
    frontend_url: str = ""
    evidence_dir: Path = Path()


def _arguments() -> _Arguments:
    parser = argparse.ArgumentParser(
        description="Verify Samurai readiness with provider-free local fixtures.",
    )
    _ = parser.add_argument(
        "--mode",
        choices=("local", "provider"),
        default="local",
        help="local is provider-free; provider mode is always refused",
    )
    _ = parser.add_argument("--base-url", required=True, help="Loopback AgentOS base URL")
    _ = parser.add_argument("--frontend-url", required=True, help="Loopback production BFF URL")
    _ = parser.add_argument("--evidence-dir", required=True, type=Path)
    return parser.parse_args(namespace=_Arguments())


def validate_local_url(value: str) -> str:
    """Accept only uncredentialed loopback HTTP endpoints."""
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as error:
        raise RunnerError(_Failure.LOCAL_URL) from error
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise RunnerError(_Failure.LOCAL_URL)
    return value.rstrip("/")


def build_result(
    required_cases: Sequence[str],
    cases: Sequence[CaseResult],
) -> ReadinessResult:
    """Fill every required case and derive a fail-closed overall status."""
    observed = {case.name: case for case in cases}
    complete = {
        name: observed.get(
            name,
            CaseResult(
                name=name,
                status=CaseStatus.BLOCKED,
                observable="case was not executed",
            ),
        )
        for name in required_cases
    }
    statuses = {case.status for case in complete.values()}
    status = (
        CaseStatus.FAILED
        if CaseStatus.FAILED in statuses
        else CaseStatus.BLOCKED
        if CaseStatus.BLOCKED in statuses
        else CaseStatus.PASSED
    )
    provider_calls = (
        1
        if complete.get("provider_guard") is not None
        and complete["provider_guard"].status is CaseStatus.FAILED
        else 0
    )
    return ReadinessResult(status=status, provider_calls=provider_calls, cases=complete)


def write_result(result: ReadinessResult, evidence_dir: Path) -> None:
    """Write the sanitized compact result without credentials."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _ = (evidence_dir / "result.json").write_text(
        result.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def load_environment(environment: Mapping[str, str], env_file: Path) -> dict[str, str]:
    """Map ignored service settings into test-only names without exposing values."""
    mapped = {key: environment[key] for key in SAFE_ENVIRONMENT_KEYS if key in environment}
    mapped["CI"] = "1"
    values = dotenv_values(env_file) if env_file.is_file() else {}
    for source, target in (
        ("SAMURAI_TEST_DATABASE_URL", "SAMURAI_TEST_DATABASE_URL"),
        ("SAMURAI_TEST_REDIS_URL", "SAMURAI_TEST_REDIS_URL"),
        ("SAMURAI_TEST_TARGET_SCHEMA", "SAMURAI_TEST_TARGET_SCHEMA"),
        ("SAMURAI_TEST_BFF_OWNER", "SAMURAI_TEST_BFF_OWNER"),
        ("SAMURAI_TEST_IAP_ASSERTION", "SAMURAI_TEST_IAP_ASSERTION"),
    ):
        value = environment.get(source) or values.get(source)
        if target not in mapped and isinstance(value, str) and value:
            mapped[target] = value
    return mapped


def _redact_output(payload: str, environment: Mapping[str, str]) -> str:
    redacted = payload
    for key in ("SAMURAI_TEST_DATABASE_URL", "SAMURAI_TEST_REDIS_URL"):
        value = environment.get(key)
        if value:
            redacted = redacted.replace(value, "[REDACTED_SERVICE_URL]")
            parsed = urlsplit(value)
            for credential in (parsed.username, parsed.password):
                if credential and len(credential) >= MIN_REDACTION_LENGTH:
                    redacted = redacted.replace(unquote(credential), "[REDACTED_CREDENTIAL]")
    assertion = environment.get("SAMURAI_TEST_IAP_ASSERTION")
    if assertion:
        redacted = redacted.replace(assertion, "[REDACTED_TEST_ASSERTION]")
    return redacted


def validate_disposable_services(environment: Mapping[str, str]) -> None:
    """Reject service URLs that are not explicit loopback disposable resources."""
    database_url = environment.get("SAMURAI_TEST_DATABASE_URL", "")
    redis_url = environment.get("SAMURAI_TEST_REDIS_URL", "")
    target_schema = environment.get("SAMURAI_TEST_TARGET_SCHEMA", "")
    bff_owner = environment.get("SAMURAI_TEST_BFF_OWNER", "")
    iap_assertion = environment.get("SAMURAI_TEST_IAP_ASSERTION", "")
    try:
        database = urlsplit(database_url)
        redis = urlsplit(redis_url)
        database_name = database.path.removeprefix("/")
        redis_database = redis.path.removeprefix("/")
        valid = (
            database.scheme in {"postgresql", "postgresql+psycopg"}
            and database.hostname in {"127.0.0.1", "localhost", "::1"}
            and database.port is not None
            and database_name.startswith("samurai_task")
            and not database.fragment
            and redis.scheme == "redis"
            and redis.hostname in {"127.0.0.1", "localhost", "::1"}
            and redis.port is not None
            and redis_database.isdigit()
            and not redis.fragment
            and target_schema.startswith("task6_queue_task10target_")
            and target_schema.replace("_", "").isalnum()
            and bff_owner == "iap:task10-local"
            and len(iap_assertion) >= MIN_TEST_ASSERTION_LENGTH
        )
    except ValueError:
        valid = False
    if not valid:
        raise RunnerError(_Failure.TEST_SERVICES)


def _require_target(*, condition: bool) -> None:
    if not condition:
        raise ValueError


def _target_receipt(
    client: httpx.Client,
    frontend_url: str,
    submission_id: uuid.UUID,
    session_id: str,
) -> _TargetReceipt:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = client.get(
            f"{frontend_url}/api/agentos/work-receipts/{submission_id}",
            params={"session_id": session_id},
        )
        if response.status_code == HTTP_OK:
            receipt = _TargetReceipt.model_validate(response.json())
            if receipt.status in {"COMPLETED", "ERROR", "CANCELLED"}:
                return receipt
        elif response.status_code != HTTP_NOT_FOUND:
            _ = response.raise_for_status()
        time.sleep(0.1)
    message = "target receipt did not reach a terminal state"
    raise TimeoutError(message)


def _submit_target_stage(  # noqa: PLR0913 - fixed production BFF submission contract.
    client: httpx.Client,
    frontend_url: str,
    session_id: str,
    *,
    stage: str,
    company_id: uuid.UUID | None,
    revision: int,
) -> _TargetReceipt:
    submission_id = uuid.uuid4()
    headers = {"x-samurai-submission-id": str(submission_id)}
    if company_id is not None:
        headers.update(
            {
                "x-samurai-operation": "journey",
                "x-samurai-stage": stage,
                "x-samurai-expected-revision": str(revision),
                "x-samurai-company-id": str(company_id),
            }
        )
    message = (
        'Prepare only my company brief using stage="brief".'
        if stage == "brief"
        else "Research our market and stop before strategy."
    )
    with client.stream(
        "POST",
        f"{frontend_url}/api/agentos/agents/samurai/runs",
        headers=headers,
        data={
            "message": message,
            "session_id": session_id,
            "stream": "true",
            "background": "true",
        },
    ) as response:
        _ = response.raise_for_status()
        for _ in response.iter_bytes():
            pass
    return _target_receipt(client, frontend_url, submission_id, session_id)


def _canonical_target_state(
    database_url: str,
    schema: str,
    owner_id: str,
    session_id: str,
) -> tuple[uuid.UUID, int, list[str], list[str]]:
    from agno.db.base import SessionType  # noqa: PLC0415 - keep CLI help import-light.
    from agno.session.workflow import WorkflowSession  # noqa: PLC0415

    from samurai.contracts import CompanyState  # noqa: PLC0415
    from samurai.execution_state import SamuraiPostgresDb  # noqa: PLC0415
    from samurai.parent import child_session_id  # noqa: PLC0415

    database = SamuraiPostgresDb(id="readiness-target", db_url=database_url, db_schema=schema)
    try:
        session = database.get_session(
            child_session_id(owner_id, session_id),
            session_type=SessionType.WORKFLOW,
            user_id=owner_id,
        )
        if not isinstance(session, WorkflowSession) or session.session_data is None:
            raise ValueError
        state = CompanyState.model_validate(session.session_data["session_state"]["company"])
        return (
            state.context.company_id,
            state.current_revision,
            [artifact.artifact_type for artifact in state.artifacts],
            [artifact.status for artifact in state.artifacts],
        )
    finally:
        database.close()


def run_target_pair_journey(
    evidence_dir: Path,
    base_url: str,
    frontend_url: str,
    environment: Mapping[str, str],
) -> CaseResult:
    """Execute staged work through the supplied BFF and its canonical target database."""
    session_id = f"task10-target-{uuid.uuid4()}"
    owner_id = environment.get("SAMURAI_TEST_BFF_OWNER", "")
    brief: _TargetReceipt | None = None
    research: _TargetReceipt | None = None
    canonical: tuple[uuid.UUID, int, list[str], list[str]] | None = None
    try:
        with httpx.Client(
            headers={
                "x-samurai-client": "1",
                "origin": frontend_url,
                "x-goog-iap-jwt-assertion": environment["SAMURAI_TEST_IAP_ASSERTION"],
            },
            follow_redirects=False,
            timeout=40,
            trust_env=False,
        ) as client:
            connection_response = client.get(f"{frontend_url}/api/agentos/connection")
            _ = connection_response.raise_for_status()
            connection = _TargetConnection.model_validate_json(connection_response.content)
            expected_namespace = hashlib.sha256(owner_id.encode()).hexdigest()
            parsed_base = urlsplit(base_url)
            expected_backend = (
                f"{parsed_base.scheme}://{parsed_base.netloc}"
                if parsed_base.path == "/agentos"
                else ""
            )
            _require_target(
                condition=(
                    connection.backend == expected_backend
                    and f"{connection.backend}/agentos" == base_url
                    and connection.storage_namespace == expected_namespace
                )
            )
            brief = _submit_target_stage(
                client,
                frontend_url,
                session_id,
                stage="brief",
                company_id=None,
                revision=0,
            )
            research = _submit_target_stage(
                client,
                frontend_url,
                session_id,
                stage="research",
                company_id=brief.company_id,
                revision=brief.revision,
            )
        canonical = _canonical_target_state(
            environment["SAMURAI_TEST_DATABASE_URL"],
            environment["SAMURAI_TEST_TARGET_SCHEMA"],
            owner_id,
            session_id,
        )
        valid = (
            brief.status == research.status == "COMPLETED"
            and brief.company_id == research.company_id == canonical[0]
            and brief.revision == 1
            and research.revision == canonical[1] == TOTAL_ATTEMPTS
            and canonical[2] == ["intake", "research"]
            and canonical[3] == ["complete", "complete"]
        )
    except ImportError, KeyError, OSError, TimeoutError, ValueError, httpx.HTTPError:
        valid = False
    artifact_name = "target-pair-journey.json"
    payload: dict[str, object] = {
        "session_id": session_id,
        "status": "passed" if valid else "failed",
        "bff_backend_resolves_to_supplied_base_url": valid,
        "identity_mode": "local-fixed-verifier",
        "canonical_owner": owner_id,
        "stages": ["brief", "research"],
        "brief": (
            {
                "run_id": str(brief.run_id),
                "company_id": str(brief.company_id),
                "revision": brief.revision,
                "status": brief.status,
            }
            if valid and brief is not None
            else None
        ),
        "research": (
            {
                "run_id": str(research.run_id),
                "company_id": str(research.company_id),
                "revision": research.revision,
                "status": research.status,
            }
            if valid and research is not None
            else None
        ),
        "canonical": (
            {
                "company_id": str(canonical[0]),
                "revision": canonical[1],
                "artifact_types": canonical[2],
                "artifact_statuses": canonical[3],
            }
            if valid and canonical is not None
            else None
        ),
        "provider_calls": 0,
    }
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _ = (evidence_dir / artifact_name).write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return CaseResult(
        name="target_pair_journey",
        status=CaseStatus.PASSED if valid else CaseStatus.FAILED,
        observable=(
            "supplied BFF/backend accepted brief and research into one canonical company"
            if valid
            else "supplied BFF/backend staged journey failed canonical assertions"
        ),
        artifact=artifact_name,
    )


def probe_local_endpoints(base_url: str, frontend_url: str) -> CaseResult:
    """Require both operator-supplied loopback services to answer without redirects."""
    health_targets = (f"{base_url}/health", f"{frontend_url}/healthz")
    try:
        health_responses = tuple(
            httpx.get(
                target,
                follow_redirects=False,
                timeout=5,
                trust_env=False,
            )
            for target in health_targets
        )
        receipt_probe = f"{base_url}/work-receipts/{PROBE_SUBMISSION_ID}?session_id=task10-probe"
        backend_auth = httpx.get(
            receipt_probe,
            follow_redirects=False,
            timeout=5,
            trust_env=False,
        )
        frontend_auth = httpx.get(
            f"{frontend_url}/api/agentos/connection",
            headers={"x-samurai-client": "1"},
            follow_redirects=False,
            timeout=5,
            trust_env=False,
        )
    except httpx.HTTPError:
        health_responses = ()
        backend_auth = frontend_auth = None
    passed = (
        len(health_responses) == len(health_targets)
        and all(
            response.status_code == HTTP_OK and not response.is_redirect
            for response in health_responses
        )
        and backend_auth is not None
        and backend_auth.status_code in {HTTP_UNAUTHORIZED, HTTP_FORBIDDEN}
        and not backend_auth.is_redirect
        and frontend_auth is not None
        and frontend_auth.status_code == HTTP_UNAUTHORIZED
        and not frontend_auth.is_redirect
    )
    return CaseResult(
        name="local_endpoints",
        status=CaseStatus.PASSED if passed else CaseStatus.FAILED,
        observable=(
            "operator-supplied services passed health and unauthenticated owner/IAP rejection"
            if passed
            else (
                "operator-supplied backend or frontend health endpoint "
                "was unavailable or redirected"
            )
        ),
    )


def verify_provider_guard(evidence_dir: Path) -> CaseResult:
    """Fail if task-owned logs show that a real provider client was reached."""
    markers = ("Error from Gemini API", "generativelanguage.googleapis.com")
    detected_in: list[str] = []
    for path in evidence_dir.glob("*.log"):
        try:
            payload = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if any(marker in payload for marker in markers):
            detected_in.append(path.name)
    return CaseResult(
        name="provider_guard",
        status=CaseStatus.FAILED if detected_in else CaseStatus.PASSED,
        observable=(
            f"real provider access detected in {', '.join(sorted(detected_in))}"
            if detected_in
            else "task-owned subprocess logs contain no real provider access"
        ),
        artifact=detected_in[0] if detected_in else None,
    )


def run_browser_evidence(repository: Path) -> CaseResult:
    """Validate independent browser, network, canonical-state, and cleanup evidence."""
    manifest_path = repository / ".omo/evidence/readiness/task-7/task10-browser-manifest.json"
    artifact = ".omo/evidence/readiness/task-7/task10-browser-manifest.json"
    try:
        manifest = _BrowserManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        network_path = repository / manifest.network.raw_log
        screenshot_path = repository / manifest.browser.screenshot
        canonical_path = repository / manifest.backend_evidence.canonical_state
        cleanup_path = repository / manifest.backend_evidence.cleanup
        network = network_path.read_text(encoding="utf-8")
        canonical = _CanonicalBrowserState.model_validate_json(
            canonical_path.read_text(encoding="utf-8")
        )
        cleanup = _BrowserCleanupProof.model_validate_json(cleanup_path.read_text(encoding="utf-8"))
        screenshot_hash = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
        observed = set(manifest.browser.result_observed)
        valid = (
            not manifest.credentials_included
            and manifest.canonical_revision == canonical.revision == TOTAL_ATTEMPTS
            and manifest.company_id == canonical.company_id
            and manifest.parent_session_id == canonical.parent_session_id
            and manifest.final_run_id == canonical.run_id
            and manifest.canonical_artifacts == ["intake:complete", "research:complete"]
            and canonical.artifact_types == ["intake", "research"]
            and canonical.artifact_statuses == ["complete", "complete"]
            and manifest.network.logical_submission_posts_total == TOTAL_ATTEMPTS
            and manifest.network.submission_replay_posts_after_reload == 0
            and manifest.network.final_run_gets_after_reload == 1
            and network.splitlines().count("POST /agentos/agents/samurai/runs") == TOTAL_ATTEMPTS
            and str(manifest.final_run_id) in network
            and manifest.browser.reload_preserved_result
            and not manifest.browser.console_warnings_or_errors
            and {"Research evidence", "Research completed", "Verify evidence completed"} <= observed
            and screenshot_hash == manifest.browser.screenshot_sha256
            and screenshot_path.stat().st_size > 0
            and not cleanup.port_18008_listener
            and cleanup.schema_remaining == 0
            and cleanup.exact_fixture_cleanup
        )
    except OSError, ValueError:
        valid = False
    return CaseResult(
        name="browser_reload",
        status=CaseStatus.PASSED if valid else CaseStatus.FAILED,
        observable=(
            "browser research approval survived reload with two intended submissions and no replay"
            if valid
            else "browser evidence was missing, inconsistent, or failed cleanup checks"
        ),
        artifact=artifact,
    )


def run_terminal_browser_evidence(repository: Path) -> CaseResult:
    """Validate browser-visible identity, cancellation, and exhaustion evidence."""
    task7 = repository / ".omo/evidence/readiness/task-7"
    manifest_path = task7 / "final-browser-failure-manifest.json"
    artifact = ".omo/evidence/readiness/task-7/final-browser-failure-manifest.json"
    try:
        manifest = _TerminalBrowserManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        cases = {case.case_id: case for case in manifest.cases}
        expired = cases["expired-iap-visible-no-replay"]
        cancelled = cases["second-replica-cancel-terminal-reload"]
        exhausted = cases["retry-exhaustion-terminal-reload"]
        referenced = [
            task7 / value
            for case in (expired, cancelled, exhausted)
            for value in case.artifacts.values()
        ]
        frontend_logs = (
            task7 / manifest.regression.frontend_check,
            task7 / manifest.regression.bff_check,
        )
        cleanup_path = task7 / manifest.cleanup.backend_fixture_cleanup
        current_hashes = {
            name: hashlib.sha256((repository / name).read_bytes()).hexdigest()
            for name in manifest.source_hashes
        }
        cancelled_dom = (task7 / cancelled.artifacts["dom"]).read_text(encoding="utf-8")
        exhausted_dom = (task7 / exhausted.artifacts["dom"]).read_text(encoding="utf-8")
        evidence_payloads = [
            path.read_text(encoding="utf-8")
            for path in task7.rglob("*")
            if path.is_file() and path.suffix in {".json", ".log", ".md", ".txt"}
        ]
        valid = (
            set(cases)
            == {
                "expired-iap-visible-no-replay",
                "second-replica-cancel-terminal-reload",
                "retry-exhaustion-terminal-reload",
            }
            and manifest.source_hashes == current_hashes
            and all(path.is_file() and path.stat().st_size > 0 for path in referenced)
            and all(
                (task7 / case.artifacts["screenshot"]).read_bytes().startswith(b"\xff\xd8\xff")
                for case in (expired, cancelled, exhausted)
            )
            and expired.http_status == HTTP_UNAUTHORIZED
            and expired.submission_post_count
            == expired.resume_post_count
            == expired.upstream_request_count
            == 0
            and cancelled.authoritative_receipt == "CANCELLED, attempt 1 of 2"
            and "acknowledged cancellation" in cancelled.visible_state
            and exhausted.authoritative_receipt
            == (
                "ERROR, attempt 2 of 2, sanitized failure_reason="
                "work stopped after the allowed attempts"
            )
            and "work stopped after the allowed attempts" in exhausted.visible_state
            and all(
                case.receipt_get_count == case.saved_run_get_count == 1
                and case.submission_post_count
                == case.resume_post_count
                == case.console_error_count
                == 0
                for case in (cancelled, exhausted)
            )
            and "The backend acknowledged cancellation." in cancelled_dom
            and "The backend run failed." in exhausted_dom
            and "Backend status: work stopped after the allowed attempts" in exhausted_dom
            and manifest.cleanup.browser_tabs_closed
            and manifest.cleanup.production_bff_port_4178_closed
            and len(manifest.cleanup.backend_fixture_ports_closed) == TOTAL_ATTEMPTS
            and not manifest.cleanup.remaining_fixture_schemas
            and hashlib.sha256(cleanup_path.read_bytes()).hexdigest()
            == manifest.cleanup.backend_fixture_cleanup_sha256
            and all(path.is_file() and path.stat().st_size > 0 for path in frontend_logs)
            and not any(
                marker in payload
                for payload in evidence_payloads
                for marker in ('"bearer_token"', "eyJ")
            )
        )
    except KeyError, OSError, ValueError:
        valid = False
    return CaseResult(
        name="browser_terminal_states",
        status=CaseStatus.PASSED if valid else CaseStatus.FAILED,
        observable=(
            "browser rendered identity expiry, cancellation, and retry exhaustion without replay"
            if valid
            else (
                "terminal browser evidence was missing, stale, unsafe, or semantically inconsistent"
            )
        ),
        artifact=artifact,
    )


def run_queue_safety_cases(
    evidence_dir: Path,
    environment: Mapping[str, str],
) -> tuple[CaseResult, CaseResult, CaseResult]:
    """Run and semantically validate duplicate, cancellation, and provider guards."""
    names = ("duplicate_submission", "cancelled_job", "provider_runtime_guard")
    if not all(
        environment.get(name) for name in ("SAMURAI_TEST_DATABASE_URL", "SAMURAI_TEST_REDIS_URL")
    ):
        blocked = "disposable PostgreSQL and Redis URLs are required"
        return (
            CaseResult(name=names[0], status=CaseStatus.BLOCKED, observable=blocked),
            CaseResult(name=names[1], status=CaseStatus.BLOCKED, observable=blocked),
            CaseResult(name=names[2], status=CaseStatus.BLOCKED, observable=blocked),
        )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    artifacts = ("idempotency.json", "cancellation.json", "provider-guard.json")
    for artifact in artifacts:
        (evidence_dir / artifact).unlink(missing_ok=True)
    process_environment = dict(environment)
    process_environment["SAMURAI_QUEUE_EVIDENCE_DIR"] = str(evidence_dir.resolve())
    command = [sys.executable, "-m", "pytest", "-q", *QUEUE_SAFETY_NODES]
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and frozen test nodes.
        command,
        cwd=Path(__file__).parents[1],
        env=process_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    log_name = "queue-safety.log"
    _ = (evidence_dir / log_name).write_text(
        _redact_output(completed.stdout + completed.stderr, environment),
        encoding="utf-8",
    )
    duplicate_valid = cancellation_valid = provider_valid = False
    if completed.returncode == 0:
        try:
            duplicate = _IdempotencyProof.model_validate_json(
                (evidence_dir / artifacts[0]).read_text(encoding="utf-8")
            )
            cancellation = _CancellationProof.model_validate_json(
                (evidence_dir / artifacts[1]).read_text(encoding="utf-8")
            )
            provider = _ProviderRuntimeProof.model_validate_json(
                (evidence_dir / artifacts[2]).read_text(encoding="utf-8")
            )
            duplicate_valid = (
                duplicate.first_status
                == duplicate.identical_replay_status
                == duplicate.second_status
                == HTTP_ACCEPTED
                and duplicate.changed_payload_status == HTTP_CONFLICT
                and duplicate.identical_replay_run_id == duplicate.first_receipt.run_id
                and duplicate.first_receipt.run_id != duplicate.second_receipt.run_id
                and duplicate.first_receipt.status == duplicate.second_receipt.status == "COMPLETED"
                and duplicate.model_invocation_count == TOTAL_ATTEMPTS
            )
            cancellation_valid = (
                cancellation.cancel_http_status == HTTP_OK
                and cancellation.running.status == "RUNNING"
                and cancellation.terminal.status
                == cancellation.after_replacement.status
                == "CANCELLED"
                and cancellation.running.run_id
                == cancellation.terminal.run_id
                == cancellation.after_replacement.run_id
                and cancellation.terminal.attempt == 1
                and not cancellation.replacement_model_invoked
                and not cancellation.child_session_created
            )
            provider_valid = (
                provider.accepted_status == HTTP_ACCEPTED
                and provider.terminal.status == "ERROR"
                and provider.terminal.attempt
                == provider.terminal.max_attempts
                == provider.attempt_after_settle
                == TOTAL_ATTEMPTS
                and provider.external_provider_calls == 0
            )
        except OSError, ValueError:
            pass
    return (
        CaseResult(
            name=names[0],
            status=CaseStatus.PASSED if duplicate_valid else CaseStatus.FAILED,
            observable=(
                "identical replay returned the same run while changed payload was rejected"
                if duplicate_valid
                else "duplicate submission evidence failed semantic checks"
            ),
            artifact=artifacts[0] if duplicate_valid else log_name,
        ),
        CaseResult(
            name=names[1],
            status=CaseStatus.PASSED if cancellation_valid else CaseStatus.FAILED,
            observable=(
                "second-replica cancellation stayed terminal with no child or replacement model"
                if cancellation_valid
                else "cancellation evidence failed semantic checks"
            ),
            artifact=artifacts[1] if cancellation_valid else log_name,
        ),
        CaseResult(
            name=names[2],
            status=CaseStatus.PASSED if provider_valid else CaseStatus.FAILED,
            observable=(
                "unexpected provider stream failed locally through both bounded attempts"
                if provider_valid
                else "provider runtime guard evidence failed semantic checks"
            ),
            artifact=artifacts[2] if provider_valid else log_name,
        ),
    )


def run_process_recovery(
    evidence_dir: Path,
    environment: Mapping[str, str],
) -> CaseResult:
    """Run the frozen Task 6 process-death scenario as a fresh subprocess."""
    return _run_pytest_case(
        evidence_dir,
        environment,
        name="process_recovery",
        node=PROCESS_NODE,
        artifact="recovery.json",
        observable=(
            "fresh process death recovered on attempt 2 and exhaustion stopped at attempt 2"
        ),
    )


def run_post_commit_recovery(
    evidence_dir: Path,
    environment: Mapping[str, str],
) -> CaseResult:
    """Run the frozen Task 6 post-commit process-death scenario."""
    return _run_pytest_case(
        evidence_dir,
        environment,
        name="post_commit_recovery",
        node=POST_COMMIT_NODE,
        artifact="post-commit.json",
        observable="retry reused the accepted child commit without duplicating its artifact",
    )


def run_domain_fixtures(
    evidence_dir: Path,
    environment: Mapping[str, str],
) -> tuple[CaseResult, CaseResult]:
    """Run provider-free workflow fixtures for staged and unsupported outcomes."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "pytest", "-q", *DOMAIN_NODES]
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and frozen test nodes.
        command,
        cwd=Path(__file__).parents[1],
        env=dict(environment),
        check=False,
        capture_output=True,
        text=True,
    )
    log_name = "domain-fixtures.log"
    _ = (evidence_dir / log_name).write_text(
        _redact_output(completed.stdout + completed.stderr, environment),
        encoding="utf-8",
    )
    status = CaseStatus.PASSED if completed.returncode == 0 else CaseStatus.FAILED
    return (
        CaseResult(
            name="domain_staged_journey",
            status=status,
            observable="provider-free workflow retained one company across approved stages",
            artifact=log_name,
        ),
        CaseResult(
            name="domain_unsupported_research",
            status=status,
            observable="provider-free unsupported research stopped before strategy acceptance",
            artifact=log_name,
        ),
    )


def run_contract_fixtures(
    evidence_dir: Path,
    environment: Mapping[str, str],
) -> tuple[CaseResult, CaseResult]:
    """Run production-BFF identity and backend owner-isolation HTTP contracts."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    repository = Path(__file__).parents[2]
    bff_command = ["npm", "--prefix", "frontend", "run", "test:server"]
    bff = subprocess.run(  # noqa: S603 - fixed repository script.
        bff_command,
        cwd=repository,
        env=dict(environment),
        check=False,
        capture_output=True,
        text=True,
    )

    owner_command = [sys.executable, "-m", "pytest", "-q", OWNER_NODE]
    owner = subprocess.run(  # noqa: S603 - fixed interpreter and frozen test node.
        owner_command,
        cwd=repository / "backend",
        env=dict(environment),
        check=False,
        capture_output=True,
        text=True,
    )
    log_name = "http-contracts.log"
    _ = (evidence_dir / log_name).write_text(
        _redact_output(
            bff.stdout + bff.stderr + owner.stdout + owner.stderr,
            environment,
        ),
        encoding="utf-8",
    )
    return (
        CaseResult(
            name="invalid_identity",
            status=CaseStatus.PASSED if bff.returncode == 0 else CaseStatus.FAILED,
            observable="production BFF rejected malformed, expired, and forged IAP identities",
            artifact=log_name,
        ),
        CaseResult(
            name="owner_isolation",
            status=(
                CaseStatus.PASSED if bff.returncode == owner.returncode == 0 else CaseStatus.FAILED
            ),
            observable="BFF derived distinct subjects and backend rejected another receipt owner",
            artifact=log_name,
        ),
    )


def run_http_journeys(
    evidence_dir: Path,
    environment: Mapping[str, str],
) -> tuple[CaseResult, CaseResult]:
    """Run approved stages and unsupported research through real HTTP processes."""
    if not all(
        environment.get(name) for name in ("SAMURAI_TEST_DATABASE_URL", "SAMURAI_TEST_REDIS_URL")
    ):
        blocked = "disposable PostgreSQL and Redis URLs are required"
        return (
            CaseResult(name="staged_journey", status=CaseStatus.BLOCKED, observable=blocked),
            CaseResult(
                name="unsupported_research",
                status=CaseStatus.BLOCKED,
                observable=blocked,
            ),
        )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    artifact_name = "http-journeys.json"
    artifact_path = evidence_dir / artifact_name
    artifact_path.unlink(missing_ok=True)
    process_environment = dict(environment)
    process_environment["SAMURAI_READINESS_HTTP_EVIDENCE"] = str(artifact_path.resolve())
    command = [sys.executable, "-m", "pytest", "-q", HTTP_JOURNEY_NODE]
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and frozen test node.
        command,
        cwd=Path(__file__).parents[1],
        env=process_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    log_name = "http-journeys.log"
    _ = (evidence_dir / log_name).write_text(
        _redact_output(completed.stdout + completed.stderr, environment),
        encoding="utf-8",
    )
    valid = False
    if completed.returncode == 0 and artifact_path.is_file():
        try:
            proof = _HttpJourneyProof.model_validate_json(artifact_path.read_text(encoding="utf-8"))
            valid = (
                proof.staged.company_id != proof.unsupported.company_id
                and proof.staged.revisions == [1, 2, 3, 5]
                and proof.staged.artifact_types
                == ["intake", "research", "strategy", "product_plan", "verification"]
                and proof.unsupported.revision == TOTAL_ATTEMPTS
                and proof.unsupported.artifact_types == ["intake", "research"]
            )
        except OSError, ValueError:
            valid = False
    status = CaseStatus.PASSED if valid else CaseStatus.FAILED
    observable = (
        "fresh real-HTTP journey retained one company through brief, research, strategy, and plan"
        if valid
        else "fresh real-HTTP journey failed or wrote invalid semantic evidence"
    )
    unsupported_observable = (
        "fresh real-HTTP unsupported research persisted research and stopped before strategy"
        if valid
        else "fresh real-HTTP unsupported research failed or wrote invalid semantic evidence"
    )
    return (
        CaseResult(
            name="staged_journey",
            status=status,
            observable=observable,
            artifact=artifact_name if valid else log_name,
        ),
        CaseResult(
            name="unsupported_research",
            status=status,
            observable=unsupported_observable,
            artifact=artifact_name if valid else log_name,
        ),
    )


def _run_pytest_case(  # noqa: PLR0913 - one fixed external scenario descriptor.
    evidence_dir: Path,
    environment: Mapping[str, str],
    *,
    name: str,
    node: str,
    artifact: str,
    observable: str,
) -> CaseResult:
    if not all(
        environment.get(name) for name in ("SAMURAI_TEST_DATABASE_URL", "SAMURAI_TEST_REDIS_URL")
    ):
        return CaseResult(
            name=name,
            status=CaseStatus.BLOCKED,
            observable="disposable PostgreSQL and Redis URLs are required",
        )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = evidence_dir / artifact
    artifact_path.unlink(missing_ok=True)
    process_environment = dict(environment)
    process_environment["SAMURAI_QUEUE_EVIDENCE_DIR"] = str(evidence_dir.resolve())
    backend_dir = Path(__file__).parents[1]
    command = [sys.executable, "-m", "pytest", "-q", node]
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and frozen test node.
        command,
        cwd=backend_dir,
        env=process_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    log_name = f"{name.replace('_', '-')}.log"
    _ = (evidence_dir / log_name).write_text(
        _redact_output(completed.stdout + completed.stderr, environment),
        encoding="utf-8",
    )
    if completed.returncode != 0:
        return CaseResult(
            name=name,
            status=CaseStatus.FAILED,
            observable="fresh process scenario exited nonzero",
            artifact=log_name,
        )
    if not artifact_path.is_file() or artifact_path.stat().st_size == 0:
        return CaseResult(
            name=name,
            status=CaseStatus.FAILED,
            observable="fresh process scenario wrote no case artifact",
            artifact=log_name,
        )
    try:
        raw = artifact_path.read_text(encoding="utf-8")
        if artifact == "recovery.json":
            proof = _RecoveryProof.model_validate_json(raw)
            valid = (
                proof.recovery.terminal.status == "COMPLETED"
                and proof.recovery.terminal.attempt == TOTAL_ATTEMPTS
                and proof.recovery.run_completed
                and proof.exhaustion.terminal.status == "ERROR"
                and proof.exhaustion.terminal.attempt
                == proof.exhaustion.terminal.max_attempts
                == TOTAL_ATTEMPTS
                and not proof.exhaustion.third_model_invocation
            )
        else:
            post_commit = _PostCommitProof.model_validate_json(raw)
            valid = (
                post_commit.terminal_receipt.status == "COMPLETED"
                and post_commit.terminal_receipt.attempt == TOTAL_ATTEMPTS
                and post_commit.committed_revision == post_commit.retained_revision == 1
                and post_commit.committed_artifact_ids == post_commit.retained_artifact_ids
                and len(post_commit.retained_artifact_ids) == 1
            )
    except OSError, ValueError:
        valid = False
    if not valid:
        return CaseResult(
            name=name,
            status=CaseStatus.FAILED,
            observable="fresh process scenario artifact failed semantic assertions",
            artifact=artifact,
        )
    return CaseResult(
        name=name,
        status=CaseStatus.PASSED,
        observable=observable,
        artifact=artifact,
    )


def run(arguments_: _Arguments, environment: Mapping[str, str]) -> ReadinessResult:
    """Execute currently available provider-free cases and block absent dependencies."""
    if arguments_.mode != "local":
        raise RunnerError(_Failure.PROVIDER_MODE)
    _ = validate_local_url(arguments_.base_url)
    _ = validate_local_url(arguments_.frontend_url)
    validate_disposable_services(environment)
    endpoints = probe_local_endpoints(arguments_.base_url, arguments_.frontend_url)
    target_pair = run_target_pair_journey(
        arguments_.evidence_dir,
        arguments_.base_url,
        arguments_.frontend_url,
        environment,
    )
    process_recovery = run_process_recovery(arguments_.evidence_dir, environment)
    staged, unsupported = run_domain_fixtures(arguments_.evidence_dir, environment)
    http_staged, http_unsupported = run_http_journeys(arguments_.evidence_dir, environment)
    identity, owner = run_contract_fixtures(arguments_.evidence_dir, environment)
    browser = run_browser_evidence(Path(__file__).parents[2])
    browser_terminal = run_terminal_browser_evidence(Path(__file__).parents[2])
    duplicate, cancelled, provider_runtime = run_queue_safety_cases(
        arguments_.evidence_dir,
        environment,
    )
    reconnect = CaseResult(
        name="receipt_reconnect",
        status=process_recovery.status,
        observable="receipt recovered the same run and SSE replay indices remained unique",
        artifact=process_recovery.artifact,
    )
    cases = (
        endpoints,
        target_pair,
        process_recovery,
        run_post_commit_recovery(arguments_.evidence_dir, environment),
        staged,
        unsupported,
        http_staged,
        http_unsupported,
        identity,
        owner,
        duplicate,
        cancelled,
        provider_runtime,
        reconnect,
        browser,
        browser_terminal,
        verify_provider_guard(arguments_.evidence_dir),
    )
    result = build_result(REQUIRED_CASES, cases)
    write_result(result, arguments_.evidence_dir)
    return result


def main() -> int:
    """Run local readiness verification with sanitized failure output."""
    parsed = _arguments()
    try:
        result = run(
            parsed,
            load_environment(
                os.environ,
                Path(__file__).parents[1] / ".env.readiness.local",
            ),
        )
    except (OSError, RunnerError) as error:
        _ = sys.stderr.write(f"readiness verification refused: {error}\n")
        return 2
    return 0 if result.status is CaseStatus.PASSED else 2


if __name__ == "__main__":
    raise SystemExit(main())
