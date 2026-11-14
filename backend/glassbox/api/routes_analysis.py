"""Static analysis route (no execution)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from ..analysis import bigo, marksweep
from ..analysis.common import SourceError
from ..schemas.analysis import BigOReport, StaticReport
from ..schemas.api import BigORequest, StaticRequest
from .deps import runtime, validated_files
from .store import Runtime

router = APIRouter(prefix="/api/analysis")


@router.post("/static", response_model=StaticReport)
async def static_report(body: StaticRequest, rt: Runtime = Depends(runtime)) -> StaticReport:
    files = validated_files(rt, body.files, body.entry)
    try:
        findings, functions = await asyncio.to_thread(marksweep.build_static, files)
    except SourceError as exc:
        raise HTTPException(422, str(exc)) from exc
    return StaticReport(findings=findings, functions=functions)


lab = APIRouter(prefix="/api/lab")


@lab.post("/bigo", response_model=BigOReport)
async def bigo_lab(body: BigORequest, rt: Runtime = Depends(runtime)) -> BigOReport:
    files = validated_files(rt, body.files, body.entry)
    if not rt.try_acquire():
        raise HTTPException(429, "all run slots are busy; retry shortly", headers={"Retry-After": "1"})
    try:
        return await bigo.run_bigo(rt.manager, files, body.entry, body.func, body.generator, body.sizes, body.extra_args, body.seed)
    except SourceError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        rt.release()
