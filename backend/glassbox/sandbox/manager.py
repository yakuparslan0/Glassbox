"""Sandbox manager: per-run temp directory, job file, backend dispatch and cleanup."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from .subprocess_backend import LaunchSpec, SubprocessBackend

DEFAULT_TIMEOUT_S = 10


@dataclass
class RunRequest:
    """One run. ``files`` maps relative POSIX paths to source text."""

    files: dict[str, str]
    entry: str = "main.py"
    stdin: str = ""
    seed: int = 0
    filter: str = "boundaries"  # user_only | boundaries | boundaries_verbose
    limits: dict[str, int] = field(default_factory=dict)
    overrides: list[dict[str, Any]] = field(default_factory=list)
    allow_network: bool = False
    tracer: str = "monitoring"  # monitoring | settrace
    keyframe_interval: int = 200
    full_snapshots: bool = False  # debug: emit ground-truth `snapshot` events
    profile: str | None = None  # None | "time" | "memory": untraced measurement pass (no tracer)


def validate_files(files: dict[str, str], entry: str) -> None:
    """Reject path traversal / absolute paths and a missing entry file (raises ValueError)."""
    if entry not in files:
        raise ValueError(f"entry file {entry!r} is not part of the submitted files")
    for name in files:
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
            raise ValueError(f"illegal file path {name!r}: only relative paths inside the project are allowed")


def _remove_tree(path: str) -> None:
    # Windows may keep handles around for a moment after the process died; retry briefly.
    for _ in range(10):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return
        import time

        time.sleep(0.1)


class SandboxManager:
    """Runs requests in the subprocess backend (default) or any backend with the same ``execute`` shape."""

    def __init__(self, keep_run_dirs: bool = False, backend: SubprocessBackend | None = None) -> None:
        self._backend = backend or SubprocessBackend()
        self._keep = keep_run_dirs

    async def run(self, request: RunRequest) -> AsyncIterator[dict[str, Any]]:
        """Async generator of runner events. Closing it early kills the run and removes its directory."""
        validate_files(request.files, request.entry)
        run_dir = tempfile.mkdtemp(prefix="glassbox-run-")
        work_dir = os.path.join(run_dir, "work")
        cap_dir = os.path.join(run_dir, "cap")
        os.makedirs(work_dir)
        os.makedirs(cap_dir)
        if self._backend.open_dirs and os.name == "posix":
            os.chmod(run_dir, 0o755)
            os.chmod(work_dir, 0o777)
            os.chmod(cap_dir, 0o777)
        try:
            for name, content in request.files.items():
                target = os.path.join(work_dir, *PurePosixPath(name).parts)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "w", encoding="utf-8", newline="") as f:
                    f.write(content)
            job = {
                "work_dir": work_dir,
                "cap_dir": cap_dir,
                "entry": request.entry,
                "stdin": request.stdin,
                "seed": request.seed,
                "filter": request.filter,
                "limits": request.limits,
                "overrides": request.overrides,
                "allow_network": request.allow_network,
                "tracer": request.tracer,
                "keyframe_interval": request.keyframe_interval,
                "full_snapshots": request.full_snapshots,
                "profile": request.profile,
            }
            job_path = os.path.join(run_dir, "job.json")  # outside the cwd: user code cannot read/alter it
            with open(job_path, "w", encoding="utf-8") as f:
                json.dump(job, f)
            timeout = float(request.limits.get("timeout_s", DEFAULT_TIMEOUT_S))
            async for event in self._backend.execute(LaunchSpec(job_path, work_dir, timeout, os.path.basename(run_dir), request.allow_network)):
                yield event
        finally:
            if not self._keep:
                await asyncio.to_thread(_remove_tree, run_dir)
