"""Bounded HTTPS client with explicit transient-only retries."""

from __future__ import annotations

import email.utils
import http.client
import logging
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit


TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class HttpResult:
    body: bytes
    status: int
    content_type: str
    headers: dict[str, str]
    attempts: int
    elapsed_seconds: float


class HttpFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        transient: bool = False,
        retry_after: float = 0.0,
    ):
        super().__init__(message)
        self.status = status
        self.transient = transient
        self.retry_after = retry_after


class BoundedHttpClient:
    def __init__(
        self,
        *,
        connect_timeout: float,
        read_timeout: float,
        max_attempts: int,
        retry_after_cap: float,
        logger: logging.Logger,
    ) -> None:
        if not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_attempts = max_attempts
        self.retry_after_cap = retry_after_cap
        self.logger = logger

    def get(
        self,
        url: str,
        params: dict[str, str],
        *,
        source: str,
        scope_id: str,
    ) -> HttpResult:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("only HTTPS endpoints are supported")
        target = parsed.path or "/"
        query = urlencode(sorted(params.items()), safe=",")
        if query:
            target = f"{target}?{query}"

        overall_start = time.monotonic()
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            started = time.monotonic()
            connection: http.client.HTTPSConnection | None = None
            try:
                connection = http.client.HTTPSConnection(
                    parsed.hostname,
                    port=parsed.port,
                    timeout=self.connect_timeout,
                    context=ssl.create_default_context(),
                )
                connection.request(
                    "GET",
                    target,
                    headers={"Accept": "application/json", "User-Agent": "kenya-econ-phase1/0.1"},
                )
                response = connection.getresponse()
                if connection.sock is not None:
                    connection.sock.settimeout(self.read_timeout)
                headers = {key.lower(): value for key, value in response.getheaders()}
                body = response.read()
                elapsed = time.monotonic() - started
                transient = response.status in TRANSIENT_STATUS
                if not 200 <= response.status < 300:
                    raise HttpFailure(
                        f"HTTP {response.status} from {source}",
                        status=response.status,
                        transient=transient,
                        retry_after=bounded_retry_after(
                            headers.get("retry-after"), self.retry_after_cap
                        ),
                    )
                self.logger.info(
                    "source=%s scope=%s http_attempt=%d elapsed=%.3fs outcome=success status=%d",
                    source, scope_id, attempt, elapsed, response.status,
                )
                return HttpResult(
                    body=body,
                    status=response.status,
                    content_type=headers.get("content-type", ""),
                    headers=headers,
                    attempts=attempt,
                    elapsed_seconds=time.monotonic() - overall_start,
                )
            except (HttpFailure, socket.timeout, TimeoutError, ConnectionError, OSError, http.client.HTTPException) as exc:
                failure = exc if isinstance(exc, HttpFailure) else HttpFailure(
                    f"{type(exc).__name__}: {exc}", transient=True
                )
                last_error = failure
                elapsed = time.monotonic() - started
                retry = failure.transient and attempt < self.max_attempts
                self.logger.warning(
                    "source=%s scope=%s http_attempt=%d elapsed=%.3fs outcome=%s status=%s",
                    source, scope_id, attempt, elapsed, "retry" if retry else "failed",
                    failure.status if failure.status is not None else "transport",
                )
                if not retry:
                    raise failure
                time.sleep(
                    min(
                        self.retry_after_cap,
                        max(failure.retry_after, 2 ** (attempt - 1)),
                    )
                )
            finally:
                if connection is not None:
                    connection.close()
        raise HttpFailure(f"request failed: {last_error}", transient=True)


def bounded_retry_after(value: str | None, cap_seconds: float) -> float:
    if not value:
        return 0.0
    try:
        seconds = float(value)
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            seconds = (parsed - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return 0.0
    return min(cap_seconds, max(0.0, seconds))

