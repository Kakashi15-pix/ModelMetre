#Tests for request details buffer.

import pytest
from datetime import datetime, timedelta
from casdk import RequestDetailsBuffer, RequestDetails


class TestRequestDetailsBuffer:
    """Test request details buffering and flushing."""

    def test_record_single_request(self):
        """Test recording a single request."""
        buffer = RequestDetailsBuffer()
        
        buffer.record_request(
            request_id="req_001",
            model="claude-3-opus-20240229",
            provider="anthropic",
            input_tokens=1000,
            output_tokens=100,
        )
        
        assert buffer.get_buffer_size() == 1
        requests = buffer.get_pending_requests()
        assert requests[0].request_id == "req_001"

    def test_buffer_accumulation(self):
        """Test requests accumulate in buffer."""
        buffer = RequestDetailsBuffer()
        
        for i in range(5):
            buffer.record_request(
                request_id=f"req_{i:03d}",
                model="claude-3-opus-20240229",
                provider="anthropic",
                input_tokens=1000,
                output_tokens=100,
            )
        
        assert buffer.get_buffer_size() == 5

    def test_flush_on_batch_threshold(self):
        """Test flush triggered at batch size threshold."""
        flush_called = []
        
        def on_flush(batch):
            flush_called.append(len(batch))
        
        buffer = RequestDetailsBuffer(on_flush=on_flush)
        
        # Record 50 requests to trigger flush
        for i in range(50):
            buffer.record_request(
                request_id=f"req_{i:03d}",
                model="claude-3-opus-20240229",
                provider="anthropic",
                input_tokens=1000,
                output_tokens=100,
            )
        
        assert len(flush_called) == 1
        assert flush_called[0] == 50
        assert buffer.get_buffer_size() == 0

    def test_flush_on_batch_threshold_is_rate_limited(self):
        """Test batch flush defers when the flush budget is exhausted."""
        flush_called = []

        def on_flush(batch):
            flush_called.append(len(batch))

        buffer = RequestDetailsBuffer(on_flush=on_flush)
        buffer._flush_timer.cancel()
        buffer._batch_flush_limiter.acquire = lambda: False

        for i in range(50):
            buffer.record_request(
                request_id=f"req_{i:03d}",
                model="claude-3-opus-20240229",
                provider="anthropic",
                input_tokens=1000,
                output_tokens=100,
            )

        assert flush_called == []
        assert buffer.get_buffer_size() == 50

    def test_manual_flush(self):
        """Test manual flush call."""
        flush_called = []
        
        def on_flush(batch):
            flush_called.append(len(batch))
        
        buffer = RequestDetailsBuffer(on_flush=on_flush)
        
        # Add a few requests
        for i in range(5):
            buffer.record_request(
                request_id=f"req_{i:03d}",
                model="claude-3-opus-20240229",
                provider="anthropic",
                input_tokens=1000,
                output_tokens=100,
            )
        
        assert buffer.get_buffer_size() == 5
        
        # Manual flush
        buffer.flush()
        
        assert len(flush_called) == 1
        assert flush_called[0] == 5
        assert buffer.get_buffer_size() == 0

    def test_request_details_with_cache_tokens(self):
        """Test recording request with cache tokens."""
        buffer = RequestDetailsBuffer()
        
        buffer.record_request(
            request_id="req_001",
            model="claude-3-opus-20240229",
            provider="anthropic",
            input_tokens=1000,
            output_tokens=100,
            cache_read_tokens=500,
            cache_creation_tokens=200,
        )
        
        requests = buffer.get_pending_requests()
        assert requests[0].cache_read_tokens == 500
        assert requests[0].cache_creation_tokens == 200

    def test_request_details_to_dict(self):
        """Test RequestDetails serialization to dict."""
        details = RequestDetails(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            request_id="req_001",
            model="claude-3-opus-20240229",
            provider="anthropic",
            input_tokens=1000,
            output_tokens=100,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            stop_reason="end_turn",
        )
        
        data = details.to_dict()
        
        assert data["request_id"] == "req_001"
        assert data["model"] == "claude-3-opus-20240229"
        assert data["input_tokens"] == 1000
        assert data["stop_reason"] == "end_turn"
        assert isinstance(data["timestamp"], str)

    def test_buffer_with_metadata(self):
        """Test recording request with metadata."""
        buffer = RequestDetailsBuffer()
        
        buffer.record_request(
            request_id="req_001",
            model="claude-3-opus-20240229",
            provider="anthropic",
            input_tokens=1000,
            output_tokens=100,
            metadata={"user_id": "user_123", "session": "sess_456"},
        )
        
        requests = buffer.get_pending_requests()
        assert requests[0].metadata["user_id"] == "user_123"
        assert requests[0].metadata["session"] == "sess_456"

    def test_clear_buffer(self):
        """Test clearing the buffer."""
        buffer = RequestDetailsBuffer()
        
        # Add some requests
        for i in range(5):
            buffer.record_request(
                request_id=f"req_{i:03d}",
                model="claude-3-opus-20240229",
                provider="anthropic",
                input_tokens=1000,
                output_tokens=100,
            )
        
        assert buffer.get_buffer_size() == 5
        
        buffer.clear()
        
        assert buffer.get_buffer_size() == 0

    def test_flush_on_empty_buffer(self):
        """Test flush on empty buffer does nothing."""
        flush_called = []
        
        def on_flush(batch):
            flush_called.append(len(batch))
        
        buffer = RequestDetailsBuffer(on_flush=on_flush)
        buffer.flush()
        
        # on_flush should not be called for empty buffer
        assert len(flush_called) == 0

    def test_flush_failure_re_adds_batch(self):
        """Test that failed flush re-adds batch to buffer."""
        flush_count = [0]
        
        def on_flush(batch):
            flush_count[0] += 1
            if flush_count[0] == 1:
                raise Exception("Flush failed")
        
        buffer = RequestDetailsBuffer(on_flush=on_flush)
        
        # Add requests
        for i in range(5):
            buffer.record_request(
                request_id=f"req_{i:03d}",
                model="claude-3-opus-20240229",
                provider="anthropic",
                input_tokens=1000,
                output_tokens=100,
            )
        
        # Manual flush (will fail)
        buffer.flush()
        
        # Buffer should still contain the 5 requests
        assert buffer.get_buffer_size() == 5

    def test_multiple_models_and_providers(self):
        """Test buffer with multiple models and providers."""
        buffer = RequestDetailsBuffer()
        
        # Anthropic requests
        for i in range(3):
            buffer.record_request(
                request_id=f"anthropic_{i:03d}",
                model="claude-3-opus-20240229",
                provider="anthropic",
                input_tokens=1000,
                output_tokens=100,
            )
        
        # OpenAI requests
        for i in range(2):
            buffer.record_request(
                request_id=f"openai_{i:03d}",
                model="gpt-4",
                provider="openai",
                input_tokens=500,
                output_tokens=50,
            )
        
        assert buffer.get_buffer_size() == 5
        requests = buffer.get_pending_requests()
        
        anthropic_requests = [r for r in requests if r.provider == "anthropic"]
        openai_requests = [r for r in requests if r.provider == "openai"]
        
        assert len(anthropic_requests) == 3
        assert len(openai_requests) == 2
        
    def test_shutdown_flushes_remaining_requests(self):
     flushed_batches = []

     buffer = RequestDetailsBuffer(
        on_flush=lambda batch: flushed_batches.append(batch)
    )

     buffer.record_request(
        request_id="1",
        model="gpt-4o",
        provider="openai",
        input_tokens=10,
        output_tokens=5,
    )

     buffer.shutdown()

     assert len(flushed_batches) == 1
     assert len(flushed_batches[0]) == 1
     assert buffer.get_buffer_size() == 0