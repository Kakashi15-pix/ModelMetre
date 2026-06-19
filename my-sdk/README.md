# LLM Cost Observability SDK

Client-side SDK for provider response interception, usage extraction, request buffering, and optional telemetry flush to a backend cost pipeline.
## What This SDK Does

- Wraps provider SDK methods without changing normal response behavior.
- Extracts usage metadata from provider responses locally.
- Buffers request details in-memory.
- Flushes buffered batches on size/time thresholds.
- Optionally sends flushed batches to backend telemetry endpoint.
- Supports lazy API-key verification for direct server API calls via `CostAnalyticsClient`.

## What This SDK Does Not Do On Client

- Does not perform authoritative upstream pricing sync on the client.
- Does not do final backend-grade cost computation in the main intercept-and-flush path.
- Does not require provider credentials to leave the client environment.

## Architecture (Current)

1. Your app calls provider SDK (Anthropic/OpenAI/custom).
2. Wrapped method runs, returns original provider response.
3. Interceptor extracts usage/model/stop reason.
4. `RequestDetailsBuffer` stores request details locally.
5. Buffer flushes when:
   - `FLUSH_BATCH_SIZE` reached (default `50`), or
   - timer hits `FLUSH_INTERVAL_SECONDS` (default `30`).
6. If telemetry is configured, flushed batch is POSTed to backend (`/v1/telemetry/flush` by default).
7. Backend resolves pricing and computes final costs.

## Package Layout (Relevant)

- `my-sdk/src/sdk.py`: `CostAnalyticsSDK` facade.
- `my-sdk/src/pricing/interceptor.py`: wrapping and extraction pipeline.
- `my-sdk/src/pricing/extractors.py`: provider extractors.
- `my-sdk/src/pricing/aggregator.py`: request buffer + flush triggers.
- `my-sdk/src/api/telemetry.py`: telemetry sender with failed flush retention/retry behavior.
- `my-sdk/src/client.py`: authenticated API client (`CostAnalyticsClient`) with lazy key verification.
- `my-sdk/src/auth/Config.py`: env-based API key loading (`CA_API_KEY`).

## Install

```bash
pip install -e .
```

## Quick Start

### 1) Wrap a Provider Client

```python
from anthropic import Anthropic
from sdk import CostAnalyticsSDK

sdk = CostAnalyticsSDK(server_url="https://telemetry.example.com")

client = Anthropic()
client = sdk.wrap_client(
    client=client,
    provider="anthropic",
    method_path="messages.create",
)

response = client.messages.create(
    model="claude-3-haiku-20240307",
    max_tokens=128,
    messages=[{"role": "user", "content": "Hello"}],
)

print(sdk.get_metrics())
```

### 2) Wrap Other Client Shapes

```python
from sdk import CostAnalyticsSDK

sdk = CostAnalyticsSDK(server_url="https://telemetry.example.com")

client = sdk.wrap_client(
    client=client,
    provider="custom-provider",
    method_path="responses.create",
)
```

### 3) Manual Flush

```python
from pricing import get_request_buffer

buffer = get_request_buffer()
buffer.flush()
```

## Core APIs

### `CostAnalyticsSDK` (`my-sdk/src/sdk.py`)

- `CostAnalyticsSDK(server_url: Optional[str] = None)`
- `wrap_client(client, provider, method_path, response_to_dict=None, metadata=None)`
- `process_response(response, provider, request_id=None, metadata=None)`
- `get_metrics()`
- `get_pending_requests()`
- `flush_buffer()`

`get_metrics()` currently returns buffer-oriented metrics:

```json
{
  "buffer_size": 12,
  "pending_requests": 12
}
```

### Buffer (`my-sdk/src/pricing/aggregator.py`)

- `FLUSH_BATCH_SIZE = 50`
- `FLUSH_INTERVAL_SECONDS = 30`
- `get_request_buffer()` / `get_cost_aggregator()`
- `RequestDetailsBuffer.record_request(...)`
- `RequestDetailsBuffer.flush()`
- `RequestDetailsBuffer.get_pending_requests()`

### Telemetry (`my-sdk/src/api/telemetry.py`)

`TelemetryClient` behavior:

- Sends flush payload to `POST {server_url}/v1/telemetry/flush` (default endpoint path).
- Includes headers:
  - `Content-Type: application/json`
  - `X-Client-ID: <uuid>`
  - optional `Authorization: Bearer <api_key>`
- On flush failure, retains up to last 5 failed batches in-memory.
- If failure looks like "request not received", retries once immediately.
- Failed batches are retried on subsequent flush attempts.

## Auth for SDK-to-Server API Calls

`CostAnalyticsClient` (`my-sdk/src/client.py`) supports direct authenticated calls to server APIs.

- Reads `CA_API_KEY` when `api_key` not passed.
- Performs lazy auth verification against `GET /v1/auth/verify` (default path).
- Sends request metadata headers:
  - `Authorization`
  - `X-CA-Key-Id`
  - `X-CA-User-Id`
  - `X-Request-Id`
  - `X-CA-Provider`
  - `X-CA-Model`

Example:

```python
from client import CostAnalyticsClient

client = CostAnalyticsClient(
    api_key="ca_live_...",
    base_url="https://api.example.com",
)

resp = client.request("GET", "/v1/costs")
print(resp.status_code)
```

## Environment Variables

- `CA_API_KEY`: client API key for `CostAnalyticsClient`.
- `CA_API_BASE_URL`: optional base URL override for `CostAnalyticsClient`.

Note: backend services may require additional variables (for example server HMAC secret) that are configured in the server repository.

## Backend Contract Expectations

Telemetry flush endpoint should accept payload in this shape:

```json
{
  "client_id": "uuid",
  "batch": [
    {
      "timestamp": "2026-01-01T00:00:00.000000",
      "request_id": "req-123",
      "model": "claude-3-haiku-20240307",
      "provider": "anthropic",
      "input_tokens": 100,
      "output_tokens": 50,
      "cache_read_tokens": 0,
      "cache_creation_tokens": 0,
      "stop_reason": "end_turn",
      "metadata": {"method": "messages.create"}
    }
  ]
}
```

Auth verification endpoint expected by `CostAnalyticsClient`:

- `GET /v1/auth/verify`
- Response:

```json
{
  "user_id": "...",
  "api_key_id": "..."
}
```

## Testing

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Notes on Compatibility Surface

The SDK exposes one generic extractor/interceptor path. Provider names are metadata values passed to `wrap_client`; authoritative pricing resolution lives on the backend.
