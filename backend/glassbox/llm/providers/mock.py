"""Deterministic provider for tests and key-less development. Reads only the trusted header of a prompt."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

from ..base import Message, ProviderFailure
from ..keyring import KeyRing


def _header(messages: list[Message], name: str) -> str:
    text = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    found = re.search(rf"^{name}: (.*)$", text, re.MULTILINE)
    return found.group(1).strip() if found else ""


def _source_line(messages: list[Message], line: int) -> str | None:
    text = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    found = re.search(rf"^\s*{line}\| (.*)$", text, re.MULTILINE)
    return found.group(1) if found else None


class MockProvider:
    """Canned, deterministic answers: memoization for repeated_computation, short scene texts."""

    name = "mock"
    model = "mock-1"

    def __init__(self) -> None:
        self._ring = KeyRing(["mock-key"])

    @property
    def ring(self) -> KeyRing:
        return self._ring

    def _answer(self, messages: list[Message]) -> str:
        task = _header(messages, "TASK")
        if task == "narrate":
            return f"[mock] {_header(messages, 'SCENE_TITLE')} ({_header(messages, 'STEPS')}): bu sahnede kod adım adım çalışır."
        if task == "refactor":
            category = _header(messages, "FINDING_CATEGORY")
            if category != "repeated_computation":
                raise ProviderFailure(f"mock provider has no canned refactoring for '{category}'")
            file = _header(messages, "FINDING_FILE")
            line = int(_header(messages, "FINDING_LINE"))
            func = _header(messages, "FINDING_FUNCTION")
            original = _source_line(messages, line)
            if original is None or not original.lstrip().startswith("def "):
                raise ProviderFailure("mock memoization expects the finding to point at a 'def' line")
            return json.dumps(
                {
                    "edits": [
                        {
                            "file": file, "start_line": line, "end_line": line,
                            "new_code": f"from functools import cache\n\n\n@cache\n{original}",
                        }
                    ],
                    "why": f"{func} is called again with arguments it has already seen; caching returns the stored result.",
                    "explanation_md": f"`{func}` recomputes the same sub-problems. `functools.cache` remembers each result, "
                    "so every distinct argument is computed once.",
                    "expected_effect": "Far fewer repeated calls; the result stays the same for pure functions.",
                }
            )
        raise ProviderFailure("mock provider received an unknown task")

    async def complete(self, messages: list[Message], key: str) -> str:
        return self._answer(messages)

    async def stream(self, messages: list[Message], key: str) -> AsyncIterator[str]:
        for word in self._answer(messages).split(" "):
            yield word + " "
