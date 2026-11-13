"""Audit-hook guard (defence in depth; NOT a security boundary, see docs/SECURITY.md)."""

from __future__ import annotations

import os
import sys
from typing import Any

_ALWAYS_BLOCKED = frozenset(
    {
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
        "os.fork",
        "os.forkpty",
        "ctypes.dlopen",
    }
)
_NETWORK = frozenset({"socket.connect", "socket.getaddrinfo", "socket.gethostbyname"})
_PATH_WRITES = frozenset({"os.remove", "os.rmdir", "os.mkdir", "os.rename"})
_WRITE_MODE_CHARS = frozenset("wax+")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
_NULL_DEVICES = frozenset({"nul", "/dev/null", os.devnull.lower()})


def install(work_dir: str, allow_network: bool, blocked: list[dict[str, str]]) -> None:
    """Install the audit hook. ``blocked`` receives one record per denied operation."""
    prefix = os.path.normcase(os.path.realpath(work_dir))
    prefix_sep = prefix if prefix.endswith(os.sep) else prefix + os.sep

    def inside(path: Any) -> bool:
        if isinstance(path, int):
            return True  # an already-open fd was vetted when it was opened
        try:
            raw = os.fsdecode(path)
        except TypeError:
            return False
        if raw.lower() in _NULL_DEVICES:
            return True
        resolved = os.path.normcase(os.path.realpath(raw))
        return resolved == prefix or resolved.startswith(prefix_sep)

    def deny(event: str, detail: str) -> None:
        blocked.append({"event": event, "detail": detail[:200]})
        raise PermissionError(f"GlassBox sandbox: '{event}' is blocked ({detail[:120]})")

    def hook(event: str, args: tuple[Any, ...]) -> None:
        if event in _ALWAYS_BLOCKED:
            deny(event, "process creation and native library loading are not allowed")
        elif event in _NETWORK:
            if not allow_network:
                deny(event, "network access is disabled for this run")
        elif event == "open":
            path, mode, flags = args
            if isinstance(mode, str):
                writes = not _WRITE_MODE_CHARS.isdisjoint(mode)
            else:
                writes = bool(flags & _WRITE_FLAGS) if isinstance(flags, int) else False
            if writes and not inside(path):
                deny(event, f"writing outside the working directory: {os.fsdecode(path) if not isinstance(path, int) else path}")
        elif event in _PATH_WRITES:
            targets = args[:2] if event == "os.rename" else args[:1]
            for target in targets:
                if not inside(target):
                    deny(event, f"modifying a path outside the working directory: {os.fsdecode(target)}")

    sys.addaudithook(hook)
