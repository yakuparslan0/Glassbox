"""Dynamic findings from a recorded trace (hot_loop, repeated_computation, loop_invariant) and the
untraced profile passes (real time via cProfile, memory via tracemalloc)."""

from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from ..sandbox.manager import RunRequest, SandboxManager
from ..schemas.analysis import (
    Finding,
    MemoryLine,
    ProfileFunc,
    ProfilePass,
    ProfileReport,
)
from .common import end_line, make_finding

HOT_LOOP_REPEATS = 5000  # spec 5.4: identical-state repeats of one line inside one frame
MIN_REPEATED_CALLS = 3
MIN_INVARIANT_HITS = 10
HIGH_MEMORY_KB = 1024.0
_PURE_CALLS = frozenset({"len", "abs", "min", "max", "sum", "sorted", "int", "float", "str", "round", "tuple", "set", "list"})


# ------------------------------------------------------------------------------------------ trace based
def hot_loops(events: Iterable[dict[str, Any]], threshold: int = HOT_LOOP_REPEATS) -> list[Finding]:
    """A line that ran ``threshold`` times in one frame with no state change anywhere in that frame since."""
    file_of: dict[int, str] = {}
    stale: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    found: dict[tuple[str, int], int] = {}
    for ev in events:
        typ = ev.get("type")
        if typ == "call" and ev.get("kind") == "user":
            file_of[ev["frame"]] = ev["file"]
        elif typ == "line":
            frame = ev["frame"]
            counters = stale[frame]
            if ev["delta"]["set"] or ev["delta"]["del"] or ev.get("globals_delta") or ev.get("heap"):
                counters.clear()
            line = ev["line"]
            counters[line] += 1
            if counters[line] == threshold:
                found.setdefault((file_of.get(frame, "?"), line), threshold)
        elif typ == "return":
            stale.pop(ev["frame"], None)
    return [
        make_finding(
            "hot_loop", "high", "confirmed", file, line, line,
            f"Line {line} ran {n}+ times in a row without changing any state (possible endless loop)",
            {"repeats": n, "threshold": threshold},
        )
        for (file, line), n in sorted(found.items())
    ]  # fmt: skip


def repeated_computations(finished: dict[str, Any], events: Iterable[dict[str, Any]]) -> list[Finding]:
    """Calls with identical argument fingerprints that happened more than once (memoization candidates)."""
    defs: dict[str, tuple[str, int]] = {}
    for ev in events:
        if ev.get("type") == "call" and ev.get("kind") == "user" and ev["func"] != "<module>":
            defs.setdefault(ev["qualname"], (ev["file"], ev["line"]))
    per_func: dict[str, list[int]] = defaultdict(list)
    for rc in finished.get("repeat_calls", []):
        per_func[rc["func"]].append(rc["count"])
    out: list[Finding] = []
    for func, counts in per_func.items():
        extra = sum(c - 1 for c in counts)
        if extra < MIN_REPEATED_CALLS - 1 or func not in defs:
            continue
        file, line = defs[func]
        out.append(
            make_finding(
                "repeated_computation", "warn", "likely", file, line, line,
                f"'{func}' was called {extra} extra time(s) with arguments it had already seen",
                {"function": func, "redundant_calls": extra, "distinct_repeated_arguments": len(counts),
                 "max_repeats": max(counts), "note": "assumes the function is pure; check before caching"},
            )
        )  # fmt: skip
    return out


