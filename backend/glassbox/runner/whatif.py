"""What-If overrides: parse and validate; applied by the Recorder at the target step.

Values are parsed with ``ast.literal_eval`` ONLY (``eval`` is forbidden by the security rules). The
injection itself is ``frame.f_locals[name] = value`` (writable since PEP 667, Python 3.13).
"""

from __future__ import annotations

import ast
from typing import Any


class OverrideError(ValueError):
    """An override entry is malformed or its value is not a plain literal."""


def load_overrides(raw: list[dict[str, Any]] | None) -> dict[int, list[tuple[int, str, Any]]]:
    """job.overrides -> {step: [(frame_depth, name, value), ...]}; raises OverrideError."""
    out: dict[int, list[tuple[int, str, Any]]] = {}
    for item in raw or []:
        try:
            step = int(item["step"])
            depth = int(item.get("frame_depth", 0))
            name = str(item["name"])
            literal = item["value_literal"]
        except (KeyError, TypeError, ValueError) as exc:
            raise OverrideError(f"invalid override entry {item!r}: {exc}") from exc
        if not name.isidentifier():
            raise OverrideError(f"override name {name!r} is not a valid identifier")
        if step < 1 or depth < 0:
            raise OverrideError("override step must be >= 1 and frame_depth >= 0")
        try:
            value = ast.literal_eval(literal)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError) as exc:
            raise OverrideError(f"value_literal {str(literal)[:60]!r} is not a plain Python literal") from exc
        out.setdefault(step, []).append((depth, name, value))
    return out
