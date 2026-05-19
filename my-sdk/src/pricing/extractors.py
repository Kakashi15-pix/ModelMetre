"""
Provider-specific usage extraction from API responses.
Client-side extractors only extract usage/model/stop_reason.
Cost computation is handled exclusively by backend orchestrator.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class UsageBreakdown:
    """Extracted usage information from an API response (no cost fields)."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    model: str = ""
    provider: str = ""
    stop_reason: Optional[str] = None
    raw_usage: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "model": self.model,
            "provider": self.provider,
            "stop_reason": self.stop_reason,
            "raw_usage": self.raw_usage,
        }


@dataclass
class ResponseBreakdown:
    """Full cost breakdown (backend-only). Includes usage + computed costs."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    input_cost: float = 0.0
    output_cost: float = 0.0
    cache_creation_input_tokens: Optional [float] = 0.0
    cache_read_input_tokens: Optional [float] = 0.0
    total_cost: float = 0.0
    model: str = ""
    provider: str = ""
    stop_reason: Optional[str] = None
    raw_usage: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "input_cost": self.input_cost,
            "output_cost": self.output_cost,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "total_cost": self.total_cost,
            "model": self.model,
            "provider": self.provider,
            "stop_reason": self.stop_reason,
            "raw_usage": self.raw_usage,
        }


class UsageExtractor(ABC):
    """Base class for provider-specific usage extraction (client-side only)."""

    @abstractmethod
    def extract_usage(self, response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract usage fields from API response.
        
        Returns:
            Dict with 'input_tokens', 'output_tokens', 'cache_*_tokens' keys
            or None if extraction failed.
        """
        pass

    @abstractmethod
    def extract_model(self, response: Dict[str, Any]) -> Optional[str]:
        """Extract model name from API response."""
        return response.get("model") 
        pass


class Extractor(UsageExtractor):
    """ API response cost extraction."""

    def extract_usage(self, response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract usage from  /v1/messages response.
        
        Response structure:
        {
            "usage": {
                "input_tokens": int,
                "output_tokens": int,
                "cache_creation_input_tokens": int (optional),
                "cache_read_input_tokens": int (optional)
            },
            ...
        }
        """
        try:
            if "usage" not in response:
                logger.warning(f'No usage field in "[model]" response')
                return None

            usage_obj = response["usage"]
            return {
                "input_tokens": usage_obj.get("input_tokens", 0),
                "output_tokens": usage_obj.get("output_tokens", 0),
                "cache_creation_input_tokens": usage_obj.get("cache_creation_input_tokens", 0),
                "cache_read_input_tokens": usage_obj.get("cache_read_input_tokens", 0),
            }
            if "cache_creation_input_tokens"  not in usage_obj:
                pass
        except (KeyError, TypeError) as e:
            logger.error(f"Failed to extract usage from  response: {e}")
            return None

    def extract_model(self, response: Dict[str, Any]) -> Optional[str]:
        """Extract model from  response."""
        return response.get("model")

    def extract_stop_reason(self, response: Dict[str, Any]) -> Optional[str]:
        """Extract stop reason from  response."""
        return response.get("stop_reason")




# Provider registry
EXTRACTORS: Dict[str, type] = {
    "": Extractor
}


def get_extractor(provider: str) -> Optional[UsageExtractor]:
    """Return an extractor instance for the given provider."""
    extractor_cls = EXTRACTORS.get(provider.lower()) if provider else None
    if not extractor_cls:
        return None
    return extractor_cls()

