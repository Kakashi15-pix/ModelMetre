"""Tests for telemetry flush retry behavior."""

from __future__ import annotations

from datetime import datetime

import requests

from sdk.api.telemetry import TelemetryClient
from sdk.pricing.aggregator import RequestDetails


class _FakeResponse:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class _FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def post(self, url, json, headers, timeout):
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )

        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self):
        return None


def _request(request_id: str) -> RequestDetails:
    return RequestDetails(
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        request_id=request_id,
        model="claude-3-haiku-20240307",
        provider="anthropic",
        input_tokens=100,
        output_tokens=50,
    )


def test_flush_batch_retries_not_received_once():
    client = TelemetryClient(
        server_url="https://telemetry.example.com",
        api_key="test-key",
        client_id="test-client",
        )                                          
    client.session = _FakeSession([
        requests.ConnectionError("not received"),
        _FakeResponse(200),
    ])

    client.flush_batch([_request("req_001")])

    assert len(client.session.calls) == 2
    assert len(client._failed_batches) == 0


def test_flush_batch_retains_last_five_failed_batches():
    client = TelemetryClient(
        server_url="https://telemetry.example.com",
        api_key="test-key",
        client_id="test-client",
        )
    client.session = _FakeSession([
        requests.ConnectionError("not received")
        for _ in range(12)
    ])

    for index in range(6):
        client.flush_batch([_request(f"req_{index:03d}")])

    assert len(client._failed_batches) == 5
    retained_request_ids = [batch[0].request_id for batch in client._failed_batches]
    assert retained_request_ids == [
        "req_001",
        "req_002",
        "req_003",
        "req_004",
        "req_005",
    ]
