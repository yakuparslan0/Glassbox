"""Mentor / refactor / LLM request and response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .api import SourceFile


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Edit(_Model):
    """Replace lines start_line..end_line (1-based, inclusive) of ``file`` by ``new_code`` (empty = delete)."""

    file: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    new_code: str = Field(max_length=20_000)


class LlmRefactorOutput(_Model):
    """The JSON contract the LLM must follow (NOT a unified diff)."""

    edits: list[Edit] = Field(min_length=1, max_length=10)
    why: str = Field(min_length=1, max_length=2000)
    explanation_md: str = Field(min_length=1, max_length=6000)
    expected_effect: str = Field(min_length=1, max_length=1000)


class RefactorProposal(_Model):
    finding_id: str
    edits: list[Edit]
    explanation_md: str
    why: str
    expected_effect: str
    source: Literal["autofix", "llm"]
    # Server-computed result of applying ``edits`` (so clients need no edit engine). Never auto-applied.
    proposed_files: dict[str, str]
    # The effect is a claim until a VerificationReport confirms it.
    verified: bool = False


class RefactorRequest(_Model):
    run_id: str
    finding_id: str


class AutofixRequest(_Model):
    files: list[SourceFile]
    finding_ids: list[str] = Field(max_length=200)
    entry: str = "main.py"


class AutofixResult(_Model):
    files: list[SourceFile]
    applied: list[str]
    skipped: list[dict[str, str]]


class VerifyRequest(_Model):
    original_files: list[SourceFile]
    proposed_files: list[SourceFile]
    entry: str = "main.py"
    stdin: str = ""
    seed: int = 0


class TimeStats(_Model):
    median: float
    min: float
    max: float


class VerificationReport(_Model):
    parses: bool
    behavior_equal: bool
    diffs: list[str]
    steps_before: int | None
    steps_after: int | None
    time_before_ms: TimeStats | None
    time_after_ms: TimeStats | None
    speedup: float | None
    verdict: Literal["verified_faster", "verified_equal", "no_measurable_change", "behavior_changed", "broken"]
