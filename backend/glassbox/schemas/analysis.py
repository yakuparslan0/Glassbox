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


# ------------------------------------------------------------------ Root-Cause Rewind (Phase 5)
class CausalLink(_Model):
    step: int
    frame: int
    file: str
    line: int
    kind: Literal["error", "assignment", "argument", "global", "return"]
    name: str
    value: str | None
    depth: int
    text: str


class CausalChain(_Model):
    exception_type: str
    message: str
    step: int
    links: list[CausalLink]  # ascending by step: origin first, the failing line last
    truncated: bool


# ------------------------------------------------------------------ What-If branches
class RunSide(_Model):
    steps: int
    status: str
    stdout: str
    returns: list[str]  # return values of the entry's top-level calls, in order
    exception: str | None


class BranchComparison(_Model):
    base_run_id: str
    branch_run_id: str
    first_divergence_step: int | None
    base: RunSide
    branch: RunSide
    output_equal: bool
    summary: list[str]


# ------------------------------------------------------------------ Big-O laboratory
class BigOPoint(_Model):
    n: int
    steps: int


class BigOFit(_Model):
    model: Literal["1", "log n", "n", "n log n", "n^2", "n^3", "2^n"]
    label: str
    r2: float
    a: float
    b: float
    predicted: list[float]


class StaticEstimate(_Model):
    model: str | None
    label: str
    basis: str


class BigOReport(_Model):
    func: str
    generator: str
    points: list[BigOPoint]
    best: BigOFit
    runner_up: BigOFit | None
    fits: list[BigOFit]
    static: StaticEstimate
    conflict: bool
    note: str
    stopped_early: str | None
