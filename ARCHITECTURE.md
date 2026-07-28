# Architecture & Design Documentation (Client-Side SDK)

## System Overview

The `cost_analytics-SDK` is a lightweight, non-blocking client-side library designed to observe, intercept, and extract usage metadata from LLM API responses without exposing credentials or introducing performance bottlenecks. 

Unlike backend billing systems, the SDK **does not compute costs locally** or manage upstream pricing databases. Instead, it captures token and model details in-memory, buffers them, and flushes request telemetry asynchronously to the server-side backend ([server-side_sdk](file:///d:/Projects/MYSDK/server-side_sdk/manager.py)) where authoritative pricing resolution and final cost computation occur.

```
┌─────────────────────────────────────────────────────────────────────┐
│                          User Application                           │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ LLM Client (Anthropic/OpenAI/Custom) - WRAPPED                 │ │
│  │                                                                │ │
│  │  Original call: client.messages.create(...) or similar         │ │
│  │  Returns: unmodified provider response object                  │ │
│  │                                                                │ │
│  │  Wrapper intercepts response:                                  │ │
│  │    1. Converts response to dict (best effort / user-supplied)  │ │
│  │    2. Extracts usage/model metadata via generic Extractor      │ │
│  │    3. Buffers details in RequestDetailsBuffer                  │ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
        │
        ▼ (Intercepts response metadata & usage)
┌─────────────────────────────────────────────────────────────────────┐
│               RequestDetailsBuffer (In-Memory Buffer)               │
│  • Accumulates RequestDetails (no cost computation on client)       │
│  • Triggers flush when size >= FLUSH_BATCH_SIZE (50)                │
│  • Triggers flush when timer >= FLUSH_INTERVAL_SECONDS (30s)        │
└─────────────────────────────────────────────────────────────────────┘
        │
        ▼ (Batch of RequestDetails)
┌─────────────────────────────────────────────────────────────────────┐
│              TelemetryClient (SDK API Client Component)             │
│  • Sends payload: POST {server_url}/v1/telemetry/flush              │
│  • Fails gracefully: keeps up to 5 failed batches in-memory         │
│  • Retries immediately once if connection is lost or not received   │
└─────────────────────────────────────────────────────────────────────┘
        │
        ▼ (Network POST to server-side_sdk backend)
┌─────────────────────────────────────────────────────────────────────┐
│            Backend Server (server-side_sdk / manager.py)            │
│  • Authenticates telemetry flush (Bearer api_key)                  │
│  • Performs authoritative pricing lookup                            │
│  • Computes final costs & saves to DB                               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Module Hierarchy

The codebase is organized as follows:

```
my-sdk/src/sdk/
├── __init__.py                 # Main SDK exports and package metadata
├── client.py                   # CostAnalyticsClient (lazy authentication & custom pricing submission)
├── sdk.py                      # CostAnalyticsSDK (unified SDK entry point / facade)
├── constants.py                # Constant declarations (currently empty)
├── errors.py                   # Custom SDK exceptions (currently empty)
│
├── api/                        # Telemetry communication layer
│   ├── __init__.py
│   ├── routes.py               # Backend endpoint constants (verify, telemetry, custom pricing)
│   └── telemetry.py            # TelemetryClient for flushing request batches to server
│
├── auth/                       # SDK key authentication configuration
│   ├── __init__.py
│   └── config.py               # Environment variable key lookup helper (CA_API_KEY)
│
├── middleware/                 # Middleware and safety helpers
│   ├── __init__.py
│   └── rate_limit.py           # TokenBucket rate-limiter for telemetry flush budget
│
└── pricing/                    # Extractor and Buffering Engine (SDK-side)
    ├── __init__.py
    ├── aggregator.py          # RequestDetails and RequestDetailsBuffer (backward-compatible aliases)
    ├── extractors.py          # Generic Extractor and UsageBreakdown model
    └── interceptor.py         # CostInterceptor and wrap_custom_client
```

### Test Directory Layout

```
my-sdk/tests/
├── conftest.py                # Pytest configuration
├── unit/                       # Unit tests
│   ├── test_client.py          # Client lifecycle, lazy auth, and pricing submission tests
│   ├── test_cache.py           # Verification cache tests
│   ├── test_errors.py          # Exception validation
│   └── pricing/
│       ├── test_extractors.py  # Usage extraction parsing correctness
│       ├── test_aggregator.py  # Buffer accumulation, flush timing, rate limits, and retry tests
│       └── test_interceptor_custom_wrapper.py # Client wrapping and converter tests
├── integration/                # Integration test suites
└── e2e/                        # End-to-end validations
```

---

## Data Flow Examples

### Example 1: Wrapped LLM Request Flow

1. **User wraps a provider client**:
   ```python
   client = sdk.wrap_client(
       client=client,
       provider="anthropic",
       method_path="messages.create"
   )
   ```
2. **User calls client method**:
   ```python
   response = client.messages.create(
       model="claude-3-opus-20240229",
       messages=[{"role": "user", "content": "Hello"}]
   )
   ```
3. **Method interceptor catches response**:
   The wrapped method in [interceptor.py](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/pricing/interceptor.py) captures the response and converts it into a dictionary using a default converter (e.g. `response.model_dump()`) or a user-provided `response_to_dict` callback.

4. **Usage extraction**:
   The [Extractor](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/pricing/extractors.py) extracts usage metrics and model attributes into a standard [UsageBreakdown](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/pricing/extractors.py) object:
   ```python
   UsageBreakdown(
       input_tokens=100,
       output_tokens=50,
       cache_creation_tokens=0,
       cache_read_tokens=0,
       model="claude-3-opus-20240229",
       provider="anthropic",
       stop_reason="end_turn",
       raw_usage={...}
   )
   ```

5. **In-Memory buffering**:
   The [CostInterceptor](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/pricing/interceptor.py) records these fields in the [RequestDetailsBuffer](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/pricing/aggregator.py) as a [RequestDetails](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/pricing/aggregator.py) instance:
   ```python
   RequestDetails(
       timestamp=datetime.now(UTC),
       request_id="uuid-...",
       model="claude-3-opus-20240229",
       provider="anthropic",
       input_tokens=100,
       output_tokens=50,
       cache_read_tokens=0,
       cache_creation_tokens=0,
       stop_reason="end_turn",
       metadata={"method": "messages.create"}
   )
   ```

6. **Batch Telemetry Flush**:
   When the buffer hits the batch threshold (`FLUSH_BATCH_SIZE = 50`) or the timer expires (`FLUSH_INTERVAL_SECONDS = 30`), the background thread flushes the batch of request records:
   - The buffer calls `on_flush(batch)`.
   - `on_flush` forwards the batch to `TelemetryClient.flush_batch(batch)` in [telemetry.py](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/api/telemetry.py).
   - The `TelemetryClient` posts the data to `POST {server_url}/v1/telemetry/flush`.

7. **Backend computation**:
   The server-side backend receives the telemetry payload, validates credentials, resolves pricing rates for the model, and computes the final cost before recording it to the analytical database.

---

### Example 2: Custom Pricing Submission Flow

A user can submit custom pricing metadata to override default backend provider prices for their account:

```
1. Developer calls:
   client.submit_custom_pricing(
       model="custom-model-v1",
       provider="my-provider",
       input_cost_per_1m_tokens=10.0,
       output_cost_per_1m_tokens=20.0,
       cache_creation_cost_per_1m_tokens=12.5,
       cache_read_cost_per_1m_tokens=1.0
   )

2. CostAnalyticsClient (client.py) prepares payload:
   POST /v1/pricing/custom
   Headers:
     Authorization: Bearer ca_live_...
     X-CA-Key-Id: key-id-...
     X-CA-User-Id: user-id-...

3. Server-side backend intercepts request, authenticates credentials, and updates 
   account-specific custom pricing records.
```

---

## Interception & Usage Extraction

### Dynamic Client Wrapper

The SDK wraps existing client libraries dynamically using the [wrap_custom_client](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/pricing/interceptor.py) function. It splits dotted method paths (e.g. `chat.completions.create` or `messages.create`) to resolve internal API objects and wraps the original method call.

The wrapper:
- Invokes the original API method synchronously.
- Converts the response to a dictionary using a standard conversion sequence (`model_dump` -> `dict` -> `__dict__` -> fallback string).
- Merges user-supplied static metadata and method path identifiers.
- Invokes [CostInterceptor.process_response](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/pricing/interceptor.py) in-line, ensuring that any failures in the extraction logic are caught gracefully and do not disrupt the client application.

### Generic Extractor

Rather than utilizing individual extractor classes for each provider, the SDK provides a single, unified [Extractor](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/pricing/extractors.py) class implementing the [UsageExtractor](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/pricing/extractors.py) base interface.

It parses standard provider formats by checking for:
- Input tokens: `input_tokens` (Anthropic) or `prompt_tokens` (OpenAI).
- Output tokens: `output_tokens` (Anthropic) or `completion_tokens` (OpenAI).
- Cached read tokens: `cache_read_tokens`, `cache_read_input_tokens`, or `cached_prompt_tokens`.
- Cache creation tokens: `cache_creation_tokens` or `cache_creation_input_tokens`.
- Stop reasons: checks `choices[0].finish_reason` (OpenAI) or `stop_reason` (Anthropic).

---

## Request Details & Buffering Model

### RequestDetails Data Structure

Records in the buffer are represented by the [RequestDetails](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/pricing/aggregator.py) dataclass. It contains exclusively metadata required for backend cost identification:

```python
@dataclass
class RequestDetails:
    timestamp: datetime
    request_id: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    stop_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### RequestDetailsBuffer & Flush Mechanism

The [RequestDetailsBuffer](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/pricing/aggregator.py) class acts as a thread-safe cache buffer:
- **Thread Safety**: Employs a reentrant lock (`threading.RLock`) to synchronize batch additions and buffer clearings.
- **Timer Trigger**: Launches a background daemon thread (`threading.Timer`) configured to run every `FLUSH_INTERVAL_SECONDS = 30` to flush the buffer even if the size limit is not reached.
- **Batch Trigger**: Immediately checks the buffer size on request entry. If `size >= FLUSH_BATCH_SIZE = 50`, it flushes immediately.
- **Rate-Limiting (Token Bucket)**: Batch-based flushes are rate-limited via a [TokenBucket](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/middleware/rate_limit.py) (capacity = 1, refill rate = 1 token per 30 seconds) to prevent redundant concurrent telemetry uploads. If rate limit is hit, the flush is deferred to the next timer tick.

For backward compatibility, a helper function `get_cost_aggregator()` is provided as an alias for `get_request_buffer()`.

---

## Telemetry & API Client

### Telemetry Client (`TelemetryClient`)

Defined in [telemetry.py](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/api/telemetry.py), the [TelemetryClient](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/api/telemetry.py) transmits batches to the backend:
- **Batch Retention**: If a telemetry request fails, the client saves the failed batch in-memory. Up to `MAX_FAILED_BATCHES = 5` batches are retained (oldest are dropped if exceeded) to prevent memory leaks during extended backend outages.
- **Immediate Retry**: If an exception indicates that the request was connection-based or "not received" (e.g. `requests.ConnectionError`), the client attempts an immediate retry once before retaining the batch.
- **Batch Re-delivery**: On subsequent successful flushes, previously retained failed batches are automatically re-submitted.

### Lazy API-Key client (`CostAnalyticsClient`)

The [CostAnalyticsClient](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/client.py) handles authenticated client-server telemetry and utility requests:
- **Lazy Authentication**: API key loading and validation against `GET /v1/auth/verify` are deferred until the first HTTP request is executed, reducing startup overhead.
- **Key Validation**: Ensures keys are format-compliant (prefixed with `ca_live_`).
- **Header Enrichment**: Automatically injects identity and routing headers into requests:
  - `Authorization: Bearer <api_key>`
  - `X-CA-Key-Id`: Hashed API key identifier returned by server auth.
  - `X-CA-User-Id`: Resolved user account ID returned by server auth.
  - `X-Request-Id`: Client-generated UUID for tracing.
  - `X-CA-Provider` / `X-CA-Model`: Target model descriptors.

---

## Error Handling Strategy

1. **Extraction Safeguards**:
   If the usage extraction fail or field parsing errors occur in [extractors.py](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/pricing/extractors.py), the error is logged as a warning, and the request details are skipped. The user application's main thread is never interrupted by extraction failures.

2. **Telemetry Failures**:
   Timer-based and batch flushes execute in separate threads. If HTTP transmission fails, the thread logs the warning and retains the batch. Exceptions are not raised to the main application thread.

3. **Lazy Key Authentication**:
   - Authentication validation failures (401/403) from `GET /v1/auth/verify` fail fast, raising an `AuthenticationError` to prevent unnecessary retries.
   - Server-side transient issues (5xx status codes) are retried up to `max_retries = 3` using exponential backoff before propagating the failure.

4. **Shutdown Operations**:
   Calling `shutdown()` on [CostAnalyticsSDK](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/src/sdk/sdk.py) manually triggers a final flush of remaining requests, cancels pending background timers, and closes HTTP sessions cleanly.

---

## Performance Considerations

- **In-Memory Buffering**: Because request metadata is kept in-memory and buffered in batches of 50 or on 30-second cycles, database and remote network latency are excluded from the main execution path.
- **Batch Retention Bounds**: Bounding retained failed telemetry batches at 5 keeps memory footprints minimal even if connection to the telemetry server is lost for hours.
- **Non-Blocking Background Threads**: Buffering and flushing actions run on daemon threads, separating network latency from user client calls.
- **Thread Safety**: Every manipulation of the in-memory queue is protected by reentrant lock semantics, preventing race conditions in highly concurrent environments (e.g. multi-threaded web servers).

---

## Security Considerations

- **Credential Separation**: The SDK does not read, store, or transmit provider-specific credentials (OpenAI keys, Anthropic keys). It only observes response structures returned by the provider SDK.
- **API Key Formatting**: Evaluates local client credentials to ensure proper `ca_live_` formatting before initiating authentication requests.
- **No Content Telemetry**: Only request tokens, provider names, model names, stop reasons, and developer-provided metadata are recorded. The SDK **never** transmits request prompt text, response completions, or other potential PII.

---

## Testing Strategy

All features are covered by targeted unit and integration suites in the `tests/` directory:

1. **Usage Extraction Tests** ([test_extractors.py](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/tests/unit/pricing/test_extractors.py)):
   Verifies model extraction, stop reason parsing, and prompt/completion extraction from standard OpenAI-style (`prompt_tokens`/`completion_tokens`/`cached_prompt_tokens`) and Anthropic-style (`input_tokens`/`output_tokens`/`cache_creation_input_tokens`/`cache_read_input_tokens`) response payloads.

2. **Details Buffer Tests** ([test_aggregator.py](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/tests/unit/pricing/test_aggregator.py)):
   Verifies request recording, size-based batch threshold triggers, flush rate-limiting, manual flushing, flush failures re-adding items back to the buffer, metadata enrichment, clear operations, and daemon shutdown cleanup.

3. **Interceptor Wrapper Tests** ([test_interceptor_custom_wrapper.py](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/tests/unit/pricing/test_interceptor_custom_wrapper.py)):
   Verifies dotted method path resolution on nested clients (e.g. `client.responses.create`), custom response conversion callbacks, and static metadata merging.

4. **Client Auth and Lifecycle Tests** ([test_client.py](file:///d:/Projects/MYSDK/cost_analytics-SDK/my-sdk/tests/unit/test_client.py)):
   Tests environment variable integration (`CA_API_KEY`), lazy authentication, connection retry behaviors under 5xx server states, custom pricing API requests (`submit_custom_pricing`), and session cleanup.
