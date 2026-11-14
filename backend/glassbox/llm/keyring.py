"""Per-provider round-robin key ring with cooldowns (429) and permanent disabling (401/403)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from .base import mask

log = logging.getLogger("glassbox.llm")
BACKOFF_BASE_S = 2.0
BACKOFF_MAX_S = 120.0


class KeyRing:
    def __init__(self, keys: list[str], clock: Callable[[], float] = time.monotonic) -> None:
        self._keys = list(dict.fromkeys(keys))  # de-duplicated, order kept
        self._clock = clock
        self._next = 0
        self._cool_until: dict[str, float] = {}
        self._failures: dict[str, int] = {}
        self._disabled: set[str] = set()
        self._lock = asyncio.Lock()

    @property
    def total(self) -> int:
        return len(self._keys)

    @property
    def usable(self) -> int:
        now = self._clock()
        return sum(1 for k in self._keys if k not in self._disabled and self._cool_until.get(k, 0.0) <= now)

    async def acquire(self) -> str | None:
        """Next usable key in round-robin order, or None if every key is cooling down / disabled."""
        async with self._lock:
            now = self._clock()
            for offset in range(len(self._keys)):
                idx = (self._next + offset) % len(self._keys)
                key = self._keys[idx]
                if key in self._disabled or self._cool_until.get(key, 0.0) > now:
                    continue
                self._next = (idx + 1) % len(self._keys)
                return key
            return None

    def ok(self, key: str) -> None:
        self._failures.pop(key, None)

    def rate_limited(self, key: str, retry_after: float | None) -> None:
        """429: cool the key for ``Retry-After`` seconds, else exponential back-off (2, 4, 8 ... capped)."""
        n = self._failures.get(key, 0) + 1
        self._failures[key] = n
        delay = retry_after if retry_after and retry_after > 0 else min(BACKOFF_BASE_S * 2 ** (n - 1), BACKOFF_MAX_S)
        self._cool_until[key] = self._clock() + delay
        log.warning("key %s rate limited; cooling down for %.1f s", mask(key), delay)

    def disable(self, key: str) -> None:
        """401/403: never use this key again in this session."""
        self._disabled.add(key)
        log.warning("key %s rejected by the provider; disabled for this session", mask(key))
