"""Verified refactoring: parse -> same behaviour -> step counts -> interleaved untraced timing (spec 7.2)."""

from __future__ import annotations

import ast
import statistics
from dataclasses import dataclass
from typing import Any

from ..sandbox.manager import RunRequest, SandboxManager
from ..schemas.llm import TimeStats, VerificationReport

REPEATS = 5  # timed pairs per version (after one discarded warm-up pair)
MIN_RELATIVE_DIFF = 0.10  # below this the difference is not reported as a speed-up
RUN_LIMITS = {"timeout_s": 10}


@dataclass
class Sample:
    stdout: str
    stderr: str
    status: str
    exit_code: int
    exc_type: str | None
    exec_ns: int
    steps: int


async def _run(manager: SandboxManager, files: dict[str, str], entry: str, stdin: str, seed: int, *, timed: bool) -> Sample:
    request = RunRequest(
        files=files, entry=entry, stdin=stdin, seed=seed, limits=dict(RUN_LIMITS), profile="timing" if timed else None
    )
    out: list[str] = []
    err: list[str] = []
    finished: dict[str, Any] = {}
    async for ev in manager.run(request):
        if ev["type"] == "output":
            (out if ev["stream"] == "stdout" else err).append(ev["text"])
        elif ev["type"] == "run_finished":
            finished = ev
    status = str(finished.get("status", "killed"))
    detail = str(finished.get("detail") or "")
    exc_type = detail.split(":", 1)[0] if status == "exception" and ":" in detail else None
    profile = finished.get("profile") or {}
    return Sample(
        "".join(out), "".join(err), status, int(finished.get("exit_code", -1)), exc_type,
        int(profile.get("exec_ns", 0)), int(finished.get("steps", 0)),
    )  # fmt: skip


def _stats(samples: list[float]) -> TimeStats:
    return TimeStats(median=statistics.median(samples), min=min(samples), max=max(samples))


def _parse_problem(files: dict[str, str]) -> str | None:
    for path, text in files.items():
        if path.endswith(".py"):
            try:
                ast.parse(text, filename=path)
            except SyntaxError as exc:
                return f"{path}: syntax error on line {exc.lineno}: {exc.msg}"
    return None


def behaviour_diffs(a: Sample, b: Sample) -> list[str]:
    diffs: list[str] = []
    if a.stdout != b.stdout:
        diffs.append(f"stdout differs: {a.stdout[:120]!r} -> {b.stdout[:120]!r}")
    if a.status != b.status:
        diffs.append(f"status differs: {a.status} -> {b.status}")
    if a.exc_type != b.exc_type:
        diffs.append(f"exception type differs: {a.exc_type} -> {b.exc_type}")
    if a.exit_code != b.exit_code:
        diffs.append(f"exit code differs: {a.exit_code} -> {b.exit_code}")
    return diffs


async def verify(
    manager: SandboxManager,
    original: dict[str, str],
    proposed: dict[str, str],
    entry: str,
    stdin: str = "",
    seed: int = 0,
) -> VerificationReport:
    problem = _parse_problem(proposed)
    if problem:
        return VerificationReport(
            parses=False, behavior_equal=False, diffs=[problem], steps_before=None, steps_after=None,
            time_before_ms=None, time_after_ms=None, speedup=None, verdict="broken",
        )  # fmt: skip
    if entry not in proposed:
        return VerificationReport(
            parses=True, behavior_equal=False, diffs=[f"the entry file {entry!r} is missing from the proposal"],
            steps_before=None, steps_after=None, time_before_ms=None, time_after_ms=None, speedup=None,
            verdict="broken",
        )  # fmt: skip

    traced_before = await _run(manager, original, entry, stdin, seed, timed=False)
    traced_after = await _run(manager, proposed, entry, stdin, seed, timed=False)

    await _run(manager, original, entry, stdin, seed, timed=True)  # warm-up pair (file cache, imports): discarded
    await _run(manager, proposed, entry, stdin, seed, timed=True)
    before: list[Sample] = []
    after: list[Sample] = []
    for _ in range(REPEATS):  # interleaved, so slow drifts hit both versions equally
        before.append(await _run(manager, original, entry, stdin, seed, timed=True))
        after.append(await _run(manager, proposed, entry, stdin, seed, timed=True))

    diffs = behaviour_diffs(before[0], after[0]) or behaviour_diffs(traced_before, traced_after)
    t_before = _stats([s.exec_ns / 1e6 for s in before])
    t_after = _stats([s.exec_ns / 1e6 for s in after])
    equal = not diffs
    speedup = t_before.median / t_after.median if t_after.median > 0 else None

    if not equal:
        verdict = "behavior_changed"
    else:
        faster = (
            t_after.median < t_before.median * (1 - MIN_RELATIVE_DIFF)
            and t_after.max < t_before.min  # the measured ranges must not overlap
        )
        if faster:
            verdict = "verified_faster"
        elif traced_before.steps == traced_after.steps:
            verdict = "verified_equal"  # same behaviour, same step count, no measurable time difference
        else:
            verdict = "no_measurable_change"
    return VerificationReport(
        parses=True,
        behavior_equal=equal,
        diffs=diffs,
        steps_before=traced_before.steps,
        steps_after=traced_after.steps,
        time_before_ms=t_before,
        time_after_ms=t_after,
        speedup=round(speedup, 2) if speedup is not None else None,
        verdict=verdict,  # type: ignore[arg-type]
    )
