"""Run event schema: the single source of truth for runner -> API -> browser events.

The runner itself is stdlib-only and emits plain dicts; the API process validates them
against these models. See docs/EVENT_SCHEMA.md for semantics.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- values
class Prim(_Strict):
    k: Literal["prim"] = "prim"
    t: str
    r: str
    trunc: bool | None = None


class Ref(_Strict):
    ref: str


class OtherValue(_Strict):
    k: Literal["func", "module", "other"]
    t: str
    r: str
    trunc: bool | None = None


Value = Prim | Ref | OtherValue


class SeqEntry(_Strict):
    k: Literal["seq"] = "seq"
    t: str
    len: int
    items: list[Value]
    trunc: bool = False
    size: int | None = None


class MapEntry(_Strict):
    k: Literal["map"] = "map"
    t: str
    len: int
    pairs: list[tuple[Value, Value]]
    trunc: bool = False
    size: int | None = None


class ObjEntry(_Strict):
    k: Literal["obj"] = "obj"
    t: str
    attrs: dict[str, Value]
    trunc: bool = False


HeapEntry = Annotated[SeqEntry | MapEntry | ObjEntry | OtherValue, Field(discriminator="k")]
Heap = dict[str, HeapEntry]


class Delta(_Strict):
    set: dict[str, Value] = Field(default_factory=dict)
    del_: list[str] = Field(default_factory=list, alias="del")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------- events
class _Event(_Strict):
    v: Literal[1] = 1
    seq: int
    t: int
    # Set when the runner had to drop heap/delta content to respect the 64 KB per-event limit.
    trunc: bool | None = None


class Capabilities(_Strict):
    whatif: bool
    threads: bool
    asyncio: bool
    rlimit: bool


class RunStarted(_Event):
    type: Literal["run_started"] = "run_started"
    python: str
    tracer: Literal["monitoring", "settrace", "profile_time", "profile_memory"]
    seed: int
    limits: dict[str, int]
    filter: Literal["user_only", "boundaries", "boundaries_verbose"]
    capabilities: Capabilities


class ImportEvent(_Event):
    type: Literal["import"] = "import"
    step: int
    module: str
    lib: Literal["user", "stdlib", "third_party"]


class CallUser(_Event):
    type: Literal["call"] = "call"
    step: int
    frame: int
    parent: int | None
    kind: Literal["user"] = "user"
    func: str
    qualname: str
    file: str
    line: int
    call_line: int | None
    args: dict[str, Value]
    globals_delta: Delta | None = None
    heap: Heap = Field(default_factory=dict)
    generator: bool | None = None


class CallBoundary(_Event):
    type: Literal["call"] = "call"
    step: int
    frame: int
    parent: int | None
    kind: Literal["boundary"] = "boundary"
    lib: Literal["stdlib", "third_party"]
    module: str
    func: str
    call_line: int | None
    args_summary: str | None = None
    args: dict[str, Value] | None = None
    globals_delta: Delta | None = None
    heap: Heap | None = None


class LineEvent(_Event):
    type: Literal["line"] = "line"
    step: int
    frame: int
    line: int
    delta: Delta
    globals_delta: Delta | None = None
    heap: Heap | None = None


class ReturnUser(_Event):
    type: Literal["return"] = "return"
    step: int
    frame: int
    kind: Literal["user"] | None = None
    value: Value
    dur_ns: int
    # True when the frame left through an exception (value is then None).
    unwound: bool | None = None
    globals_delta: Delta | None = None
    heap: Heap | None = None


class ReturnBoundary(_Event):
    type: Literal["return"] = "return"
    step: int
    frame: int
    kind: Literal["boundary"]
    value_summary: str | None = None
    dur_ns: int
    raised: bool | None = None
    synthetic: bool | None = None
    globals_delta: Delta | None = None
    heap: Heap | None = None


class ExceptionEvent(_Event):
    type: Literal["exception"] = "exception"
    step: int
    frame: int
    line: int
    exc_type: str
    message: str
    handled: bool
    globals_delta: Delta | None = None
    heap: Heap | None = None


class OutputEvent(_Event):
    type: Literal["output"] = "output"
    step: int
    stream: Literal["stdout", "stderr"]
    text: str


class StackFrame(_Strict):
    frame: int
    func: str
    line: int
    locals: dict[str, Value]


class Keyframe(_Event):
    type: Literal["keyframe"] = "keyframe"
    step: int
    stack: list[StackFrame]
    globals: dict[str, Value]
    heap: Heap


class SnapshotFrame(_Strict):
    frame: int
    func: str
    line: int


class Snapshot(_Event):
    """Debug-only (job.full_snapshots): ground truth taken from the live frames after a step."""

    type: Literal["snapshot"] = "snapshot"
    step: int
    stack: list[SnapshotFrame]
    frame: int | None
    locals: dict[str, Value] | None
    globals: dict[str, Value]
    heap: Heap


class WhatIfApplied(_Event):
    type: Literal["whatif_applied"] = "whatif_applied"
    step: int
    frame: int
    name: str
    old: Value | None
    new: Value
    heap: Heap | None = None


class LimitExceeded(_Event):
    type: Literal["limit_exceeded"] = "limit_exceeded"
    step: int
    limit: Literal["max_steps", "timeout", "memory", "output", "event_bytes"]
    detail: str


class RepeatCall(_Strict):
    func: str
    args_fp: str
    count: int


class FuncStat(_Strict):
    calls: int
    steps: int
    self_ns: int
    total_ns: int


class RunFinished(_Event):
    type: Literal["run_finished"] = "run_finished"
    status: Literal["ok", "exception", "limit", "killed", "blocked"]
    exit_code: int
    steps: int
    wall_ms: int
    line_hits: dict[str, dict[str, int]]
    func_stats: dict[str, FuncStat]
    executed_lines: dict[str, list[int]]
    repeat_calls: list[RepeatCall]
    detail: str | None = None
    blocked: list[dict[str, str]] | None = None
    whatif_unapplied: int | None = None
    # Only in untraced profile passes (job.profile): {"kind": "time"|"memory", ...}.
    profile: dict[str, Any] | None = None


# call/return share a discriminator value, so validation goes through a callable discriminator.
RunEvent = Annotated[
        RunStarted
        | ImportEvent
        | LineEvent
        | ExceptionEvent
        | OutputEvent
        | Keyframe
        | Snapshot
        | WhatIfApplied
        | LimitExceeded
        | RunFinished
        | CallUser
        | CallBoundary
        | ReturnUser
        | ReturnBoundary,
        Field(union_mode="left_to_right"),
    ]
EVENT_ADAPTER: TypeAdapter[Any] = TypeAdapter(RunEvent)


def validate_event(raw: dict[str, Any]) -> Any:
    """Validate one runner event dict against the schema (raises pydantic.ValidationError)."""
    return EVENT_ADAPTER.validate_python(raw)
