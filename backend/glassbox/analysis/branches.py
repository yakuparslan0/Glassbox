"""What-If branch comparison: find the first diverging step and summarize the difference of two runs."""

from __future__ import annotations

import json
from typing import Any

from ..mentor.digest import fmt_val
from ..schemas.analysis import BranchComparison, RunSide

_STEP_TYPES = ("call", "line", "return", "exception")
_DROP = {"seq", "t", "dur_ns", "heap", "wall_ms"}


def _signature(ev: dict[str, Any]) -> str:
    """Control flow + values of one step (heap labels and timings are excluded)."""
    keep = {k: v for k, v in ev.items() if k not in _DROP}
    return json.dumps(keep, sort_keys=True, separators=(",", ":"))


def _steps(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events if e["type"] in _STEP_TYPES]


def _side(events: list[dict[str, Any]]) -> RunSide:
    heap: dict[str, Any] = {}
    module = next((e["frame"] for e in events if e["type"] == "call" and e.get("kind") == "user"), None)
    top_frames: set[int] = set()
    returns: list[str] = []
    out: list[str] = []
    for e in events:
        if e.get("heap"):
            heap.update(e["heap"])
        if e["type"] == "call" and e.get("parent") == module and e.get("kind") == "user":
            top_frames.add(e["frame"])
        elif e["type"] == "return" and e["frame"] in top_frames and "value" in e:
            returns.append(f"{e.get('frame')}:{fmt_val(e['value'], heap)}")
        elif e["type"] == "output" and e["stream"] == "stdout":
            out.append(e["text"])
    done = next((e for e in reversed(events) if e["type"] == "run_finished"), {})
    detail = str(done.get("detail") or "")
    return RunSide(
        steps=int(done.get("steps", 0)), status=str(done.get("status", "unknown")), stdout="".join(out),
        returns=[r.split(":", 1)[1] for r in returns],
        exception=detail if done.get("status") == "exception" else None,
    )  # fmt: skip


def compare(base_id: str, base: list[dict[str, Any]], branch_id: str, branch: list[dict[str, Any]]) -> BranchComparison:
    a, b = _steps(base), _steps(branch)
    first: int | None = None
    for ea, eb in zip(a, b, strict=False):
        if _signature(ea) != _signature(eb):
            first = ea["step"]
            break
    else:
        if len(a) != len(b):
            first = (a if len(a) < len(b) else b)[-1]["step"] + 1 if min(len(a), len(b)) else 1
    sa, sb = _side(base), _side(branch)
    summary: list[str] = []
    if first is None:
        summary.append("The two timelines are identical.")
    else:
        summary.append(f"The timelines first diverge at step {first}.")
    if sa.stdout != sb.stdout:
        summary.append(f"Output differs: {sa.stdout[:80]!r} -> {sb.stdout[:80]!r}")
    if sa.returns != sb.returns:
        summary.append(f"Top-level return values differ: {sa.returns[:4]} -> {sb.returns[:4]}")
    if sa.steps != sb.steps:
        summary.append(f"Step count: {sa.steps} -> {sb.steps}")
    if sa.status != sb.status:
        summary.append(f"Status: {sa.status} -> {sb.status}" + (f" ({sb.exception})" if sb.exception else ""))
    return BranchComparison(
        base_run_id=base_id, branch_run_id=branch_id, first_divergence_step=first, base=sa, branch=sb,
        output_equal=sa.stdout == sb.stdout, summary=summary,
    )  # fmt: skip
