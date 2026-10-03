import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _Entry:
    failures: int = 0
    last_failure: float = 0.0


class LoginThrottle:
    """Slows down password guessing per client IP.

    In memory, which is fine for one process and one user. There is deliberately no global
    lockout: TOTP already makes online guessing hopeless, and a global lock would let anyone
    on the network lock the owner out.
    """

    def __init__(
        self,
        *,
        free_attempts: int = 5,
        lockout_after: int = 10,
        lockout_seconds: float = 900,
        base_delay: float = 30,
        forget_after: float = 3600,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._free = free_attempts
        self._lockout_after = lockout_after
        self._lockout_seconds = lockout_seconds
        self._base_delay = base_delay
        self._forget_after = forget_after
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> float:
        """Seconds until `key` may try again; 0 when allowed now."""
        with self._lock:
            entry = self._current(key)
            if entry is None or entry.failures < self._free:
                return 0.0
            if entry.failures >= self._lockout_after:
                delay = self._lockout_seconds
            else:
                delay = min(
                    self._base_delay * 2 ** (entry.failures - self._free), self._lockout_seconds
                )
            return max(0.0, entry.last_failure + delay - self._clock())

    def record_failure(self, key: str) -> None:
        with self._lock:
            entry = self._current(key) or self._entries.setdefault(key, _Entry())
            entry.failures += 1
            entry.last_failure = self._clock()

    def record_success(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def _current(self, key: str) -> _Entry | None:
        entry = self._entries.get(key)
        if entry is not None and self._clock() - entry.last_failure > self._forget_after:
            del self._entries[key]
            return None
        return entry
