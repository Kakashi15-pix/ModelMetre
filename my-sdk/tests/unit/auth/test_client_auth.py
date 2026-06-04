"""Unit tests for the lazy API-key authentication client."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Ensure local imports like `from client import ...` resolve in tests.
SRC_DIR = Path(__file__).resolve().parents[3] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from client import AuthenticationError, CostAnalyticsClient


class _DummyResponse:
    def __init__(self, status_code: int, payload=None, raise_error: Exception | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self._raise_error = raise_error

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self._raise_error is not None:
            raise self._raise_error


class _SessionDouble:
    def __init__(self, verify_response: _DummyResponse, request_responses=None):
        self.verify_response = verify_response
        self.request_responses = list(request_responses or [])
        self.verify_calls = 0
        self.request_calls = []

    def get(self, *args, **kwargs):
        self.verify_calls += 1
        return self.verify_response

    def request(self, *args, **kwargs):
        self.request_calls.append({"args": args, "kwargs": kwargs})
        if self.request_responses:
            return self.request_responses.pop(0)
        return _DummyResponse(200, payload={"ok": True})

    def close(self):
        return None


def test_constructor_requires_api_key(monkeypatch):
    monkeypatch.delenv("CA_API_KEY", raising=False)

    with pytest.raises(AuthenticationError, match="CA_API_KEY is required"):
        CostAnalyticsClient(api_key=None, session=_SessionDouble(_DummyResponse(200)))


def test_ensure_authenticated_rejects_non_live_key():
    client = CostAnalyticsClient(api_key="sk_test_abc", session=_SessionDouble(_DummyResponse(200)))

    with pytest.raises(AuthenticationError, match="Invalid API key format"):
        client._ensure_authenticated()


def test_ensure_authenticated_caches_successful_identity():
    session = _SessionDouble(
        _DummyResponse(
            200,
            payload={"user_id": "user_1", "api_key_id": "key_1"},
        )
    )
    client = CostAnalyticsClient(api_key="ca_live_abc", session=session)

    first = client._ensure_authenticated()
    second = client._ensure_authenticated()

    assert first.user_id == "user_1"
    assert first.api_key_id == "key_1"
    assert second == first
    assert session.verify_calls == 1


def test_request_attaches_auth_and_metadata_headers():
    verify = _DummyResponse(200, payload={"user_id": "user_1", "api_key_id": "key_1"})
    session = _SessionDouble(verify, request_responses=[_DummyResponse(200, payload={"ok": True})])
    client = CostAnalyticsClient(api_key="ca_live_abc", session=session)

    response = client.request(
        "POST",
        "/v1/events",
        json={"event": "tracked"},
        provider="openai",
        model="gpt-4o-mini",
        request_id="req_123",
    )

    assert response.status_code == 200
    call = session.request_calls[0]["kwargs"]
    assert call["headers"]["Authorization"] == "Bearer ca_live_abc"
    assert call["headers"]["X-CA-Key-Id"] == "key_1"
    assert call["headers"]["X-CA-User-Id"] == "user_1"
    assert call["headers"]["X-Request-Id"] == "req_123"
    assert call["headers"]["X-CA-Provider"] == "openai"
    assert call["headers"]["X-CA-Model"] == "gpt-4o-mini"


def test_request_retries_on_server_errors(monkeypatch):
    verify = _DummyResponse(200, payload={"user_id": "user_1", "api_key_id": "key_1"})
    session = _SessionDouble(
        verify,
        request_responses=[
            _DummyResponse(500),
            _DummyResponse(502),
            _DummyResponse(200, payload={"ok": True}),
        ],
    )
    client = CostAnalyticsClient(
        api_key="ca_live_abc",
        session=session,
        max_retries=3,
        backoff_factor=0.0,
    )

    monkeypatch.setattr("client.time.sleep", lambda *_: None)
    result = client.request("GET", "/v1/costs")

    assert result.status_code == 200
    assert len(session.request_calls) == 3


def test_request_fails_fast_on_auth_error():
    verify = _DummyResponse(200, payload={"user_id": "user_1", "api_key_id": "key_1"})
    session = _SessionDouble(
        verify,
        request_responses=[_DummyResponse(401, payload={"error": "invalid_api_key"})],
    )
    client = CostAnalyticsClient(api_key="ca_live_abc", session=session)

    with pytest.raises(AuthenticationError, match="invalid_api_key"):
        client.request("GET", "/v1/costs")

    assert len(session.request_calls) == 1


def test_uses_environment_api_key_when_not_passed(monkeypatch):
    monkeypatch.setenv("CA_API_KEY", "ca_live_from_env")
    verify = _DummyResponse(200, payload={"user_id": "user_1", "api_key_id": "key_1"})
    session = _SessionDouble(verify)

    client = CostAnalyticsClient(api_key=None, session=session)
    client._ensure_authenticated()

    assert client.api_key == "ca_live_from_env"
