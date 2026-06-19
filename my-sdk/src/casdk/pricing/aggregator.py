"""
Request details buffer and backend flush mechanism.
Accumulates request data extraction only, flushes to backend on threshold or timer.
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Dict, List, Any, Optional, Callable
import logging
import threading

from ..middleware.rate_limit import TokenBucket

logger = logging.getLogger(__name__)

# Flush constants
FLUSH_BATCH_SIZE = 50  # Flush after 50 requests
FLUSH_INTERVAL_SECONDS = 30  # Flush after 30 seconds


@dataclass
class RequestDetails:
    """Single API request details record (extraction only, no costs)."""
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

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for backend transmission."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "request_id": self.request_id,
            "model": self.model,
            "provider": self.provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "stop_reason": self.stop_reason,
            "metadata": self.metadata,
        }


class RequestDetailsBuffer:
    """Buffers request details and flushes to backend on threshold or timer."""

    def __init__(self, on_flush: Optional[Callable[[List[RequestDetails]], None]] = None):
        """
        Initialize buffer.
        
        Args:
            on_flush: Callback when buffer should flush to backend.
                      Receives list of RequestDetails to send.
        """
        self.buffer: List[RequestDetails] = []
        self.on_flush = on_flush
        self._lock = threading.RLock()
        self._last_flush_time = datetime.now(UTC)
        self._flush_timer: Optional[threading.Timer] = None
        self._batch_flush_limiter = TokenBucket(capacity=1, refill_rate=1 / FLUSH_INTERVAL_SECONDS)
        self._start_timer()

    def _start_timer(self) -> None:
        """Start a timer to flush after FLUSH_INTERVAL_SECONDS."""
        with self._lock:
            if self._flush_timer:
                self._flush_timer.cancel()
            self._flush_timer = threading.Timer(
                FLUSH_INTERVAL_SECONDS,
                self._on_timer_flush
            )
            self._flush_timer.daemon = True
            self._flush_timer.start()

    def _on_timer_flush(self) -> None:
        """Called by timer to flush if buffer has data."""
        with self._lock:
            if self.buffer:
                logger.debug(
                    f"Flushing {len(self.buffer)} requests due to timer ({FLUSH_INTERVAL_SECONDS}s)"
                )
                self.flush()
            # Restart timer
            self._start_timer()

    def record_request(
        self,
        request_id: str,
        model: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        stop_reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record a request and check if flush is needed.
        
        Args:
            request_id: Unique request identifier
            model: Model used for request
            provider: Provider name ('anthropic', 'openai', etc.)
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cache_read_tokens: Cache read tokens (optional)
            cache_creation_tokens: Cache creation tokens (optional)
            stop_reason: Reason request stopped (optional)
            metadata: Additional metadata (optional)
        """
        details = RequestDetails(
            timestamp=datetime.now(UTC),
            request_id=request_id,
            model=model,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            stop_reason=stop_reason,
            metadata=metadata or {},
        )

        with self._lock:
            self.buffer.append(details)
            logger.debug(
                f"Buffered request {request_id} for {model} "
                f"({input_tokens} in, {output_tokens} out) - buffer size: {len(self.buffer)}"
            )

            # Check if batch threshold reached
            if len(self.buffer) >= FLUSH_BATCH_SIZE and self._batch_flush_limiter.acquire():
                logger.debug(
                    f"Flushing {len(self.buffer)} requests due to batch size threshold"
                )
                self.flush()
            elif len(self.buffer) >= FLUSH_BATCH_SIZE:
                logger.debug(
                    "Batch size threshold reached but flush budget is exhausted; waiting for timer"
                )

    def flush(self) -> None:
        """Flush buffer to backend and clear."""
        with self._lock:
            if not self.buffer:
                logger.debug("Buffer is empty, skipping flush")
                return

            batch = self.buffer.copy()
            self.buffer.clear()
            self._last_flush_time = datetime.now(UTC)

            # Call backend callback outside lock to avoid blocking
            if self.on_flush:
                try:
                    logger.info(f"Flushing {len(batch)} requests to backend")
                    self.on_flush(batch)
                except Exception as e:
                    logger.error(f"Failed to flush to backend: {e}")
                    # Re-add batch to buffer on failure
                    self.buffer.extend(batch)

    def get_buffer_size(self) -> int:
        """Get current buffer size."""
        with self._lock:
            return len(self.buffer)

    def get_pending_requests(self) -> List[RequestDetails]:
        """Get copy of pending requests (for inspection/testing)."""
        with self._lock:
            return self.buffer.copy()

    def set_on_flush(self, on_flush: Optional[Callable[[List[RequestDetails]], None]]) -> None:
        """Update flush callback used for backend batch handling."""
        with self._lock:
            self.on_flush = on_flush

    def clear(self) -> None:
        """Clear buffer and stop timer."""
        with self._lock:
            self.buffer.clear()
            if self._flush_timer:
                self._flush_timer.cancel()
                self._flush_timer = None
            logger.info("Buffer cleared and timer stopped")
    def shutdown(self) -> None:
    #Flush remaining requests and stop timer.
         with self._lock:
               self.flush()

               if self._flush_timer:
                self._flush_timer.cancel()
                self._flush_timer = None

    logger.info("Buffer shutdown complete")
    def __del__(self) -> None:
       """Cleanup on garbage collection."""
       timer = getattr(self, "_flush_timer", None)

       if timer:
           timer.cancel() 


# Global buffer instance
_buffer = None


def get_request_buffer(on_flush: Optional[Callable[[List[RequestDetails]], None]] = None) -> RequestDetailsBuffer:
    """Get or create global request details buffer."""
    global _buffer
    if _buffer is None:
        _buffer = RequestDetailsBuffer(on_flush=on_flush)
    elif on_flush is not None:
        _buffer.set_on_flush(on_flush)
    return _buffer


# Backward compatibility alias
def get_cost_aggregator() -> RequestDetailsBuffer:
    """Get or create global cost aggregator (alias for backward compatibility)."""
    return get_request_buffer()
