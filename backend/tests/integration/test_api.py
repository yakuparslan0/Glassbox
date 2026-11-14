"""API, WebSocket streaming, limits and startup-guard tests (real runner subprocesses, real ASGI app)."""

from __future__ import annotations

import glob
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import example_source

from glassbox.api.app import create_app
from glassbox.config import Settings, StartupError
from glassbox.sandbox.docker_backend import HARDENING_FLAGS, build_docker_argv
from glassbox.sandbox.subprocess_backend import LaunchSpec

ROOT = Path(__file__).resolve().parents[3]


def make_client(**overrides: Any) -> TestClient:
    settings = Settings(_env_file=None, validate_events="strict", **overrides)
    return TestClient(create_app(settings))


@pytest.fixture
def client():
    with make_client() as c:
        yield c


def body(source: str, **extra: Any) -> dict[str, Any]:
    return {"files": [{"path": "main.py", "content": source}], "entry": "main.py", **extra}


def wait_done(client: TestClient, run_id: str, timeout: float = 30) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        summary = client.get(f"/api/runs/{run_id}").json()
        if summary["state"] != "running":
            return summary
        time.sleep(0.05)
    raise AssertionError("run did not finish in time")


def collect(ws, until_close: bool = True) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while True:
        try:
            message = ws.receive_json()
        except Exception:  # server closed the socket after run_finished
            return events
        events.extend(message["batch"])


# ------------------------------------------------------------------------------------------ basics
def test_health_and_run_summary(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok", "llm": {"providers": []}, "sandbox_mode": "subprocess"}
    run_id = client.post("/api/runs", json=body("print('hi')\n")).json()["run_id"]
    summary = wait_done(client, run_id)
    assert summary["state"] == "finished" and summary["run_finished"]["status"] == "ok"
    trace = client.get(f"/api/runs/{run_id}/trace")
    lines = [json.loads(line) for line in trace.text.splitlines()]
    assert [e["seq"] for e in lines] == list(range(1, len(lines) + 1))
    assert lines[-1]["type"] == "run_finished"


def test_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/api/runs/deadbeef").status_code == 404
    assert client.get("/api/runs/deadbeef/marksweep").status_code == 404


def test_static_endpoint_reports_dead_code(client: TestClient) -> None:
    r = client.post("/api/analysis/static", json=body(example_source("dead_code_zoo.py")))
    assert r.status_code == 200
    cats = {f["category"] for f in r.json()["findings"]}
    assert {"unused_import", "uncalled_function", "unreachable_code", "duplicate_block"} <= cats
    assert r.json()["functions"]


def test_static_endpoint_syntax_error_is_422(client: TestClient) -> None:
    r = client.post("/api/analysis/static", json=body("def (:\n"))
    assert r.status_code == 422 and "syntax error on line 1" in r.json()["detail"]


def test_marksweep_and_profile_endpoints(client: TestClient) -> None:
    run_id = client.post("/api/runs", json=body(example_source("fib_naive.py"))).json()["run_id"]
    wait_done(client, run_id)
    ms = client.get(f"/api/runs/{run_id}/marksweep").json()
    assert ms["run_status"] == "ok" and any(f["category"] == "repeated_computation" for f in ms["findings"])
    prof = client.post(f"/api/runs/{run_id}/profile").json()
    assert prof["time_pass"]["status"] == "ok" and any(f["func"] == "fib" for f in prof["functions"])


def test_marksweep_before_the_run_finished_is_409(client: TestClient) -> None:
    run_id = client.post("/api/runs", json=body("import time\ntime.sleep(5)\n", limits={"timeout_s": 10})).json()["run_id"]
    assert client.get(f"/api/runs/{run_id}/marksweep").status_code == 409
    assert client.get(f"/api/runs/{run_id}/trace").status_code == 409


# ------------------------------------------------------------------------------------------ limits
def test_path_traversal_and_absolute_paths_are_rejected(client: TestClient) -> None:
    for bad in ("../evil.py", "/etc/passwd", "C:/x.py", "a\\b.py"):
        payload = {"files": [{"path": "main.py", "content": "x=1"}, {"path": bad, "content": "x=1"}], "entry": "main.py"}
        r = client.post("/api/runs", json=payload)
        assert r.status_code == 422, bad
    assert client.post("/api/runs", json=body("x=1", entry="missing.py")).status_code == 422


def test_source_size_and_file_count_limits_are_413(client: TestClient) -> None:
    assert client.post("/api/runs", json=body("#" * (201 * 1024))).status_code == 413
    many = {"files": [{"path": f"f{i}.py", "content": "x=1"} for i in range(21)], "entry": "f0.py"}
    assert client.post("/api/runs", json=many).status_code == 413


def test_concurrency_limit_is_429_and_slot_is_released() -> None:
    with make_client(max_concurrent_runs=1) as c:
        slow = c.post("/api/runs", json=body("import time\ntime.sleep(30)\n", limits={"timeout_s": 30})).json()["run_id"]
        busy = c.post("/api/runs", json=body("x=1"))
        assert busy.status_code == 429 and busy.headers["retry-after"] == "1"
        with c.websocket_connect(f"/ws/runs/{slow}") as ws:
            ws.send_json({"cmd": "cancel"})
        assert wait_done(c, slow)["state"] == "cancelled"
        assert c.post("/api/runs", json=body("x=1")).status_code == 201


def test_invalid_limits_are_rejected(client: TestClient) -> None:
    assert client.post("/api/runs", json=body("x=1", limits={"max_steps": 0})).status_code == 422


# ------------------------------------------------------------------------------------------ websocket
LONG_LOOP = "total = 0\nfor i in range(30000):\n    total += i\n"


def test_websocket_streams_20000_steps_complete_and_ordered(client: TestClient) -> None:
    run_id = client.post("/api/runs", json=body(LONG_LOOP)).json()["run_id"]
    with client.websocket_connect(f"/ws/runs/{run_id}") as ws:
        events = collect(ws)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1)), "seq must be gap-free"
    assert events[-1]["type"] == "run_finished" and events[-1]["status"] == "limit"
    assert events[-1]["steps"] == 20000
    assert any(e["type"] == "limit_exceeded" and e["limit"] == "max_steps" for e in events)


