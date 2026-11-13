"""Runner-side limits and OS resource limits (POSIX only)."""

from __future__ import annotations

from typing import Any

MAX_EVENT_BYTES = 64 * 1024
MAX_TOTAL_EVENT_BYTES = 50 * 1024 * 1024
DEFAULTS: dict[str, int] = {
    "max_steps": 20000,
    "timeout_s": 10,
    "memory_mb": 512,
    "max_output_kb": 256,
}


def effective_limits(requested: dict[str, Any] | None) -> dict[str, int]:
    limits = dict(DEFAULTS)
    for key, value in (requested or {}).items():
        if key in DEFAULTS and value is not None:
            limits[key] = int(value)
    return limits


def apply_rlimits(limits: dict[str, int]) -> bool:
    """Apply RLIMIT_CPU/AS/FSIZE/NOFILE. Returns False where the platform has no `resource` (Windows)."""
    try:
        import resource  # POSIX only
    except ImportError:
        return False
    mb = 1024 * 1024
    wanted = (
        ("RLIMIT_CPU", limits["timeout_s"] + 2),
        ("RLIMIT_AS", limits["memory_mb"] * mb),
        ("RLIMIT_FSIZE", max(16 * mb, limits["max_output_kb"] * 1024 * 8)),
        ("RLIMIT_NOFILE", 256),
    )
    applied = False
    for name, value in wanted:
        const = getattr(resource, name, None)
        if const is None:
            continue
        try:
            _soft, hard = resource.getrlimit(const)
            new = value if hard == resource.RLIM_INFINITY else min(value, hard)
            resource.setrlimit(const, (new, hard))
            applied = True
        except (ValueError, OSError):
            continue
    return applied
