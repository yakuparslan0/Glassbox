"""One adapter for every OpenAI-compatible chat endpoint (Groq and Gemini both offer one)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from ..base import AuthRejected, Message, ProviderFailure, RateLimited
from ..keyring import KeyRing


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status == 429:
        raise RateLimited(_retry_after(response))
    if status in (401, 403):
        raise AuthRejected(f"HTTP {status}")
    if status >= 400:
        raise ProviderFailure(f"HTTP {status}")  # the body is deliberately not echoed (may contain request data)


class OpenAICompatProvider:
    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        keys: list[str],
        timeout_s: float = 30.0,
        max_output_tokens: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._ring = KeyRing(keys)
        self._timeout = timeout_s
        self._max_tokens = max_output_tokens
        self._transport = transport

    @property
    def ring(self) -> KeyRing:
        return self._ring

    def _payload(self, messages: list[Message], stream: bool) -> dict[str, object]:
        payload: dict[str, object] = {"model": self.model, "messages": messages, "stream": stream}
        if self._max_tokens:
            payload["max_tokens"] = self._max_tokens
        return payload

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    async def complete(self, messages: list[Message], key: str) -> str:
        try:
            async with self._client() as client:
                response = await client.post(
                    self._url, json=self._payload(messages, False), headers={"Authorization": f"Bearer {key}"}
                )
        except httpx.HTTPError as exc:
            raise ProviderFailure(type(exc).__name__) from None
        raise_for_status(response)
        try:
            return str(response.json()["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, ValueError, TypeError):
            raise ProviderFailure("malformed response") from None

    async def stream(self, messages: list[Message], key: str) -> AsyncIterator[str]:
        try:
            async with (
                self._client() as client,
                client.stream(
                    "POST", self._url, json=self._payload(messages, True), headers={"Authorization": f"Bearer {key}"}
                ) as response,
            ):
                if response.status_code >= 400:
                    await response.aread()
                    raise_for_status(response)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        delta = json.loads(data)["choices"][0]["delta"].get("content")
                    except (KeyError, IndexError, ValueError, TypeError):
                        continue
                    if delta:
                        yield str(delta)
        except httpx.HTTPError as exc:
            raise ProviderFailure(type(exc).__name__) from None
