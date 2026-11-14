"""Dynamic findings (trace-based) and the untraced profile passes."""

from __future__ import annotations

import asyncio

from helpers import example_source, run

from glassbox.analysis import aliasing, dynamic_profile, marksweep
from glassbox.analysis.common import parse_files
from glassbox.sandbox.manager import RunRequest, SandboxManager


def _findings(name: str, **kwargs):
    source = example_source(name)
    return marksweep.build({name: source}, name, run(source, entry=name, **kwargs)).findings


def test_fib_naive_has_repeated_computation() -> None:
    found = [f for f in _findings("fib_naive.py") if f.category == "repeated_computation"]
    assert len(found) == 1
    assert found[0].evidence["function"] == "fib"
    assert found[0].evidence["redundant_calls"] > 100


def test_alias_bug_has_mutable_default_and_alias_mutation() -> None:
    found = {f.category: f for f in _findings("alias_bug.py")}
    default = found["mutable_default"]
    assert (default.start_line, default.evidence["parameter"]) == (4, "bucket")
    alias = found["alias_mutation"]
    assert alias.evidence["mutated_through"] == "copy"
    assert alias.evidence["read_through"] == ["original"]
    assert (alias.evidence["mutation_line"], alias.evidence["read_line"]) == (15, 16)


def test_intentionally_shared_list_without_mutation_is_not_an_alias_finding() -> None:
    src = "a = [1, 2]\nb = a\nprint(a, b)\n"
    trees = parse_files({"main.py": src})
    assert aliasing.analyze(run(src), trees) == []


def test_hot_loop_is_found_when_state_stops_changing() -> None:
    src = "x = 1\nwhile True:\n    y = x\n"
    events = run(src, limits={"max_steps": 600})
    trees = parse_files({"main.py": src})
    found = dynamic_profile.analyze_trace(events, trees, hot_loop_threshold=100)
    hot = [f for f in found if f.category == "hot_loop"]
    assert hot and hot[0].file == "main.py" and hot[0].evidence["threshold"] == 100


def test_changing_state_is_not_a_hot_loop() -> None:
    src = example_source("infinite_loop.py")
    events = run(src, limits={"max_steps": 600})
    found = dynamic_profile.analyze_trace(events, parse_files({"main.py": src}), hot_loop_threshold=100)
    assert not [f for f in found if f.category == "hot_loop"]


def test_loop_invariant_is_detected() -> None:
    src = "xs = list(range(50))\ntotal = 0\nfor i in range(40):\n    n = len(xs)\n    total += i * n\nprint(total)\n"
    events = run(src)
    found = [f for f in dynamic_profile.analyze_trace(events, parse_files({"main.py": src})) if f.category == "loop_invariant"]
    assert [(f.start_line, f.evidence["hits"]) for f in found] == [(4, 40)]


def test_profile_passes_are_untraced_and_measure_time_and_memory() -> None:
    src = example_source("fib_naive.py") + "\nbig = [0] * 600000\n"
    request = RunRequest(files={"main.py": src}, entry="main.py")
    report = asyncio.run(dynamic_profile.run_profile(SandboxManager(), request))
    assert report.time_pass.status == "ok" and report.memory_pass.status == "ok"
    fib = next(f for f in report.functions if f.func == "fib")
    assert fib.calls == 1973 and fib.total_ms >= 0 and fib.file == "main.py"
    assert report.memory_peak_kb > 4000
    assert any(f.category == "high_memory" for f in report.findings)
    assert any("untraced" in n for n in report.notes)


def test_profile_job_emits_no_line_events() -> None:
    events = run("x = 1\nprint(x)\n", profile="time")
    assert not [e for e in events if e["type"] in ("line", "call")]
    assert events[-1]["type"] == "run_finished" and events[-1]["profile"]["kind"] == "time"
