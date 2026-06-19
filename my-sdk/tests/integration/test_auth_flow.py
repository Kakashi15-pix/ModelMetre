#Integration tests for end-to-end SDK API-key auth flow.

from __future__ import annotations

import sys
from pathlib import Path

import pytest


SRC_DIR = Path(__file__).resolve().parents[2] / "src"
if str(SRC_DIR) not in sys.path:
	sys.path.insert(0, str(SRC_DIR))

from casdk import AuthenticationError, CostAnalyticsClient


class _Response:
	def __init__(self, status_code, payload=None):
		self.status_code = status_code
		self._payload = payload or {}

	def json(self):
		return self._payload

	def raise_for_status(self):
		if self.status_code >= 400:
			raise RuntimeError(f"http_status_{self.status_code}")


class _FlowSession:
	def __init__(self, verify_payload=None, verify_status=200, request_status=200):
		self.verify_payload = verify_payload or {"user_id": "user_123", "api_key_id": "key_123"}
		self.verify_status = verify_status
		self.request_status = request_status
		self.verify_calls = 0
		self.request_calls = 0

	def get(self, *args, **kwargs):
		self.verify_calls += 1
		if self.verify_status in (401, 403):
			return _Response(self.verify_status, payload={"error": "invalid_api_key"})
		return _Response(self.verify_status, payload=self.verify_payload)

	def request(self, *args, **kwargs):
		self.request_calls += 1
		return _Response(self.request_status, payload={"ok": self.request_status < 400})

	def close(self):
		return None


def test_auth_verify_then_request_success_path():
	session = _FlowSession()
	client = CostAnalyticsClient(api_key="ca_live_integration", session=session)

	response = client.request("POST", "/v1/events", json={"hello": "world"})

	assert response.status_code == 200
	assert session.verify_calls == 1
	assert session.request_calls == 1


def test_auth_failure_during_verify_bubbles_as_authentication_error():
	session = _FlowSession(verify_status=401)
	client = CostAnalyticsClient(api_key="ca_live_integration", session=session)

	with pytest.raises(AuthenticationError, match="invalid_api_key"):
		client.request("GET", "/v1/events")


def test_subsequent_requests_do_not_reverify_identity():
	session = _FlowSession()
	client = CostAnalyticsClient(api_key="ca_live_integration", session=session)

	first = client.request("GET", "/v1/events")
	second = client.request("GET", "/v1/events")

	assert first.status_code == 200
	assert second.status_code == 200
	assert session.verify_calls == 1
	assert session.request_calls == 2

