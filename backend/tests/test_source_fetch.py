from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal, TypedDict, Unpack, final

import anyio
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pydantic import BaseModel, ConfigDict, TypeAdapter

from samurai import source_fetch
from samurai.source_fetch import (
    SourceFetchFailure,
    SourceFetchSuccess,
    fetch_sources,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from types import TracebackType

    from anyio.abc import Process


_HELPER_PATH = Path(source_fetch.__file__).with_name("source_fetch_helper.py").resolve()


@dataclass(slots=True)
class _SpawnCapture:
    command: tuple[str, ...] = ()
    stdin: int | None = None
    stdout: int | None = None
    stderr: int | None = None
    cwd: Path | None = None
    env: Mapping[str, str] | None = None
    pass_fds: tuple[int, ...] = ()
    start_new_session: bool = False


@dataclass(frozen=True, slots=True)
class _TestProcessLimits:
    total_seconds: float = 20.0
    cleanup_seconds: float = 2.0
    terminate_grace_seconds: float = 0.25
    stdin_bytes: int = 16 * 1024
    stdout_bytes: int = 2 * 1024 * 1024
    stderr_bytes: int = 4 * 1024


class _OpenProcessOptions(TypedDict):
    stdin: int
    stdout: int
    stderr: int
    cwd: Path
    env: Mapping[str, str]
    pass_fds: Sequence[int]
    start_new_session: bool


class _CaEvidence(BaseModel):
    cafile: str
    exists: bool
    count: int


class _ParentRequest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    version: int
    urls: tuple[str, ...]
    remaining_budget_ms: int


@dataclass(frozen=True, slots=True)
class _TlsReply:
    payload: bytes
    chunk_size: int = 0
    delay_seconds: float = 0.0
    immediate_bytes: int = 0
    before_seconds: float = 0.0


@final
class _TlsServer:
    def __init__(
        self,
        certificate_path: Path,
        key_path: Path,
        replies: tuple[_TlsReply, ...],
    ) -> None:
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen()
        self._listener.settimeout(2)
        _host, self.port = TypeAdapter(tuple[str, int]).validate_python(
            self._listener.getsockname()
        )
        self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._context.load_cert_chain(certificate_path, key_path)
        self._context.set_servername_callback(self._record_sni)
        self._replies = replies
        self.requests: list[bytes] = []
        self.server_names: list[str | None] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> _TlsServer:
        self._thread.start()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exception_type, exception, traceback
        self._listener.close()
        self._thread.join(timeout=3)
        assert not self._thread.is_alive()

    def _record_sni(
        self,
        connection: ssl.SSLSocket | ssl.SSLObject,
        server_name: str | None,
        context: ssl.SSLSocket,
    ) -> None:
        del connection, context
        self.server_names.append(server_name)

    def _serve(self) -> None:
        for reply in self._replies:
            try:
                raw_connection = self._listener.accept()[0]
                with self._context.wrap_socket(raw_connection, server_side=True) as connection:
                    connection.settimeout(2)
                    request = bytearray()
                    while b"\r\n\r\n" not in request:
                        chunk = connection.recv(4096)
                        if not chunk:
                            break
                        request.extend(chunk)
                    self.requests.append(bytes(request))
                    time.sleep(reply.before_seconds)
                    if reply.chunk_size:
                        connection.sendall(reply.payload[: reply.immediate_bytes])
                        for index in range(
                            reply.immediate_bytes,
                            len(reply.payload),
                            reply.chunk_size,
                        ):
                            connection.sendall(reply.payload[index : index + reply.chunk_size])
                            time.sleep(reply.delay_seconds)
                    else:
                        connection.sendall(reply.payload)
            except OSError, ssl.SSLError:
                continue


def _certificate(tmp_path: Path, hostname: str) -> tuple[Path, Path]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(private_key, hashes.SHA256())
    )
    certificate_path = tmp_path / f"{hostname}.pem"
    key_path = tmp_path / f"{hostname}.key"
    _ = certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    _ = key_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return certificate_path, key_path


def _launcher(path: Path, body: str) -> tuple[str, ...]:
    _ = path.write_text(body, encoding="utf-8")
    return sys.executable, "-I", "-S", str(path)