def test_batches_are_bounded_and_a_slow_client_does_not_stall_the_run(client: TestClient) -> None:
    run_id = client.post("/api/runs", json=body(LONG_LOOP)).json()["run_id"]
    with client.websocket_connect(f"/ws/runs/{run_id}") as ws:
        first = ws.receive_json()["batch"]
        time.sleep(1.5)  # stalled consumer
        assert wait_done(client, run_id, timeout=0.1)["state"] in ("finished", "running")
        rest = collect(ws)
    events = first + rest
    assert len(first) <= 200
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert events[-1]["type"] == "run_finished"


def test_reconnect_with_from_seq_loses_no_events(client: TestClient) -> None:
    run_id = client.post("/api/runs", json=body(LONG_LOOP)).json()["run_id"]
    with client.websocket_connect(f"/ws/runs/{run_id}") as ws:
        got = ws.receive_json()["batch"] + ws.receive_json()["batch"]
    last = got[-1]["seq"]
    with client.websocket_connect(f"/ws/runs/{run_id}?from_seq={last}") as ws:
        rest = collect(ws)
    events = got + rest
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert events[-1]["type"] == "run_finished"


def test_from_seq_beyond_the_end_yields_nothing_new(client: TestClient) -> None:
    run_id = client.post("/api/runs", json=body("x=1\n")).json()["run_id"]
    wait_done(client, run_id)
    with client.websocket_connect(f"/ws/runs/{run_id}?from_seq=100000") as ws:
        assert collect(ws) == []


def test_cancel_kills_the_run_and_cleans_up() -> None:
    before = set(glob.glob(str(Path(tempfile.gettempdir()) / "glassbox-run-*")))
    with make_client() as c:
        run_id = c.post("/api/runs", json=body("import time\ntime.sleep(999)\n", limits={"timeout_s": 60})).json()["run_id"]
        started = time.time()
        with c.websocket_connect(f"/ws/runs/{run_id}") as ws:
            ws.receive_json()
            ws.send_json({"cmd": "cancel"})
            events = collect(ws)
        summary = wait_done(c, run_id, timeout=15)
        assert time.time() - started < 15, "cancel must not wait for the 60 s timeout"
    assert summary["state"] == "cancelled"
    assert events[-1]["type"] == "run_finished" and events[-1]["status"] == "killed"
    deadline = time.time() + 10
    while time.time() < deadline and set(glob.glob(str(Path(tempfile.gettempdir()) / "glassbox-run-*"))) - before:
        time.sleep(0.2)
    assert not set(glob.glob(str(Path(tempfile.gettempdir()) / "glassbox-run-*"))) - before, "run directory leaked"


