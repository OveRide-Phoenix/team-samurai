from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from agno.db.base import SessionType
from agno.db.schemas.jobs import QueuedJob
from agno.session.workflow import WorkflowSession
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from redis import Redis
from sqlalchemy import MetaData, Table, create_engine, select, text
from sqlalchemy.orm import Session as SqlAlchemySession
from sqlalchemy.schema import DropSchema

from samurai.company_store import CompanyStore
from samurai.contracts import CompanyState
from samurai.execution_state import (
    ApprovedStage,
    SamuraiPostgresDb,
    WorkIntentInput,
    WorkOperation,
    WorkReceipt,
)
from samurai.parent import child_session_id
from samurai.workspace_api import CompanyView, WorkspaceView

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from io import TextIOWrapper


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return cast("tuple[str, int]", listener.getsockname())[1]


def _token(
    private_key: rsa.RSAPrivateKey,
    owner: str,
    *,
    scopes: tuple[str, ...] = ("agents:run", "agents:read"),
) -> str:
    return jwt.encode(
        {
            "sub": owner,
            "scopes": list(scopes),
            "exp": datetime.now(UTC) + timedelta(minutes=10),
        },
        private_key,
        algorithm="RS256",
    )


def start_test_process(
    port: int,
    environment: dict[str, str],
    log_path: Path,
    *,
    factory: str = "tests.queue_process_app:create_queue_process_app",
) -> tuple[subprocess.Popen[str], TextIOWrapper]:
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "uvicorn",
            factory,
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=Path(__file__).parent.parent,
        env=environment,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log.flush()
            message = log_path.read_text(encoding="utf-8")
            log.close()
            raise RuntimeError(message)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return process, log
        except OSError:
            time.sleep(0.05)
    process.kill()
    _ = process.wait(timeout=5)
    log.close()
    message = "queue test process did not start"
    raise TimeoutError(message)


def stop_test_process(
    process: subprocess.Popen[str],
    log: TextIOWrapper,
    *,
    kill: bool,
) -> None:
    if process.poll() is None:
        process.send_signal(signal.SIGKILL if kill else signal.SIGTERM)
    try:
        _ = process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        _ = process.wait(timeout=5)
    log.close()


def _submit(port: int, token: str, session_id: str, submission_id: UUID) -> None:
    with (
        httpx.Client(timeout=10) as client,
        client.stream(
            "POST",
            f"http://127.0.0.1:{port}/agentos/agents/samurai/runs",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": str(submission_id),
            },
            data={
                "message": "Build a durable company brief",
                "session_id": session_id,
                "stream": "true",
                "background": "true",
            },
        ) as response,
    ):
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")


def _cancel(port: int, token: str, receipt: WorkReceipt) -> httpx.Response:
    return httpx.post(
        f"http://127.0.0.1:{port}/agentos/agents/samurai/runs/{receipt.run_id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
        params={"session_id": receipt.session_id},
        timeout=10,
    )


def _submit_non_stream(
    port: int,
    token: str,
    session_id: str,
    submission_id: UUID,
    message: str,
) -> httpx.Response:
    return httpx.post(
        f"http://127.0.0.1:{port}/agentos/agents/samurai/runs",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": str(submission_id),
        },
        data={
            "message": message,
            "session_id": session_id,
            "stream": "false",
            "background": "true",
        },
        timeout=10,
    )


def _receipt(
    port: int,
    token: str,
    session_id: str,
    submission_id: UUID,
) -> WorkReceipt | None:
    response = httpx.get(
        f"http://127.0.0.1:{port}/agentos/work-receipts/{submission_id}",
        headers={"Authorization": f"Bearer {token}"},
        params={"session_id": session_id},
        timeout=5,
    )
    if response.status_code == 404:
        return None
    assert response.status_code == 200, response.text
    return WorkReceipt.model_validate(response.json())


def _wait_for_receipt(
    port: int,
    token: str,
    session_id: str,
    submission_id: UUID,
    statuses: set[str],
) -> WorkReceipt:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        receipt = _receipt(port, token, session_id, submission_id)
        if receipt is not None and receipt.status in statuses:
            return receipt
        time.sleep(0.1)
    message = f"receipt did not reach {statuses}"
    raise TimeoutError(message)


def _wait_for_marker(marker: Path) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if marker.exists():
            return
        time.sleep(0.05)
    message = "model invocation marker was not written"
    raise TimeoutError(message)


def _expire_lease(database_url: str, schema: str, run_id: str) -> None:
    database = SamuraiPostgresDb(
        id="queue-process-expiry",
        db_url=database_url,
        db_schema=schema,
    )
    jobs = Table(
        database.job_table_name,
        MetaData(schema=database.db_schema),
        autoload_with=database.db_engine,
    )
    with SqlAlchemySession(database.db_engine) as session, session.begin():
        _ = session.execute(jobs.update().where(jobs.c.id == run_id).values(locked_at=0))
    database.close()


