"""Analysis result models (findings, static / mark & sweep / profile reports)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal[
    "unused_import",
    "unused_variable",
    "uncalled_function",
    "unreachable_code",
    "duplicate_block",
    "cold_code",
    "hot_loop",
    "repeated_computation",
    "loop_invariant",
    "high_memory",
    "mutable_default",
    "alias_mutation",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Finding(_Model):
    id: str
    category: Category
    severity: Literal["info", "warn", "high"]
    confidence: Literal["confirmed", "likely", "suspect"]
    file: str
    start_line: int
    end_line: int
    title: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    autofixable: bool = False


class FunctionComplexity(_Model):
    file: str
    qualname: str
    start_line: int
    end_line: int
    cyclomatic: int
    max_loop_depth: int


class StaticReport(_Model):
    findings: list[Finding]
    functions: list[FunctionComplexity]


class MarkSweepSummary(_Model):
    confirmed_dead: int
    cold: int
    suspect: int
    reclaimable_lines: int


class MarkSweepReport(_Model):
    """Static + dynamic findings of one run. ``steps`` / ``line_hits`` come from the traced run."""

    run_status: str
    steps: int
    findings: list[Finding]
    functions: list[FunctionComplexity]
    summary: MarkSweepSummary


class ProfileFunc(_Model):
    func: str
    file: str
    line: int
    calls: int
    self_ms: float
    total_ms: float


class MemoryLine(_Model):
    file: str
    line: int
    size_kb: float
    count: int


class ProfilePass(_Model):
    status: str
    wall_ms: int


class ProfileReport(_Model):
    """Untraced profile passes: real timings (cProfile) and memory (tracemalloc), measured separately."""

    time_pass: ProfilePass
    memory_pass: ProfilePass
    functions: list[ProfileFunc]
    memory_peak_kb: float
    memory_top_lines: list[MemoryLine]
    findings: list[Finding]
    notes: list[str]
