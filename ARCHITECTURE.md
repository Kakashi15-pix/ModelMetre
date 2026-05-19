# Architecture & Design Documentation

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    User Application                                  │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ LLM Client (Anthropic/OpenAI) - WRAPPED                       │ │
│  │                                                                 │ │
│  │  Original: client.messages.create(...)                        │ │
│  │  Returns: response (unmodified)                               │ │
│  │                                                                 │ │
│  │  Wrapper intercepts:                                           │ │
│  │    1. Extract usage from response (SIGNAL)                    │ │
│  │    2. Look up pricing (PULL)                                  │ │
│  │    3. Compute cost                                            │ │
│  │    4. Aggregate                                               │ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
        ↓ (API request - no credentials exposed)
    ┌───────────────────────────────────────────────────────────────┐
    │              LLM Provider (Anthropic/OpenAI)                  │
    │              (Credentials on client machine)                 │
    └───────────────────────────────────────────────────────────────┘
        ↓ (API response with usage)
    ┌───────────────────────────────────────────────────────────────┐
    │           CostExtractor (Provider-Specific)                   │
    │  • Extracts usage fields from response                        │
    │  • Maps to standard format                                    │
    │  • Handles provider-specific cache fields                     │
    └───────────────────────────────────────────────────────────────┘
        ↓
    ┌───────────────────────────────────────────────────────────────┐
    │         Server-side PricingManager (server-side_sdk)          │
    │  • Located in server-side_sdk/manager.py                      │
    │  • Local cache + upstream sync managed on backend             │
    │  • Silent fallback on network error; server exposes pricing API
    └───────────────────────────────────────────────────────────────┘
        ↓
    ┌───────────────────────────────────────────────────────────────┐
    │          CostExtractor.compute_cost()                         │
    │  • Input cost = (tokens * rate) / 1M                          │
    │  • Output cost = (tokens * rate) / 1M                         │
    │  • Cache costs (provider-specific)                            │
    └───────────────────────────────────────────────────────────────┘
        ↓
    ┌───────────────────────────────────────────────────────────────┐
    │               CostAggregator                                   │
    │  • Record request with cost/tokens/metadata                   │
    │  • Compute aggregations (total, by model, by provider)        │
    │  • Support time windows                                       │
    │  • Export to JSON                                             │
    └───────────────────────────────────────────────────────────────┘
        ↓
    ┌───────────────────────────────────────────────────────────────┐
    │           User Gets Metrics (local only)                      │
    │  • get_aggregated_metrics()                                   │
    │  • get_metrics_in_window()                                    │
    │  • export_costs()                                             │
    └───────────────────────────────────────────────────────────────┘
```

## Module Hierarchy

```
src/
├── __init__.py                 # Main SDK exports
├── sdk.py                      # CostAnalyticsSDK unified client
│
└── pricing/                    # Cost analytics engine (SDK-side)
  ├── __init__.py            # Pricing module exports
  ├── extractors.py          # Provider-specific extractors
  ├── aggregator.py          # Cost aggregation + metrics
  ├── interceptor.py         # Client library wrappers

Note: The authoritative PricingManager that performs upstream sync,
cache management and pricing lookups lives in the backend at
`server-side_sdk/manager.py`. The SDK is responsible for extraction,
interception and buffering of request details; final pricing resolution
is performed on the server unless the SDK is explicitly configured
to perform local lookups.

examples/
├── cost_tracking.py            # Basic usage examples
└── production_observer.py       # Production patterns

tests/
├── unit/
│   └── pricing/
│       ├── test_extractors.py  # ExtractorTests
│       └── test_aggregator.py  # AggregatorTests
│
└── integration/
    └── test_cost_tracking.py   # End-to-end tests
```

## Data Flow Examples

### Example 1: Anthropic Request

```
1. User calls:
   response = client.messages.create(model="claude-3-opus-...", messages=[...])

2. Wrapper intercepts response:
   {
     "id": "msg_123",
     "model": "claude-3-opus-20240229",
     "usage": {
       "input_tokens": 100,
       "output_tokens": 50,
       "cache_creation_input_tokens": 0,
       "cache_read_input_tokens": 0
     }
   }

3. AnthropicExtractor.extract_usage():
   {
     "input_tokens": 100,
     "output_tokens": 50,
     "cache_creation_tokens": 0,
     "cache_read_tokens": 0
   }

4. PricingManager.get_pricing("claude-3-opus-20240229"):
   {
     "input_cost_per_1m_tokens": 15.0,
     "output_cost_per_1m_tokens": 75.0,
     "cache_creation_cost_per_1m_tokens": 18.75,
     "cache_read_cost_per_1m_tokens": 1.5
   }

