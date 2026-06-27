# Auth configuration helpers for API-key only setup.

from __future__ import annotations

import os


class ConfigError(RuntimeError):
    """Raised when required auth configuration is missing or invalid."""
    pass


def get_api_key() -> str:
    """Return the API key from CA_API_KEY."""

    try:
        api_key = os.environ["CA_API_KEY"].strip()
    except KeyError as exc:
        raise ConfigError("CA_API_KEY is required in the environment") from exc

    if not api_key:
        raise ConfigError("CA_API_KEY cannot be empty")

    return api_key