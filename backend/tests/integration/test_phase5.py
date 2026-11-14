"""Phase 5: What-If, Root-Cause Rewind, Big-O laboratory, exports (real runner subprocesses)."""

from __future__ import annotations

import asyncio
import json
import math
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import example_source, run, stdout_text

from glassbox.analysis import bigo
from glassbox.analysis.branches import compare
from glassbox.analysis.slicing import SliceError, backward_slice
from glassbox.api.app import create_app
from glassbox.config import Settings
from glassbox.export.html_replay import PLAYER_JS, build_replay, thin
from glassbox.export.mermaid import escape_label, to_mermaid, to_svg
from glassbox.sandbox.manager import SandboxManager

CRASH = example_source("crash_chain.py")


def client() -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, validate_events="strict")))


def body(source: str, **extra: Any) -> dict[str, Any]:
    return {"files": [{"path": "main.py", "content": source}], "entry": "main.py", **extra}


def done(c: TestClient, run_id: str) -> None:
    deadline = time.time() + 30
    while c.get(f"/api/runs/{run_id}").json()["state"] == "running" and time.time() < deadline:
        time.sleep(0.05)


# ------------------------------------------------------------------------------------------ What-If
def _fix_override(events: list[dict[str, Any]]) -> dict[str, Any]:
    step = next(e["step"] for e in events if e["type"] == "line" and e["line"] == 14)  # summarize() after count = ...
    return {"step": step, "frame_depth": 2, "name": "count", "value_literal": "1"}


def test_fixing_the_bad_value_makes_the_branch_finish_without_the_exception() -> None:
    base = run(CRASH)
    override = _fix_override(base)
    branch = run(CRASH, overrides=[override])
    assert base[-1]["status"] == "exception" and branch[-1]["status"] == "ok"
    assert stdout_text(branch) == "average of big items: 29.0\n"
    applied = [e for e in branch if e["type"] == "whatif_applied"]
    assert [(a["name"], a["old"]["r"], a["new"]["r"]) for a in applied] == [("count", "0", "1")]


def test_divergence_step_is_reported_and_the_outcome_difference_summarized() -> None:
    base = run(CRASH)
    override = _fix_override(base)
    branch = run(CRASH, overrides=[override])
    cmp = compare("base", base, "branch", branch)
    assert cmp.first_divergence_step is not None
    assert override["step"] <= cmp.first_divergence_step <= override["step"] + 6, cmp.first_divergence_step
    assert cmp.base.status == "exception" and cmp.branch.status == "ok"
    assert cmp.branch.exception is None and cmp.base.exception and "ZeroDivisionError" in cmp.base.exception
    assert not cmp.output_equal and any("diverge" in s for s in cmp.summary) and any("Status" in s for s in cmp.summary)
    same = compare("a", base, "b", base)
    assert same.first_divergence_step is None and same.output_equal


def test_api_branch_flow_and_rejection_of_non_literal_overrides() -> None:
    with client() as c:
        base_id = c.post("/api/runs", json=body(CRASH)).json()["run_id"]
        done(c, base_id)
        events = [json.loads(line) for line in c.get(f"/api/runs/{base_id}/trace").text.splitlines()]
        o = _fix_override(events)
        branch_id = c.post("/api/runs", json=body(CRASH, overrides=[o])).json()["run_id"]
        done(c, branch_id)
        cmp = c.get(f"/api/runs/{base_id}/compare", params={"other": branch_id}).json()
        assert cmp["first_divergence_step"] and cmp["branch"]["status"] == "ok"
        for bad in ("__import__('os')", "open('x').read()", "1 + 1", "[x for x in ()]", "lambda: 1"):
            r = c.post("/api/runs", json=body(CRASH, overrides=[{**o, "value_literal": bad}]))
            assert r.status_code == 422 and "rejected" in r.json()["detail"], bad
        assert c.post("/api/runs", json=body(CRASH, overrides=[{**o, "name": "not valid"}])).status_code == 422


def test_runner_also_refuses_a_non_literal_override_by_itself() -> None:
    events = run("x = 1\nprint(x)\n", overrides=[{"step": 2, "frame_depth": 0, "name": "x", "value_literal": "__import__('os')"}])
    assert events[-1]["status"] == "blocked" and "plain Python literal" in events[-1]["detail"]


