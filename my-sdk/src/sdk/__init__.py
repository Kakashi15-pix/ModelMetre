#LLM Cost Observability SDK.

from .client import CostAnalyticsClient,AuthenticationError, DEFAULT_BASE_URL, DEFAULT_AUTH_PATH, AuthContext
from .sdk import CostAnalyticsSDK, get_sdk
from .pricing import (
    CostExtractor,
    get_extractor,
    RequestDetailsBuffer,
    RequestDetails,
    get_request_buffer,
    get_cost_aggregator,
    CostInterceptor,
    wrap_custom_client,
    FLUSH_BATCH_SIZE,
    FLUSH_INTERVAL_SECONDS,
)

__version__ = "0.1.0"
__all__ = [
    # Authenticated analytics client
    "CostAnalyticsClient",
    "AuthenticationError",
    # Main SDK
    "CostAnalyticsSDK",
    "get_sdk",
    # Extractors
    "CostExtractor",
    "get_extractor",
    # Buffer (replaces aggregator)
    "RequestDetailsBuffer",
    "RequestDetails",
    "get_request_buffer",
    "get_cost_aggregator",
    "FLUSH_BATCH_SIZE",
    "FLUSH_INTERVAL_SECONDS",
    # Interceptor
    "CostInterceptor",
    "wrap_custom_client",
]
