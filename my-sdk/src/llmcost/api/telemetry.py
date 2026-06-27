"""Backend telemetry API routes for flushed SDK request batches."""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

import requests

from .routes import TELEMETRY_FLUSH_PATH
from ..pricing.aggregator import RequestDetails

logger = logging.getLogger(__name__)

DEFAULT_TELEMETRY_PATH = TELEMETRY_FLUSH_PATH
MAX_FAILED_BATCHES = 5


class TelemetryClient:
    """HTTP sender that connects the client-side SDK buffer to the backend."""

    def __init__(
        self,
        server_url: str,
        endpoint: Optional[str] = None,
        *,
        api_key: Optional[str] = None,
        client_id: Optional[str] = None,
        timeout: float = 30.0,
        telemetry_path: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.client_id = client_id or str(uuid.uuid4())
        self.timeout = timeout
        self.telemetry_path = telemetry_path or endpoint or DEFAULT_TELEMETRY_PATH
        self.session = session or requests.Session()
        self._failed_batches: List[List[RequestDetails]] = []

    @property
    def flush_url(self) -> str:
        """Full backend route used for telemetry flushes."""

        return f"{self.server_url}/{self.telemetry_path.lstrip('/')}"

    def flush_batch(self, batch: List[RequestDetails]) -> None:
        """POST a flushed request-details batch to the backend."""

        if not batch:
            return

        pending_batches = [*self._failed_batches, batch]
        self._failed_batches = []

        for pending_batch in pending_batches:
            try:
                self._post_batch(pending_batch)
            except Exception as exc:
                if self._looks_not_received(exc):
                    try:
                        self._post_batch(pending_batch)
                        continue
                    except Exception as retry_exc:
                        exc = retry_exc

                logger.warning("Telemetry flush failed; retaining batch: %s", exc)
                self._retain_failed_batch(pending_batch)

    def _post_batch(self, batch: List[RequestDetails]) -> None:
        payload = {
            "client_id": self.client_id,
            "batch": [request.to_dict() for request in batch],
        }

        response = self.session.post(
            self.flush_url,
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "X-Client-ID": self.client_id,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _retain_failed_batch(self, batch: List[RequestDetails]) -> None:
        self._failed_batches.append(batch)
        if len(self._failed_batches) > MAX_FAILED_BATCHES:
            self._failed_batches = self._failed_batches[-MAX_FAILED_BATCHES:]

    def _looks_not_received(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return isinstance(exc, requests.ConnectionError) or "not received" in message

    def close(self) -> None:
        """Close the underlying HTTP session."""

        self.session.close()