# ------------------------------------------------------------------------------------------ Root-Cause
def test_root_cause_chain_reaches_the_origin_of_the_bad_value() -> None:
    events = run(CRASH, entry="main.py")
    chain = backward_slice(events, {"main.py": CRASH})
    assert chain.exception_type == "ZeroDivisionError" and not chain.truncated
    steps = [link.step for link in chain.links]
    assert steps == sorted(steps), "origin first, failure last"
    assert chain.links[-1].kind == "error" and chain.links[-1].line == 9
    by_kind = {(link.kind, link.name, link.line): link.value for link in chain.links}
    assert by_kind[("argument", "count", 15)] == "0", "count=0 is handed to compute_ratio at line 15"
    assert by_kind[("assignment", "count", 13)] == "0", "summarize assigned count at line 13"
    assert ("return", "load_count", 5) in by_kind and by_kind[("return", "load_count", 5)] == "0", "...from load_count's return"
    assert ("assignment", "data", 19) in by_kind, "the chain continues back to the input data"
    first_bad = next(link for link in chain.links if link.value == "0")
    assert first_bad.line in (5, 13), "the first place the faulty value appears is inside load_count / its assignment"
    assert not [link for link in chain.links if link.kind == "global"], "function objects are noise"


def test_root_cause_needs_an_uncaught_exception() -> None:
    events = run("x = 1\n")
    with pytest.raises(SliceError, match="no failure"):
        backward_slice(events, {"main.py": "x = 1\n"})
    with client() as c:
        run_id = c.post("/api/runs", json=body("x = 1\n")).json()["run_id"]
        done(c, run_id)
        assert c.get(f"/api/runs/{run_id}/rootcause").status_code == 404
        crash_id = c.post("/api/runs", json=body(CRASH)).json()["run_id"]
        done(c, crash_id)
        chain = c.get(f"/api/runs/{crash_id}/rootcause").json()
        assert chain["links"][-1]["kind"] == "error" and chain["exception_type"] == "ZeroDivisionError"


def test_mentor_narration_of_the_crash_includes_the_causal_chain() -> None:
    with client() as c:
        run_id = c.post("/api/runs", json=body(CRASH)).json()["run_id"]
        done(c, run_id)
        with c.stream("GET", f"/api/mentor/narrate?run_id={run_id}&lang=en") as r:
            text = "".join(r.iter_text())
    assert "Root-cause chain (origin to failure)" in text and "load_count() returned 0" in text


# ------------------------------------------------------------------------------------------ Big-O
LINEAR = "def find(xs, target):\n    for i, x in enumerate(xs):\n        if x == target:\n            return i\n    return -1\n"
BINARY = (
    "def bsearch(xs, target):\n    lo, hi = 0, len(xs) - 1\n    while lo <= hi:\n        mid = (lo + hi) // 2\n"
    "        if xs[mid] == target:\n            return mid\n        if xs[mid] < target:\n            lo = mid + 1\n"
    "        else:\n            hi = mid - 1\n    return -1\n"
)


def measure(source: str, func: str, generator: str, extra: list[str] | None = None, sizes: list[int] | None = None):
    return asyncio.run(bigo.run_bigo(SandboxManager(), {"main.py": source}, "main.py", func, generator, sizes, extra or []))


@pytest.mark.parametrize(
    ("source", "func", "generator", "extra", "expected"),
    [
        (example_source("bubble_sort.py"), "bubble_sort", "random_ints", [], "n^2"),
        (LINEAR, "find", "random_ints", ["$missing"], "n"),
        (BINARY, "bsearch", "sorted_ints", ["$missing"], "log n"),
        (example_source("fib_naive.py"), "fib", "int_n", [], "2^n"),
    ],
)
def test_empirical_growth_class(source: str, func: str, generator: str, extra: list[str], expected: str) -> None:
    report = measure(source, func, generator, extra)
    assert report.best.model == expected, [(f.model, f.r2) for f in report.fits]
    assert report.best.r2 > 0.97 and len(report.points) >= 4
    assert report.runner_up is not None and report.runner_up.model != expected
    assert "THIS input family" in report.note and "not a proof" in report.note