def _resume_events(port: int, token: str, receipt: WorkReceipt) -> list[dict[str, object]]:
    response = httpx.post(
        f"http://127.0.0.1:{port}/agentos/agents/samurai/runs/{receipt.run_id}/resume",
        headers={"Authorization": f"Bearer {token}"},
        data={"session_id": receipt.session_id, "last_event_index": "-1"},
        timeout=10,
    )
    assert response.status_code == 200
    return [
        cast("dict[str, object]", json.loads(line.removeprefix("data: ")))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _record_evidence(name: str, payload: dict[str, object]) -> None:
    evidence_dir = os.environ.get("SAMURAI_QUEUE_EVIDENCE_DIR")
    if evidence_dir is not None:
        evidence_path = Path(evidence_dir) / name
    elif configured_path := os.environ.get("SAMURAI_QUEUE_EVIDENCE_PATH"):
        evidence_path = Path(configured_path)
    else:
        return
    _ = evidence_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _company_state(
    database_url: str,
    schema: str,
    owner_id: str,
    parent_session_id: str,
) -> CompanyState:
    database = SamuraiPostgresDb(
        id="queue-process-state",
        db_url=database_url,
        db_schema=schema,
    )
    try:
        if database.table_exists("samurai_company_actor_bindings"):
            access = CompanyStore(database.db_engine, schema=schema).read_for_actor(
                owner_id, parent_session_id
            )
            assert access is not None
            return access.state
        session = database.get_session(
            child_session_id(owner_id, parent_session_id),
            session_type=SessionType.WORKFLOW,
            user_id=owner_id,
        )
        assert isinstance(session, WorkflowSession)
        assert session.session_data is not None
        return CompanyState.model_validate(session.session_data["session_state"]["company"])
    finally:
        database.close()


def _database_receipt(
    database_url: str,
    schema: str,
    owner_id: str,
    parent_session_id: str,
    submission_id: UUID,
) -> WorkReceipt:
    database = SamuraiPostgresDb(
        id="queue-process-receipt",
        db_url=database_url,
        db_schema=schema,
    )
    try:
        receipt = database.get_work_receipt(owner_id, parent_session_id, submission_id)
        assert receipt is not None
        return receipt
    finally:
        database.close()


def _cleanup_queue_environment(database_url: str, redis_url: str, schema: str) -> None:
    assert schema.startswith("task6_queue_")
    assert schema.replace("_", "").isalnum()
    engine = create_engine(database_url)
    run_ids: list[str] = []
    try:
        with engine.connect() as connection:
            table_exists = cast(
                "str | None",
                connection.scalar(
                    text("select to_regclass(:table_name)"),
                    {"table_name": f"{schema}.agno_jobs"},
                ),
            )
            if table_exists is not None:
                jobs = Table(
                    "agno_jobs",
                    MetaData(schema=schema),
                    autoload_with=connection,
                )
                run_ids = list(connection.scalars(select(jobs.c.id)))
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            _ = connection.execute(DropSchema(schema, cascade=True, if_exists=True))
    finally:
        engine.dispose()

    parsed_redis = urlsplit(redis_url)
    redis = Redis(
        host=parsed_redis.hostname or "127.0.0.1",
        port=parsed_redis.port or 6379,
        db=int(parsed_redis.path.lstrip("/") or "0"),
        username=parsed_redis.username,
        password=parsed_redis.password,
        ssl=parsed_redis.scheme == "rediss",
    )
    try:
        keys_for_pattern = cast("Callable[[str], list[bytes | str]]", redis.keys)
        for run_id in run_ids:
            keys = keys_for_pattern(f"*{run_id}*")
            if keys:
                _ = redis.delete(*keys)
    finally:
        redis.close()


@pytest.fixture
def queue_environment(
    tmp_path: Path,
) -> Iterator[tuple[dict[str, str], str, str, str]]:
    database_url = os.environ.get("SAMURAI_TEST_DATABASE_URL")
    redis_url = os.environ.get("SAMURAI_TEST_REDIS_URL")
    if not database_url or not redis_url:
        pytest.skip("SAMURAI_TEST_DATABASE_URL and SAMURAI_TEST_REDIS_URL are required")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_key_file = tmp_path / "public.pem"
    _ = public_key_file.write_bytes(public_key)
    token = _token(private_key, "queue-founder")
    backend_root = Path(__file__).parent.parent
    schema = f"task6_queue_{uuid4().hex}"
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(backend_root / "src"), str(backend_root))),
        "SAMURAI_QUEUE_DATABASE_URL": database_url,
        "SAMURAI_QUEUE_REDIS_URL": redis_url,
        "SAMURAI_QUEUE_PUBLIC_KEY_FILE": str(public_key_file),
        "SAMURAI_QUEUE_DB_SCHEMA": schema,
        "SAMURAI_QUEUE_SECOND_TOKEN": _token(private_key, "queue-founder-two"),
        "SAMURAI_QUEUE_ADMIN_TOKEN": _token(
            private_key,
            "queue-admin",
            scopes=("agent_os:admin",),
        ),
    }
    try:
        yield environment, token, database_url, schema
    finally:
        _cleanup_queue_environment(database_url, redis_url, schema)


def test_native_queue_recovers_once_replays_sse_and_exhausts_after_second_kill(  # noqa: PLR0915
    queue_environment: tuple[dict[str, str], str, str, str],
    tmp_path: Path,
) -> None:
    base_environment, token, database_url, schema = queue_environment
    first_submission = uuid4()
    first_session = f"recover-{uuid4()}"
    first_marker = tmp_path / "recover-attempt-1"
    first_port = _free_port()
    first_environment = {
        **base_environment,
        "SAMURAI_QUEUE_MODEL_MODE": "block",
        "SAMURAI_QUEUE_MODEL_MARKER": str(first_marker),
    }
    first_process, first_log = start_test_process(
        first_port,
        first_environment,
        tmp_path / "recover-attempt-1.log",
    )
    try:
        _submit(first_port, token, first_session, first_submission)
        _wait_for_marker(first_marker)
        first_receipt = _wait_for_receipt(
            first_port,
            token,
            first_session,
            first_submission,
            {"RUNNING"},
        )
        assert first_receipt.attempt == 1
    finally:
        stop_test_process(first_process, first_log, kill=True)

    _expire_lease(database_url, schema, first_receipt.run_id)
    recovered_marker = tmp_path / "recover-attempt-2"
    recovered_port = _free_port()
    recovered_environment = {
        **base_environment,
        "SAMURAI_QUEUE_MODEL_MODE": "complete",
        "SAMURAI_QUEUE_MODEL_MARKER": str(recovered_marker),
    }
    recovered_process, recovered_log = start_test_process(
        recovered_port,
        recovered_environment,
        tmp_path / "recover-attempt-2.log",
    )
    try:
        recovered = _wait_for_receipt(
            recovered_port,
            token,
            first_session,
            first_submission,
            {"COMPLETED"},
        )
        assert recovered.attempt == 2
        _wait_for_marker(recovered_marker)
        events = _resume_events(recovered_port, token, recovered)
        indices = [cast("int", event["event_index"]) for event in events if "event_index" in event]
        assert indices == sorted(set(indices))
        assert any(event.get("event") == "RunCompleted" for event in events)
    finally:
        stop_test_process(recovered_process, recovered_log, kill=False)

    exhausted_submission = uuid4()
    exhausted_session = f"exhaust-{uuid4()}"
    exhausted_receipt: WorkReceipt | None = None
    for attempt in (1, 2):
        marker = tmp_path / f"exhaust-attempt-{attempt}"
        port = _free_port()
        environment = {
            **base_environment,
            "SAMURAI_QUEUE_MODEL_MODE": "block",
            "SAMURAI_QUEUE_MODEL_MARKER": str(marker),
        }
        process, log = start_test_process(port, environment, tmp_path / f"exhaust-{attempt}.log")
        try:
            if attempt == 1:
                _submit(port, token, exhausted_session, exhausted_submission)
            _wait_for_marker(marker)
            exhausted_receipt = _wait_for_receipt(
                port,
                token,
                exhausted_session,
                exhausted_submission,
                {"RUNNING"},
            )
            assert exhausted_receipt.attempt == attempt
        finally:
            stop_test_process(process, log, kill=True)
        _expire_lease(database_url, schema, exhausted_receipt.run_id)

    assert exhausted_receipt is not None
    third_marker = tmp_path / "exhaust-attempt-3"
    third_port = _free_port()
    third_environment = {
        **base_environment,
        "SAMURAI_QUEUE_MODEL_MODE": "complete",
        "SAMURAI_QUEUE_MODEL_MARKER": str(third_marker),
    }
    third_process, third_log = start_test_process(
        third_port,
        third_environment,
        tmp_path / "exhaust-attempt-3.log",
    )
    try:
        terminal = _wait_for_receipt(
            third_port,
            token,
            exhausted_session,
            exhausted_submission,
            {"ERROR"},
        )
        assert terminal.attempt == 2
        assert terminal.max_attempts == 2
        assert terminal.failure_reason == "work stopped after the allowed attempts"
        time.sleep(1)
        assert not third_marker.exists()
        _record_evidence(
            "recovery.json",
            {
                "scenario": "native queue process restart, SSE replay, and retry exhaustion",
                "recovery": {
                    "first": first_receipt.model_dump(mode="json"),
                    "terminal": recovered.model_dump(mode="json"),
                    "event_indices": indices,
                    "run_completed": any(event.get("event") == "RunCompleted" for event in events),
                },
                "exhaustion": {
                    "second_attempt": exhausted_receipt.model_dump(mode="json"),
                    "terminal": terminal.model_dump(mode="json"),
                    "third_model_invocation": third_marker.exists(),
                },
            },
        )
    finally:
        stop_test_process(third_process, third_log, kill=False)