5. AnthropicExtractor.compute_cost():
   input_cost = (100 * 15.0) / 1_000_000 = 0.0015
   output_cost = (50 * 75.0) / 1_000_000 = 0.00375
   total_cost = 0.00525

6. CostAggregator.record_request():
   RequestCost(
     timestamp=datetime.utcnow(),
     request_id="...",
     model="claude-3-opus-20240229",
     provider="anthropic",
     total_cost=0.00525,
     input_tokens=100,
     output_tokens=50,
     cache_read_tokens=0,
     cache_creation_tokens=0
   )
```

### Example 2: Pricing Sync

```
Scheduled (daily):

1. The backend `PricingManager` (server-side_sdk/manager.py) manages upstream sync
  and local caching. Typical flow:

  • Check sync interval and decide whether to contact upstream
  • GET upstream JSON from LiteLLM
  • Compute hash of upstream data and compare with last known hash
  • If changed: update pricing cache and sync state files on server
  • On error: increment sync failures and continue serving cached data

2. The backend cache and sync state paths are located under the server-side
  repository (see `server-side_sdk/manager.py` for exact paths and defaults).
```

## Provider Integration Pattern

Each provider follows same pattern:

```python
class ProviderExtractor(CostExtractor):
    """Extract costs from Provider API."""
    
    def extract_usage(response):
        """
        Map response fields to standard format:
        {
            "input_tokens": int,
            "output_tokens": int,
            "cache_read_tokens": int,
            "cache_creation_tokens": int
        }
        """
        # Provider-specific field mapping
        pass
    
    def extract_model(response):
        """Get model identifier for pricing lookup."""
        pass
    
    def compute_cost(usage, pricing):
        """Compute cost using provider-specific formula."""
        # Some providers have different cache models
        pass

# Register in EXTRACTORS dict
EXTRACTORS = {
    "provider_name": ProviderExtractor,
}

# Optional: Create convenience wrapper
class ProviderInterceptor(CostInterceptor):
    def wrap_client(self, client):
        # Specific client wrapping logic
        pass
```

## Pricing Data Model

### Source Hierarchy

```
1. Primary (Upstream LiteLLM)
   URL: https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json
   Format: Full upstream JSON with all fields
   Sync: Daily with hash-based change detection
   Fallback: Saved cache from last successful sync

3. Secondary (Server Local Cache)
  Path: server-side_sdk/pricing_cache.json
  Format: Same as upstream
  Created: After successful sync
  Used: If sync fails

4. Tertiary (Bundled / Initial)
  Path: server-side_sdk/pricing_cache.json (created on first sync)
  Format: Extracted fields only (cost_per_1m_tokens, cache rates)
  Used: Initial load, network offline

4. Tracking
   Path: src/pricing/pricing_sync.json
   Format: {
     "last_sync": "2024-01-15T10:30:00",
     "last_hash": "sha256...",
     "sync_failures": 0
   }
```

### Pricing JSON Format

```json
{
  "model-name": {
    "input_cost_per_1m_tokens": float,
    "output_cost_per_1m_tokens": float,
    "cache_creation_cost_per_1m_tokens": float (optional),
    "cache_read_cost_per_1m_tokens": float (optional)
  }
}
```

**Notes**:
- Cache rates optional: computed from input_rate if not provided
- Default cache_creation_rate = input_rate * 1.25
- Default cache_read_rate = input_rate * 0.1
- All rates are per 1M tokens

## Cost Computation Formulas

### Standard Formula (Both Providers)

```
total_cost = (
    (input_tokens * input_rate) +
    (output_tokens * output_rate) +
    (cache_creation_tokens * cache_creation_rate) +
    (cache_read_tokens * cache_read_rate)
) / 1_000_000
```

### Anthropic Specifics

```
# Cache tokens reduce input cost by ~90%
cache_read_cost_per_1m = input_cost_per_1m * 0.1

# Creating cache adds 25% premium to input
cache_creation_cost_per_1m = input_cost_per_1m * 1.25

# Example:
input_tokens: 100 (10 cached)
cache_read_tokens: 10
cache_creation_tokens: 5

input_cost = (100 - 10) * 15.0 / 1M = 0.0013
cache_read_cost = 10 * 1.5 / 1M = 0.000015
cache_creation_cost = 5 * 18.75 / 1M = 0.0000938
total = 0.0013088
```

### OpenAI Specifics

```
# Cache tokens reuse input rate
cache_read_cost_per_1m = input_cost_per_1m * discount_factor (varies by model)

# OpenAI doesn't separately charge for cache creation
cache_creation_tokens = 0

# Example (gpt-4-turbo):
prompt_tokens: 100
completion_tokens: 50
cached_prompt_tokens: 20