def _loop_invariants(file: str, tree: ast.Module, hits: dict[int, int]) -> list[Finding]:
    out: list[Finding] = []
    for loop in (n for n in ast.walk(tree) if isinstance(n, (ast.For, ast.While, ast.AsyncFor))):
        stored = {n.id for n in ast.walk(loop) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        stored |= {n.arg for n in ast.walk(loop) if isinstance(n, ast.arg)}
        mutated = {
            n.func.value.id
            for n in ast.walk(loop)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
        }  # `xs.append(..)` may change `xs`, so len(xs) is not invariant
        for stmt in loop.body:
            if not isinstance(stmt, (ast.Assign, ast.Expr, ast.AugAssign)):
                continue
            value = stmt.value
            calls = [n for n in ast.walk(value) if isinstance(n, ast.Call)]
            if not calls or any(not (isinstance(c.func, ast.Name) and c.func.id in _PURE_CALLS) for c in calls):
                continue
            names = {n.id for n in ast.walk(value) if isinstance(n, ast.Name) and n.id not in _PURE_CALLS}
            if not names or names & (stored | mutated):
                continue
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in names for t in stmt.targets
            ):
                continue
            n_hits = hits.get(stmt.lineno, 0)
            if n_hits < MIN_INVARIANT_HITS:
                continue
            out.append(
                make_finding(
                    "loop_invariant", "info", "likely", file, stmt.lineno, end_line(stmt),
                    f"The computation on line {stmt.lineno} does not depend on the loop and ran {n_hits} times",
                    {"hits": n_hits, "depends_on": sorted(names)},
                )
            )  # fmt: skip
    return out


def loop_invariants(trees: dict[str, ast.Module], line_hits: dict[str, dict[str, int]]) -> list[Finding]:
    found: list[Finding] = []
    for file, tree in trees.items():
        hits = {int(k): v for k, v in line_hits.get(file, {}).items()}
        found += _loop_invariants(file, tree, hits)
    return found


def analyze_trace(
    events: list[dict[str, Any]], trees: dict[str, ast.Module], hot_loop_threshold: int = HOT_LOOP_REPEATS
) -> list[Finding]:
    finished = next((e for e in reversed(events) if e.get("type") == "run_finished"), {})
    return [
        *hot_loops(events, hot_loop_threshold),
        *repeated_computations(finished, events),
        *loop_invariants(trees, finished.get("line_hits", {})),
    ]


# ------------------------------------------------------------------------------------------ profile passes
async def _profile_once(manager: SandboxManager, base: RunRequest, kind: str) -> dict[str, Any]:
    request = RunRequest(
        files=base.files, entry=base.entry, stdin=base.stdin, seed=base.seed, limits=dict(base.limits),
        allow_network=base.allow_network, profile=kind,
    )  # fmt: skip
    finished: dict[str, Any] = {}
    async for event in manager.run(request):
        if event.get("type") == "run_finished":
            finished = event
    return finished


async def run_profile(manager: SandboxManager, base: RunRequest) -> ProfileReport:
    """Two separate UNTRACED runs: cProfile (time) and tracemalloc (memory). Never mixed with the traced run."""
    timing = await _profile_once(manager, base, "time")
    memory = await _profile_once(manager, base, "memory")
    t_prof = (timing.get("profile") or {})
    m_prof = (memory.get("profile") or {})
    functions = [ProfileFunc(**f) for f in t_prof.get("functions", [])]
    lines = [MemoryLine(**m) for m in m_prof.get("live_lines", [])]
    peak = float(m_prof.get("peak_kb", 0.0))
    findings = [
        make_finding(
            "high_memory", "warn", "likely", m.file, m.line, m.line,
            f"{m.size_kb:.0f} KB were still allocated from this line when the program ended",
            {"size_kb": m.size_kb, "allocations": m.count, "pass": "memory (tracemalloc, untraced)"},
        )
        for m in lines
        if m.size_kb >= HIGH_MEMORY_KB
    ]  # fmt: skip
    notes = [
        "Times come from an untraced cProfile pass; memory from a separate untraced tracemalloc pass.",
        "memory_top_lines lists allocations still alive at the end of the run; memory_peak_kb is the process-wide traced peak.",
    ]
    for label, fin in (("time", timing), ("memory", memory)):
        if fin.get("status") != "ok":
            notes.append(f"The {label} pass ended with status '{fin.get('status', 'unknown')}'; its numbers may be partial.")
    return ProfileReport(
        time_pass=ProfilePass(status=str(timing.get("status", "unknown")), wall_ms=int(timing.get("wall_ms", 0))),
        memory_pass=ProfilePass(status=str(memory.get("status", "unknown")), wall_ms=int(memory.get("wall_ms", 0))),
        functions=functions,
        memory_peak_kb=peak,
        memory_top_lines=lines,
        findings=findings,
        notes=notes,
    )
