"""Export routes: Mermaid text, SVG drawing and the self-contained Replay HTML of a finished run."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..export.html_replay import DEFAULT_MAX_BYTES, build_replay
from ..export.mermaid import to_mermaid, to_svg
from .deps import get_record, runtime
from .store import RunRecord, Runtime

router = APIRouter(prefix="/api/export")


def _finished(rt: Runtime, run_id: str) -> RunRecord:
    record = get_record(rt, run_id)
    if not record.done:
        raise HTTPException(409, "the run is still in progress; export needs the finished trace")
    return record


@router.get("/{run_id}/mermaid")
async def export_mermaid(run_id: str, rt: Runtime = Depends(runtime)) -> Response:
    record = _finished(rt, run_id)
    text = await asyncio.to_thread(to_mermaid, record.events)
    return Response(text, media_type="text/plain; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{run_id}.mmd"'})


@router.get("/{run_id}/svg")
async def export_svg(run_id: str, rt: Runtime = Depends(runtime)) -> Response:
    record = _finished(rt, run_id)
    text = await asyncio.to_thread(to_svg, record.events)
    return Response(text, media_type="image/svg+xml", headers={"Content-Disposition": f'attachment; filename="{run_id}.svg"'})


@router.get("/{run_id}/html")
async def export_html(run_id: str, max_kb: int = DEFAULT_MAX_BYTES // 1000, rt: Runtime = Depends(runtime)) -> Response:
    record = _finished(rt, run_id)
    request = record.request
    page = await asyncio.to_thread(
        build_replay, record.events, request.files[request.entry], request.entry, max(50, min(max_kb, 20_000)) * 1000
    )
    return Response(page, media_type="text/html; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{run_id}.replay.html"'})
