import logging

import pytest

from kenya_economic_data.http_client import BoundedHttpClient, HttpFailure


class _Socket:
    def settimeout(self, _value: float) -> None:
        pass


class _Response:
    def __init__(self, status: int, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self._headers = headers or {}

    def getheaders(self):
        return list(self._headers.items())

    def read(self) -> bytes:
        return b"{}"


class _Connection:
    statuses: list[tuple[int, dict[str, str]]] = []
    calls = 0

    def __init__(self, *_args, **_kwargs) -> None:
        self.sock = _Socket()

    def request(self, *_args, **_kwargs) -> None:
        type(self).calls += 1

    def getresponse(self) -> _Response:
        status, headers = type(self).statuses.pop(0)
        return _Response(status, headers)

    def close(self) -> None:
        pass


def _client() -> BoundedHttpClient:
    return BoundedHttpClient(
        connect_timeout=1,
        read_timeout=1,
        max_attempts=3,
        retry_after_cap=10,
        logger=logging.getLogger("test-http"),
    )


def test_transient_status_retries_with_capped_retry_after(monkeypatch) -> None:
    _Connection.statuses = [(503, {"Retry-After": "999"}), (200, {"Content-Type": "application/json"})]
    _Connection.calls = 0
    sleeps: list[float] = []
    monkeypatch.setattr("kenya_economic_data.http_client.http.client.HTTPSConnection", _Connection)
    monkeypatch.setattr("kenya_economic_data.http_client.time.sleep", sleeps.append)

    result = _client().get("https://example.test/data", {}, source="synthetic", scope_id="scope")

    assert result.attempts == 2
    assert _Connection.calls == 2
    assert sleeps == [10]


def test_permanent_client_error_is_not_retried(monkeypatch) -> None:
    _Connection.statuses = [(404, {})]
    _Connection.calls = 0
    monkeypatch.setattr("kenya_economic_data.http_client.http.client.HTTPSConnection", _Connection)
    monkeypatch.setattr("kenya_economic_data.http_client.time.sleep", lambda _seconds: None)

    with pytest.raises(HttpFailure, match="HTTP 404"):
        _client().get("https://example.test/data", {}, source="synthetic", scope_id="scope")
    assert _Connection.calls == 1