def test_native_retry_reuses_child_commit_after_pre_ack_process_kill(
    queue_environment: tuple[dict[str, str], str, str, str],
    tmp_path: Path,
) -> None:
    base_environment, token, database_url, schema = queue_environment
    submission_id = uuid4()
    session_id = f"commit-{uuid4()}"
    first_marker = tmp_path / "commit-attempt-1"
    first_port = _free_port()
    first_environment = {
        **base_environment,
        "SAMURAI_QUEUE_MODEL_MODE": "journey_block_after_commit",
        "SAMURAI_QUEUE_MODEL_MARKER": str(first_marker),
    }
    first_process, first_log = start_test_process(
        first_port,
        first_environment,
        tmp_path / "commit-attempt-1.log",
    )
    try:
        _submit(first_port, token, session_id, submission_id)
        _wait_for_marker(first_marker)
        running = _database_receipt(
            database_url,
            schema,
            "queue-founder",
            session_id,
            submission_id,
        )
        assert running.status == "RUNNING"
        committed = _company_state(
            database_url,
            schema,
            "queue-founder",
            session_id,
        )
    finally:
        stop_test_process(first_process, first_log, kill=True)

    _expire_lease(database_url, schema, running.run_id)
    retry_marker = tmp_path / "commit-attempt-2"
    retry_port = _free_port()
    retry_environment = {
        **base_environment,
        "SAMURAI_QUEUE_MODEL_MODE": "journey_complete",
        "SAMURAI_QUEUE_MODEL_MARKER": str(retry_marker),
    }
    retry_process, retry_log = start_test_process(
        retry_port,
        retry_environment,
        tmp_path / "commit-attempt-2.log",
    )
    try:
        completed = _wait_for_receipt(
            retry_port,
            token,
            session_id,
            submission_id,
            {"COMPLETED"},
        )
        retained = _company_state(
            database_url,
            schema,
            "queue-founder",
            session_id,
        )
        assert completed.attempt == 2
        assert completed.company_id == committed.context.company_id
        assert completed.revision == committed.current_revision == 1
        assert retained.current_revision == 1
        assert [artifact.artifact_id for artifact in retained.artifacts] == [
            artifact.artifact_id for artifact in committed.artifacts
        ]
        assert len(retained.artifacts) == 1
        _record_evidence(
            "post-commit.json",
            {
                "scenario": "worker killed after child commit and before parent acknowledgement",
                "external_provider_calls": 0,
                "provider_guard": "local fail-closed Gemini invoke patch",
                "public_source_fetch_guard": (
                    "local fail-closed company_workflow.fetch_sources patch"
                ),
                "first_receipt": running.model_dump(mode="json"),
                "terminal_receipt": completed.model_dump(mode="json"),
                "committed_revision": committed.current_revision,
                "retained_revision": retained.current_revision,
                "committed_artifact_ids": [
                    str(artifact.artifact_id) for artifact in committed.artifacts
                ],
                "retained_artifact_ids": [
                    str(artifact.artifact_id) for artifact in retained.artifacts
                ],
            },
        )
    finally:
        stop_test_process(retry_process, retry_log, kill=False)


