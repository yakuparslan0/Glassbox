"""LLM service: provider order, key rotation, response cache. Failure of everything = ``LlmUnavailable``."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import Any

from ..config import Settings, split_csv
from .base import AuthRejected, LlmUnavailable, Message, Provider, ProviderFailure, RateLimited, mask
from .providers.openai_compat import OpenAICompatProvider

log = logging.getLogger("glassbox.llm")
MAX_TRANSIENT_RETRIES = 2  # per provider, for timeouts / 5xx (a different key is tried each time)


class LlmService:
    def __init__(self, providers: list[Provider], cache_size: int = 128) -> None:
        self.providers = providers
        self._cache: OrderedDict[tuple[str, str], str] = OrderedDict()
        self._cache_size = cache_size

    @classmethod
    def from_settings(cls, settings: Settings) -> LlmService:
        """Providers listed in LLM_PROVIDER_ORDER that have keys, a model AND a base URL configured."""
        providers: list[Provider] = []
        for name in split_csv(settings.llm_provider_order):
            keys = split_csv(getattr(settings, f"{name}_api_keys", ""))
            model = getattr(settings, f"{name}_model", "")
            base = getattr(settings, f"{name}_base_url", "")
            if keys and model and base:
                providers.append(
                    OpenAICompatProvider(
                        name, base, model, keys, settings.llm_timeout_s, settings.llm_max_output_tokens
                    )
                )
        return cls(providers)

    # ------------------------------------------------------------------ health
    def health(self) -> list[dict[str, Any]]:
        return [
            {"name": p.name, "model": p.model, "keys": p.ring.total, "available": p.ring.usable > 0}
            for p in self.providers
        ]

    @property
    def available(self) -> bool:
        return any(p.ring.usable > 0 for p in self.providers)

    # ------------------------------------------------------------------ cache
    @staticmethod
    def _digest(messages: list[Message]) -> str:
        return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()

    def _cached(self, digest: str) -> tuple[str, str] | None:
        for p in self.providers:
            hit = self._cache.get((digest, p.model))
            if hit is not None:
                self._cache.move_to_end((digest, p.model))
                return hit, p.name
        return None

    def _remember(self, digest: str, model: str, text: str) -> None:
        self._cache[(digest, model)] = text
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    # ------------------------------------------------------------------ calls
    async def complete(self, messages: list[Message]) -> tuple[str, str]:
        """(text, provider name). Raises LlmUnavailable when nothing could answer."""
        digest = self._digest(messages)
        if (hit := self._cached(digest)) is not None:
            return hit
        async for provider, key in self._attempts():
            try:
                text = await provider.complete(messages, key)
            except RateLimited as exc:
                provider.ring.rate_limited(key, exc.retry_after)
                continue
            except AuthRejected:
                provider.ring.disable(key)
                continue
            except ProviderFailure as exc:
                log.warning("%s call failed with key %s: %s", provider.name, mask(key), exc)
                continue
            provider.ring.ok(key)
            self._remember(digest, provider.model, text)
            return text, provider.name
        raise LlmUnavailable("no LLM provider could answer (no keys configured, or all keys are exhausted)")

    async def stream(self, messages: list[Message]) -> AsyncIterator[tuple[str, str]]:
        """Yield (token, provider name). Fails over only before the first token has been produced."""
        digest = self._digest(messages)
        if (hit := self._cached(digest)) is not None:
            text, name = hit
            for i in range(0, len(text), 24):
                yield text[i : i + 24], name
            return
        async for provider, key in self._attempts():
            parts: list[str] = []
            try:
                async for token in provider.stream(messages, key):
                    parts.append(token)
                    yield token, provider.name
            except RateLimited as exc:
                provider.ring.rate_limited(key, exc.retry_after)
                if parts:
                    raise LlmUnavailable("the stream was cut off by a rate limit") from None
                continue
            except AuthRejected:
                provider.ring.disable(key)
                if parts:
                    raise LlmUnavailable("the stream was cut off by an authentication error") from None
                continue
            except ProviderFailure as exc:
                log.warning("%s stream failed with key %s: %s", provider.name, mask(key), exc)
                if parts:
                    raise LlmUnavailable("the stream was cut off") from None
                continue
            provider.ring.ok(key)
            self._remember(digest, provider.model, "".join(parts))
            return
        raise LlmUnavailable("no LLM provider could answer (no keys configured, or all keys are exhausted)")

    async def _attempts(self) -> AsyncIterator[tuple[Provider, str]]:
        """Yield (provider, key) pairs in provider order until the caller returns; exhausted providers are skipped."""
        for provider in self.providers:
            budget = provider.ring.total + MAX_TRANSIENT_RETRIES
            for _ in range(budget):
                key = await provider.ring.acquire()
                if key is None:
                    break
                yield provider, key
