"""Tests for generic custom client wrapper support."""

from sdk.pricing.aggregator import RequestDetailsBuffer
from sdk.pricing.interceptor import CostInterceptor, wrap_custom_client
from sdk.sdk import CostAnalyticsSDK


class _ResponseObject:
    def __init__(self, model: str, stop_reason: str = "end_turn"):
        self.model = model
        self.stop_reason = stop_reason


class _NestedAPI:
    def __init__(self):
        self._calls = 0

    def create(self, prompt: str):
        self._calls += 1
        return {
            "model": "custom-model-v1",
            "stop_reason": "stop",
            "echo": prompt,
        }


class _DummyClient:
    def __init__(self):
        self.responses = _NestedAPI()


class _DummyDirectClient:
    def __init__(self):
        self._calls = 0

    def invoke(self, prompt: str):
        self._calls += 1
        return _ResponseObject(model="direct-model-v1")


class TestCustomClientWrapper:
    def setup_method(self):
        self.aggregator = RequestDetailsBuffer()
        

    def test_wrap_custom_nested_method_path(self):
        client = _DummyClient()
        interceptor = CostInterceptor(aggregator=self.aggregator)

        wrap_custom_client(
            client=client,
            provider="custom",
            method_path="responses.create",
            interceptor=interceptor,
            static_metadata={"source": "unit-test"},
        )

        response = client.responses.create("hello")

        assert response["model"] == "custom-model-v1"
        assert self.aggregator.get_buffer_size() == 1

        pending = self.aggregator.get_pending_requests()[0]
        assert pending.provider == "custom"
        assert pending.metadata["method"] == "responses.create"
        assert pending.metadata["source"] == "unit-test"
        assert pending.model == "custom-model-v1"

    def test_wrap_custom_with_response_converter(self):
        client = _DummyDirectClient()
        interceptor = CostInterceptor(aggregator=self.aggregator)

        wrap_custom_client(
            client=client,
            provider="direct",
            method_path="invoke",
            interceptor=interceptor,
            response_to_dict=lambda r: {
                "model": r.model,
                "stop_reason": r.stop_reason,
            },
        )

        response = client.invoke("run")

        assert response.model == "direct-model-v1"
        assert self.aggregator.get_buffer_size() == 1

        pending = self.aggregator.get_pending_requests()[0]
        assert pending.provider == "direct"
        assert pending.metadata["method"] == "invoke"
        assert pending.model == "direct-model-v1"

    def test_sdk_wrap_custom_reuses_sdk_interceptor(self):
        client = _DummyClient()
        sdk = CostAnalyticsSDK(api_key="test-key", client_id="test-client")
        

        sdk.wrap_client(
            client=client,
            provider="sdk-custom",
            method_path="responses.create",
            metadata={"integration": "sdk"},
        )

        client.responses.create("track")

        assert sdk.aggregator.get_buffer_size() == 1
        pending = sdk.aggregator.get_pending_requests()[0]
        assert pending.provider == "sdk-custom"
        assert pending.metadata["integration"] == "sdk"
        assert pending.metadata["method"] == "responses.create"
