#Main SDK client for unified cost tracking.

from typing import Any, Optional, Dict, Callable
import logging
from .client import DEFAULT_BASE_URL, DEFAULT_AUTH_PATH, AuthContext, AuthenticationError
from .pricing import (
    CostInterceptor,
    get_cost_aggregator,
    wrap_custom_client,
)
from .api.telemetry import TelemetryClient

logger = logging.getLogger(__name__)


class CostAnalyticsSDK:
    """
    Unified SDK for LLM cost tracking across providers.
    
    Example:
        sdk = CostAnalyticsSDK()
        sdk.wrap_client(client, provider="custom", method_path="responses.create")
        
        # Use client normally, costs tracked automatically
        response = client.messages.create(...)
        
        metrics = sdk.get_metrics()
    """

    def __init__(self):
     self.interceptor = CostInterceptor()
     self.aggregator = get_cost_aggregator()
     self.telemetry_client = TelemetryClient(server_url=DEFAULT_BASE_URL)
     self.aggregator.set_on_flush(self.telemetry_client.flush_batch)

    def wrap_client(
        self,
        client: Any,
        provider: str,
        method_path: str,
        response_to_dict: Optional[Callable[[Any], Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Generic client wrapper for any provider.

        Args:
            client: Provider SDK client instance
            provider: Provider identifier (e.g. 'cohere', 'groq', 'mistral', 'anthropic', 'openai')
            method_path: Dotted callable path on client (e.g. 'messages.create')
            response_to_dict: Optional response conversion function
            metadata: Optional static metadata attached to tracked request

        Returns:
            Wrapped client (modified in place)
        """
        return wrap_custom_client(
            client=client,
            provider=provider,
            method_path=method_path,
            response_to_dict=response_to_dict,
            interceptor=self.interceptor,
            static_metadata=metadata,
        )

    def process_response(
        self,
        response: Dict[str, Any],
        provider: str,
        request_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Manually process API response to extract usage details.
        
        Args:
            response: API response dict
            provider: Provider name ('anthropic', 'openai', etc.)
            request_id: Optional request tracking ID
            metadata: Optional metadata
        
        Returns:
            Usage breakdown dict or None
        
        Example:
            usage = sdk.process_response(response, provider="custom")
        """
        cost_breakdown = self.interceptor.process_response(
            response,
            provider=provider,
            request_id=request_id,
            metadata=metadata,
        )
        
        if cost_breakdown:
            return cost_breakdown.to_dict()
        
        return None

    def get_metrics(self) -> Dict[str, Any]:
        #Get request buffer size and pending requests (metrics now computed on backend).
        return {
            "buffer_size": self.aggregator.get_buffer_size(),
            "pending_requests": len(self.aggregator.get_pending_requests()),
        }

    def get_pending_requests(self) -> list:
        #Get all pending requests awaiting flush to backend.
        return [r.to_dict() for r in self.aggregator.get_pending_requests()]

    def flush_buffer(self) -> None:
        #Manually flush the request buffer to backend.
        self.aggregator.flush()
        logger.info("Buffer flushed manually")
    def shutdown(self) -> None:
     self.flush()
     with self._lock:
        if self._flush_timer:
            self._flush_timer.cancel()
            self._flush_timer = None

    logger.info("Buffer shutdown complete")

# Global SDK instance
_sdk_instance = None


def get_sdk(server_url: Optional[str] = None) -> CostAnalyticsSDK:
    #Get or create global SDK instance.
    global _sdk_instance
    if _sdk_instance is None:
        _sdk_instance = CostAnalyticsSDK(server_url=server_url)
    return _sdk_instance

