"""Untraced profile passes (stdlib only): cProfile for real timings, tracemalloc for memory.

The two measurements run in SEPARATE processes (each distorts the other). The result travels in
``run_finished.profile``; no per-line events are produced in these passes.
"""

from __future__ import annotations

import cProfile
import tracemalloc
from typing import Any

from .noise import Classifier
from .recorder import Recorder

TOP_N = 30


class ProfileHarness:
    """Same start/stop shape as a tracer backend, but only measures."""

    def __init__(self, kind: str, recorder: Recorder, classifier: Classifier) -> None:
        self.kind = kind
        self.rec = recorder
        self.classifier = classifier
        self._profile: cProfile.Profile | None = None
        self._stopped = False

    def start(self) -> None:
        if self.kind == "memory":
            tracemalloc.start(1)
        else:
            self._profile = cProfile.Profile()
            self._profile.enable()

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        if self.kind == "memory":
            self.rec.extra_finish["profile"] = self._memory_result()
        else:
            assert self._profile is not None
            self._profile.disable()
            self.rec.extra_finish["profile"] = self._time_result(self._profile)

    def _time_result(self, profile: cProfile.Profile) -> dict[str, Any]:
        import pstats

        funcs: list[dict[str, Any]] = []
        for (path, line, name), (_cc, calls, tottime, cumtime, _callers) in pstats.Stats(profile).stats.items():  # type: ignore[attr-defined]
            if not self.classifier.is_user_file(path):
                continue
            funcs.append(
                {
                    "func": name,
                    "file": self.classifier.relpath(path),
                    "line": line,
                    "calls": calls,
                    "self_ms": round(tottime * 1000, 3),
                    "total_ms": round(cumtime * 1000, 3),
                }
            )
        funcs.sort(key=lambda f: (-f["self_ms"], f["file"], f["line"]))
        return {"kind": "time", "functions": funcs[:TOP_N]}

    def _memory_result(self) -> dict[str, Any]:
        _current, peak = tracemalloc.get_traced_memory()
        snapshot = tracemalloc.take_snapshot()
        tracemalloc.stop()
        lines: list[dict[str, Any]] = []
        for stat in snapshot.statistics("lineno"):
            frame = stat.traceback[0]
            if not self.classifier.is_user_file(frame.filename):
                continue
            lines.append(
                {
                    "file": self.classifier.relpath(frame.filename),
                    "line": frame.lineno,
                    "size_kb": round(stat.size / 1024, 2),
                    "count": stat.count,
                }
            )
        lines.sort(key=lambda m: (-m["size_kb"], m["file"], m["line"]))
        # peak covers the whole process (runner included); the per-line list is what is still alive at the end.
        return {"kind": "memory", "peak_kb": round(peak / 1024, 2), "live_lines": lines[:TOP_N]}
