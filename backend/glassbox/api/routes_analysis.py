"""Static analysis route (no execution)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from ..analysis import marksweep
from ..analysis.common import SourceError
from ..schemas.analysis import StaticReport
from ..schemas.api import StaticRequest
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
