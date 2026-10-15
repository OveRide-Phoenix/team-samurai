"""Fetch retained public sources through one bounded, killable helper process."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, ClassVar, Final, Literal, Protocol

import anyio
from anyio import EndOfStream
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from anyio.abc import ByteReceiveStream, ByteSendStream, Process

_PROTOCOL_VERSION: Final = 1
_HELPER_PATH: Final = Path(__file__).with_name("source_fetch_helper.py").resolve()
_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
_MAX_URLS: Final = 5


@dataclass(frozen=True, slots=True)
class SourceFetchSuccess:
    """Bounded fetched content and the provenance needed by adjudication."""

    original_url: str
    final_url: str
    fetched_at: datetime
    content_sha256: str
    media_type: str
    text: str


@dataclass(frozen=True, slots=True)
class SourceFetchFailure:
    """Sanitized result for any inaccessible or rejected source."""

    original_url: str
    reason: Literal["inaccessible"] = "inaccessible"


type SourceFetchResult = SourceFetchSuccess | SourceFetchFailure


@dataclass(frozen=True, slots=True)
class _ProcessLimits:
    total_seconds: float = 20.0
    cleanup_seconds: float = 2.0
    terminate_grace_seconds: float = 0.25
    stdin_bytes: int = 16 * 1024
    stdout_bytes: int = 2 * 1024 * 1024
    stderr_bytes: int = 4 * 1024


_DEFAULT_LIMITS: Final = _ProcessLimits()


class _ProcessLimitValues(Protocol):
    @property
    def total_seconds(self) -> float: ...

    @property
    def cleanup_seconds(self) -> float: ...

    @property
    def terminate_grace_seconds(self) -> float: ...

    @property
    def stdin_bytes(self) -> int: ...

    @property
    def stdout_bytes(self) -> int: ...

    @property
    def stderr_bytes(self) -> int: ...


@dataclass(slots=True)
class _Capture:
    data: bytearray
    overflowed: bool = False


class _SourceFetchInternalError(RuntimeError):
    pass


class _ProtocolError(ValueError):
    pass


type _CommandFactory = Callable[[Path], Sequence[str]]


class _ResponseModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)


class _SuccessRow(_ResponseModel):
    status: Literal["success"]
    original_url: str
    final_url: str
    fetched_at: str
    content_sha256: str
    media_type: Literal["text/html", "application/xhtml+xml", "text/plain"]
    text: str = Field(max_length=64 * 1024)


class _FailureRow(_ResponseModel):
    status: Literal["failure"]
    original_url: str
    reason: Literal["inaccessible"]


class _HelperResponse(_ResponseModel):
    version: Literal[1]
    results: tuple[Annotated[_SuccessRow | _FailureRow, Field(discriminator="status")], ...]


def _production_command(_temporary_directory: Path) -> Sequence[str]:
    return (sys.executable, "-I", "-S", str(_HELPER_PATH))


async def fetch_sources(
    urls: Sequence[str],
    *,
    _limits: _ProcessLimitValues = _DEFAULT_LIMITS,
    _command_factory: _CommandFactory = _production_command,
) -> tuple[SourceFetchResult, ...]:
    """Fetch at most five deduplicated URLs within one authoritative deadline."""
    retained_urls = tuple(dict.fromkeys(urls))
    if not retained_urls:
        return ()
    if len(retained_urls) > _MAX_URLS or any(not url for url in retained_urls):
        return _failures(retained_urls)

    deadline = anyio.current_time() + _limits.total_seconds
    temporary_directory = Path(tempfile.mkdtemp(prefix="samurai-source-fetch-"))
    process: Process | None = None
    response: bytes | None = None
    failed = False
    try:
        remaining_ms = max(1, int((deadline - anyio.current_time()) * 1000))
        request = json.dumps(
            {
                "version": _PROTOCOL_VERSION,
                "urls": list(retained_urls),
                "remaining_budget_ms": remaining_ms,
            },
            separators=(",", ":"),
        ).encode()
        if len(request) > _limits.stdin_bytes:
            return _failures(retained_urls)
        command = tuple(_command_factory(temporary_directory))
        with anyio.CancelScope(shield=True):
            with anyio.fail_after(max(0.0, deadline - anyio.current_time())):
                started_process = await anyio.open_process(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=temporary_directory,
                    env={},
                    pass_fds=(),
                    start_new_session=True,
                )
                process = started_process
        started_process = _require_started_process(process)
        stdin, stdout_stream, stderr_stream = _require_process_streams(started_process)
        with anyio.fail_after(max(0.0, deadline - anyio.current_time())):
            await stdin.send(request)
            await stdin.aclose()
            stdout = _Capture(bytearray())
            stderr = _Capture(bytearray())
            return_code: int | None = None
            with anyio.CancelScope() as io_scope:
                async with anyio.create_task_group() as tasks:
                    _ = tasks.start_soon(
                        _drain,
                        stdout_stream,
                        stdout,
                        _limits.stdout_bytes,
                        io_scope,
                    )
                    _ = tasks.start_soon(
                        _drain,
                        stderr_stream,
                        stderr,
                        _limits.stderr_bytes,
                        io_scope,
                    )
                    return_code = await started_process.wait()
            if return_code != 0 or stdout.overflowed or stderr.overflowed or stderr.data:
                failed = True
            else:
                response = bytes(stdout.data)
    except OSError, TimeoutError, _ProtocolError:
        failed = True
    finally:
        await _cleanup(process, temporary_directory, _limits)

    if failed or response is None:
        return _failures(retained_urls)
    try:
        return _parse_response(response, retained_urls)
    except UnicodeDecodeError, json.JSONDecodeError, _ProtocolError, ValueError:
        return _failures(retained_urls)


def _require_process_streams(
    process: Process,
) -> tuple[ByteSendStream, ByteReceiveStream, ByteReceiveStream]:
    if process.stdin is None or process.stdout is None or process.stderr is None:
        raise _ProtocolError
    return process.stdin, process.stdout, process.stderr


def _require_started_process(process: Process | None) -> Process:
    if process is None:
        raise _ProtocolError
    return process


async def _drain(
    stream: ByteReceiveStream,
    capture: _Capture,
    limit: int,
    scope: anyio.CancelScope,
) -> None:
    while True:
        try:
            chunk = await stream.receive(64 * 1024)
        except EndOfStream:
            return
        available = max(0, limit + 1 - len(capture.data))
        capture.data.extend(chunk[:available])
        if len(capture.data) > limit or len(chunk) > available:
            capture.overflowed = True
            scope.cancel()
            return


async def _cleanup(
    process: Process | None,
    temporary_directory: Path,
    limits: _ProcessLimitValues,
) -> None:
    cleanup_error: BaseException | None = None
    with anyio.CancelScope(shield=True):
        try:
            with anyio.fail_after(limits.cleanup_seconds):
                if process is not None:
                    if process.returncode is None:
                        process.terminate()
                        with anyio.move_on_after(limits.terminate_grace_seconds):
                            _ = await process.wait()
                    if process.returncode is None:
                        process.kill()
                        _ = await process.wait()
                    await process.aclose()
        except (OSError, TimeoutError) as error:
            cleanup_error = error
        finally:
            try:
                shutil.rmtree(temporary_directory)
            except OSError as error:
                cleanup_error = error
    if cleanup_error is not None:
        raise _SourceFetchInternalError from cleanup_error


def _parse_response(
    response: bytes,
    expected_urls: tuple[str, ...],
) -> tuple[SourceFetchResult, ...]:
    rows = _HelperResponse.model_validate_json(response).results
    if len(rows) != len(expected_urls):
        raise _ProtocolError
    parsed: list[SourceFetchResult] = []
    for expected_url, row in zip(expected_urls, rows, strict=True):
        parsed.append(_parse_row(row, expected_url))
    return tuple(parsed)


def _parse_row(row: _SuccessRow | _FailureRow, expected_url: str) -> SourceFetchResult:
    if row.original_url != expected_url:
        raise _ProtocolError
    match row:
        case _FailureRow():
            return SourceFetchFailure(original_url=expected_url)
        case _SuccessRow():
            if not _SHA256.fullmatch(row.content_sha256):
                raise _ProtocolError
            fetched_at = datetime.fromisoformat(row.fetched_at)
            if fetched_at.tzinfo is None:
                raise _ProtocolError
            return SourceFetchSuccess(
                original_url=expected_url,
                final_url=row.final_url,
                fetched_at=fetched_at,
                content_sha256=row.content_sha256,
                media_type=row.media_type,
                text=row.text,
            )


def _failures(urls: Sequence[str]) -> tuple[SourceFetchFailure, ...]:
    return tuple(SourceFetchFailure(original_url=url) for url in urls)
