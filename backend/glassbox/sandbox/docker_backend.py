"""Docker sandbox backend: same runner, same NDJSON protocol, inside a locked-down container.

This is the only mode that may be exposed beyond localhost (``GLASSBOX_ALLOW_REMOTE``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from typing import Any

from .subprocess_backend import LaunchSpec, SubprocessBackend

CONTAINER_WORK = "/work"
CONTAINER_CAP = "/cap"
CONTAINER_JOB = "/job/job.json"

# Spec section 5.6, verbatim.
HARDENING_FLAGS = [
    "--read-only", "--tmpfs", "/tmp", "--memory", "512m", "--cpus", "1", "--pids-limit", "64",
    "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534",
]  # fmt: skip


def container_name(spec: LaunchSpec) -> str:
    return f"glassbox-{spec.run_id or os.path.basename(os.path.dirname(spec.job_path))}".replace("_", "-")[:60]


def container_job(spec: LaunchSpec) -> str:
    """Write a copy of job.json whose paths are the container paths; returns the host path of the copy."""
    with open(spec.job_path, encoding="utf-8") as f:
        job: dict[str, Any] = json.load(f)
    job["work_dir"] = CONTAINER_WORK
    job["cap_dir"] = CONTAINER_CAP
    path = os.path.join(os.path.dirname(spec.job_path), "job.container.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(job, f)
    return path


def build_docker_argv(spec: LaunchSpec, image: str, docker_job_path: str) -> list[str]:
    run_dir = os.path.dirname(spec.job_path)
    cap_dir = os.path.join(run_dir, "cap")
    argv = ["docker", "run", "--rm", "--name", container_name(spec)]
    # --network none unless this run explicitly opted in to network access.
    argv += ["--network", "bridge" if spec.allow_network else "none"]
    argv += HARDENING_FLAGS
    argv += ["-e", "PYTHONHASHSEED=0", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "LANG=C.UTF-8", "-e", "PYTHONPATH=/opt/glassbox"]
    argv += ["-v", f"{spec.work_dir}:{CONTAINER_WORK}", "-v", f"{cap_dir}:{CONTAINER_CAP}"]
    argv += ["-v", f"{docker_job_path}:{CONTAINER_JOB}:ro", "-w", CONTAINER_WORK, image]
    argv += ["python", "-s", "-P", "-X", "utf8", "-m", "glassbox.runner", CONTAINER_JOB]
    return argv


class DockerBackend(SubprocessBackend):
    # The container runs as uid 65534, so the bind-mounted run directories must be writable by it.
    open_dirs = True

    def __init__(self, image: str = "glassbox-runner") -> None:
        self.image = image

    def argv(self, spec: LaunchSpec) -> list[str]:
        docker_job = container_job(spec)
        return build_docker_argv(spec, self.image, docker_job)

    def env(self, spec: LaunchSpec) -> dict[str, str]:
        # The docker CLI needs the host environment (PATH, DOCKER_HOST ...); the CONTAINER gets a scrubbed one
        # because only the -e flags above reach it.
        return dict(os.environ)

    async def kill(self, proc: asyncio.subprocess.Process, spec: LaunchSpec) -> None:
        killer = await asyncio.create_subprocess_exec(
            "docker", "kill", container_name(spec),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
        with contextlib.suppress(Exception):
            await asyncio.wait_for(killer.wait(), 10)
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
