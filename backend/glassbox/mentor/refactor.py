"""Refactoring proposals: LLM-free autofix where possible, otherwise a validated LLM answer (max 2 retries)."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from ..llm.base import LlmUnavailable
from ..llm.prompts import new_nonce, refactor_messages
from ..llm.service import LlmService
from ..schemas.analysis import Finding
from ..schemas.llm import Edit, LlmRefactorOutput, RefactorProposal
from .autofix import FIXABLE, apply_autofix
from .edits import EditError, apply_edits

MAX_RETRIES = 2
_CLAIM = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(?:x|×|%|kat\b|times\b|ms\b|s\b|sn\b|saniye|seconds?\b|adım|steps?\b)", re.I)


class RefactorError(Exception):
    """User-facing failure (the message says what to do next)."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


def measured_for(finding: Finding, finished: dict[str, Any]) -> dict[str, Any]:
    """The only numbers the LLM may quote: recorded run totals + numeric evidence of this finding."""
    measured: dict[str, Any] = {"total_steps": finished.get("steps"), "finding_line": finding.start_line}
    hits = finished.get("line_hits", {}).get(finding.file, {})
    measured["finding_line_hits"] = hits.get(str(finding.start_line))
    for key, value in finding.evidence.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            measured[key] = value
    return {k: v for k, v in measured.items() if v is not None}


def _allowed_numbers(measured: dict[str, Any]) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", json.dumps(measured)))


def invented_numbers(texts: list[str], measured: dict[str, Any]) -> list[str]:
    """Performance-style claims ('3x', '40%', '12 ms') whose number was not measured."""
    allowed = _allowed_numbers(measured)
    bad: list[str] = []
    for text in texts:
        bad += [m.group(0).strip() for m in _CLAIM.finditer(text) if m.group(1) not in allowed]
    return bad


def _parse_llm_json(text: str) -> LlmRefactorOutput:
    cleaned = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    try:
        return LlmRefactorOutput.model_validate_json(cleaned)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise ValueError(f"the answer is not the required JSON ({where or 'root'}: {first['msg']})") from None


def _autofix_proposal(files: dict[str, str], finding: Finding, lang: str) -> RefactorProposal | None:
    new_files, applied, _ = apply_autofix(files, [finding.id])
    if not applied:
        return None
    edits = [
        Edit(file=path, start_line=1, end_line=max(1, len(files[path].splitlines())), new_code=text)
        for path, text in new_files.items()
        if text != files[path]
    ]
    tr = lang == "tr"
    return RefactorProposal(
        finding_id=finding.id, edits=edits,
        explanation_md=(
            "Bu düzeltme LLM kullanmadan, kural tabanlı olarak üretildi; yalnızca kanıtlanmış ölü kodu siler."
            if tr else "This fix is rule-based (no LLM) and only removes provably dead code."
        ),
        why=finding.title,
        expected_effect=(
            "Daha az kod, davranış değişmez (doğrulanmadı)." if tr else "Less code, same behaviour (not verified yet)."
        ),
        source="autofix", proposed_files=new_files,
    )  # fmt: skip


async def propose(
    llm: LlmService | None,
    files: dict[str, str],
    finding: Finding,
    finished: dict[str, Any],
    lang: str = "tr",
) -> RefactorProposal:
    if finding.category in FIXABLE and finding.autofixable and finding.confidence != "suspect":
        proposal = _autofix_proposal(files, finding, lang)
        if proposal is not None:
            return proposal
    if llm is None or not llm.available:
        raise RefactorError(
            "No LLM provider is available for this finding. Add API keys, models and base URLs to .env "
            "(see .env.example) or pick a finding that can be fixed automatically.",
            status=503,
        )
    measured = measured_for(finding, finished)
    nonce = new_nonce()
    previous: str | None = None
    for attempt in range(1, MAX_RETRIES + 2):
        messages = refactor_messages(finding.model_dump(), files, measured, lang, nonce, previous, attempt)
        try:
            text, _provider = await llm.complete(messages)
        except LlmUnavailable as exc:
            raise RefactorError(f"{exc}. Try again later or use an automatic fix.", status=503) from None
        try:
            out = _parse_llm_json(text)
            proposed = apply_edits(files, out.edits)
            bad = invented_numbers([out.why, out.explanation_md, out.expected_effect], measured)
            if bad:
                raise ValueError(f"it cites numbers that were not measured: {', '.join(bad)}")
        except (ValueError, EditError) as exc:
            previous = str(exc)
            continue
        return RefactorProposal(
            finding_id=finding.id, edits=out.edits, explanation_md=out.explanation_md, why=out.why,
            expected_effect=out.expected_effect, source="llm", proposed_files=proposed,
        )  # fmt: skip
    raise RefactorError(
        f"The LLM did not produce a valid proposal after {MAX_RETRIES + 1} attempts (last problem: {previous}). "
        "Nothing was changed; try again or refactor manually."
    )
