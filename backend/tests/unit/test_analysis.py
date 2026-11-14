"""Static / mark & sweep analysis acceptance tests (spec Phase 2). Runs use the real runner subprocess."""

from __future__ import annotations

from helpers import example_source, run

from glassbox.analysis import clones, complexity, marksweep, static_dead
from glassbox.analysis.common import finalize, parse_files
from glassbox.schemas.analysis import Finding


def _static(files: dict[str, str]) -> list[Finding]:
    trees = parse_files(files)
    return finalize([*static_dead.analyze(trees), *clones.find(trees)])


def _spans(findings: list[Finding], category: str) -> list[tuple[int, int]]:
    return [(f.start_line, f.end_line) for f in findings if f.category == category]


def _report(name: str):
    source = example_source(name)
    return marksweep.build({name: source}, name, run(source, entry=name))


# --------------------------------------------------------------------- dead_code_zoo.py (expected list)
def test_dead_code_zoo_reports_every_expected_finding_with_exact_lines() -> None:
    report = _report("dead_code_zoo.py")
    got = {(f.category, f.confidence, f.start_line, f.end_line) for f in report.findings}
    expected = {
        ("unused_import", "confirmed", 2, 2),  # import json
        ("unused_import", "confirmed", 3, 3),  # import os
        ("unused_variable", "likely", 6, 6),  # UNUSED_CONSTANT
        ("unused_variable", "confirmed", 10, 10),  # unused_local
        ("uncalled_function", "confirmed", 14, 15),  # never_called
        ("unreachable_code", "confirmed", 20, 20),  # after return
        ("unreachable_code", "confirmed", 25, 25),  # if False body
        ("duplicate_block", "likely", 29, 36),  # block_one / block_two
        ("cold_code", "likely", 51, 51),  # rarely_used(False): the 'rare path' return never ran
    }
    assert expected <= got
    assert {c for c, *_ in got - expected} == set(), f"unexpected extra findings: {got - expected}"
    assert report.summary.confirmed_dead == 6
    assert report.summary.reclaimable_lines == 7  # 2 imports + unused_local + never_called(2) + 2 dead lines


def test_duplicate_group_contains_both_blocks() -> None:
    report = _report("dead_code_zoo.py")
    dup = next(f for f in report.findings if f.category == "duplicate_block")
    spots = {(s["start_line"], s["end_line"]) for s in dup.evidence["locations"]}
    assert spots == {(29, 36), (39, 46)}


def test_clones_ignore_names_and_constants_but_not_structure() -> None:
    a = "def f(xs):\n    t = 0\n    for x in xs:\n        if x > 1:\n            t += x\n        else:\n            t -= 1\n    return t\n"
    b = a.replace("f(xs)", "g(items)").replace("xs", "items").replace("x ", "value ").replace("t ", "acc ").replace("t -", "acc -")
    c = a.replace("t += x", "t *= x")  # different operator: not a clone
    found = clones.find(parse_files({"a.py": a, "b.py": b, "c.py": c}))
    members = {(s["file"]) for f in found for s in f.evidence["locations"]}
    assert {"a.py", "b.py"} <= members and "c.py" not in members


# --------------------------------------------------------------------- false positives
FALSE_POSITIVES = '''\
__all__ = ["exported"]
import functools
registry = {}

def exported():
    return 1

def register(fn):
    registry[fn.__name__] = fn
    return fn

@register
def decorated():
    return 2

def by_getattr():
    return 3

class Plugin:
    def hook(self):
        return 4

def run(name):
    import sys
    return getattr(sys.modules[__name__], name)()

if __name__ == "__main__":
    print(run("by_getattr"), Plugin().hook())
'''


def test_exported_decorated_and_getattr_functions_are_never_confirmed_dead() -> None:
    files = {"main.py": FALSE_POSITIVES}
    report = marksweep.build(files, "main.py", run(FALSE_POSITIVES))
    dead = {f.evidence.get("name") for f in report.findings if f.category == "uncalled_function" and f.confidence == "confirmed"}
    assert dead.isdisjoint({"exported", "decorated", "by_getattr", "hook", "run", "Plugin", "register"}), dead
    flagged = {f.evidence.get("name"): f.confidence for f in report.findings if f.category == "uncalled_function"}
    assert flagged.get("decorated") in (None, "suspect")


def test_transitively_dead_function_is_found() -> None:
    src = "def helper():\n    return 1\n\ndef dead_root():\n    return helper()\n\nprint('hi')\n"
    report = marksweep.build({"main.py": src}, "main.py", run(src))
    names = {(f.evidence.get("name"), f.confidence) for f in report.findings if f.category == "uncalled_function"}
    assert ("dead_root", "confirmed") in names
    assert ("helper", "confirmed") in names  # only reachable from dead code


def test_executed_despite_static_unreachable_is_downgraded_to_suspect() -> None:
    src = "def f():\n    return 1\n\nglobals()['unused'] = f\nprint(globals()['unused']())\n"
    report = marksweep.build({"main.py": src}, "main.py", run(src))
    dead = [f for f in report.findings if f.category == "uncalled_function" and f.evidence.get("name") == "f"]
    assert not dead or all(f.confidence == "suspect" for f in dead)


def test_unreachable_code_variants() -> None:
    src = (
        "def a():\n    raise ValueError()\n    print(1)\n\n"
        "def b():\n    while True:\n        pass\n    print(2)\n\n"
        "def c(x):\n    for i in x:\n        break\n        print(3)\n\n"
        "def d():\n    if True:\n        return 1\n    else:\n        return 2\n"
    )
    findings = _static({"main.py": src})
    assert _spans(findings, "unreachable_code") == [(3, 3), (8, 8), (13, 13), (19, 19)]


def test_complexity_counts_branches_and_loop_depth() -> None:
    src = "def f(xs):\n    n = 0\n    for x in xs:\n        for y in xs:\n            if x and y:\n                n += 1\n    return n\n"
    (fn,) = complexity.analyze(parse_files({"main.py": src}))
    assert fn.cyclomatic == 5  # 1 + for + for + if + and
    assert fn.max_loop_depth == 2


def test_syntax_error_is_reported_not_crashed() -> None:
    import pytest

    from glassbox.analysis.common import SourceError

    with pytest.raises(SourceError, match="syntax error on line 1"):
        parse_files({"main.py": "def (:\n"})