def test_native_cancel_from_second_replica_reaches_terminal_without_child_artifacts(
    queue_environment: tuple[dict[str, str], str, str, str],
    tmp_path: Path,
) -> None:
    base_environment, token, database_url, schema = queue_environment
    submission_id = uuid4()
    session_id = f"cancel-{uuid4()}"
    marker = tmp_path / "cancel-model"
    environment = {
        **base_environment,
        "SAMURAI_QUEUE_MODEL_MODE": "block",
        "SAMURAI_QUEUE_MODEL_MARKER": str(marker),
    }
    executing_port = _free_port()
    executing_process, executing_log = start_test_process(
        executing_port,
        environment,
        tmp_path / "cancel-executing.log",
    )
    cancelling_process: subprocess.Popen[str] | None = None
    cancelling_log: TextIOWrapper | None = None
    replacement_process: subprocess.Popen[str] | None = None
    replacement_log: TextIOWrapper | None = None
    try:
        _submit(executing_port, token, session_id, submission_id)
        _wait_for_marker(marker)
        running = _wait_for_receipt(
            executing_port,
            token,
            session_id,
            submission_id,
            {"RUNNING"},
        )
        cancelling_port = _free_port()
        cancelling_process, cancelling_log = start_test_process(
            cancelling_port,
            environment,
            tmp_path / "cancel-other-replica.log",
        )
        cancelled = _cancel(cancelling_port, token, running)
        assert cancelled.status_code == 200, cancelled.text
        terminal = _wait_for_receipt(
            cancelling_port,
            token,
            session_id,
            submission_id,
            {"CANCELLED"},
        )
        stop_test_process(executing_process, executing_log, kill=False)
        stop_test_process(cancelling_process, cancelling_log, kill=False)
        replacement_marker = tmp_path / "cancel-replacement-model"
        replacement_environment = {
            **base_environment,
            "SAMURAI_QUEUE_MODEL_MODE": "complete",
            "SAMURAI_QUEUE_MODEL_MARKER": str(replacement_marker),
        }
        replacement_port = _free_port()
        replacement_process, replacement_log = start_test_process(
            replacement_port,
            replacement_environment,
            tmp_path / "cancel-replacement.log",
        )
        after_replacement = _wait_for_receipt(
            replacement_port,
            token,
            session_id,
            submission_id,
            {"CANCELLED"},
        )
        time.sleep(1)
        assert not replacement_marker.exists()
        database = SamuraiPostgresDb(
            id="queue-cancel-state",
            db_url=database_url,
            db_schema=schema,
        )
        try:
            child = database.get_session(
                child_session_id("queue-founder", session_id),
                session_type=SessionType.WORKFLOW,
                user_id="queue-founder",
            )
        finally:
            database.close()
        assert child is None
        assert terminal.attempt == 1
        assert terminal.max_attempts == 2
        assert after_replacement.run_id == terminal.run_id
        assert after_replacement.status == "CANCELLED"
        _record_evidence(
            "cancellation.json",
            {
                "scenario": "second replica cancellation survives worker replacement",
                "cancel_http_status": cancelled.status_code,
                "running": running.model_dump(mode="json"),
                "terminal": terminal.model_dump(mode="json"),
                "after_replacement": after_replacement.model_dump(mode="json"),
                "replacement_model_invoked": replacement_marker.exists(),
                "child_session_created": child is not None,
                "public_source_fetch_guard": (
                    "local fail-closed company_workflow.fetch_sources patch"
                ),
            },
        )
    finally:
        if replacement_process is not None and replacement_log is not None:
            stop_test_process(replacement_process, replacement_log, kill=False)
        if cancelling_process is not None and cancelling_log is not None:
            stop_test_process(cancelling_process, cancelling_log, kill=False)
        stop_test_process(executing_process, executing_log, kill=False)


def test_native_http_idempotency_is_scoped_by_owner_and_rejects_changed_payload(
    queue_environment: tuple[dict[str, str], str, str, str],
    tmp_path: Path,
) -> None:
    environment, first_token, _database_url, _schema = queue_environment
    environment = {
        **environment,
        "SAMURAI_QUEUE_MODEL_MODE": "complete",
        "SAMURAI_QUEUE_MODEL_MARKER": str(tmp_path / "idempotency-model"),
    }
    second_token = environment["SAMURAI_QUEUE_SECOND_TOKEN"]
    submission_id = uuid4()
    first_session = f"owner-one-{uuid4()}"
    second_session = f"owner-two-{uuid4()}"
    port = _free_port()
    process, log = start_test_process(
        port,
        environment,
        tmp_path / "idempotency.log",
    )
    try:
        first = _submit_non_stream(
            port,
            first_token,
            first_session,
            submission_id,
            "Build the approved company brief",
        )
        assert first.status_code == 202, first.text
        identical_replay = _submit_non_stream(
            port,
            first_token,
            first_session,
            submission_id,
            "Build the approved company brief",
        )
        assert identical_replay.status_code == 202, identical_replay.text
        assert identical_replay.json()["run_id"] == first.json()["run_id"]
        changed = _submit_non_stream(
            port,
            first_token,
            first_session,
            submission_id,
            "Use the same ticket for changed work",
        )
        assert changed.status_code == 409, changed.text
        second = _submit_non_stream(
            port,
            second_token,
            second_session,
            submission_id,
            "Build the approved company brief",
        )
        assert second.status_code == 202, second.text
        first_receipt = _wait_for_receipt(
            port,
            first_token,
            first_session,
            submission_id,
            {"COMPLETED"},
        )
        second_receipt = _wait_for_receipt(
            port,
            second_token,
            second_session,
            submission_id,
            {"COMPLETED"},
        )
        assert first_receipt.run_id != second_receipt.run_id
        model_invocations = (
            (tmp_path / "idempotency-model").read_text(encoding="utf-8").splitlines()
        )
        assert len(model_invocations) == 2
        cross_owner = _receipt(port, second_token, first_session, submission_id)
        cross_session = _receipt(port, first_token, second_session, submission_id)
        assert cross_owner is None
        assert cross_session is None
        _record_evidence(
            "idempotency.json",
            {
                "scenario": "same logical UUID is isolated per JWT owner",
                "first_status": first.status_code,
                "identical_replay_status": identical_replay.status_code,
                "identical_replay_run_id": identical_replay.json()["run_id"],
                "changed_payload_status": changed.status_code,
                "second_status": second.status_code,
                "first_receipt": first_receipt.model_dump(mode="json"),
                "second_receipt": second_receipt.model_dump(mode="json"),
                "cross_owner_receipt": cross_owner,
                "cross_session_receipt": cross_session,
                "model_invocation_count": len(model_invocations),
            },
        )
    finally:
        stop_test_process(process, log, kill=False)


def test_unexpected_provider_stream_fails_locally_before_network(
    queue_environment: tuple[dict[str, str], str, str, str],
    tmp_path: Path,
) -> None:
    environment, token, _database_url, _schema = queue_environment
    marker = tmp_path / "provider-guard-model"
    environment = {
        **environment,
        "SAMURAI_QUEUE_MODEL_MODE": "provider_guard",
        "SAMURAI_QUEUE_MODEL_MARKER": str(marker),
    }
    submission_id = uuid4()
    session_id = f"provider-guard-{uuid4()}"
    port = _free_port()
    process, log = start_test_process(
        port,
        environment,
        tmp_path / "provider-guard.log",
    )
    try:
        accepted = _submit_non_stream(
            port,
            token,
            session_id,
            submission_id,
            "Exercise the local provider guard",
        )
        assert accepted.status_code == 202, accepted.text
        terminal = _wait_for_receipt(
            port,
            token,
            session_id,
            submission_id,
            {"ERROR"},
        )
        assert marker.exists()
        assert terminal.attempt == terminal.max_attempts == 2
        time.sleep(1)
        unchanged = _receipt(port, token, session_id, submission_id)
        assert unchanged is not None
        assert unchanged.attempt == 2
        _record_evidence(
            "provider-guard.json",
            {
                "scenario": "unexpected Gemini streaming path fails locally",
                "accepted_status": accepted.status_code,
                "terminal": terminal.model_dump(mode="json"),
                "attempt_after_settle": unchanged.attempt,
                "external_provider_calls": 0,
                "public_source_fetch_guard": (
                    "local fail-closed company_workflow.fetch_sources patch"
                ),
            },
        )
    finally:
        stop_test_process(process, log, kill=False)


