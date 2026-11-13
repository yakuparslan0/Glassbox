"""Shared test helpers: run a program through the real runner subprocess and reconstruct state."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Any

from glassbox.sandbox.manager import RunRequest, SandboxManager

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
TIME_KEYS = {"t", "dur_ns", "wall_ms", "self_ns", "total_ns"}


def example_source(name: str) -> str:
    return (EXAMPLES / name).read_text(encoding="utf-8")


def run_request(request: RunRequest) -> list[dict[str, Any]]:
    async def go() -> list[dict[str, Any]]:
        return [event async for event in SandboxManager().run(request)]

    return asyncio.run(go())


def run(source: str | dict[str, str], entry: str = "main.py", **kwargs: Any) -> list[dict[str, Any]]:
    files = {entry: source} if isinstance(source, str) else source
    return run_request(RunRequest(files=files, entry=entry, **kwargs))


def of_type(events: list[dict[str, Any]], typ: str, **match: Any) -> list[dict[str, Any]]:
    return [e for e in events if e["type"] == typ and all(e.get(k) == v for k, v in match.items())]


def finished(events: list[dict[str, Any]]) -> dict[str, Any]:
    return of_type(events, "run_finished")[-1]


def stdout_text(events: list[dict[str, Any]], stream: str = "stdout") -> str:
    return "".join(e["text"] for e in of_type(events, "output", stream=stream))


def strip_time(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy of the events without time-dependent fields and without the tracer name (backend comparisons)."""

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in TIME_KEYS - {"t"}}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    out = []
    for event in events:
        event = {k: v for k, v in event.items() if k not in ("t", "tracer")}
        out.append(clean(event))
    return out


# --------------------------------------------------------------------------- state reconstruction
class State:
    """What a client knows after applying events: call stack (user frames), entry globals, heap."""

    def __init__(self) -> None:
        self.stack: list[dict[str, Any]] = []
        self.globals: dict[str, Any] = {}
        self.heap: dict[str, Any] = {}

    def structure(self) -> list[tuple[int, str, int]]:
        return [(f["frame"], f["func"], f["line"]) for f in self.stack]

    def reachable_heap(self) -> dict[str, Any]:
        roots = list(self.globals.values())
        for frame in self.stack:
            roots.extend(frame["locals"].values())
        out: dict[str, Any] = {}
        todo = [r["ref"] for r in roots if "ref" in r]
        while todo:
            label = todo.pop()
            if label in out or label not in self.heap:
                continue
            out[label] = self.heap[label]
            todo.extend(_refs(self.heap[label]))
        return out


def _refs(entry: dict[str, Any]) -> list[str]:
    kind = entry.get("k")
    if kind == "seq":
        values = entry["items"]
    elif kind == "map":
        values = [v for pair in entry["pairs"] for v in pair]
    elif kind == "obj":
        values = list(entry["attrs"].values())
    else:
        return []
    return [v["ref"] for v in values if "ref" in v]


def _apply_delta(target: dict[str, Any], delta: dict[str, Any] | None) -> None:
    if not delta:
        return
    target.update(copy.deepcopy(delta["set"]))
    for name in delta["del"]:
        target.pop(name, None)


def apply_event(state: State, ev: dict[str, Any]) -> None:
    typ = ev["type"]
    if "heap" in ev and typ != "snapshot":
        state.heap.update(copy.deepcopy(ev["heap"]))
    if typ == "call":
        if ev["kind"] == "user":
            state.stack.append(
                {"frame": ev["frame"], "func": ev["func"], "line": ev["line"], "locals": copy.deepcopy(ev["args"])}
            )
        _apply_delta(state.globals, ev.get("globals_delta"))
    elif typ == "line":
        frame = next(f for f in state.stack if f["frame"] == ev["frame"])
        frame["line"] = ev["line"]
        # The entry module's locals ARE the globals (frame 1): its delta is the globals delta.
        _apply_delta(state.globals if ev["frame"] == 1 else frame["locals"], ev["delta"])
        _apply_delta(state.globals, ev.get("globals_delta"))
    elif typ == "return":
        _apply_delta(state.globals, ev.get("globals_delta"))
        if ev.get("kind") != "boundary":
            state.stack = [f for f in state.stack if f["frame"] != ev["frame"]]
    elif typ == "exception":
        _apply_delta(state.globals, ev.get("globals_delta"))
    elif typ == "keyframe":
        state.stack = [
            {"frame": f["frame"], "func": f["func"], "line": f["line"], "locals": copy.deepcopy(f["locals"])}
            for f in ev["stack"]
        ]
        state.globals = copy.deepcopy(ev["globals"])
        state.heap = copy.deepcopy(ev["heap"])


STRUCTURAL = {"call", "line", "return", "exception", "keyframe"}


def reduce_events(events: list[dict[str, Any]], until_seq: int, from_keyframe: bool) -> State:
    """State after all events with seq <= until_seq, optionally starting at the last keyframe before it."""
    relevant = [e for e in events if e["seq"] <= until_seq and e["type"] in STRUCTURAL]
    start = 0
    if from_keyframe:
        keyframes = [i for i, e in enumerate(relevant) if e["type"] == "keyframe"]
        if keyframes:
            start = keyframes[-1]
    state = State()
    for ev in relevant[start:]:
        apply_event(state, ev)
    return state
