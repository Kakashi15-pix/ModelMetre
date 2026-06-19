"""
Generic usage extraction from API responses.
Client-side extraction only captures usage/model/stop_reason.
Cost computation is handled exclusively by the backend orchestrator.
"""
from abc import ABC, abstractmethod
from secrets import choice
from typing import Dict, Any, Optional
from dataclasses import dataclass
import logging
from urllib import response

logger = logging.getLogger(__name__)


@dataclass
class UsageBreakdown:
    #Extracted usage information from an API response (no cost fields).
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    model: str = ""
    provider: str = ""
    stop_reason: Optional[str] = None
    raw_usage: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        #Convert to dictionary.
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


class UsageExtractor(ABC):
    """Base class for client-side usage extraction."""

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
        pass


class Extractor(UsageExtractor):
    """Generic API response usage extraction."""

    def extract_usage(self, response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract usage from common response payloads.
        
        Response structure:
        {
            "usage": {
                "input_tokens": int,
                "output_tokens": int,
                "prompt_tokens": int,
                "completion_tokens": int,
                "cache_creation_input_tokens": int (optional),
                "cache_read_input_tokens": int (optional),
                "cached_prompt_tokens": int (optional)
            },
            ...
        }
        """
        try:
            if "usage" not in response:
                logger.warning("No usage field in response")
                return None

            usage_obj = response["usage"]
            return {
                "input_tokens": usage_obj.get("input_tokens", usage_obj.get("prompt_tokens", 0)),
                "output_tokens": usage_obj.get("output_tokens", usage_obj.get("completion_tokens", 0)),
                "cache_creation_tokens": usage_obj.get(
                    "cache_creation_tokens",
                    usage_obj.get("cache_creation_input_tokens", 0),
                ),
                "cache_read_tokens": usage_obj.get(
                    "cache_read_tokens",
                    usage_obj.get("cache_read_input_tokens", usage_obj.get("cached_prompt_tokens", 0)),
                ),
            }
        except (KeyError, TypeError) as e:
            logger.error(f"Failed to extract usage from response: {e}")
            return None

    def extract_model(self, response: Dict[str, Any]) -> Optional[str]:
        """Extract model from response."""
        return response.get("model")

    def extract_stop_reason(self, response: Dict[str, Any]) -> Optional[str]:
     choices = response.get("choices", [])
     # OpenAI shape
     if choices and isinstance(choices, list):
        return choices[0].get("finish_reason")
    # Anthropic shape
     return response.get("stop_reason")

def get_extractor(provider: str) -> Optional[UsageExtractor]:
    """Return the generic extractor for any named provider."""
    if not provider:
        return None
    return Extractor()