def _load_helper_source() -> str:
    return (
        "import importlib.util, sys\n"
        f"path={json.dumps(str(_HELPER_PATH))}\n"
        "spec=importlib.util.spec_from_file_location('samurai_source_fetch_helper', path)\n"
        "module=importlib.util.module_from_spec(spec)\n"
        "sys.modules[spec.name]=module\n"
        "spec.loader.exec_module(module)\n"
    )


def _tls_launcher(
    path: Path,
    *,
    port: int,
    certificate_path: Path,
    read_seconds: float | None = None,
    reject_changed_resolution: Path | None = None,
) -> tuple[str, ...]:
    read_override = "" if read_seconds is None else f"module._READ_SECONDS={read_seconds!r}\n"
    resolution_evidence = (
        ""
        if reject_changed_resolution is None
        else (
            f"open({json.dumps(str(reject_changed_resolution))},'w',"
            "encoding='utf-8').write(str(resolve_count))\n"
        )
    )
    body = "".join(
        (
            _load_helper_source(),
            "import socket, ssl\n",
            "original_resolve=module._resolve\n",
            "resolve_count=0\n",
            "def resolve(hostname, port, deadline):\n",
            " global resolve_count\n",
            " resolve_count+=1\n",
            (
                " if resolve_count > 1:\n  raise module._FetchError\n"
                if reject_changed_resolution is not None
                else ""
            ),
            " if hostname != 'source.test':\n",
            "  return original_resolve(hostname, port, deadline)\n",
            " return (module._Resolved(socket.AF_INET,socket.SOCK_STREAM,",
            "socket.IPPROTO_TCP,('93.184.216.34',443)),)\n",
            "def connect(resolved, deadline):\n",
            " connection=socket.socket(socket.AF_INET,socket.SOCK_STREAM)\n",
            " connection.settimeout(module._remaining(deadline,module._STAGE_SECONDS))\n",
            f" connection.connect(('127.0.0.1',{port}))\n",
            " return connection\n",
            "def context():\n",
            f" return ssl.create_default_context(cafile={json.dumps(str(certificate_path))})\n",
            "module._resolve=resolve\n",
            "module._connect=connect\n",
            "module._create_tls_context=context\n",
            read_override,
            "rc=module.main()\n",
            resolution_evidence,
            "raise SystemExit(rc)\n",
        )
    )
    return _launcher(path, body)


def _response(
    status: str,
    body: bytes = b"",
    *,
    headers: tuple[tuple[str, str], ...] = (("Content-Type", "text/html; charset=utf-8"),),
    include_length: bool = True,
) -> bytes:
    rendered_headers = list(headers)
    if include_length:
        rendered_headers.append(("Content-Length", str(len(body))))
    header_lines = "".join(f"{name}: {value}\r\n" for name, value in rendered_headers)
    return f"HTTP/1.1 {status}\r\n{header_lines}Connection: close\r\n\r\n".encode() + body


def _wait_for_file(path: Path) -> None:
    deadline = time.monotonic() + 2
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError
        time.sleep(0.01)


def _assert_process_gone(pid: int) -> None:
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    with pytest.raises(ChildProcessError):
        _ = os.waitpid(pid, os.WNOHANG)


def test_rejects_private_destination_without_returning_source_content() -> None:
    result = anyio.run(fetch_sources, ("http://127.0.0.1/secret",))

    assert result == (
        SourceFetchFailure(
            original_url="http://127.0.0.1/secret",
            reason="inaccessible",
        ),
    )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "http://user:password@example.com/",
        "http://example.com/#fragment",
        "http://example.com:8080/",
        "https://example.com:444/",
        "http://0.0.0.0/",
        "http://10.0.0.1/",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.1/",
        "http://224.0.0.1/",
        "http://240.0.0.1/",
        "http://[::]/",
        "http://[::1]/",
        "http://[ff02::1]/",
        "http://[::ffff:127.0.0.1]/",
    ],
)
def test_rejects_unsafe_url_and_address_classes(url: str) -> None:
    result = anyio.run(fetch_sources, (url,))

    assert result == (SourceFetchFailure(original_url=url),)


