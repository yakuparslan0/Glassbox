"""Subprocess sandbox backend: spawn the runner, stream its NDJSON events, enforce the wall-clock watchdog.

NOT a security boundary (see docs/SECURITY.md): it protects against runaway resource use and accidents.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

_STDERR_TAIL = 8 * 1024


@dataclass(frozen=True)
class LaunchSpec:
    job_path: str
    work_dir: str
    timeout_s: float
    run_id: str = ""
    allow_network: bool = False


def build_env() -> dict[str, str]:
    """Environment for the runner, built FROM SCRATCH: nothing of the parent's environment leaks."""
    env = {"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}
    if sys.platform == "win32":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return env


def build_argv(job_path: str) -> list[str]:
    # NEVER "-I": it would make the interpreter ignore PYTHONHASHSEED (determinism, spec 2.8).
    return [sys.executable, "-s", "-P", "-X", "utf8", "-m", "glassbox.runner", job_path]


async def kill_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the runner and everything it started (process group on POSIX, process tree on Windows)."""
    pid = proc.pid
    if sys.platform == "win32":
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/PID", str(pid), "/T", "/F",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
        await killer.wait()
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError):
        proc.kill()


class SubprocessBackend:
    """Runs the runner as a local child process. ``DockerBackend`` overrides the three hooks below."""

    open_dirs = False

    def argv(self, spec: LaunchSpec) -> list[str]:
        return build_argv(spec.job_path)

    def env(self, spec: LaunchSpec) -> dict[str, str]:
        return build_env()

    async def kill(self, proc: asyncio.subprocess.Process, spec: LaunchSpec) -> None:
        await kill_tree(proc)

    async def execute(self, spec: LaunchSpec) -> AsyncIterator[dict[str, Any]]:
        started = time.monotonic()
        popen_kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            popen_kwargs["start_new_session"] = True
        proc = await asyncio.create_subprocess_exec(
            *self.argv(spec),
            cwd=spec.work_dir,
            env=self.env(spec),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=2**20,
            **popen_kwargs,
        )
        loop = asyncio.get_running_loop()
        state = {"timed_out": False}
        kill_tasks: list[asyncio.Task[None]] = []

        def on_timeout() -> None:
            state["timed_out"] = True
            kill_tasks.append(loop.create_task(self.kill(proc, spec)))

        # The watchdog is independent of the event stream: it fires even if the runner is silent.
        watchdog = loop.call_later(spec.timeout_s, on_timeout)
        stderr_task = loop.create_task(self._drain_stderr(proc))
        last_seq = last_t = last_step = 0
        finished = False
        try:
            assert proc.stdout is not None
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue  # cannot happen through the dup'ed fd; ignore defensively
                last_seq = event.get("seq", last_seq)
                last_t = event.get("t", last_t)
                last_step = event.get("step", last_step)
                if event.get("type") == "run_finished":
                    finished = True
                yield event
            await proc.wait()
            stderr_tail = await stderr_task
            if not finished:
                wall_ms = int((time.monotonic() - started) * 1000)
                for event in self._synthesize(
                    state["timed_out"], spec.timeout_s, proc.returncode, stderr_tail, last_seq, last_t, last_step, wall_ms
                ):
                    yield event
        finally:
            watchdog.cancel()
            if proc.returncode is None:
                await self.kill(proc, spec)
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), 5)
            for task in kill_tasks:
                with contextlib.suppress(Exception):
                    await task
            stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await stderr_task

    @staticmethod
    async def _drain_stderr(proc: asyncio.subprocess.Process) -> str:
        assert proc.stderr is not None
        tail = b""
        while True:
            chunk = await proc.stderr.read(4096)
            if not chunk:
                break
            tail = (tail + chunk)[-_STDERR_TAIL:]
        return tail.decode("utf-8", "replace")

    @staticmethod
    def _synthesize(
        timed_out: bool,
        timeout_s: float,
        returncode: int | None,
        stderr_tail: str,
        seq: int,
        t: int,
        step: int,
        wall_ms: int,
    ) -> list[dict[str, Any]]:
        """The runner died without run_finished (killed by the watchdog or crashed): report it."""
        events: list[dict[str, Any]] = []

        def add(typ: str, **fields: Any) -> None:
            nonlocal seq
            seq += 1
            events.append({"v": 1, "seq": seq, "t": t, "type": typ, **fields})

        if timed_out:
            add("limit_exceeded", step=step, limit="timeout", detail=f"wall-clock timeout of {timeout_s:g} s; process killed")
            detail = f"killed after the {timeout_s:g} s wall-clock timeout"
        else:
            detail = f"runner exited unexpectedly with code {returncode}"
            if stderr_tail.strip():
                add("output", step=step, stream="stderr", text=stderr_tail[-2000:])
        add(
            "run_finished", status="killed", exit_code=returncode if returncode is not None else -1, steps=step,
            wall_ms=wall_ms, line_hits={}, func_stats={}, executed_lines={}, repeat_calls=[], detail=detail,
        )  # fmt: skip
        return events
