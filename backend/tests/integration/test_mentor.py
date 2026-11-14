"""Mentor flows end to end: autofix, refactor proposals (mock + fake LLMs), verification, SSE narration."""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import example_source, run, stdout_text

from glassbox.api.app import create_app
from glassbox.config import Settings
from glassbox.llm.base import Message
from glassbox.llm.keyring import KeyRing
from glassbox.llm.providers.mock import MockProvider
from glassbox.llm.service import LlmService
from glassbox.mentor.autofix import findings_for


class Scripted:
    """LLM test double: returns the scripted answers in order and counts calls."""

    name = "scripted"
    model = "scripted-1"

    def __init__(self, answers: list[str]) -> None:
        self.answers = answers
        self.calls = 0
        self._ring = KeyRing(["k"])

    @property
    def ring(self) -> KeyRing:
        return self._ring

    async def complete(self, messages: list[Message], key: str) -> str:
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return answer

    async def stream(self, messages: list[Message], key: str):  # pragma: no cover - not used here
        yield await self.complete(messages, key)


def client_with(llm: LlmService) -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, validate_events="strict"), llm=llm))


def body(source: str, **extra: Any) -> dict[str, Any]:
    return {"files": [{"path": "main.py", "content": source}], "entry": "main.py", **extra}


def finished_run(c: TestClient, source: str) -> str:
    run_id = c.post("/api/runs", json=body(source)).json()["run_id"]
    deadline = time.time() + 30
    while c.get(f"/api/runs/{run_id}").json()["state"] == "running" and time.time() < deadline:
        time.sleep(0.05)
    return run_id


def finding_id(c: TestClient, run_id: str, category: str) -> str:
    report = c.get(f"/api/runs/{run_id}/marksweep").json()
    return next(f["id"] for f in report["findings"] if f["category"] == category)


# ------------------------------------------------------------------------------ keyless operation
def test_whole_app_works_without_any_api_key() -> None:
    with client_with(LlmService([])) as c:
        assert c.get("/api/health").json()["llm"] == {"providers": []}
        run_id = finished_run(c, example_source("fib_naive.py"))
        with c.stream("GET", f"/api/mentor/narrate?run_id={run_id}&lang=tr") as r:
            text = "".join(r.iter_text())
        assert "event: meta" in text and "event: layer_a" in text and "event: token" not in text
        assert '"llm": false' in text and "fib(n=15)" in text and "event: done" in text
        fid = finding_id(c, run_id, "repeated_computation")
        r = c.post("/api/mentor/refactor", json={"run_id": run_id, "finding_id": fid})
        assert r.status_code == 503 and ".env" in r.json()["detail"], "needs an LLM: clear, actionable message"


def test_autofix_findings_do_not_need_an_llm() -> None:
    with client_with(LlmService([])) as c:
        run_id = finished_run(c, example_source("dead_code_zoo.py"))
        fid = finding_id(c, run_id, "unused_import")
        r = c.post("/api/mentor/refactor", json={"run_id": run_id, "finding_id": fid})
        assert r.status_code == 200
        proposal = r.json()
        assert proposal["source"] == "autofix" and proposal["verified"] is False
        assert "import json" not in proposal["proposed_files"]["main.py"].split("\n", 3)[1]


# ------------------------------------------------------------------------------ autofix endpoint
def test_autofix_keeps_behaviour_and_reduces_findings() -> None:
    source = example_source("dead_code_zoo.py")
    files = {"main.py": source}
    before = findings_for(files)
    assert len(before) >= 6
    with client_with(LlmService([])) as c:
        r = c.post("/api/refactor/autofix", json={**body(source), "finding_ids": [f.id for f in before]})
    assert r.status_code == 200
    result = r.json()
    new_source = result["files"][0]["content"]
    assert result["skipped"] == [] and len(result["applied"]) == len(before)
    compile(new_source, "main.py", "exec")  # parses
    assert stdout_text(run(new_source)) == stdout_text(run(source)), "output unchanged"
    after = findings_for({"main.py": new_source})
    assert len(after) < len(before) and after == []


def test_autofix_skips_unknown_ids_instead_of_guessing() -> None:
    with client_with(LlmService([])) as c:
        r = c.post("/api/refactor/autofix", json={**body("import os\nprint(1)\n"), "finding_ids": ["unused_import:main.py:1", "nope"]})
    result = r.json()
    assert result["applied"] == ["unused_import:main.py:1"] and result["skipped"][0]["id"] == "nope"
    assert "import os" not in result["files"][0]["content"]