def test_binary_search_static_estimate_disagrees_and_is_flagged() -> None:
    report = measure(BINARY, "bsearch", "sorted_ints", ["$missing"])
    assert report.static.model == "n" and report.best.model == "log n" and report.conflict
    agree = measure(example_source("bubble_sort.py"), "bubble_sort", "random_ints")
    assert agree.static.model == "n^2" and not agree.conflict


def test_fit_models_is_exact_on_synthetic_data_and_prefers_the_simpler_model_on_ties() -> None:
    sizes = [8, 16, 32, 64, 128]
    assert bigo.fit_models([(n, 3 * n * n + 7) for n in sizes])[0].model == "n^2"
    assert bigo.fit_models([(n, 5 * n + 2) for n in sizes])[0].model == "n"
    assert bigo.fit_models([(n, 42) for n in sizes])[0].model == "1"
    assert bigo.fit_models([(n, 4 * n * math.log2(n)) for n in sizes])[0].model == "n log n"


def test_bigo_rejects_bad_requests_with_clear_errors() -> None:
    with client() as c:
        base = {**body(LINEAR), "func": "find"}
        assert c.post("/api/lab/bigo", json={**base, "func": "find; import os"}).status_code == 422
        assert c.post("/api/lab/bigo", json={**base, "extra_args": ["open('x')"]}).status_code == 422
        assert c.post("/api/lab/bigo", json={**base, "sizes": [1, 2, 3, 4]}).status_code == 422
        assert c.post("/api/lab/bigo", json={**base, "func": "missing", "sizes": [8, 16, 32, 64]}).status_code == 422
        ok = c.post("/api/lab/bigo", json={**base, "extra_args": ["$missing"], "sizes": [8, 16, 32, 64, 128]})
        assert ok.status_code == 200 and ok.json()["best"]["model"] == "n"


# ------------------------------------------------------------------------------------------ exports
GRAMMAR = [
    re.compile(r"^flowchart TD$"),
    re.compile(r'^    n\d+(\["[^"]+"\]|\("[^"]+"\))$'),
    re.compile(r"^    n\d+ -->\|\d+\| n\d+$"),
    re.compile(r"^    classDef lib stroke-dasharray: 4 3$"),
    re.compile(r"^    class n\d+(,n\d+)* lib$"),
]


def test_mermaid_output_follows_the_grammar_and_escapes_hostile_names() -> None:
    src = 'def f(x):\n    return x\n\nclass K:\n    def m(self):\n        return f(1)\n\nimport json\nprint(json.dumps(K().m()))\n'
    text = to_mermaid(run(src))
    lines = text.rstrip("\n").split("\n")
    assert all(any(g.match(line) for g in GRAMMAR) for line in lines), lines
    ids = [re.match(r"^    (n\d+)[\[(]", line).group(1) for line in lines if re.match(r"^    n\d+[\[(]", line)]
    assert len(ids) == len(set(ids)) and "json.dumps" in text
    assert escape_label('a"b<c>|`d\\#') == "a#34;b#60;c#62;#124;#96;d#92;#35;"
    assert "<" not in text.replace("-->", "") and "#60;module#62;" in text


def test_svg_is_well_formed_xml_with_all_nodes() -> None:
    events = run(example_source("fib_naive.py"))
    root = ET.fromstring(to_svg(events))
    assert root.tag.endswith("svg")
    texts = [t.text for t in root.iter() if t.tag.endswith("text")]
    assert any(t and t.startswith("fib") for t in texts) and any(t and "module" in t for t in texts)
    assert ET.fromstring(to_svg([])).tag.endswith("svg")


def _data_of(page: str) -> dict[str, Any]:
    m = re.search(r'<script id="gb-data" type="application/json">(.*?)</script>', page, re.DOTALL)
    assert m
    return json.loads(m.group(1))