def test_registry_input_check_is_permanent_and_does_not_invoke_provider(
    queue_environment: tuple[dict[str, str], str, str, str],
    tmp_path: Path,
) -> None:
    environment, token, _database_url, _schema = queue_environment
    marker = tmp_path / "registration-guard-model"
    environment = {
        **environment,
        "SAMURAI_QUEUE_MODEL_MODE": "registration_guard",
        "SAMURAI_QUEUE_MODEL_MARKER": str(marker),
    }
    submission_id = uuid4()
    session_id = f"registration-guard-{uuid4()}"
    port = _free_port()
    process, log = start_test_process(
        port,
        environment,
        tmp_path / "registration-guard.log",
    )
    try:
        accepted = _submit_non_stream(
            port,
            token,
            session_id,
            submission_id,
            "Exercise the permanent registry input check",
        )
        assert accepted.status_code == 202, accepted.text
        terminal = _wait_for_receipt(
            port,
            token,
            session_id,
            submission_id,
            {"ERROR"},
        )
        assert terminal.attempt == 1
        assert terminal.max_attempts == 2
        assert not marker.exists()
        time.sleep(1)
        unchanged = _receipt(port, token, session_id, submission_id)
        assert unchanged is not None
        assert unchanged.attempt == 1
        _record_evidence(
            "permanent-input-check.json",
            {
                "scenario": "registry InputCheckError is permanent",
                "accepted_status": accepted.status_code,
                "terminal": terminal.model_dump(mode="json"),
                "attempt_after_settle": unchanged.attempt,
                "model_invoked": marker.exists(),
            },
        )
    finally:
        stop_test_process(process, log, kill=False)