# ------------------------------------------------------------------------------ LLM refactoring + verification
def test_memoization_with_the_mock_is_verified_faster_with_measured_numbers() -> None:
    with client_with(LlmService([MockProvider()])) as c:
        run_id = finished_run(c, example_source("fib_naive.py"))
        fid = finding_id(c, run_id, "repeated_computation")
        proposal = c.post("/api/mentor/refactor", json={"run_id": run_id, "finding_id": fid}).json()
        assert proposal["source"] == "llm" and proposal["verified"] is False
        assert "@cache" in proposal["proposed_files"]["main.py"]
        report = c.post(
            "/api/refactor/verify",
            json={"original_files": body(example_source("fib_naive.py"))["files"],
                  "proposed_files": [{"path": "main.py", "content": proposal["proposed_files"]["main.py"]}],
                  "entry": "main.py"},
        ).json()  # fmt: skip
    assert report["parses"] and report["behavior_equal"], report["diffs"]
    assert report["steps_after"] < report["steps_before"]
    assert report["verdict"] == "verified_faster", report
    assert report["speedup"] and report["speedup"] > 1
    assert report["time_after_ms"]["max"] < report["time_before_ms"]["min"]


def test_behaviour_changing_and_broken_proposals_are_flagged() -> None:
    original = [{"path": "main.py", "content": "print('a')\n"}]
    with client_with(LlmService([])) as c:
        changed = c.post("/api/refactor/verify", json={"original_files": original, "proposed_files": [{"path": "main.py", "content": "print('b')\n"}], "entry": "main.py"}).json()
        broken = c.post("/api/refactor/verify", json={"original_files": original, "proposed_files": [{"path": "main.py", "content": "print('a'\n"}], "entry": "main.py"}).json()
        same = c.post("/api/refactor/verify", json={"original_files": original, "proposed_files": original, "entry": "main.py"}).json()
    assert changed["verdict"] == "behavior_changed" and changed["behavior_equal"] is False and "stdout differs" in changed["diffs"][0]
    assert broken["verdict"] == "broken" and broken["parses"] is False and "syntax error" in broken["diffs"][0]
    assert same["verdict"] in ("verified_equal", "no_measurable_change") and same["behavior_equal"]


def test_invalid_json_from_the_llm_gives_a_clean_error_after_two_retries() -> None:
    llm = Scripted(["definitely not json", "{broken", '{"edits": []}'])
    with client_with(LlmService([llm])) as c:
        run_id = finished_run(c, example_source("fib_naive.py"))
        fid = finding_id(c, run_id, "repeated_computation")
        r = c.post("/api/mentor/refactor", json={"run_id": run_id, "finding_id": fid})
    assert llm.calls == 3, "first attempt + exactly 2 retries"
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "did not produce a valid proposal after 3 attempts" in detail and "Nothing was changed" in detail
    assert "Traceback" not in detail


def test_retry_prompt_carries_the_validation_error_and_a_later_valid_answer_is_accepted() -> None:
    good = json.dumps({"edits": [{"file": "main.py", "start_line": 4, "end_line": 4, "new_code": "from functools import cache\n\n\n@cache\ndef fib(n):"}],
                       "why": "caching", "explanation_md": "cache results", "expected_effect": "fewer repeated calls"})  # fmt: skip
    seen: list[str] = []

    class Spy(Scripted):
        async def complete(self, messages: list[Message], key: str) -> str:
            seen.append(messages[-1]["content"])
            return await super().complete(messages, key)

    llm = Spy(["oops", good])
    with client_with(LlmService([llm])) as c:
        run_id = finished_run(c, example_source("fib_naive.py"))
        fid = finding_id(c, run_id, "repeated_computation")
        r = c.post("/api/mentor/refactor", json={"run_id": run_id, "finding_id": fid})
    assert r.status_code == 200 and "@cache" in r.json()["proposed_files"]["main.py"]
    assert "YOUR PREVIOUS ANSWER WAS REJECTED" in seen[1] and "not the required JSON" in seen[1]