def test_rejects_mixed_public_private_dns_answers(tmp_path: Path) -> None:
    launcher = tmp_path / "mixed_dns.py"
    body = _load_helper_source() + (
        "import socket\n"
        "def mixed(*args, **kwargs):\n"
        " return [(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',"
        "('93.184.216.34',80)),(socket.AF_INET,socket.SOCK_STREAM,"
        "socket.IPPROTO_TCP,'',('127.0.0.1',80))]\n"
        "module.socket.getaddrinfo=mixed\n"
        "raise SystemExit(module.main())\n"
    )

    result = anyio.run(
        lambda: fetch_sources(
            ("http://source.test/",),
            _command_factory=lambda _directory: _launcher(launcher, body),
        )
    )

    assert result == (SourceFetchFailure(original_url="http://source.test/"),)


def test_process_spawn_is_fixed_isolated_and_closes_parent_descriptors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = os.open(tmp_path / "sentinel", os.O_CREAT | os.O_RDWR, 0o600)
    desired_inheritable = True
    os.set_inheritable(sentinel, desired_inheritable)
    launcher = tmp_path / "sentinel_launcher.py"
    body = "".join(
        (
            "import os\n",
            "try:\n",
            f" os.fstat({sentinel})\n",
            "except OSError:\n",
            " pass\n",
            "else:\n",
            " raise SystemExit(91)\n",
            _load_helper_source(),
            "raise SystemExit(module.main())\n",
        )
    )
    capture = _SpawnCapture()
    original_open_process = anyio.open_process

    async def recording_open_process(
        command: Sequence[str], **options: Unpack[_OpenProcessOptions]
    ) -> Process:
        capture.command = tuple(command)
        capture.stdin = options["stdin"]
        capture.stdout = options["stdout"]
        capture.stderr = options["stderr"]
        capture.cwd = options["cwd"]
        capture.env = options["env"]
        capture.pass_fds = tuple(options["pass_fds"])
        capture.start_new_session = options["start_new_session"]
        return await original_open_process(
            command,
            **options,
        )

    monkeypatch.setattr(anyio, "open_process", recording_open_process)
    try:
        result = anyio.run(
            lambda: fetch_sources(
                ("http://127.0.0.1/",),
                _command_factory=lambda _directory: _launcher(launcher, body),
            )
        )
    finally:
        os.close(sentinel)

    assert result == (SourceFetchFailure(original_url="http://127.0.0.1/"),)
    assert capture.command == (sys.executable, "-I", "-S", str(launcher))
    assert capture.stdin == subprocess.PIPE
    assert capture.stdout == subprocess.PIPE
    assert capture.stderr == subprocess.PIPE
    assert capture.cwd is not None
    assert not capture.cwd.exists()
    assert capture.env == {}
    assert capture.pass_fds == ()
    assert capture.start_new_session is True