def test_replay_html_is_self_contained_and_contains_trace_and_source() -> None:
    src = example_source("alias_bug.py")
    events = run(src, entry="alias_bug.py", keyframe_interval=7)
    page = build_replay(events, src, "alias_bug.py")
    assert not re.search(r"https?://|//cdn|@import|<link|<img|src=|href=", page), "no external references"
    data = _data_of(page)
    assert data["source"] == src and data["info"]["thinned"] is False
    assert {e["type"] for e in data["events"]} >= {"run_started", "call", "line", "output", "run_finished"}
    assert "</script>" not in json.dumps(data["events"]).replace("<\\/", "")  # embedded data cannot close the tag


def test_replay_html_survives_hostile_source_text() -> None:
    src = 'x = "</script><script>alert(1)</script>"\nprint(x)\n'
    page = build_replay(run(src), src, "<b>t</b>")
    assert page.count("</script>") == 2, "only the two real closing tags"
    assert _data_of(page)["source"] == src and "<b>t</b>" not in page


def test_oversized_traces_are_thinned_by_growing_the_keyframe_stride() -> None:
    events = run(example_source("fib_naive.py"))
    full_events, info = thin(events, 10**9)
    assert info["thinned"] is False
    small, info = thin(events, 60_000)
    assert info["thinned"] is True and info["keyframe_stride"] >= 1 and len(small) < len(full_events)
    assert len(json.dumps(small)) <= 60_000 or info["keyframes"] <= 1
    page = build_replay(events, "x", "t", max_bytes=60_000)
    assert "thinned to fit" in page and _data_of(page)["info"]["thinned"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="node is needed to execute the embedded player logic")
def test_the_embedded_player_logic_reproduces_the_final_state_in_node() -> None:
    src = example_source("alias_bug.py")
    events = run(src, entry="alias_bug.py", keyframe_interval=7)
    page = build_replay(events, src, "alias_bug.py")
    data = page.split('type="application/json">', 1)[1].split("</script>", 1)[0].replace("<\\/", "</")
    harness = (
        "const vm=require('vm');globalThis.__GB_DATA__=process.argv[1];const m={exports:{}};"
        "vm.runInThisContext('(function(module){'+process.argv[2]+'})')(m);"
        "const p=m.exports;const last=p.steps()-1;const s=p.stateAt(last);"
        "console.log(JSON.stringify({steps:p.steps(),globals:Object.keys(s.globals).sort(),"
        "copy:p.show(s.globals.copy,s.heap),out:p.outputAt(last)}));"
    )
    proc = subprocess.run(["node", "-e", harness, data, PLAYER_JS], capture_output=True, text=True, check=False, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["copy"] == "[1, 2, 3, 4]" and "original" in out["globals"] and out["out"].startswith("['apple', 'pear']")
    assert out["steps"] == len([e for e in events if e["type"] in ("call", "line", "return", "exception")])


def test_export_endpoints_and_cli(tmp_path: Any) -> None:
    with client() as c:
        run_id = c.post("/api/runs", json=body(example_source("fib_naive.py"))).json()["run_id"]
        done(c, run_id)
        mmd = c.get(f"/api/export/{run_id}/mermaid")
        svg = c.get(f"/api/export/{run_id}/svg")
        html = c.get(f"/api/export/{run_id}/html")
        assert mmd.status_code == svg.status_code == html.status_code == 200
        assert mmd.text.startswith("flowchart TD") and svg.headers["content-type"].startswith("image/svg+xml")
        assert html.headers["content-type"].startswith("text/html") and "gb-data" in html.text
        assert c.get("/api/export/nope/mermaid").status_code == 404
    out = tmp_path / "r.html"
    script = str(Path(__file__).resolve().parents[3] / "examples" / "alias_bug.py")
    proc = subprocess.run(
        [sys.executable, "-m", "glassbox.cli", "export", script, "--html", str(out), "--mermaid", str(tmp_path / "g.mmd"), "--svg", str(tmp_path / "g.svg")],
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>") and (tmp_path / "g.mmd").read_text().startswith("flowchart")
    nothing = subprocess.run([sys.executable, "-m", "glassbox.cli", "export", script], capture_output=True, text=True, check=False)
    assert nothing.returncode == 2 and "choose at least one" in nothing.stderr
