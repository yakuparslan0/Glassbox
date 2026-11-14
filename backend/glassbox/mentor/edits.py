"""Line-range edit engine shared by autofix and LLM refactoring. Pure, validating, never touches disk."""

from __future__ import annotations

import ast
from itertools import pairwise

from ..schemas.llm import Edit


class EditError(ValueError):
    """The edits are inconsistent or would produce invalid Python; the message is user-facing."""


def apply_edits(files: dict[str, str], edits: list[Edit]) -> dict[str, str]:
    """Apply edits (1-based inclusive line ranges) to a copy of ``files``; every changed .py file must still parse."""
    out = dict(files)
    by_file: dict[str, list[Edit]] = {}
    for edit in edits:
        if edit.file not in files:
            raise EditError(f"edit refers to unknown file {edit.file!r}")
        by_file.setdefault(edit.file, []).append(edit)
    for path, items in by_file.items():
        lines = files[path].splitlines(keepends=True)
        ordered = sorted(items, key=lambda e: (e.start_line, e.end_line))
        for a, b in pairwise(ordered):
            if b.start_line <= a.end_line:
                raise EditError(f"edits overlap in {path} (lines {a.start_line}-{a.end_line} and {b.start_line}-{b.end_line})")
        for e in reversed(ordered):
            if e.end_line < e.start_line or e.end_line > len(lines):
                raise EditError(f"line range {e.start_line}-{e.end_line} is outside {path} ({len(lines)} lines)")
            new = e.new_code
            if new and not new.endswith("\n"):
                new += "\n"
            lines[e.start_line - 1 : e.end_line] = [new] if new else []
        text = "".join(lines)
        if path.endswith(".py"):
            try:
                ast.parse(text, filename=path)
            except SyntaxError as exc:
                raise EditError(f"{path} would not parse after the edit (line {exc.lineno}: {exc.msg})") from None
        out[path] = text
    return out
