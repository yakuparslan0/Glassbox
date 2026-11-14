"""Mentor routes: SSE narration, refactoring proposals, verification and LLM-free autofix."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..analysis import marksweep
from ..analysis.common import SourceError
from ..llm.base import LlmUnavailable
from ..llm.prompts import new_nonce, scene_messages
from ..mentor import narrator
from ..mentor.autofix import apply_autofix
from ..mentor.digest import build_scenes
from ..mentor.refactor import RefactorError, propose
from ..mentor.verify import verify
from ..schemas.analysis import MarkSweepReport
from ..schemas.api import SourceFile
from ..schemas.llm import (
    AutofixRequest,
    AutofixResult,
    RefactorProposal,
    RefactorRequest,
    VerificationReport,
    VerifyRequest,
)
from .deps import get_record, runtime, validated_files
from .store import RunRecord, Runtime

router = APIRouter()
Lang = Literal["tr", "en"]


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _report(rt: Runtime, record: RunRecord) -> MarkSweepReport:
    if not record.done:
        raise HTTPException(409, "the run is still in progress; wait until it has finished")
    if record.marksweep is None:
        try:
            record.marksweep = await asyncio.to_thread(
                marksweep.build, record.request.files, record.request.entry, record.events
            )
        except SourceError as exc:
            raise HTTPException(422, str(exc)) from exc
    return record.marksweep


@router.get("/api/mentor/narrate")
async def narrate(
    run_id: str,
    from_step: int | None = Query(None, ge=1),
    to_step: int | None = Query(None, ge=1),
    lang: Lang = "tr",
    llm: bool = True,
    rt: Runtime = Depends(runtime),
) -> StreamingResponse:
    """SSE. Per scene: ``layer_a`` (instant, deterministic) then optional ``token`` events (LLM) and ``scene_done``."""
    record = get_record(rt, run_id)
    if not record.done:
        raise HTTPException(409, "the run is still in progress; narration needs the finished trace")
    scenes = await asyncio.to_thread(build_scenes, record.events, record.request.files, from_step, to_step)
    use_llm = llm and rt.llm.available

    async def stream() -> AsyncIterator[str]:
        yield _sse("meta", {
            "llm": use_llm, "lang": lang,
            "scenes": [{"index": s.index, "kind": s.kind, "title": narrator.scene_title(s, lang),
                        "from_step": s.from_step, "to_step": s.to_step} for s in scenes],
        })  # fmt: skip
        for scene in scenes:
            base = narrator.narrate_scene(scene, lang)
            yield _sse("layer_a", {"scene": scene.index, "text": base})
            source = "narrator"
            if use_llm:
                messages = scene_messages(
                    {"title": scene.title, "from_step": scene.from_step, "to_step": scene.to_step,
                     "measured": scene.measured, "digest_text": scene.digest_text},
                    lang, new_nonce(),
                )  # fmt: skip
                try:
                    async for token, provider in rt.llm.stream(messages):
                        source = f"llm:{provider}"
                        yield _sse("token", {"scene": scene.index, "text": token})
                except LlmUnavailable as exc:
                    yield _sse("fallback", {"scene": scene.index, "reason": str(exc), "text": base})
                    source = "narrator"
            yield _sse("scene_done", {"scene": scene.index, "source": source})
        yield _sse("done", {})

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/api/mentor/refactor", response_model=RefactorProposal)
async def refactor(body: RefactorRequest, lang: Lang = "tr", rt: Runtime = Depends(runtime)) -> RefactorProposal:
    record = get_record(rt, body.run_id)
    report = await _report(rt, record)
    finding = next((f for f in report.findings if f.id == body.finding_id), None)
    if finding is None:
        raise HTTPException(404, f"finding {body.finding_id!r} is not part of this run's report")
    finished = record.run_finished or {}
    try:
        return await propose(rt.llm, record.request.files, finding, finished, lang)
    except RefactorError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


def _as_files(items: list[SourceFile]) -> dict[str, str]:
    return {f.path: f.content for f in items}


@router.post("/api/refactor/verify", response_model=VerificationReport)
async def verify_refactor(body: VerifyRequest, rt: Runtime = Depends(runtime)) -> VerificationReport:
    original = validated_files(rt, body.original_files, body.entry)
    proposed = _as_files(body.proposed_files)
    if sum(len(c.encode()) for c in proposed.values()) > rt.settings.max_source_kb * 1024 or len(proposed) > rt.settings.max_files:
        raise HTTPException(413, "the proposed files exceed the size / file-count limits")
    if not rt.try_acquire():
        raise HTTPException(429, "all run slots are busy; retry shortly", headers={"Retry-After": "1"})
    try:
        return await verify(rt.manager, original, proposed, body.entry, body.stdin, body.seed)
    finally:
        rt.release()


@router.post("/api/refactor/autofix", response_model=AutofixResult)
async def autofix(body: AutofixRequest, rt: Runtime = Depends(runtime)) -> AutofixResult:
    files = validated_files(rt, body.files, body.entry)
    try:
        new_files, applied, skipped = await asyncio.to_thread(apply_autofix, files, body.finding_ids)
    except SourceError as exc:
        raise HTTPException(422, str(exc)) from exc
    return AutofixResult(files=[SourceFile(path=p, content=c) for p, c in new_files.items()], applied=applied, skipped=skipped)