input_cost = 100 * 10.0 / 1M = 0.001
completion_cost = 50 * 30.0 / 1M = 0.0015
cache_cost = 20 * 5.0 / 1M = 0.0001
total = 0.0026
```

## Aggregation Model

```python
AggregatedMetrics:
  - total_cost: sum(request.total_cost)
  - total_requests: len(requests)
  - total_input_tokens: sum(request.input_tokens)
  - total_output_tokens: sum(request.output_tokens)
  - total_cache_read_tokens: sum(request.cache_read_tokens)
  - total_cache_creation_tokens: sum(request.cache_creation_tokens)
  - by_model: {model → total_cost}
  - by_provider: {provider → total_cost}
  - cost_breakdown: {type → cost}
```

## Extension Points

### Add New Provider

1. Create `ProviderExtractor` class
2. Register in `EXTRACTORS`
3. (Optional) Create `ProviderInterceptor` class
4. Add pricing to `pricing.json`

### Add New Aggregation

1. Extend `CostAggregator` with new method
2. Follow pattern of `get_aggregated_metrics()`
3. Example: `get_metrics_by_user()`, `get_metrics_by_endpoint()`

### Add New Alert

1. Create alert class/function
2. Call from `CostInterceptor.process_response()`
3. Example: cost threshold, anomaly detection, rate limiting

### Add New Export Format

1. Add method to `CostAggregator`
2. Transform `self.requests` to desired format
3. Example: CSV, Parquet, Cloud Storage

## Error Handling Strategy

```
Layer 1 - Extraction
├─ Try extract_usage()
├─ If fails: log warning, return None (cost not recorded)
└─ If succeeds: continue

Layer 2 - Pricing Lookup
├─ Try get_pricing()
├─ If not found: log warning, return None (cost not recorded)
└─ If found: continue

Layer 3 - Computation
├─ Try compute_cost()
├─ If fails: log error, return None
└─ If succeeds: record to aggregator

Layer 4 - Aggregation
├─ Try record_request()
├─ If fails: log error (cost discarded)
└─ If succeeds: silent success

Layer 5 - Pricing Sync
├─ Try sync_from_upstream()
├─ If fails: log warning, use cached/bundled (no exception)
├─ If succeeds: update pricing_data
└─ Always falls back gracefully
```

**Philosophy**: 
- Never break user's code
- Log all failures for debugging
- Always have fallback
- Silent failures for sync (important in production)

## Performance Considerations

### Memory

- `CostAggregator.requests` is unbounded list
  - Solution: Implement sliding window (keep last N requests)
  - Or: Periodically archive and clear
  - Or: Use circular buffer

- `PricingManager.pricing_data` (~100-500KB)
  - Full LiteLLM upstream JSON
  - Loaded once at startup
  - Cached to disk

### CPU

- `compute_cost()`: O(1) arithmetic
- `extract_usage()`: O(1) dict access
- `get_aggregated_metrics()`: O(N) where N = request count
  - Linearity acceptable for small N (<100K)
  - Could optimize with running totals

### I/O

- Pricing sync: Async in background (future)
- Export: Streaming write to file
- No DB overhead: All in-memory

### Recommended Limits

- Keep <100K requests in memory at once
- Sync pricing once per day
- Export costs daily
- Archive old requests weekly

## Security Considerations

### Data Protection

✓ **Credentials never exposed**: Only API responses processed  
✓ **No central server**: All local storage  
✓ **No PII by default**: Only cost metrics  
✓ **Export control**: User explicitly exports  

### Future Considerations

- Encryption for cost exports
- Audit logging for access
- Role-based access control (in multi-user scenarios)
- Cost data retention policies

## Testing Strategy

```
Unit Tests:
├─ Extractors
│  ├─ Valid response extraction
│  ├─ Missing fields handling
│  └─ Cost computation accuracy
├─ Aggregator
│  ├─ Record + aggregate
│  ├─ Time windows
│  └─ Export formats
└─ Manager
   ├─ Pricing lookup
   └─ Sync behavior

Integration Tests:
├─ End-to-end tracking
├─ Multi-provider scenarios
└─ Error recovery

Manual Tests:
├─ Real API calls
├─ Pricing accuracy vs. dashboard
└─ Production patterns
```

## Future Enhancements

### Phase 2: Cloud Infrastructure

- AWS CUR + Athena
- GCP BigQuery
- Azure Cost Management

### Phase 3: Advanced Features

- ML-based cost anomaly detection
- Budget alerts and forecasting
- Cost optimization recommendations
- Integration with popular frameworks (LangChain, etc.)

### Phase 4: Enterprise

- Multi-tenant support
- Fine-grained access control
- Cost attribution (by user, team, project)
- Historical trending and analysis
