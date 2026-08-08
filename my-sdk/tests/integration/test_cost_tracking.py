"""Integration tests for request-detail tracking."""

from sdk.pricing import CostInterceptor
from sdk.pricing import aggregator
from sdk.pricing.aggregator import RequestDetailsBuffer


class TestCostInterceptor:
    """Test SDK-side request detail buffering."""

    def setup_method(self):
        self.aggregator = RequestDetailsBuffer()
       

    def test_process_response_buffers_common_usage_shape(self):
        interceptor = CostInterceptor(aggregator=self.aggregator)
        response = {
            "id": "msg_123",
            "model": "custom-model-v1",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_creation_input_tokens": 25,
                "cache_read_input_tokens": 10,
            },
            "stop_reason": "end_turn",
        }

        result = interceptor.process_response(
            response,
            provider="custom-provider",
            request_id="req_001",
            metadata={"tenant": "test"},
        )

        assert result is not None
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.cache_creation_tokens == 25
        assert result.cache_read_tokens == 10
        assert result.model == "custom-model-v1"
        assert result.provider == "custom-provider"
        assert self.aggregator.get_buffer_size() == 1

        pending = self.aggregator.get_pending_requests()[0]
        assert pending.request_id == "req_001"
        assert pending.provider == "custom-provider"
        assert pending.model == "custom-model-v1"
        assert pending.input_tokens == 100
        assert pending.output_tokens == 50
        assert pending.cache_creation_tokens == 25
        assert pending.cache_read_tokens == 10
        assert pending.stop_reason == "end_turn"
        assert pending.metadata["tenant"] == "test"

    def test_process_response_buffers_prompt_completion_usage_shape(self):
        interceptor = CostInterceptor(aggregator=self.aggregator)
        response = {
            "id": "resp_123",
            "model": "another-model-v1",
            "usage": {
                "prompt_tokens": 200,
                "completion_tokens": 75,
                "cached_prompt_tokens": 20,
            },
        }

        interceptor.process_response(
            response,
            provider="another-provider",
            request_id="req_002",
        )

        pending = self.aggregator.get_pending_requests()[0]
        assert pending.provider == "another-provider"
        assert pending.model == "another-model-v1"
        assert pending.input_tokens == 200
        assert pending.output_tokens == 75
        assert pending.cache_read_tokens == 20

    def test_multiple_requests_are_buffered_for_backend_flush(self):
        interceptor = CostInterceptor(aggregator=self.aggregator)

        for index in range(3):
            interceptor.process_response(
                {
                    "model": f"model-{index}",
                    "usage": {
                        "input_tokens": 100 + index,
                        "output_tokens": 50 + index,
                    },
                },
                provider="custom-provider",
                request_id=f"req_{index:03d}",
            )

        pending = self.aggregator.get_pending_requests()
        assert len(pending) == 3
        assert [request.request_id for request in pending] == [
            "req_000",
            "req_001",
            "req_002",
        ]
