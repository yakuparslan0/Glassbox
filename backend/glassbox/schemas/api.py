"""HTTP / WebSocket request and response models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceFile(_Model):
    path: str
    content: str


class Limits(_Model):
    max_steps: int | None = Field(default=None, ge=1, le=200_000)
    timeout_s: int | None = Field(default=None, ge=1, le=60)
    memory_mb: int | None = Field(default=None, ge=16, le=4096)
    max_output_kb: int | None = Field(default=None, ge=1, le=4096)


class Override(_Model):
    step: int = Field(ge=0)
    frame_depth: int = Field(ge=0)
    name: str
    value_literal: str


class RunCreate(_Model):
    files: list[SourceFile]
    entry: str = "main.py"
    stdin: str = ""
    seed: int = 0
    filter: Literal["user_only", "boundaries", "boundaries_verbose"] = "boundaries"
    limits: Limits = Field(default_factory=Limits)
    overrides: list[Override] = Field(default_factory=list)
    allow_network: bool = False


class RunCreated(_Model):
    run_id: str


class RunSummary(_Model):
    run_id: str
    state: Literal["running", "finished", "cancelled", "error"]
    entry: str
    events: int
    created_at: float
    run_finished: dict[str, Any] | None = None
    error: str | None = None


class StaticRequest(_Model):
    files: list[SourceFile]
    entry: str = "main.py"


class LlmHealth(_Model):
    providers: list[dict[str, Any]] = Field(default_factory=list)


class Health(_Model):
    status: Literal["ok"]
    llm: LlmHealth
    sandbox_mode: Literal["subprocess", "docker"]


class BigORequest(_Model):
    files: list[SourceFile]
    entry: str = "main.py"
    func: str
    generator: Literal["random_ints", "sorted_ints", "reversed_ints", "int_n", "string_n"] = "random_ints"
    sizes: list[int] | None = Field(default=None, max_length=14)
    extra_args: list[str] = Field(default_factory=list, max_length=4)
    seed: int = 0
