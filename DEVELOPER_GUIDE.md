# Developer Guide: Cost Analytics + Server Auth

This document is an onboarding map for engineers working across both repositories:
- cost_analytics-SDK
- server-side_sdk

It explains ownership boundaries, key runtime flows, where to implement changes, and how to test safely.

## 1) Repo responsibilities

### cost_analytics-SDK
Client-side SDK for LLM cost observability.

Main responsibilities:
- wrap LLM clients (Anthropic/OpenAI/custom)
- capture response context and metadata for analytics
- buffer and flush request details to backend
- expose SDK wrappers and authenticated client for backend calls
- provide a lightweight authenticated HTTP client for backend calls

### server-side_sdk
Server-side auth and policy primitives.

Main responsibilities:
- API key verification dependency for FastAPI
- API key lifecycle service (create, revoke, rotate)
- key-first then user-fallback rate limiting middleware
- pricing lookup and cost computation orchestration
- security rules for key hashing, masking, expiry clock skew, cache TTL

## 2) High-level architecture

### SDK-side flow (cost_analytics-SDK)
1. App calls wrapped provider SDK.
2. Interceptor captures response payload and request metadata.
3. RequestDetailsBuffer records lightweight request details.
4. Buffer flush callback sends batched request details to backend.
5. Backend computes usage/cost using pricing data.
6. App and dashboard consume backend analytics data.

Primary files:
- [my-sdk/src/sdk.py](my-sdk/src/sdk.py)
- [my-sdk/src/client.py](my-sdk/src/client.py)
- [my-sdk/src/pricing/interceptor.py](my-sdk/src/pricing/interceptor.py)
- [my-sdk/src/pricing/extractors.py](my-sdk/src/pricing/extractors.py)
- [my-sdk/src/pricing/aggregator.py](my-sdk/src/pricing/aggregator.py)

Note: Pricing lookup and upstream sync are handled by the backend `PricingManager`
located at [server-side_sdk/manager.py](../server-side_sdk/manager.py). The SDK's
pricing modules focus on extraction, buffering and the interceptor flow; the
backend performs authoritative pricing resolution and caching by default.

### Server-side auth flow (server-side_sdk)
1. Request carries Bearer API key.
2. verify_api_key derives HMAC hash and loads key record.
3. Validation checks run in order: exists, revoked, expiry with clock skew.
4. Auth context is attached to request state.
5. Optional cache stores auth context using hashed key only.
6. Rate-limiter consumes key bucket first, then user bucket fallback.

Primary files:
- [server-side_sdk/auth.py](../server-side_sdk/auth.py)
- [server-side_sdk/api_keys.py](../server-side_sdk/api_keys.py)
- [server-side_sdk/rate_limit.py](../server-side_sdk/rate_limit.py)
- [server-side_sdk/manager.py](../server-side_sdk/manager.py)

## 3) End-to-end request path between repos

When SDK API-key client is used against backend auth:
1. SDK client validates key lazily on first request via verify endpoint.
2. Backend verify_api_key checks hash/revocation/expiry and returns identity.
3. SDK caches identity in-memory and includes metadata headers on requests.
4. Backend middleware can use request auth context for rate limiting.

Relevant files:
- [my-sdk/src/client.py](my-sdk/src/client.py)
- [server-side_sdk/auth.py](../server-side_sdk/auth.py)
- [server-side_sdk/rate_limit.py](../server-side_sdk/rate_limit.py)

## 4) Security invariants (must not change)

1. Never persist or log raw API keys.
2. Key hash algorithm is HMAC-SHA256 with CA_KEY_HMAC_SECRET.
3. Log masking format is ca_live_****.
4. Expiry checks must allow bounded clock skew.
5. Auth cache TTL must stay at or below 60 seconds.
6. Authentication failures must fail fast and not retry as transient errors.

## 5) Where to implement common changes

### Add a new provider to SDK pricing
1. Add extractor mapping logic in pricing extractors.
2. Register provider in extractor registry.
3. Update backend pricing/cost orchestration if provider pricing rules differ.
4. Add wrapper integration in interceptor layer.
5. Add tests for extraction and backend cost computation.

Start here:
- [my-sdk/src/pricing/extractors.py](my-sdk/src/pricing/extractors.py)
- [my-sdk/src/pricing/interceptor.py](my-sdk/src/pricing/interceptor.py)
- Backend pricing manager: [server-side_sdk/manager.py](../server-side_sdk/manager.py)
- [my-sdk/tests/integration/test_cost_tracking.py](my-sdk/tests/integration/test_cost_tracking.py)

### Modify API key policy
1. Update verify logic and security helpers.
2. Update API key lifecycle behavior if needed.
3. Re-run auth, skew, and security-at-rest tests.

Start here:
- [server-side_sdk/auth.py](../server-side_sdk/auth.py)
- [server-side_sdk/api_keys.py](../server-side_sdk/api_keys.py)
- [server-side_sdk/tests/test_auth.py](../server-side_sdk/tests/test_auth.py)
- [server-side_sdk/tests/test_api_keys.py](../server-side_sdk/tests/test_api_keys.py)

### Change rate-limiting strategy
1. Update key-first/user-fallback policy.
2. Validate middleware behavior with and without auth context.

Start here:
- [server-side_sdk/rate_limit.py](../server-side_sdk/rate_limit.py)
- [server-side_sdk/tests/test_rate_limit.py](../server-side_sdk/tests/test_rate_limit.py)

## 6) Testing map

### SDK tests
- Auth-focused script: [my-sdk/scripts/test_auth.sh](my-sdk/scripts/test_auth.sh)
- Unit auth tests: [my-sdk/tests/unit/auth/test_client_auth.py](my-sdk/tests/unit/auth/test_client_auth.py)
- Integration auth tests: [my-sdk/tests/integration/test_auth_flow.py](my-sdk/tests/integration/test_auth_flow.py)

### Server tests
- Auth test script: [server-side_sdk/test.sh](../server-side_sdk/test.sh)
- Auth verification tests: [server-side_sdk/tests/test_auth.py](../server-side_sdk/tests/test_auth.py)
- API key lifecycle tests: [server-side_sdk/tests/test_api_keys.py](../server-side_sdk/tests/test_api_keys.py)
- Rate-limit tests: [server-side_sdk/tests/test_rate_limit.py](../server-side_sdk/tests/test_rate_limit.py)
- Real DB test guide: [server-side_sdk/docs/auth-db-testing.md](../server-side_sdk/docs/auth-db-testing.md)

## 7) Local run checklist

1. Set required env vars before auth tests (especially CA_KEY_HMAC_SECRET on server-side).
2. Run unit tests first, integration tests second.
3. Keep test data isolated and never target shared environments.
4. Verify no raw key appears in logs, assertions, or snapshots.

## 8) Quick onboarding path for new developers

1. Read [README.md](README.md) for SDK usage.
2. Read [ARCHITECTURE.md](ARCHITECTURE.md) for pricing/interceptor internals.
3. Read [server-side_sdk/docs/auth-db-testing.md](../server-side_sdk/docs/auth-db-testing.md) for DB-backed auth testing expectations.
4. Run auth tests in both repos.
5. Make small, test-backed changes before touching shared interfaces.
