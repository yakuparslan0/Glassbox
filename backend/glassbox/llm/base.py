"""Provider protocol and error types."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, TypedDict


class Message(TypedDict):
    role: str  # "system" | "user" | "assistant"
    content: str


class LlmError(Exception):
    """Base class. Messages never contain keys, headers or request bodies."""


class RateLimited(LlmError):
    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


class AuthRejected(LlmError):
    """HTTP 401/403: the key is invalid or lacks permission."""


class ProviderFailure(LlmError):
    """Timeouts, connection errors, 5xx, malformed responses."""


class LlmUnavailable(LlmError):
    """Every key of every provider is exhausted (or none is configured): callers fall back to Layer A."""


class Provider(Protocol):
    name: str
    model: str

    @property
    def ring(self) -> KeyRingLike: ...

    async def complete(self, messages: list[Message], key: str) -> str: ...

    def stream(self, messages: list[Message], key: str) -> AsyncIterator[str]: ...


class KeyRingLike(Protocol):
    @property
    def total(self) -> int: ...

    @property
    def usable(self) -> int: ...

    async def acquire(self) -> str | None: ...

    def ok(self, key: str) -> None: ...

    def rate_limited(self, key: str, retry_after: float | None) -> None: ...

    def disable(self, key: str) -> None: ...


def mask(key: str) -> str:
    """Only the last 4 characters of a key may ever appear in logs (spec 5.8)."""
    return "…" + key[-4:] if len(key) > 4 else "…"