def test_redis_outage_rejects_admission_and_reports_admin_unhealthy(
    queue_environment: tuple[dict[str, str], str, str, str],
    tmp_path: Path,
) -> None:
    environment, token, _database_url, _schema = queue_environment
    unavailable_redis_port = _free_port()
    marker = tmp_path / "redis-outage-model"
    environment = {
        **environment,
        "SAMURAI_QUEUE_REDIS_URL": f"redis://127.0.0.1:{unavailable_redis_port}/0",
        "SAMURAI_QUEUE_MODEL_MODE": "complete",
        "SAMURAI_QUEUE_MODEL_MARKER": str(marker),
    }
    port = _free_port()
    process, log = start_test_process(
        port,
        environment,
        tmp_path / "redis-outage.log",
    )
    try:
        rejected = _submit_non_stream(
            port,
            token,
            f"redis-outage-{uuid4()}",
            uuid4(),
            "Do not accept without durable coordination",
        )
        assert rejected.status_code == 503, rejected.text
        assert not marker.exists()
        non_admin = httpx.get(
            f"http://127.0.0.1:{port}/agentos/queue/samurai-readiness",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        admin = httpx.get(
            f"http://127.0.0.1:{port}/agentos/queue/samurai-readiness",
            headers={"Authorization": f"Bearer {environment['SAMURAI_QUEUE_ADMIN_TOKEN']}"},
            timeout=5,
        )
        assert non_admin.status_code == 403
        assert admin.status_code == 200, admin.text
        diagnostics = cast("dict[str, object]", admin.json())
        assert diagnostics["status"] == "unhealthy"
        assert diagnostics["worker_available"] is True
        assert diagnostics["coordination_available"] is False
        _record_evidence(
            "redis-outage.json",
            {
                "scenario": "Redis outage fails admission before model work",
                "admission_status": rejected.status_code,
                "model_invoked": marker.exists(),
                "non_admin_diagnostics_status": non_admin.status_code,
                "admin_diagnostics": diagnostics,
            },
        )
    finally:
        stop_test_process(process, log, kill=False)


def test_admin_diagnostics_reports_delayed_old_pending_job(
    queue_environment: tuple[dict[str, str], str, str, str],
    tmp_path: Path,
) -> None:
    environment, _token_value, database_url, schema = queue_environment
    environment = {
        **environment,
        "SAMURAI_QUEUE_MODEL_MODE": "complete",
        "SAMURAI_QUEUE_MODEL_MARKER": str(tmp_path / "diagnostics-model"),
    }
    port = _free_port()
    process, log = start_test_process(
        port,
        environment,
        tmp_path / "diagnostics-delayed.log",
    )
    database = SamuraiPostgresDb(
        id="queue-delayed-diagnostics",
        db_url=database_url,
        db_schema=schema,
    )
    try:
        now = int(time.time())
        owner_id = "delayed-owner"
        session_id = f"delayed-{uuid4()}"
        run_id = str(uuid4())
        intent = WorkIntentInput(
            owner_id=owner_id,
            parent_session_id=session_id,
            child_session_id=child_session_id(owner_id, session_id),
            operation=WorkOperation.JOURNEY,
            stage=ApprovedStage.BRIEF,
            expected_revision=0,
            approved_input={"idea": "Delayed queue diagnostic", "stage": "brief"},
        )
        queued_job = QueuedJob(
            id=run_id,
            component_type="agent",
            component_id="samurai",
            session_id=session_id,
            user_id=owner_id,
            payload={"input": "Delayed queue diagnostic", "kwargs": {}},
            max_attempts=2,
            idempotency_key=str(uuid4()),
            available_at=now + 600,
            created_at=now - 121,
            updated_at=now - 121,
        ).to_dict()
        admitted = database.enqueue_work_job(queued_job, intent)
        assert admitted["accepted"] is True
        response = httpx.get(
            f"http://127.0.0.1:{port}/agentos/queue/samurai-readiness",
            headers={"Authorization": f"Bearer {environment['SAMURAI_QUEUE_ADMIN_TOKEN']}"},
            timeout=5,
        )
        assert response.status_code == 200, response.text
        diagnostics = cast("dict[str, object]", response.json())
        assert diagnostics["status"] == "delayed"
        assert diagnostics["worker_available"] is True
        assert diagnostics["coordination_available"] is True
        assert diagnostics["queued_jobs"] == 1
        oldest = diagnostics["oldest_pending_seconds"]
        assert isinstance(oldest, int)
        assert oldest > 120
        _record_evidence(
            "diagnostics-delayed.json",
            {
                "scenario": "admin diagnostics classify an old pending job as delayed",
                "http_status": response.status_code,
                "diagnostics": diagnostics,
                "queued_run_id": run_id,
            },
        )
    finally:
        database.close()
        stop_test_process(process, log, kill=False)


def test_agui_uses_claimed_worker_and_recovers_accepted_brief(
    queue_environment: tuple[dict[str, str], str, str, str],
    tmp_path: Path,
) -> None:
    environment, token, database_url, schema = queue_environment
    port = _free_port()
    session_id, submission_id = f"agui-{uuid4()}", uuid4()
    process, log = start_test_process(
        port,
        {
            **environment,
            "SAMURAI_QUEUE_MODEL_MODE": "journey_complete",
            "SAMURAI_QUEUE_CANONICAL": "1",
            "SAMURAI_QUEUE_MODEL_MARKER": str(tmp_path / "agui-model"),
        },
        tmp_path / "agui.log",
    )
    try:
        headers = {"Authorization": f"Bearer {token}"}
        workspace_response = httpx.post(
            f"http://127.0.0.1:{port}/agentos/samurai/workspaces",
            headers=headers,
            json={"display_name": "AGUI integration"},
        )
        assert workspace_response.status_code == 201, workspace_response.text
        workspace = WorkspaceView.model_validate(cast("object", workspace_response.json()))
        company_response = httpx.post(
            f"http://127.0.0.1:{port}/agentos/samurai/workspaces/{workspace.workspace_id}/companies",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={},
        )
        assert company_response.status_code == 201, company_response.text
        company = CompanyView.model_validate(cast("object", company_response.json()))
        assert company.parent_session_id is not None
        session_id = company.parent_session_id
        body = {
            "threadId": session_id,
            "runId": str(submission_id),
            "messages": [{"id": "founder-turn", "role": "user", "content": "Build my brief"}],
            "state": {},
            "tools": [],
            "context": [],
            "forwardedProps": {
                "team_area": "overview",
                "work_approval": {
                    "operation": "journey",
                    "stage": "brief",
                    "expected_revision": 0,
                    "company_id": str(company.company_id),
                },
            },
        }
        response = httpx.post(
            f"http://127.0.0.1:{port}/agentos/agents/samurai/agui",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=30,
        )
        assert response.status_code == 200, response.text
        events = [
            cast("dict[str, object]", json.loads(line[6:]))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        native = [
            cast("dict[str, object]", event["value"])
            for event in events
            if event.get("name") == "samurai"
        ]
        assert native[0]["event"] == "RunStarted"
        assert native[-1]["event"] == "RunCompleted", native
        assert all(event["run_id"] == str(submission_id) for event in native)
        receipt = _wait_for_receipt(port, token, session_id, submission_id, {"COMPLETED"})
        assert receipt.run_id == str(submission_id)
        committed = _company_state(database_url, schema, "queue-founder", session_id)
        assert committed.current_revision == 1
        assert len(committed.artifacts) == 1
        assert committed.artifacts[0].artifact_type.value == "intake"
        duplicate = httpx.post(
            f"http://127.0.0.1:{port}/agentos/agents/samurai/agui",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=10,
        )
        assert duplicate.status_code == 409
        assert _company_state(database_url, schema, "queue-founder", session_id) == committed
        foreign = httpx.post(
            f"http://127.0.0.1:{port}/agentos/agents/samurai/agui",
            headers={"Authorization": f"Bearer {environment['SAMURAI_QUEUE_SECOND_TOKEN']}"},
            json={**body, "runId": str(uuid4())},
            timeout=10,
        )
        assert foreign.status_code in {403, 404}
        stale = httpx.post(
            f"http://127.0.0.1:{port}/agentos/agents/samurai/agui",
            headers={"Authorization": f"Bearer {token}"},
            json={**body, "runId": str(uuid4())},
            timeout=10,
        )
        assert stale.status_code == 403
        replay = _resume_events(port, token, receipt)
        assert replay[-1]["event"] == "RunCompleted"
    finally:
        stop_test_process(process, log, kill=False)


def test_agui_read_only_turn_keeps_team_scope_and_can_be_cancelled(
    queue_environment: tuple[dict[str, str], str, str, str],
    tmp_path: Path,
) -> None:
    environment, token, _database_url, _schema = queue_environment
    port, submission = _free_port(), uuid4()
    session_id = f"agui-cancel-{uuid4()}"
    marker = tmp_path / "read-only-model"
    process, log = start_test_process(
        port,
        {
            **environment,
            "SAMURAI_QUEUE_MODEL_MODE": "block",
            "SAMURAI_QUEUE_MODEL_MARKER": str(marker),
        },
        tmp_path / "agui-cancel.log",
    )
    try:
        with httpx.stream(
            "POST",
            f"http://127.0.0.1:{port}/agentos/agents/samurai/agui",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "threadId": session_id,
                "runId": str(submission),
                "messages": [{"id": "turn", "role": "user", "content": "Discuss our research"}],
                "state": {},
                "context": [],
                "tools": [],
                "forwardedProps": {"team_area": "research"},
            },
            timeout=10,
        ) as response:
            assert response.status_code == 200
            assert next(response.iter_lines()).startswith("data:")
        _wait_for_marker(marker)
        receipt = _wait_for_receipt(port, token, session_id, submission, {"RUNNING"})
        assert _cancel(port, token, receipt).status_code == 200
        _ = marker.with_name(marker.name + ".release").touch()
        cancelled = _wait_for_receipt(port, token, session_id, submission, {"CANCELLED"})
        saved = httpx.get(
            f"http://127.0.0.1:{port}/agentos/agents/samurai/runs/{cancelled.run_id}",
            params={"session_id": session_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert saved.status_code == 200
        database = SamuraiPostgresDb(db_url=_database_url, db_schema=_schema)
        try:
            jobs = Table(
                database.job_table_name, MetaData(schema=_schema), autoload_with=database.db_engine
            )
            with database.db_engine.connect() as connection:
                payload = connection.scalar(
                    select(jobs.c.payload).where(jobs.c.id == str(submission))
                )
            assert isinstance(payload, dict)
            fields = cast("dict[str, object]", payload)
            kwargs = cast("dict[str, object]", fields["kwargs"])
            metadata = cast("dict[str, object]", kwargs["metadata"])
            assert metadata["team_area"] == "research"
        finally:
            database.close()
    finally:
        _ = marker.with_name(marker.name + ".release").touch()
        stop_test_process(process, log, kill=False)


def test_agui_full_journey_keeps_canonical_actions_and_verification_scope(  # noqa: PLR0915
    queue_environment: tuple[dict[str, str], str, str, str],
    tmp_path: Path,
) -> None:
    environment, token, database_url, schema = queue_environment
    port = _free_port()
    process, log = start_test_process(
        port,
        {
            **environment,
            "SAMURAI_QUEUE_MODEL_MODE": "journey_full",
            "SAMURAI_QUEUE_CANONICAL": "1",
            "SAMURAI_QUEUE_MODEL_MARKER": str(tmp_path / "full-journey-model"),
        },
        tmp_path / "full-journey.log",
    )
    headers = {"Authorization": f"Bearer {token}"}
    root = f"http://127.0.0.1:{port}/agentos"
    try:
        response = httpx.post(
            f"{root}/samurai/workspaces",
            headers=headers,
            json={"display_name": "Full journey integration"},
        )
        assert response.status_code == 201
        workspace = WorkspaceView.model_validate(cast("object", response.json()))
        company_url = f"{root}/samurai/workspaces/{workspace.workspace_id}/companies"
        response = httpx.post(
            company_url, headers={**headers, "Idempotency-Key": str(uuid4())}, json={}
        )
        assert response.status_code == 201
        company = CompanyView.model_validate(cast("object", response.json()))
        assert company.parent_session_id is not None
        session_id = company.parent_session_id
        arguments = {
            "idea": "AI receptionist for Indian dental clinics",
            "target_customer": "Independent Indian dental clinics",
            "geography": "India",
            "budget": "INR 50,000",
            "founder_skills": "Python and Next.js",
            "goal": "Validate demand in 30 days",
        }
        revision = 0
        proof: list[dict[str, object]] = []
        stages = (
            ("brief", "overview", 1, "research"),
            ("research", "research", 3, "strategy"),
            ("strategy", "strategy", 4, "plan"),
            ("plan", "strategy", 6, "sales"),
            ("verify", "verification", 7, "sales"),
        )
        for stage, area, expected, next_action in stages:
            submission = uuid4()
            body = {
                "threadId": session_id,
                "runId": str(submission),
                "messages": [
                    {
                        "id": str(uuid4()),
                        "role": "user",
                        "content": json.dumps(
                            {
                                "tool": "run_company_journey",
                                "arguments": {**arguments, "stage": stage},
                            }
                        ),
                    }
                ],
                "state": {},
                "tools": [],
                "context": [],
                "forwardedProps": {
                    "team_area": area,
                    "work_approval": {
                        "operation": "journey",
                        "stage": stage,
                        "expected_revision": revision,
                        "company_id": str(company.company_id),
                    },
                },
            }
            response = httpx.post(
                f"{root}/agents/samurai/agui", headers=headers, json=body, timeout=30
            )
            assert response.status_code == 200, response.text
            receipt = _wait_for_receipt(port, token, session_id, submission, {"COMPLETED"})
            assert receipt.revision == expected
            response = httpx.post(
                f"{company_url}/{company.company_id}/open", headers=headers, json={}
            )
            assert response.status_code == 200, response.text
            opened = CompanyView.model_validate(cast("object", response.json()))
            assert opened.current_revision == expected
            assert opened.snapshot is not None
            assert opened.snapshot.summary.next_action == next_action
            assert next(
                action for action in opened.snapshot.summary.actions if action.id == next_action
            ).eligible
            retained = _company_state(database_url, schema, "queue-founder", session_id)
            assert len(retained.artifacts) == expected
            assert _resume_events(port, token, receipt)[-1]["event"] == "RunCompleted"
            proof.append(
                {
                    "stage": stage,
                    "area": area,
                    "revision": expected,
                    "next_action": next_action,
                    "receipt": receipt.model_dump(mode="json"),
                }
            )
            revision = expected
        retained = _company_state(database_url, schema, "queue-founder", session_id)
        assert [artifact.artifact_type.value for artifact in retained.artifacts] == [
            "intake",
            "research",
            "research",
            "strategy",
            "product_plan",
            "verification",
            "verification",
        ]
        for kind in ("sales", "builder", "marketer"):
            submission = uuid4()
            area = "sales" if kind == "sales" else "overview"
            body = {
                "threadId": session_id,
                "runId": str(submission),
                "messages": [
                    {
                        "id": str(uuid4()),
                        "role": "user",
                        "content": json.dumps(
                            {
                                "tool": "create_launch_drafts",
                                "arguments": {"kind": kind, "action": "draft"},
                            }
                        ),
                    }
                ],
                "state": {},
                "tools": [],
                "context": [],
                "forwardedProps": {
                    "team_area": area,
                    "work_approval": {
                        "operation": "launch_drafts",
                        "stage": "plan",
                        "expected_revision": revision,
                        "company_id": str(company.company_id),
                    },
                },
            }
            response = httpx.post(
                f"{root}/agents/samurai/agui", headers=headers, json=body, timeout=30
            )
            assert response.status_code == 200, response.text
            receipt = _wait_for_receipt(port, token, session_id, submission, {"COMPLETED"})
            revision += 1
            assert receipt.revision == revision
            retained = _company_state(database_url, schema, "queue-founder", session_id)
            assert retained.artifacts[-1].status == "draft_only"
            assert (
                retained.artifacts[-1].artifact_type.value
                == {
                    "sales": "sales_draft",
                    "builder": "builder_draft",
                    "marketer": "marketing_draft",
                }[kind]
            )
            proof.append(
                {"draft": kind, "revision": revision, "receipt": receipt.model_dump(mode="json")}
            )
        submission = uuid4()
        measured_at = datetime.now(UTC) - timedelta(minutes=1)
        measurement = {
            "name": "qualified_leads",
            "value": 12,
            "unit": "leads",
            "window_start": (measured_at - timedelta(days=7)).isoformat(),
            "window_end": (measured_at - timedelta(hours=1)).isoformat(),
            "source_label": "founder-supplied test ledger",
            "collected_at": measured_at.isoformat(),
        }
        body = {
            "threadId": session_id,
            "runId": str(submission),
            "messages": [
                {
                    "id": str(uuid4()),
                    "role": "user",
                    "content": json.dumps(
                        {"tool": "analyze_metrics", "arguments": {"measurements": [measurement]}}
                    ),
                }
            ],
            "state": {},
            "tools": [],
            "context": [],
            "forwardedProps": {
                "team_area": "overview",
                "work_approval": {
                    "operation": "metrics_analysis",
                    "stage": "plan",
                    "expected_revision": revision,
                    "company_id": str(company.company_id),
                },
            },
        }
        response = httpx.post(f"{root}/agents/samurai/agui", headers=headers, json=body, timeout=30)
        assert response.status_code == 200, response.text
        receipt = _wait_for_receipt(port, token, session_id, submission, {"COMPLETED"})
        assert receipt.revision == revision + 1
        retained = _company_state(database_url, schema, "queue-founder", session_id)
        analysis = retained.artifacts[-1]
        assert analysis.artifact_type.value == "analysis"
        assert analysis.status == "based_on_founder_supplied_metrics"
        assert analysis.measurements[0].provenance == "founder_supplied"
        assert analysis.measurements[0].trusted_connector_receipt is None
        proof.append(
            {
                "operation": "metrics_analysis",
                "revision": receipt.revision,
                "receipt": receipt.model_dump(mode="json"),
            }
        )
        original_ids = [item.artifact_id for item in retained.artifacts]
        arguments["budget"] = "INR 75000"
        for stage, area, expected, next_action in (
            ("brief", "overview", 12, "research"),
            ("research", "research", 14, "strategy"),
            ("strategy", "strategy", 15, "plan"),
            ("plan", "strategy", 17, "sales"),
        ):
            submission = uuid4()
            before = retained.current_revision
            amended_body = {
                **body,
                "runId": str(submission),
                "messages": [
                    {
                        "id": str(uuid4()),
                        "role": "user",
                        "content": json.dumps(
                            {
                                "tool": "run_company_journey",
                                "arguments": {**arguments, "stage": stage},
                            }
                        ),
                    }
                ],
                "forwardedProps": {
                    "team_area": area,
                    "work_approval": {
                        "operation": "journey",
                        "stage": stage,
                        "expected_revision": before,
                        "company_id": str(company.company_id),
                    },
                },
            }
            response = httpx.post(
                f"{root}/agents/samurai/agui", headers=headers, json=amended_body, timeout=30
            )
            assert response.status_code == 200, response.text
            receipt = _wait_for_receipt(port, token, session_id, submission, {"COMPLETED"})
            assert receipt.revision == expected
            retained = _company_state(database_url, schema, "queue-founder", session_id)
            assert [
                item.artifact_id for item in retained.artifacts[: len(original_ids)]
            ] == original_ids
            response = httpx.post(
                f"{company_url}/{company.company_id}/open", headers=headers, json={}
            )
            opened = CompanyView.model_validate(cast("object", response.json()))
            assert opened.snapshot is not None
            assert opened.snapshot.summary.next_action == next_action
            if stage == "brief":
                assert opened.snapshot.summary.current_artifact_ids is not None
                assert (
                    retained.artifacts[3].artifact_id
                    not in opened.snapshot.summary.current_artifact_ids
                )
                assert not next(
                    action for action in opened.snapshot.summary.actions if action.id == "sales"
                ).eligible
            proof.append(
                {
                    "amendment_stage": stage,
                    "revision": expected,
                    "receipt": receipt.model_dump(mode="json"),
                }
            )
        submission = uuid4()
        handoff_body = {
            **amended_body,
            "runId": str(submission),
            "forwardedProps": {
                "team_area": "research",
                "work_approval": {
                    "operation": "journey",
                    "stage": "plan",
                    "expected_revision": 17,
                    "company_id": str(company.company_id),
                },
            },
        }
        response = httpx.post(
            f"{root}/agents/samurai/agui", headers=headers, json=handoff_body, timeout=30
        )
        assert response.status_code == 200, response.text
        assert "SAMURAI_HANDOFF=" in response.text
        receipt = _wait_for_receipt(port, token, session_id, submission, {"COMPLETED"})
        assert _company_state(database_url, schema, "queue-founder", session_id) == retained
        proof.append(
            {
                "scenario": "off-area delivery request produces a handoff without mutation",
                "receipt": receipt.model_dump(mode="json"),
            }
        )
        _record_evidence(
            "full-customer-journey.json",
            {"external_provider_calls": 0, "public_source_fetches": 0, "steps": proof},
        )
    finally:
        stop_test_process(process, log, kill=False)


def test_agui_stream_failure_keeps_receipt_and_native_run_failed(
    queue_environment: tuple[dict[str, str], str, str, str], tmp_path: Path
) -> None:
    environment, token, _database_url, _schema = queue_environment
    port, submission = _free_port(), uuid4()
    session_id = f"agui-failure-{uuid4()}"
    marker = tmp_path / "stream-failure-model"
    process, log = start_test_process(
        port,
        {
            **environment,
            "SAMURAI_QUEUE_MODEL_MODE": "stream_failure",
            "SAMURAI_QUEUE_MODEL_MARKER": str(marker),
        },
        tmp_path / "agui-failure.log",
    )
    try:
        response = httpx.post(
            f"http://127.0.0.1:{port}/agentos/agents/samurai/agui",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "threadId": session_id,
                "runId": str(submission),
                "messages": [{"id": "turn", "role": "user", "content": "Discuss our research"}],
                "state": {},
                "context": [],
                "tools": [],
                "forwardedProps": {"team_area": "research"},
            },
            timeout=60,
        )
        assert response.status_code == 200
        assert "RUN_ERROR" in response.text
        assert "provider-free-stream-failure" not in response.text
        receipt = _wait_for_receipt(port, token, session_id, submission, {"ERROR"})
        assert receipt.attempt == receipt.max_attempts == 2
        saved = httpx.get(
            f"http://127.0.0.1:{port}/agentos/agents/samurai/runs/{receipt.run_id}",
            params={"session_id": session_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert saved.status_code == 200
        assert saved.json()["status"] == "ERROR"
        assert marker.read_text().splitlines() == [str(process.pid), str(process.pid)]
    finally:
        stop_test_process(process, log, kill=False)