def test_parent_sends_only_bounded_protocol_fields(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    launcher = tmp_path / "capture_request.py"
    body = "".join(
        (
            _load_helper_source(),
            "raw=module.sys.stdin.buffer.read(module._MAX_INPUT_BYTES+1)\n",
            f"open({json.dumps(str(request_path))},'wb').write(raw)\n",
            "module.sys.stdout.buffer.write(module._run(raw))\n",
            "raise SystemExit(0)\n",
        )
    )

    result = anyio.run(
        lambda: fetch_sources(
            ("http://127.0.0.1/", "http://127.0.0.1/"),
            _command_factory=lambda _directory: _launcher(launcher, body),
        )
    )
    request = _ParentRequest.model_validate_json(request_path.read_bytes())

    assert result == (SourceFetchFailure(original_url="http://127.0.0.1/"),)
    assert request.version == 1
    assert request.urls == ("http://127.0.0.1/",)
    assert 0 < request.remaining_budget_ms <= 20_000
    assert len(request_path.read_bytes()) <= 16 * 1024


def test_parent_remaining_budget_is_computed_after_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = tmp_path / "request.json"
    launcher = tmp_path / "capture_delayed_request.py"
    body = "".join(
        (
            _load_helper_source(),
            "raw=module.sys.stdin.buffer.read(module._MAX_INPUT_BYTES+1)\n",
            f"open({json.dumps(str(request_path))},'wb').write(raw)\n",
            "module.sys.stdout.buffer.write(module._run(raw))\n",
            "raise SystemExit(0)\n",
        ),
    )
    original_open_process = anyio.open_process

    async def delayed_open_process(
        command: Sequence[str], **options: Unpack[_OpenProcessOptions]
    ) -> Process:
        await anyio.sleep(0.2)
        return await original_open_process(command, **options)

    monkeypatch.setattr(anyio, "open_process", delayed_open_process)

    _ = anyio.run(
        lambda: fetch_sources(
            ("http://127.0.0.1/",),
            _limits=_TestProcessLimits(total_seconds=0.6),
            _command_factory=lambda _directory: _launcher(launcher, body),
        ),
    )
    request = _ParentRequest.model_validate_json(request_path.read_bytes())

    assert 0 < request.remaining_budget_ms < 500


def test_parent_rejects_more_than_five_urls_before_spawn() -> None:
    urls = tuple(f"https://source-{index}.test/" for index in range(6))

    def unexpected_spawn(_directory: Path) -> tuple[str, ...]:
        raise AssertionError

    result = anyio.run(
        lambda: fetch_sources(urls, _command_factory=unexpected_spawn),
    )

    assert result == tuple(SourceFetchFailure(original_url=url) for url in urls)


def test_parent_rejects_non_strict_helper_response(tmp_path: Path) -> None:
    launcher = tmp_path / "malformed_response.py"
    body = (
        'import sys\nsys.stdin.buffer.read()\nsys.stdout.write(\'{"version":"1","results":[]}\')\n'
    )

    result = anyio.run(
        lambda: fetch_sources(
            ("https://source.test/",),
            _command_factory=lambda _directory: _launcher(launcher, body),
        ),
    )

    assert result == (SourceFetchFailure(original_url="https://source.test/"),)


@pytest.mark.parametrize("version", [True, 1.0])
def test_helper_rejects_non_integer_request_version(version: object) -> None:
    request = json.dumps(
        {
            "version": version,
            "urls": ["https://source.test/"],
            "remaining_budget_ms": 1000,
        },
        separators=(",", ":"),
    ).encode()

    completed = anyio.run(
        lambda: anyio.run_process(
            [sys.executable, "-I", "-S", str(_HELPER_PATH)],
            input=request,
            env={},
            check=False,
        ),
    )

    assert completed.returncode == 2
    assert completed.stdout == b""
    assert completed.stderr == b""


def test_helper_attempts_only_one_validated_sockaddr_per_hop(tmp_path: Path) -> None:
    attempts_path = tmp_path / "attempts.json"
    launcher = tmp_path / "single_address.py"
    body = _load_helper_source() + (
        "import json, socket\n"
        "attempts=[]\n"
        "def resolve(hostname, port, deadline):\n"
        " return (module._Resolved(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,"
        "('93.184.216.34',80)),module._Resolved(socket.AF_INET,socket.SOCK_STREAM,"
        "socket.IPPROTO_TCP,('1.1.1.1',80)))\n"
        "def connect(resolved, deadline):\n"
        " attempts.append(resolved.sockaddr[0])\n"
        f" path={json.dumps(str(attempts_path))}\n"
        " open(path,'w',encoding='utf-8').write(json.dumps(attempts))\n"
        " raise OSError\n"
        "module._resolve=resolve\n"
        "module._connect=connect\n"
        "raise SystemExit(module.main())\n"
    )

    result = anyio.run(
        lambda: fetch_sources(
            ("http://source.test/",),
            _command_factory=lambda _directory: _launcher(launcher, body),
        ),
    )

    assert result == (SourceFetchFailure(original_url="http://source.test/"),)
    assert TypeAdapter(list[str]).validate_json(attempts_path.read_bytes()) == ["93.184.216.34"]


def test_cancellation_during_spawn_waits_for_handle_then_reaps_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid_path = tmp_path / "spawn.pid"
    launcher = tmp_path / "spawn_blocked.py"
    body = "".join(
        (
            "import os, signal\n",
            f"open({json.dumps(str(pid_path))},'w',encoding='utf-8').write(str(os.getpid()))\n",
            "while True:\n",
            " signal.pause()\n",
        )
    )
    spawned = anyio.Event()
    original_open_process = anyio.open_process

    async def delayed_open_process(
        command: Sequence[str], **options: Unpack[_OpenProcessOptions]
    ) -> Process:
        process = await original_open_process(command, **options)
        await anyio.to_thread.run_sync(_wait_for_file, pid_path)
        spawned.set()
        await anyio.sleep(0.2)
        return process

    monkeypatch.setattr(anyio, "open_process", delayed_open_process)

    async def scenario() -> bool:
        cancellation_observed = False

        async def invoke() -> None:
            nonlocal cancellation_observed
            try:
                _ = await fetch_sources(
                    ("https://source.test/",),
                    _command_factory=lambda _directory: _launcher(launcher, body),
                )
            except anyio.get_cancelled_exc_class():
                cancellation_observed = True
                raise

        async with anyio.create_task_group() as tasks:
            _ = tasks.start_soon(invoke)
            await spawned.wait()
            tasks.cancel_scope.cancel()
        return cancellation_observed

    assert anyio.run(scenario) is True
    _assert_process_gone(int(pid_path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("mode", ["timeout", "cancel"])
def test_blocked_resolver_is_terminated_reaped_and_cleaned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: Literal["timeout", "cancel"],
) -> None:
    pid_path = tmp_path / "helper.pid"
    launcher = tmp_path / "blocked_resolver.py"
    body = _load_helper_source() + (
        "import os, signal\n"
        f"open({json.dumps(str(pid_path))},'w',encoding='utf-8').write(str(os.getpid()))\n"
        "def blocked(*args, **kwargs):\n"
        " while True:\n"
        "  signal.pause()\n"
        "module.socket.getaddrinfo=blocked\n"
        "raise SystemExit(module.main())\n"
    )
    created_directories: list[Path] = []
    original_mkdtemp = tempfile.mkdtemp

    def recording_mkdtemp(*, prefix: str) -> str:
        path = Path(original_mkdtemp(prefix=prefix, dir=tmp_path))
        created_directories.append(path)
        return str(path)

    monkeypatch.setattr(tempfile, "mkdtemp", recording_mkdtemp)

    async def scenario() -> tuple[tuple[SourceFetchFailure, ...] | None, bool]:
        result: tuple[SourceFetchFailure, ...] | None = None
        cancellation_observed = False

        async def invoke() -> None:
            nonlocal result, cancellation_observed
            try:
                fetched = await fetch_sources(
                    ("http://source.test/",),
                    _limits=_TestProcessLimits(total_seconds=0.25),
                    _command_factory=lambda _directory: _launcher(launcher, body),
                )
                result = tuple(item for item in fetched if isinstance(item, SourceFetchFailure))
            except anyio.get_cancelled_exc_class():
                cancellation_observed = True
                raise

        if mode == "cancel":
            async with anyio.create_task_group() as tasks:
                _ = tasks.start_soon(invoke)
                await anyio.to_thread.run_sync(_wait_for_file, pid_path)
                tasks.cancel_scope.cancel()
        else:
            await invoke()
        return result, cancellation_observed

    result, cancellation_observed = anyio.run(scenario)
    pid = int(pid_path.read_text(encoding="utf-8"))

    _assert_process_gone(pid)
    assert all(not path.exists() for path in created_directories)
    if mode == "cancel":
        assert result is None
        assert cancellation_observed is True
    else:
        assert result == (SourceFetchFailure(original_url="http://source.test/"),)
        assert cancellation_observed is False


def test_oversized_stdout_kills_hanging_helper_promptly(tmp_path: Path) -> None:
    pid_path = tmp_path / "overflow.pid"
    launcher = tmp_path / "overflow.py"
    stdout_limit = 1024
    body = (
        "import os, signal, sys\n"
        f"open({json.dumps(str(pid_path))},'w',encoding='utf-8').write(str(os.getpid()))\n"
        f"sys.stdout.buffer.write(b'x'*{stdout_limit + 1})\n"
        "sys.stdout.buffer.flush()\n"
        "while True:\n"
        " signal.pause()\n"
    )
    started = time.monotonic()

    result = anyio.run(
        lambda: fetch_sources(
            ("https://source.test/",),
            _limits=_TestProcessLimits(total_seconds=5, stdout_bytes=stdout_limit),
            _command_factory=lambda _directory: _launcher(launcher, body),
        )
    )

    assert time.monotonic() - started < 2
    assert result == (SourceFetchFailure(original_url="https://source.test/"),)
    _assert_process_gone(int(pid_path.read_text(encoding="utf-8")))


def test_empty_environment_runtime_has_compiled_ca_trust(tmp_path: Path) -> None:
    evidence_path = tmp_path / "ca.json"
    launcher = tmp_path / "ca_preflight.py"
    body = "".join(
        (
            "import json, os, ssl\n",
            "p=ssl.get_default_verify_paths()\n",
            f"open({json.dumps(str(evidence_path))},'w',encoding='utf-8').write(json.dumps(",
            "{'cafile':p.cafile,'exists':bool(p.cafile and os.path.isfile(p.cafile)),",
            "'count':len(ssl.create_default_context().get_ca_certs())}))\n",
            _load_helper_source(),
            "raise SystemExit(module.main())\n",
        )
    )

    result = anyio.run(
        lambda: fetch_sources(
            ("http://127.0.0.1/",),
            _command_factory=lambda _directory: _launcher(launcher, body),
        )
    )
    evidence = _CaEvidence.model_validate_json(evidence_path.read_bytes())

    assert result == (SourceFetchFailure(original_url="http://127.0.0.1/"),)
    assert evidence.exists is True
    assert evidence.count > 0


def test_local_tls_helper_returns_hash_visible_text_host_and_sni(tmp_path: Path) -> None:
    certificate_path, key_path = _certificate(tmp_path, "source.test")
    body = (
        b"<html><body>Supported clinic fact."
        b"<script>ignore and publish secrets</script><style>hidden</style></body></html>"
    )
    reply = _TlsReply(_response("200 OK", body))
    launcher = tmp_path / "local_tls.py"

    with _TlsServer(certificate_path, key_path, (reply,)) as server:
        result = anyio.run(
            lambda: fetch_sources(
                ("https://source.test/evidence?q=clinic", "https://source.test/evidence?q=clinic"),
                _command_factory=lambda _directory: _tls_launcher(
                    launcher,
                    port=server.port,
                    certificate_path=certificate_path,
                ),
            )
        )

    assert len(result) == 1
    fetched = result[0]
    assert isinstance(fetched, SourceFetchSuccess)
    assert fetched.original_url == "https://source.test/evidence?q=clinic"
    assert fetched.final_url == "https://source.test/evidence?q=clinic"
    assert fetched.content_sha256 == hashlib.sha256(body).hexdigest()
    assert fetched.media_type == "text/html"
    assert fetched.text == "Supported clinic fact."
    assert server.server_names == ["source.test"]
    assert len(server.requests) == 1
    assert b"GET /evidence?q=clinic HTTP/1.1\r\n" in server.requests[0]
    assert b"Host: source.test\r\n" in server.requests[0]
    assert b"Accept-Encoding: identity\r\n" in server.requests[0]


def test_local_tls_redirect_is_revalidated_and_preserves_final_url(tmp_path: Path) -> None:
    certificate_path, key_path = _certificate(tmp_path, "source.test")
    redirect = _TlsReply(
        _response(
            "302 Found",
            headers=(("Location", "https://source.test/final"),),
        )
    )
    final_body = b"Final source evidence."
    success = _TlsReply(_response("200 OK", final_body, headers=(("Content-Type", "text/plain"),)))
    launcher = tmp_path / "redirect.py"

    with _TlsServer(certificate_path, key_path, (redirect, success)) as server:
        result = anyio.run(
            lambda: fetch_sources(
                ("https://source.test/start",),
                _command_factory=lambda _directory: _tls_launcher(
                    launcher,
                    port=server.port,
                    certificate_path=certificate_path,
                ),
            )
        )

    assert isinstance(result[0], SourceFetchSuccess)
    assert result[0].final_url == "https://source.test/final"
    assert result[0].text == "Final source evidence."
    assert server.server_names == ["source.test", "source.test"]
    assert [request.split(b" ", 2)[1] for request in server.requests] == [b"/start", b"/final"]


@pytest.mark.parametrize(
    "location",
    ["http://127.0.0.1/private", "https://source.test/start"],
    ids=["unsafe_destination", "redirect_loop"],
)
def test_local_tls_rejects_unsafe_and_looping_redirects(
    tmp_path: Path,
    location: str,
) -> None:
    certificate_path, key_path = _certificate(tmp_path, "source.test")
    redirect = _TlsReply(_response("302 Found", headers=(("Location", location),)))
    launcher = tmp_path / "rejected_redirect.py"

    with _TlsServer(certificate_path, key_path, (redirect,)) as server:
        result = anyio.run(
            lambda: fetch_sources(
                ("https://source.test/start",),
                _command_factory=lambda _directory: _tls_launcher(
                    launcher,
                    port=server.port,
                    certificate_path=certificate_path,
                ),
            )
        )

    assert result == (SourceFetchFailure(original_url="https://source.test/start"),)
    assert len(server.requests) == 1


def test_local_tls_redirect_rejects_changed_dns_answer(tmp_path: Path) -> None:
    certificate_path, key_path = _certificate(tmp_path, "source.test")
    redirect = _TlsReply(
        _response(
            "302 Found",
            headers=(("Location", "https://source.test/final"),),
        )
    )
    resolution_count_path = tmp_path / "resolution-count.txt"
    launcher = tmp_path / "changed_dns.py"

    with _TlsServer(certificate_path, key_path, (redirect,)) as server:
        result = anyio.run(
            lambda: fetch_sources(
                ("https://source.test/start",),
                _command_factory=lambda _directory: _tls_launcher(
                    launcher,
                    port=server.port,
                    certificate_path=certificate_path,
                    reject_changed_resolution=resolution_count_path,
                ),
            )
        )

    assert result == (SourceFetchFailure(original_url="https://source.test/start"),)
    assert resolution_count_path.read_text(encoding="utf-8") == "2"
    assert len(server.requests) == 1


@pytest.mark.parametrize(
    ("reply", "name"),
    [
        (_TlsReply(_response("404 Not Found")), "unsupported_status"),
        (
            _TlsReply(_response("200 OK", b"{}", headers=(("Content-Type", "application/json"),))),
            "unsupported_media",
        ),
        (
            _TlsReply(
                _response(
                    "200 OK",
                    b"compressed",
                    headers=(("Content-Type", "text/plain"), ("Content-Encoding", "gzip")),
                )
            ),
            "unsupported_encoding",
        ),
        (
            _TlsReply(
                _response(
                    "200 OK",
                    b"short",
                    headers=(
                        ("Content-Type", "text/plain"),
                        ("Content-Length", str(256 * 1024 + 1)),
                    ),
                    include_length=False,
                )
            ),
            "declared_oversized",
        ),
    ],
)
def test_local_tls_rejects_unsupported_responses(
    tmp_path: Path,
    reply: _TlsReply,
    name: str,
) -> None:
    certificate_path, key_path = _certificate(tmp_path, "source.test")
    launcher = tmp_path / f"{name}.py"

    with _TlsServer(certificate_path, key_path, (reply,)) as server:
        result = anyio.run(
            lambda: fetch_sources(
                ("https://source.test/",),
                _command_factory=lambda _directory: _tls_launcher(
                    launcher,
                    port=server.port,
                    certificate_path=certificate_path,
                ),
            )
        )

    assert result == (SourceFetchFailure(original_url="https://source.test/"),)


def test_local_tls_rejects_streamed_oversized_body(tmp_path: Path) -> None:
    certificate_path, key_path = _certificate(tmp_path, "source.test")
    oversized = b"x" * (256 * 1024 + 1)
    reply = _TlsReply(
        _response("200 OK", oversized, include_length=False),
        chunk_size=16 * 1024,
    )
    launcher = tmp_path / "streamed_oversized.py"

    with _TlsServer(certificate_path, key_path, (reply,)) as server:
        result = anyio.run(
            lambda: fetch_sources(
                ("https://source.test/",),
                _command_factory=lambda _directory: _tls_launcher(
                    launcher,
                    port=server.port,
                    certificate_path=certificate_path,
                ),
            )
        )

    assert result == (SourceFetchFailure(original_url="https://source.test/"),)


def test_local_tls_rejects_wrong_hostname_certificate(tmp_path: Path) -> None:
    certificate_path, key_path = _certificate(tmp_path, "wrong.test")
    launcher = tmp_path / "wrong_hostname.py"
    reply = _TlsReply(_response("200 OK", b"must not be accepted"))

    with _TlsServer(certificate_path, key_path, (reply,)) as server:
        result = anyio.run(
            lambda: fetch_sources(
                ("https://source.test/",),
                _command_factory=lambda _directory: _tls_launcher(
                    launcher,
                    port=server.port,
                    certificate_path=certificate_path,
                ),
            )
        )

    assert result == (SourceFetchFailure(original_url="https://source.test/"),)
    assert server.server_names == ["source.test"]
    assert server.requests == []


def test_slow_drip_headers_obey_absolute_read_cap(tmp_path: Path) -> None:
    certificate_path, key_path = _certificate(tmp_path, "source.test")
    reply = _TlsReply(
        _response("200 OK", b"slow"),
        chunk_size=1,
        delay_seconds=0.03,
    )
    launcher = tmp_path / "slow_headers.py"
    started = time.monotonic()

    with _TlsServer(certificate_path, key_path, (reply,)) as server:
        result = anyio.run(
            lambda: fetch_sources(
                ("https://source.test/",),
                _limits=_TestProcessLimits(total_seconds=1),
                _command_factory=lambda _directory: _tls_launcher(
                    launcher,
                    port=server.port,
                    certificate_path=certificate_path,
                    read_seconds=0.15,
                ),
            )
        )

    assert time.monotonic() - started < 1
    assert result == (SourceFetchFailure(original_url="https://source.test/"),)


def test_local_tls_slow_body_obeys_absolute_read_cap(tmp_path: Path) -> None:
    certificate_path, key_path = _certificate(tmp_path, "source.test")
    payload = _response("200 OK", b"slow-body-evidence")
    header_end = payload.index(b"\r\n\r\n") + 4
    reply = _TlsReply(
        payload,
        chunk_size=1,
        delay_seconds=0.03,
        immediate_bytes=header_end,
    )
    launcher = tmp_path / "slow_body.py"
    started = time.monotonic()

    with _TlsServer(certificate_path, key_path, (reply,)) as server:
        result = anyio.run(
            lambda: fetch_sources(
                ("https://source.test/",),
                _limits=_TestProcessLimits(total_seconds=1),
                _command_factory=lambda _directory: _tls_launcher(
                    launcher,
                    port=server.port,
                    certificate_path=certificate_path,
                    read_seconds=0.15,
                ),
            ),
        )

    assert time.monotonic() - started < 1
    assert result == (SourceFetchFailure(original_url="https://source.test/"),)


def test_local_tls_remaining_budget_spans_redirect_and_slow_body(tmp_path: Path) -> None:
    certificate_path, key_path = _certificate(tmp_path, "source.test")
    redirect = _TlsReply(
        _response(
            "302 Found",
            headers=(("Location", "https://source.test/final"),),
        ),
        before_seconds=0.15,
    )
    payload = _response("200 OK", b"bounded-body-evidence")
    header_end = payload.index(b"\r\n\r\n") + 4
    slow_body = _TlsReply(
        payload,
        chunk_size=1,
        delay_seconds=0.04,
        immediate_bytes=header_end,
    )
    launcher = tmp_path / "remaining_budget.py"
    started = time.monotonic()

    with _TlsServer(certificate_path, key_path, (redirect, slow_body)) as server:
        result = anyio.run(
            lambda: fetch_sources(
                ("https://source.test/start",),
                _limits=_TestProcessLimits(total_seconds=0.45),
                _command_factory=lambda _directory: _tls_launcher(
                    launcher,
                    port=server.port,
                    certificate_path=certificate_path,
                ),
            ),
        )

    assert time.monotonic() - started < 1
    assert result == (SourceFetchFailure(original_url="https://source.test/start"),)
    assert len(server.requests) == 2
