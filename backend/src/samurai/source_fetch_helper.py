"""Standard-library-only child process for bounded public HTTP(S) retrieval."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import signal
import socket
import ssl
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Final, final, override
from urllib.parse import urljoin, urlsplit, urlunsplit

if TYPE_CHECKING:
    from collections.abc import Generator

type _JsonValue = bool | int | float | str | list[_JsonValue] | dict[str, _JsonValue] | None

_PROTOCOL_VERSION: Final = 1
_MAX_INPUT_BYTES: Final = 16 * 1024
_MAX_RAW_BYTES: Final = 256 * 1024
_MAX_TEXT_CHARS: Final = 64 * 1024
_MAX_URLS: Final = 5
_MAX_REDIRECTS: Final = 3
_TOTAL_SECONDS: Final = 20.0
_STAGE_SECONDS: Final = 3.0
_READ_SECONDS: Final = 5.0
_ALLOWED_MEDIA: Final = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
_REDIRECT_STATUSES: Final = frozenset({301, 302, 303, 307, 308})
_HIDDEN_ELEMENTS: Final = frozenset({"script", "style", "noscript", "template"})
_SUCCESS_STATUS: Final = 200
_JSON_NUMBER: Final = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
_JSON_CONTROL_LIMIT: Final = 0x20
_HEX_QUAD_LENGTH: Final = 4
_HIGH_SURROGATE_MIN: Final = 0xD800
_HIGH_SURROGATE_MAX: Final = 0xDBFF
_LOW_SURROGATE_MIN: Final = 0xDC00
_LOW_SURROGATE_MAX: Final = 0xDFFF
_SUPPLEMENTARY_PLANE_START: Final = 0x10000
_JSON_ESCAPES: Final = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


class _FetchError(RuntimeError):
    pass


@final
class _JsonReader:
    def __init__(self, text: str) -> None:
        self.text = text
        self.index = 0

    def parse(self) -> _JsonValue:
        value = self._value()
        self._whitespace()
        if self.index != len(self.text):
            raise _FetchError
        return value

    def _value(self) -> _JsonValue:
        self._whitespace()
        if self.index >= len(self.text):
            raise _FetchError
        character = self.text[self.index]
        match character:
            case '"':
                value: _JsonValue = self._string()
            case "{":
                value = self._object()
            case "[":
                value = self._array()
            case "t" if self.text.startswith("true", self.index):
                self.index += 4
                value = True
            case "f" if self.text.startswith("false", self.index):
                self.index += 5
                value = False
            case "n" if self.text.startswith("null", self.index):
                self.index += 4
                value = None
            case _:
                value = self._number()
        return value

    def _string(self) -> str:
        self._expect('"')
        value: list[str] = []
        while self.index < len(self.text):
            character = self.text[self.index]
            self.index += 1
            if character == '"':
                return "".join(value)
            if ord(character) < _JSON_CONTROL_LIMIT:
                raise _FetchError
            if character != "\\":
                value.append(character)
                continue
            if self.index >= len(self.text):
                raise _FetchError
            escaped = self.text[self.index]
            self.index += 1
            if escaped == "u":
                value.append(self._unicode_escape())
            elif replacement := _JSON_ESCAPES.get(escaped):
                value.append(replacement)
            else:
                raise _FetchError
        raise _FetchError

    def _unicode_escape(self) -> str:
        code_point = self._hex_quad()
        if _HIGH_SURROGATE_MIN <= code_point <= _HIGH_SURROGATE_MAX:
            if not self.text.startswith("\\u", self.index):
                raise _FetchError
            self.index += 2
            low_surrogate = self._hex_quad()
            if not _LOW_SURROGATE_MIN <= low_surrogate <= _LOW_SURROGATE_MAX:
                raise _FetchError
            code_point = (
                _SUPPLEMENTARY_PLANE_START
                + ((code_point - _HIGH_SURROGATE_MIN) << 10)
                + low_surrogate
                - _LOW_SURROGATE_MIN
            )
        elif _LOW_SURROGATE_MIN <= code_point <= _LOW_SURROGATE_MAX:
            raise _FetchError
        return chr(code_point)

    def _hex_quad(self) -> int:
        raw = self.text[self.index : self.index + _HEX_QUAD_LENGTH]
        if len(raw) != _HEX_QUAD_LENGTH or any(
            character not in "0123456789abcdefABCDEF" for character in raw
        ):
            raise _FetchError
        self.index += _HEX_QUAD_LENGTH
        return int(raw, 16)

    def _object(self) -> dict[str, _JsonValue]:
        self.index += 1
        result: dict[str, _JsonValue] = {}
        self._whitespace()
        if self._consume("}"):
            return result
        while True:
            self._whitespace()
            if self.index >= len(self.text) or self.text[self.index] != '"':
                raise _FetchError
            key = self._string()
            if key in result:
                raise _FetchError
            self._whitespace()
            self._expect(":")
            result[key] = self._value()
            self._whitespace()
            if self._consume("}"):
                return result
            self._expect(",")

    def _array(self) -> list[_JsonValue]:
        self.index += 1
        result: list[_JsonValue] = []
        self._whitespace()
        if self._consume("]"):
            return result
        while True:
            result.append(self._value())
            self._whitespace()
            if self._consume("]"):
                return result
            self._expect(",")

    def _number(self) -> int | float:
        match = _JSON_NUMBER.match(self.text, self.index)
        if match is None:
            raise _FetchError
        raw = match.group()
        self.index = match.end()
        return float(raw) if "." in raw or "e" in raw.casefold() else int(raw)

    def _whitespace(self) -> None:
        while self.index < len(self.text) and self.text[self.index] in " \t\r\n":
            self.index += 1

    def _consume(self, expected: str) -> bool:
        if self.index < len(self.text) and self.text[self.index] == expected:
            self.index += 1
            return True
        return False

    def _expect(self, expected: str) -> None:
        if not self._consume(expected):
            raise _FetchError


@dataclass(frozen=True, slots=True)
class _Target:
    url: str
    scheme: str
    hostname: str
    port: int
    request_target: str
    host_header: str


@dataclass(frozen=True, slots=True)
class _Resolved:
    family: int
    socket_type: int
    protocol: int
    sockaddr: tuple[str, int] | tuple[str, int, int, int]


@final
class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth: int = 0
        self.parts: list[str] = []

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in _HIDDEN_ELEMENTS:
            self._hidden_depth += 1

    @override
    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in _HIDDEN_ELEMENTS and self._hidden_depth:
            self._hidden_depth -= 1

    @override
    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


def _remaining(deadline: float, cap: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _FetchError
    return min(cap, remaining)


def _parse_target(url: str) -> _Target:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise _FetchError from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise _FetchError
    expected_port = 443 if parsed.scheme == "https" else 80
    if port is not None and port != expected_port:
        raise _FetchError
    try:
        hostname = parsed.hostname.encode("idna").decode("ascii").casefold()
    except UnicodeError as error:
        raise _FetchError from error
    if not hostname or any(character.isspace() for character in hostname):
        raise _FetchError
    effective_port = port or expected_port
    path = parsed.path or "/"
    request_target = urlunsplit(("", "", path, parsed.query, ""))
    host_name = f"[{hostname}]" if ":" in hostname else hostname
    host_header = host_name if effective_port == expected_port else f"{host_name}:{effective_port}"
    canonical = urlunsplit((parsed.scheme, host_header, path, parsed.query, ""))
    return _Target(canonical, parsed.scheme, hostname, effective_port, request_target, host_header)


def _public_address(raw_address: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        address = ipaddress.ip_address(raw_address)
    except ValueError as error:
        raise _FetchError from error
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if (
        not address.is_global
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        raise _FetchError
    return address


def _alarm_timeout(_signal_number: int, _frame: object) -> None:
    raise TimeoutError


@contextmanager
def _stage_timeout(deadline: float, cap: float) -> Generator[float]:
    timeout = _remaining(deadline, cap)
    previous_handler = signal.signal(signal.SIGALRM, _alarm_timeout)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        yield timeout
    except TimeoutError as error:
        raise _FetchError from error
    finally:
        _ = signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        _ = signal.signal(signal.SIGALRM, previous_handler)


def _resolve(hostname: str, port: int, deadline: float) -> tuple[_Resolved, ...]:
    try:
        with _stage_timeout(deadline, _STAGE_SECONDS):
            answers = socket.getaddrinfo(
                hostname,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
    except OSError as error:
        raise _FetchError from error
    if not answers:
        raise _FetchError
    resolved: list[_Resolved] = []
    for family, socket_type, protocol, _canonical_name, sockaddr in answers:
        normalized = _normalize_sockaddr(family, sockaddr)
        _ = _public_address(normalized[0])
        resolved.append(_Resolved(family, socket_type, protocol, normalized))
    return tuple(resolved)


def _normalize_sockaddr(
    family: int,
    sockaddr: tuple[str, int] | tuple[str, int, int, int] | tuple[int, bytes],
) -> tuple[str, int] | tuple[str, int, int, int]:
    match sockaddr:
        case (str(host), int(port)) if family == socket.AF_INET:
            return host, port
        case (str(host), int(port), int(flow_info), int(scope_id)) if family == socket.AF_INET6:
            return host, port, flow_info, scope_id
        case _:
            pass
    raise _FetchError


def _connect(resolved: _Resolved, deadline: float) -> socket.socket:
    connection = socket.socket(resolved.family, resolved.socket_type, resolved.protocol)
    try:
        with _stage_timeout(deadline, _STAGE_SECONDS) as timeout:
            connection.settimeout(timeout)
            connection.connect(resolved.sockaddr)
    except OSError, _FetchError:
        connection.close()
        raise
    return connection


def _create_tls_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def _open_connection(target: _Target, deadline: float) -> socket.socket:
    resolved = _resolve(target.hostname, target.port, deadline)
    connection = _connect(resolved[0], deadline)
    if target.scheme == "https":
        try:
            with _stage_timeout(deadline, _STAGE_SECONDS) as timeout:
                connection.settimeout(timeout)
                return _create_tls_context().wrap_socket(
                    connection,
                    server_hostname=target.hostname,
                )
        except OSError, ssl.SSLError, _FetchError:
            connection.close()
            raise
    return connection


def _request(
    target: _Target,
    deadline: float,
) -> tuple[int, http.client.HTTPResponse, socket.socket]:
    try:
        request = (
            f"GET {target.request_target} HTTP/1.1\r\n"
            f"Host: {target.host_header}\r\n"
            "User-Agent: SamuraiSourceFetcher/1\r\n"
            "Accept: text/html, application/xhtml+xml, text/plain\r\n"
            "Accept-Encoding: identity\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
    except UnicodeEncodeError as error:
        raise _FetchError from error
    connection = _open_connection(target, deadline)
    try:
        with _stage_timeout(deadline, _STAGE_SECONDS) as timeout:
            connection.settimeout(timeout)
            connection.sendall(request)
        with _stage_timeout(deadline, _READ_SECONDS) as timeout:
            connection.settimeout(timeout)
            response = http.client.HTTPResponse(connection)
            response.begin()
    except OSError, _FetchError, http.client.HTTPException:
        connection.close()
        raise
    return response.status, response, connection


def _read_body(
    response: http.client.HTTPResponse,
    connection: socket.socket,
    deadline: float,
) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared is not None:
        try:
            if int(declared) > _MAX_RAW_BYTES:
                raise _FetchError
        except ValueError as error:
            raise _FetchError from error
    body = bytearray()
    while True:
        with _stage_timeout(deadline, _READ_SECONDS) as timeout:
            connection.settimeout(timeout)
            chunk = response.read(min(64 * 1024, _MAX_RAW_BYTES + 1 - len(body)))
        if not chunk:
            return bytes(body)
        body.extend(chunk)
        if len(body) > _MAX_RAW_BYTES:
            raise _FetchError


def _media_type(response: http.client.HTTPResponse) -> str:
    encoding = (response.headers.get("Content-Encoding") or "identity").strip().casefold()
    media_type = response.headers.get_content_type().casefold()
    if encoding != "identity" or media_type not in _ALLOWED_MEDIA:
        raise _FetchError
    return media_type


def _normalize_text(body: bytes, media_type: str, response: http.client.HTTPResponse) -> str:
    charset = response.headers.get_content_charset("utf-8")
    try:
        decoded = body.decode(charset, errors="strict")
    except (LookupError, UnicodeDecodeError) as error:
        raise _FetchError from error
    if media_type == "text/plain":
        visible = decoded
    else:
        parser = _VisibleText()
        parser.feed(decoded)
        parser.close()
        visible = " ".join(parser.parts)
    return " ".join(visible.split())[:_MAX_TEXT_CHARS]


def _fetch_one(original_url: str, deadline: float) -> dict[str, str]:
    current_url = original_url
    visited: set[str] = set()
    for redirect_count in range(_MAX_REDIRECTS + 1):
        _ = _remaining(deadline, _STAGE_SECONDS)
        target = _parse_target(current_url)
        if target.url in visited:
            raise _FetchError
        visited.add(target.url)
        status, response, connection = _request(target, deadline)
        try:
            if status in _REDIRECT_STATUSES:
                if redirect_count >= _MAX_REDIRECTS:
                    raise _FetchError
                location = response.headers.get("Location")
                if not location:
                    raise _FetchError
                _ = _remaining(deadline, _STAGE_SECONDS)
                current_url = _parse_target(urljoin(target.url, location)).url
                continue
            if status != _SUCCESS_STATUS:
                raise _FetchError
            media_type = _media_type(response)
            body = _read_body(response, connection, deadline)
            text = _normalize_text(body, media_type, response)
            return {
                "status": "success",
                "original_url": original_url,
                "final_url": target.url,
                "fetched_at": datetime.now(UTC).isoformat(),
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "media_type": media_type,
                "text": text,
            }
        finally:
            response.close()
    raise _FetchError


def _parse_request(raw_request: bytes) -> tuple[tuple[str, ...], float]:
    if len(raw_request) > _MAX_INPUT_BYTES:
        raise _FetchError
    decoded = _JsonReader(raw_request.decode("utf-8")).parse()
    if not isinstance(decoded, dict) or set(decoded) != {"version", "urls", "remaining_budget_ms"}:
        raise _FetchError
    version = decoded["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version != _PROTOCOL_VERSION:
        raise _FetchError
    urls = decoded["urls"]
    budget = decoded["remaining_budget_ms"]
    if (
        not isinstance(urls, list)
        or not 1 <= len(urls) <= _MAX_URLS
        or not isinstance(budget, int)
        or isinstance(budget, bool)
        or budget <= 0
    ):
        raise _FetchError
    parsed_urls: list[str] = []
    for url in urls:
        if not isinstance(url, str) or not url:
            raise _FetchError
        parsed_urls.append(url)
    if len(set(parsed_urls)) != len(parsed_urls):
        raise _FetchError
    return tuple(parsed_urls), min(budget / 1000, _TOTAL_SECONDS)


def _run(raw_request: bytes) -> bytes:
    urls, budget_seconds = _parse_request(raw_request)
    deadline = time.monotonic() + budget_seconds
    results: list[dict[str, str]] = []
    for url in urls:
        try:
            results.append(_fetch_one(url, deadline))
        except (
            _FetchError,
            OSError,
            TimeoutError,
            ssl.SSLError,
            http.client.HTTPException,
            ValueError,
        ):
            results.append({"status": "failure", "original_url": url, "reason": "inaccessible"})
    return json.dumps(
        {"version": _PROTOCOL_VERSION, "results": results},
        separators=(",", ":"),
    ).encode()


def main() -> int:
    """Read one bounded request and emit one bounded response."""
    raw_request = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
    try:
        response = _run(raw_request)
    except (
        _FetchError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return 2
    _ = sys.stdout.buffer.write(response)
    _ = sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
