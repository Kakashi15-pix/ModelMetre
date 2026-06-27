"""
Interceptor middleware for LLM client libraries.
Forwards request/response and telemetry details to backend where cost computation happen.
"""
from typing import Any, Optional, Dict, Callable, Tuple
import logging
import uuid

from .extractors import get_extractor
from .aggregator import get_cost_aggregator

logger = logging.getLogger(__name__)


def _default_response_to_dict(response: Any) -> Dict[str, Any]:
    """Best-effort response conversion for provider SDK objects."""
    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if hasattr(response, "dict"):
        return response.dict()
    if hasattr(response, "__dict__"):
        return dict(response.__dict__)
    return {"raw_response": str(response)}


def _resolve_owner_and_attr(root: Any, attr_path: str) -> Tuple[Any, str]:
    """Resolve dotted path to (owner_object, attribute_name)."""
    if not attr_path or not isinstance(attr_path, str):
        raise ValueError("method_path must be a non-empty string")

    parts = attr_path.split(".")
    owner = root
    for part in parts[:-1]:
        owner = getattr(owner, part)
    return owner, parts[-1]


class CostInterceptor:

    def __init__(self):
        self.aggregator = get_cost_aggregator()

    def process_response(
        self,
        response: Dict[str, Any],
        provider: str,
        request_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Process API response to extract and record request details.
        Extraction happens locally, but cost computation is handled by backend.
        
        Args:
            response: API response dict from provider
            provider: Provider name ('anthropic', 'openai', etc.)
            request_id: Optional request tracking ID
            metadata: Optional metadata to attach to request
        """
        if not response:
            return None

        request_id = request_id or str(uuid.uuid4())
        request_metadata: Dict[str, Any] = dict(metadata or {})
        
        extractor = get_extractor(provider)
        if not extractor:
            logger.warning(f"No extractor found for provider: {provider}")
            return None

        usage = extractor.extract_usage(response) or {}
        model = extractor.extract_model(response) or response.get("model", "unknown")
        
        stop_reason = None
        if hasattr(extractor, "extract_stop_reason"):
            stop_reason = extractor.extract_stop_reason(response)
        if not stop_reason:
            stop_reason = response.get("stop_reason")

        # Record request details (tokens only, NO raw response) for backend costing.
        self.aggregator.record_request(
            request_id=request_id,
            model=model,
            provider=provider,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_tokens", 0),
            stop_reason=stop_reason,
            metadata=request_metadata,
        )

        logger.debug(
            f"Buffered usage for {request_id} "
            f"({provider}/{model}): {usage}"
        )



def wrap_custom_client(
    client: Any,
    provider: str,
    method_path: str,
    response_to_dict: Optional[Callable[[Any], Dict[str, Any]]] = None,
    interceptor: Optional[CostInterceptor] = None,
    static_metadata: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Wrap any provider client method using a dotted method path.

    Args:
        client: Client instance to wrap
        provider: Provider name used in tracking payload
        method_path: Dotted method path (e.g. 'responses.create', 'chat.completions.create')
        response_to_dict: Optional converter for provider response objects
        interceptor: Optional interceptor instance to reuse
        static_metadata: Optional metadata merged into each tracked request

    Returns:
        Wrapped client (modified in place)
    """
    active_interceptor = interceptor or CostInterceptor()
    converter = response_to_dict or _default_response_to_dict

    owner, method_name = _resolve_owner_and_attr(client, method_path)
    original_method = getattr(owner, method_name)

    def wrapped_method(*args, **kwargs):
        response = original_method(*args, **kwargs)
        response_dict = converter(response)

        metadata = dict(static_metadata or {})
        metadata["method"] = method_path

        active_interceptor.process_response(
            response=response_dict,
            provider=provider,
            metadata=metadata,
        )
        return response

    setattr(owner, method_name, wrapped_method)
    return client
