"""Split a trace into scenes and compress each into a small digest (the LLM never sees the raw trace)."""

from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

MAX_SCENES = 40
MAX_DIGEST_CHARS = 1800
MAX_SOURCE_LINES = 12


@dataclass
class Scene:
    index: int
    kind: str  # "call" | "module" | "exception"
    title: str  # neutral English (goes into prompts); the UI localizes through narrator.scene_title
    from_step: int
    to_step: int
    facts: dict[str, Any] = field(default_factory=dict)
    measured: dict[str, int] = field(default_factory=dict)
    digest_text: str = ""


def fmt_val(v: dict[str, Any], heap: dict[str, Any], depth: int = 0) -> str:
    if "ref" in v:
        e = heap.get(v["ref"])
        if e is None:
            return f"<{v['ref']}>"
        if depth >= 2:
            return f"{e.get('t')}…"
        sub = lambda x: fmt_val(x, heap, depth + 1)  # noqa: E731
        kind = e.get("k")
        if kind == "seq":
            body = ", ".join(sub(x) for x in e["items"]) + (", …" if e.get("trunc") else "")
            return f"({body})" if e.get("t") == "tuple" else f"[{body}]"
        if kind == "map":
            return "{" + ", ".join(f"{sub(a)}: {sub(b)}" for a, b in e["pairs"]) + "}"
        if kind == "obj":
            return f"{e.get('t')}(" + ", ".join(f"{k}={sub(x)}" for k, x in e["attrs"].items()) + ")"
        return str(e.get("r", ""))[:60]
    text = str(v.get("r", ""))
    return text if len(text) <= 60 else text[:59] + "…"


def _line_names(source: str | None, line: int) -> list[str]:
    """Names read on a source line (for 'which values were involved in the error')."""
    if not source:
        return []
    lines = source.splitlines()
    if not 1 <= line <= len(lines):
        return []
    try:
        tree = ast.parse(lines[line - 1].strip())
    except SyntaxError:
        return []
    return list(dict.fromkeys(n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)))


