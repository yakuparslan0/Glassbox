"""Root-Cause Rewind: dynamic backward slice from an uncaught exception (spec 7.4).

From the failing line: names READ there -> the step where each was last WRITTEN (from delta records) -> names read on
that line -> ... (depth limit 6). Function boundaries are crossed through argument binding (a parameter's origin is the
call site) and through return values (a value assigned from a call originates in the callee's return line).
"""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass, field
from typing import Any

from ..mentor.digest import fmt_val
from ..schemas.analysis import CausalChain, CausalLink

MAX_DEPTH = 6
MAX_LINKS = 40
_BUILTINS = frozenset(dir(builtins))


@dataclass
class _Frame:
    id: int
    file: str
    func: str
    parent: int | None
    call_line: int | None
    call_step: int
    args: dict[str, str] = field(default_factory=dict)
    lines: list[tuple[int, int]] = field(default_factory=list)  # (step, line) of its line events
    writes: dict[str, list[tuple[int, int, str]]] = field(default_factory=dict)  # name -> [(step, line, value)]
    ret: tuple[int, int, str] | None = None  # (step, line, value) of the return


class SliceError(ValueError):
    """The run has no uncaught exception to explain."""


def _reads(source: str | None, line: int) -> list[str]:
    """Names read on a source line (compound headers are completed so they parse)."""
    if not source:
        return []
    rows = source.splitlines()
    if not 1 <= line <= len(rows):
        return []
    text = rows[line - 1].strip()
    for candidate in (text, text + "\n    pass", text.removeprefix("elif ").join(["if ", ":\n    pass"])):
        try:
            tree = ast.parse(candidate)
        except SyntaxError:
            continue
        names = [n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)]
        return [n for n in dict.fromkeys(names) if n not in _BUILTINS]
    return []


def _index(events: list[dict[str, Any]]) -> tuple[dict[int, _Frame], dict[str, Any] | None]:
    heap: dict[str, Any] = {}
    frames: dict[int, _Frame] = {}
    exc: dict[str, Any] | None = None
    for e in events:
        if e.get("heap"):
            heap.update(e["heap"])
        typ = e["type"]
        if typ == "call" and e.get("kind") == "user":
            f = _Frame(
                e["frame"], e["file"], e["func"], e.get("parent"), e.get("call_line"), e["step"],
                {k: fmt_val(v, heap) for k, v in e["args"].items()},
            )  # fmt: skip
            frames[f.id] = f
        elif typ == "line" and e["frame"] in frames:
            f = frames[e["frame"]]
            if e["delta"]["set"] and f.lines:
                prev_step, prev_line = f.lines[-1]  # the delta shows the effect of the PREVIOUS line
                for name, val in e["delta"]["set"].items():
                    f.writes.setdefault(name, []).append((prev_step, prev_line, fmt_val(val, heap)))
            f.lines.append((e["step"], e["line"]))
        elif typ == "return" and e.get("kind") != "boundary" and e["frame"] in frames and "value" in e:
            f = frames[e["frame"]]
            if f.lines:
                f.ret = (f.lines[-1][0], f.lines[-1][1], fmt_val(e["value"], heap))
        elif typ == "exception" and not e["handled"] and exc is None:
            exc = e
    return frames, exc


def backward_slice(events: list[dict[str, Any]], sources: dict[str, str]) -> CausalChain:
    frames, exc = _index(events)
    if exc is None or exc["frame"] not in frames:
        raise SliceError("this run did not end with an uncaught exception, so there is no failure to trace back")
    module = next((f for f in frames.values() if f.parent is None), None)
    links: dict[tuple[int, int, str, str], CausalLink] = {}
    truncated = False

    def add(frame: _Frame, step: int, line: int, kind: str, name: str, value: str | None, depth: int, text: str) -> bool:
        nonlocal truncated
        key = (frame.id, step, name, kind)
        if key in links or (kind == "global" and (value or "").startswith(("<function", "<class"))):
            return False
        if any(k[0] == frame.id and k[2] == name and k[3] == kind and links[k].line == line for k in links):
            return False  # the same statement re-run in a loop: the most recent write (found first) is enough
        if len(links) >= MAX_LINKS:
            truncated = True
            return False
        links[key] = CausalLink(
            step=step, frame=frame.id, file=frame.file, line=line, kind=kind,  # type: ignore[arg-type]
            name=name, value=value, depth=depth, text=text,
        )  # fmt: skip
        return True

    def last_write(frame: _Frame, name: str, before: int) -> tuple[int, int, str] | None:
        for w in reversed(frame.writes.get(name, [])):
            if w[0] < before:
                return w
        return None

    def visit(frame: _Frame, line: int, before: int, depth: int) -> None:
        if depth > MAX_DEPTH:
            truncated_marker()
            return
        for name in _reads(sources.get(frame.file), line):
            write = last_write(frame, name, before)
            if write is not None:
                step, wline, value = write
                if add(frame, step, wline, "assignment", name, value, depth, f"{name} = {value} (line {wline})"):
                    follow_calls(frame, wline, step, depth)
                    visit(frame, wline, step, depth + 1)
            elif name in frame.args:
                parent = frames.get(frame.parent) if frame.parent is not None else None
                if parent is not None and frame.call_line is not None:
                    value = frame.args[name]
                    if add(parent, frame.call_step, frame.call_line, "argument", name, value, depth,
                           f"{frame.func}({name}={value}) called from line {frame.call_line}"):  # fmt: skip
                        visit(parent, frame.call_line, frame.call_step, depth + 1)
            elif module is not None and frame is not module:
                write = last_write(module, name, before)
                if write is not None:
                    step, wline, value = write
                    if add(module, step, wline, "global", name, value, depth, f"global {name} = {value} (line {wline})"):
                        visit(module, wline, step, depth + 1)

    def follow_calls(frame: _Frame, wline: int, wstep: int, depth: int) -> None:
        """A value assigned from a call originates in the callee's return line."""
        next_line_step = next((s for s, _ln in frame.lines if s > wstep), 10**12)
        for child in frames.values():
            if child.parent == frame.id and child.call_line == wline and wstep < child.call_step < next_line_step and child.ret:
                rstep, rline, rvalue = child.ret
                if add(child, rstep, rline, "return", child.func, rvalue, depth, f"{child.func}() returned {rvalue} (line {rline})"):
                    visit(child, rline, rstep, depth + 1)

    def truncated_marker() -> None:
        nonlocal truncated
        truncated = True

    failing = frames[exc["frame"]]
    add(failing, exc["step"], exc["line"], "error", exc["exc_type"], exc["message"], 0, f"{exc['exc_type']}: {exc['message']} (line {exc['line']})")
    visit(failing, exc["line"], exc["step"], 1)
    ordered = sorted(links.values(), key=lambda link: (link.step, -link.depth))
    return CausalChain(exception_type=exc["exc_type"], message=exc["message"], step=exc["step"], links=ordered, truncated=truncated)
