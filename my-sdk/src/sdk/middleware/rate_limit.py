# _internal/middleware/rate_limit.py

import time
import threading

class TokenBucket:
    def __init__(self, capacity: int, refill_rate: float):
        """
        capacity    : max burst allowed ( 5 flushes)
        refill_rate : tokens added per second (  = 1 token per 10s)
        """
        self.capacity = capacity
        self.tokens = capacity       # start full
        self.refill_rate = refill_rate
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last

            # refill proportional to time passed
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * self.refill_rate
            )
            self._last = now

            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False