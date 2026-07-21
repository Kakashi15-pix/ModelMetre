#Client-side analytics API client with lazy API-key authentication.

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import requests

from .api.routes import AUTH_VERIFY_PATH, CUSTOM_PRICING_PATH
from .auth.config import ConfigError, get_api_key


DEFAULT_BASE_URL = "https://server-sidesdk-production.up.railway.app"
DEFAULT_AUTH_PATH = AUTH_VERIFY_PATH


@dataclass(frozen=True)
class AuthContext:

	user_id: str
	api_key_id: str


class AuthenticationError(RuntimeError):
	"""Raised when API-key authentication fails or is missing."""


class CostAnalyticsClient:
	"""HTTP client that lazily validates an SDK API key on first use."""

	def __init__(
		self,
		api_key: Optional[str] = None,
		base_url: Optional[str] = None,
		timeout: float = 30.0,
		session: Optional[requests.Session] = None,
		auth_path: str = DEFAULT_AUTH_PATH,
		max_retries: int = 3,
		backoff_factor: float = 0.5,
		request_id_factory: Optional[Callable[[], str]] = None,
	) -> None:
		"""Initialize the client without forcing network validation."""

		try:
			self.api_key = api_key or get_api_key()
		except ConfigError as exc:
			raise AuthenticationError(str(exc)) from exc
		self.base_url = (base_url or os.getenv("CA_API_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
		self.timeout = timeout
		self.session = session or requests.Session()
		self.auth_path = auth_path
		self.max_retries = max(1, max_retries)
		self.backoff_factor = backoff_factor
		self._auth_context: Optional[AuthContext] = None
		self._authenticated = False
		self._request_id_factory = request_id_factory or (lambda: str(uuid.uuid4()))

	def _ensure_authenticated(self) -> AuthContext:
		"""Validate the API key only once, on the first real request."""

		if self._authenticated and self._auth_context is not None:
			return self._auth_context

		if not self.api_key:
			raise AuthenticationError("CA_API_KEY is required")

		if not self.api_key.startswith("ca_live_"):
			raise AuthenticationError("Invalid API key format")

		url = f"{self.base_url}{self.auth_path}"
		response = self.session.get(
			url,
			headers={"Authorization": f"Bearer {self.api_key}"},
			timeout=self.timeout,
		)

		if response.status_code in (401, 403):
			# Never retry auth failures; they are not transient.
			error_payload = self._safe_json(response)
			raise AuthenticationError(error_payload.get("error", "invalid_api_key"))

		response.raise_for_status()
		payload = self._safe_json(response)

		user_id = payload.get("user_id")
		api_key_id = payload.get("api_key_id")
		if not user_id or not api_key_id:
			raise AuthenticationError("Authentication response missing identity fields")

		self._auth_context = AuthContext(user_id=str(user_id), api_key_id=str(api_key_id))
		self._authenticated = True
		return self._auth_context

	def _safe_json(self, response: requests.Response) -> Dict[str, Any]:
		"""Parse JSON without leaking raw response bodies into exception traces."""

		try:
			data = response.json()
			return data if isinstance(data, dict) else {}
		except ValueError:
			return {}

	def _request_headers(
		self,
		*,
		provider: Optional[str] = None,
		model: Optional[str] = None,
		request_id: Optional[str] = None,
	) -> Dict[str, str]:
		"""Attach request metadata to every analytics call."""

		auth_context = self._ensure_authenticated()
		return {
			"Authorization": f"Bearer {self.api_key}",
			"X-CA-Key-Id": auth_context.api_key_id,
			"X-CA-User-Id": auth_context.user_id,
			"X-Request-Id": request_id or self._request_id_factory(),
			"X-CA-Provider": provider or "",
			"X-CA-Model": model or "",
		}

	def request(
		self,
		method: str,
		path: str,
		*,
		json: Optional[Dict[str, Any]] = None,
		params: Optional[Dict[str, Any]] = None,
		provider: Optional[str] = None,
		model: Optional[str] = None,
		request_id: Optional[str] = None,
	) -> requests.Response:
		"""Send an authenticated request with 5xx retry only."""

		url = f"{self.base_url}/{path.lstrip('/')}"
		headers = self._request_headers(provider=provider, model=model, request_id=request_id)

		for attempt in range(self.max_retries):
			response = self.session.request(
				method=method,
				url=url,
				headers=headers,
				json=json,
				params=params,
				timeout=self.timeout,
			)

			if response.status_code in (401, 403):
				# Authentication and authorization errors must fail fast.
				error_payload = self._safe_json(response)
				raise AuthenticationError(error_payload.get("error", "invalid_api_key"))

			if response.status_code < 500:
				return response

			if attempt == self.max_retries - 1:
				response.raise_for_status()

			time.sleep(self.backoff_factor * (2**attempt))

		raise RuntimeError("Request retry loop exited unexpectedly")

	def submit_custom_pricing(
		self,
		*,
		model: str,
		provider: str,
		input_cost_per_1m_tokens: float,
		output_cost_per_1m_tokens: float,
		cache_creation_cost_per_1m_tokens: Optional[float] = None,
		cache_read_cost_per_1m_tokens: Optional[float] = None,
		source: Optional[str] = None,
		currency: str = "USD",
		path: str = CUSTOM_PRICING_PATH,
	) -> requests.Response:
		"""Send client-supplied pricing data to the server for this account."""

		payload: Dict[str, Any] = {
			"model": model,
			"provider": provider,
			"input_cost_per_1m_tokens": input_cost_per_1m_tokens,
			"output_cost_per_1m_tokens": output_cost_per_1m_tokens,
			"currency": currency,
		}
		if cache_creation_cost_per_1m_tokens is not None:
			payload["cache_creation_cost_per_1m_tokens"] = cache_creation_cost_per_1m_tokens
		if cache_read_cost_per_1m_tokens is not None:
			payload["cache_read_cost_per_1m_tokens"] = cache_read_cost_per_1m_tokens
		if source is not None:
			payload["source"] = source

		return self.request(
			"POST",
			path,
			json=payload,
			provider=provider,
			model=model,
		)

	def close(self) -> None:
		"""Close the underlying HTTP session."""

		self.session.close()