def test_websocket_rejects_unknown_run_and_foreign_origin(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as unknown, client.websocket_connect("/ws/runs/nope"):
        pass
    assert unknown.value.code == 4404
    run_id = client.post("/api/runs", json=body("x=1")).json()["run_id"]
    with pytest.raises(WebSocketDisconnect) as foreign, client.websocket_connect(
        f"/ws/runs/{run_id}", headers={"origin": "http://evil.example"}
    ):
        pass
    assert foreign.value.code == 4403


def test_run_store_evicts_oldest_finished_runs() -> None:
    with make_client(run_store_size=2) as c:
        ids = []
        for _ in range(3):
            ids.append(c.post("/api/runs", json=body("x=1\n")).json()["run_id"])
            wait_done(c, ids[-1])
        assert c.get(f"/api/runs/{ids[0]}").status_code == 404
        assert c.get(f"/api/runs/{ids[2]}").status_code == 200


def test_runs_dir_persists_ndjson_and_serves_it_after_eviction(tmp_path: Path) -> None:
    with make_client(run_store_size=1, runs_dir=str(tmp_path)) as c:
        first = c.post("/api/runs", json=body("print(1)\n")).json()["run_id"]
        wait_done(c, first)
        second = c.post("/api/runs", json=body("print(2)\n")).json()["run_id"]
        wait_done(c, second)
        assert c.get(f"/api/runs/{first}").status_code == 404
        evicted_trace = c.get(f"/api/runs/{first}/trace")
        assert evicted_trace.status_code == 200
        assert json.loads(evicted_trace.text.splitlines()[-1])["type"] == "run_finished"
        assert c.get("/api/runs/..%2f..%2fetc/trace").status_code == 404


# ------------------------------------------------------------------------------------------ startup guard
def test_remote_access_without_docker_refuses_to_start() -> None:
    with pytest.raises(StartupError, match="SANDBOX_MODE=docker"):
        create_app(Settings(_env_file=None, allow_remote=True, sandbox_mode="subprocess"))
    create_app(Settings(_env_file=None, allow_remote=True, sandbox_mode="docker"))  # allowed (not started)


def test_cli_serve_refuses_unsafe_config() -> None:
    env = {"PATH": "", "SYSTEMROOT": "C:\\Windows", "GLASSBOX_ALLOW_REMOTE": "true", "SANDBOX_MODE": "subprocess"}
    proc = subprocess.run(
        [sys.executable, "-m", "glassbox.cli", "serve"], env=env, capture_output=True, text=True, timeout=60, check=False
    )
    assert proc.returncode == 2 and "SANDBOX_MODE=docker" in proc.stderr


# ------------------------------------------------------------------------------------------ docker + schema
def test_docker_command_carries_every_hardening_flag() -> None:
    spec = LaunchSpec("/tmp/r/job.json", "/tmp/r/work", 10, run_id="abc")
    argv = build_docker_argv(spec, "glassbox-runner", "/tmp/r/job.container.json")
    joined = " ".join(argv)
    for flag in ("--network none", "--read-only", "--tmpfs /tmp", "--memory 512m", "--cpus 1", "--pids-limit 64",
                 "--cap-drop ALL", "--security-opt no-new-privileges", "--user 65534:65534"):  # fmt: skip
        assert flag in joined, flag
    assert HARDENING_FLAGS[0] == "--read-only"
    assert argv[-8:-1] == ["python", "-s", "-P", "-X", "utf8", "-m", "glassbox.runner"]
    assert "--network bridge" in " ".join(build_docker_argv(LaunchSpec("/t/job.json", "/t/work", 10, "x", True), "i", "j"))


def test_generated_schema_files_are_up_to_date() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_types.py"), "--check"], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