def build_scenes(
    events: list[dict[str, Any]],
    sources: dict[str, str],
    from_step: int | None = None,
    to_step: int | None = None,
) -> list[Scene]:
    steps = [e for e in events if e["type"] in ("call", "line", "return", "exception")]
    if not steps:
        return []
    last_step = steps[-1]["step"]
    lo, hi = from_step or 1, min(to_step or last_step, last_step)

    # ---- pass 1: top-level boundaries
    module_frame = next((e["frame"] for e in steps if e["type"] == "call" and e.get("kind") == "user"), None)
    top: list[tuple[int, int, dict[str, Any]]] = []  # (start, end, call event)
    open_calls: dict[int, tuple[int, dict[str, Any]]] = {}
    unhandled = next((e for e in steps if e["type"] == "exception" and not e["handled"]), None)
    for e in steps:
        if e["type"] == "call" and e.get("parent") == module_frame:
            open_calls[e["frame"]] = (e["step"], e)
        elif e["type"] == "return" and e["frame"] in open_calls:
            start, call = open_calls.pop(e["frame"])
            top.append((start, e["step"], call))
    for start, call in open_calls.values():  # never returned (exception / limit)
        top.append((start, last_step, call))
    top.sort(key=lambda t: t[0])
    if unhandled is not None:
        top = [(s, min(e, unhandled["step"] - 1), c) for s, e, c in top if s < unhandled["step"]]

    # ---- pass 2: contiguous ranges: module segments in between
    ranges: list[tuple[str, int, int, dict[str, Any] | None]] = []
    cursor = 1
    for start, end, call in top:
        if start > cursor:
            ranges.append(("module", cursor, start - 1, None))
        ranges.append(("call", start, end, call))
        cursor = end + 1
    end_of_normal = (unhandled["step"] - 1) if unhandled is not None else last_step
    if cursor <= end_of_normal:
        ranges.append(("module", cursor, end_of_normal, None))
    if unhandled is not None:
        ranges.append(("exception", unhandled["step"], last_step, unhandled))
    ranges = [r for r in ranges if r[2] >= lo and r[1] <= hi and r[2] >= r[1]]
    if len(ranges) > MAX_SCENES:  # merge the tail so the scene count (and token budget) stays bounded
        head, tail = ranges[: MAX_SCENES - 1], ranges[MAX_SCENES - 1 :]
        ranges = [*head, ("module", tail[0][1], tail[-1][2], None)]

    # ---- pass 3: facts per range (single sweep over events with running state)
    heap: dict[str, Any] = {}
    locals_by_frame: dict[int, dict[str, Any]] = {}
    file_of: dict[int, str] = {}
    scenes = [Scene(i, kind, "", a, b) for i, (kind, a, b, _) in enumerate(ranges)]
    stats = [{"calls": Counter(), "lines": Counter(), "files": {}, "changes": {}, "out": [], "ret": None, "src": set()} for _ in ranges]

    def scene_at(step: int) -> int | None:
        for i, (_, a, b, _c) in enumerate(ranges):
            if a <= step <= b:
                return i
        return None

    call_args: dict[int, str] = {}  # formatted at call time: later heap states would show mutated values
    for e in events:
        if e.get("heap"):
            heap.update(e["heap"])
        typ = e["type"]
        step = e.get("step", 0)
        if typ == "call" and e.get("kind") == "user":
            locals_by_frame[e["frame"]] = dict(e["args"])
            file_of[e["frame"]] = e["file"]
            call_args[e["frame"]] = ", ".join(f"{k}={fmt_val(v, heap)}" for k, v in e["args"].items())
        elif typ == "line":
            frame_locals = locals_by_frame.setdefault(e["frame"], {})
            frame_locals.update(e["delta"]["set"])
            for name in e["delta"]["del"]:
                frame_locals.pop(name, None)
        i = scene_at(step) if step else None
        if i is None:
            continue
        st = stats[i]
        if typ == "call":
            name = e["func"] if e["kind"] == "user" else f"{e['module']}.{e['func']}"
            st["calls"][name] += 1
        elif typ == "line":
            f = file_of.get(e["frame"], "")
            st["lines"][(f, e["line"])] += 1
            st["src"].add((f, e["line"]))
            for name, val in e["delta"]["set"].items():
                st["changes"][name] = fmt_val(val, heap)
        elif typ == "output" and e["stream"] == "stdout":
            st["out"].append(e["text"])
        elif typ == "return" and ranges[i][0] == "call" and e["frame"] == ranges[i][3]["frame"]:
            st["ret"] = fmt_val(e["value"], heap) if "value" in e else e.get("value_summary")
        elif typ == "exception" and not e["handled"] and ranges[i][0] == "exception" and "exc" not in st:
            names = _line_names(sources.get(file_of.get(e["frame"], "")), e["line"])
            local = locals_by_frame.get(e["frame"], {})
            values = {n: fmt_val(local[n], heap) for n in names if n in local}
            st["exc"] = {"type": e["exc_type"], "message": e["message"], "line": e["line"], "values": values}

    # ---- assemble
    for scene, (kind, a, b, call), st in zip(scenes, ranges, stats, strict=True):
        calls = sum(st["calls"].values())
        (rep_loc, rep_n) = st["lines"].most_common(1)[0] if st["lines"] else (("", 0), 0)
        scene.facts = {
            "calls": dict(st["calls"].most_common(5)),
            "changes": dict(list(st["changes"].items())[-6:]),
            "stdout": "".join(st["out"])[:300],
            "return": st["ret"],
            "repeat_line": rep_loc[1] if rep_n > 2 else None,
            "repeat_count": rep_n if rep_n > 2 else 0,
            "exc": st.get("exc"),
        }
        if kind == "call" and call is not None:
            args = call_args.get(call["frame"], "")
            name = call["func"] if call["kind"] == "user" else f"{call['module']}.{call['func']}"
            scene.facts.update(func=name, args=args)
            scene.title = f"call {name}({args})"
        elif kind == "exception":
            scene.facts["func"] = (st.get("exc") or {}).get("type", "exception")
            scene.title = f"exception {scene.facts['func']}"
        else:
            scene.title = "module-level code"
        scene.measured = {"steps": b - a + 1, "calls": calls, "max_line_repeats": rep_n if rep_n > 2 else 0}
        src_lines = []
        for f, n in sorted(st["src"])[:MAX_SOURCE_LINES]:
            text = sources.get(f, "").splitlines()
            if 1 <= n <= len(text):
                src_lines.append(f"{n:4d}| {text[n - 1][:120]}")
        parts = [f"scene: {scene.title}", f"steps {a}-{b}", *(f"measured {k}={v}" for k, v in scene.measured.items())]
        if scene.facts["changes"]:
            parts.append("last values: " + ", ".join(f"{k}={v}" for k, v in scene.facts["changes"].items()))
        if scene.facts["return"] is not None:
            parts.append(f"returned: {scene.facts['return']}")
        if scene.facts["stdout"]:
            parts.append("stdout: " + re.sub(r"\s+", " ", scene.facts["stdout"]))
        if st.get("exc"):
            ex = st["exc"]
            parts.append(f"exception: {ex['type']}: {ex['message']} at line {ex['line']}; values: {ex['values']}")
        if src_lines:
            parts.append("source lines executed:\n" + "\n".join(src_lines))
        scene.digest_text = "\n".join(parts)[:MAX_DIGEST_CHARS]
    return scenes