def test_invented_performance_numbers_are_rejected() -> None:
    def answer(effect: str) -> str:
        return json.dumps({"edits": [{"file": "main.py", "start_line": 4, "end_line": 4, "new_code": "from functools import cache\n\n\n@cache\ndef fib(n):"}],
                           "why": "caching", "explanation_md": "cache results", "expected_effect": effect})  # fmt: skip

    invented = Scripted([answer("about 40x faster")])
    with client_with(LlmService([invented])) as c:
        run_id = finished_run(c, example_source("fib_naive.py"))
        fid = finding_id(c, run_id, "repeated_computation")
        r = c.post("/api/mentor/refactor", json={"run_id": run_id, "finding_id": fid})
        assert r.status_code == 502 and invented.calls == 3 and "40x" in r.json()["detail"]
    measured = Scripted([answer("removes the 1957 redundant calls that were recorded")])
    with client_with(LlmService([measured])) as c:
        run_id = finished_run(c, example_source("fib_naive.py"))
        fid = finding_id(c, run_id, "repeated_computation")
        assert c.post("/api/mentor/refactor", json={"run_id": run_id, "finding_id": fid}).status_code == 200


def test_edits_that_break_the_code_are_rejected_before_the_user_sees_them() -> None:
    bad = json.dumps({"edits": [{"file": "main.py", "start_line": 4, "end_line": 4, "new_code": "def fib(n:"}],
                      "why": "x", "explanation_md": "x", "expected_effect": "x"})  # fmt: skip
    llm = Scripted([bad])
    with client_with(LlmService([llm])) as c:
        run_id = finished_run(c, example_source("fib_naive.py"))
        fid = finding_id(c, run_id, "repeated_computation")
        r = c.post("/api/mentor/refactor", json={"run_id": run_id, "finding_id": fid})
    assert r.status_code == 502 and "would not parse" in r.json()["detail"]


# ------------------------------------------------------------------------------ SSE with the mock LLM
def test_narration_streams_llm_tokens_after_the_instant_layer_a_text() -> None:
    with client_with(LlmService([MockProvider()])) as c:
        run_id = finished_run(c, example_source("fib_naive.py"))
        assert c.get("/api/health").json()["llm"]["providers"][0]["name"] == "mock"
        with c.stream("GET", f"/api/mentor/narrate?run_id={run_id}&lang=en") as r:
            text = "".join(r.iter_text())
    events = [line.removeprefix("event: ") for line in text.splitlines() if line.startswith("event: ")]
    assert events[0] == "meta" and events[-1] == "done"
    first_scene = events[1 : events.index("scene_done") + 1]
    assert first_scene[0] == "layer_a" and "token" in first_scene, first_scene
    assert '"source": "llm:mock"' in text and "[mock]" in text


def test_narration_falls_back_to_layer_a_when_every_key_is_exhausted() -> None:
    class Dead(Scripted):
        async def complete(self, messages: list[Message], key: str) -> str:  # pragma: no cover
            raise AssertionError

        async def stream(self, messages: list[Message], key: str):
            from glassbox.llm.base import RateLimited

            raise RateLimited(60)
            yield ""  # pragma: no cover

    with client_with(LlmService([Dead([""])])) as c:
        run_id = finished_run(c, "x = 1\nprint(x)\n")
        with c.stream("GET", f"/api/mentor/narrate?run_id={run_id}") as r:
            text = "".join(r.iter_text())
    assert "event: fallback" in text and "event: layer_a" in text and '"source": "narrator"' in text


def test_crash_narration_names_the_offending_value() -> None:
    with client_with(LlmService([])) as c:
        run_id = finished_run(c, example_source("crash_chain.py"))
        with c.stream("GET", f"/api/mentor/narrate?run_id={run_id}&lang=tr") as r:
            text = "".join(r.iter_text())
    assert "ZeroDivisionError" in text and "`count` = 0" in text


def test_narration_requires_a_finished_run() -> None:
    with client_with(LlmService([])) as c:
        run_id = c.post("/api/runs", json=body("import time\ntime.sleep(5)\n", limits={"timeout_s": 10})).json()["run_id"]
        assert c.get(f"/api/mentor/narrate?run_id={run_id}").status_code == 409
        assert c.get("/api/mentor/narrate?run_id=nope").status_code == 404


@pytest.mark.parametrize("url", ["/api/mentor/refactor", "/api/refactor/verify", "/api/refactor/autofix"])
def test_mentor_posts_validate_their_bodies(url: str) -> None:
    with client_with(LlmService([])) as c:
        assert c.post(url, json={}).status_code == 422
