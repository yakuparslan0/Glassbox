"""Run lifecycle, trace download, profile pass and Mark & Sweep routes."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse

from ..analysis import marksweep
from ..analysis.branches import compare
from ..analysis.common import SourceError
from ..analysis.dynamic_profile import run_profile
from ..analysis.slicing import SliceError, backward_slice
from ..runner.whatif import OverrideError, load_overrides
from ..sandbox.manager import RunRequest
from ..schemas.analysis import BranchComparison, CausalChain, MarkSweepReport, ProfileReport
from ..schemas.api import RunCreate, RunCreated, RunSummary
from .deps import get_record, runtime, validated_files
from .store import Runtime

router = APIRouter(prefix="/api/runs")
_BUSY = "all run slots are busy; wait for a running program to finish and retry"


def _request_from(body: RunCreate, files: dict[str, str]) -> RunRequest:
    limits = {k: v for k, v in body.limits.model_dump().items() if v is not None}
    overrides = [o.model_dump() for o in body.overrides]
    try:
        load_overrides(overrides)  # literal_eval ONLY; anything else (e.g. __import__('os')) is refused up front
    except OverrideError as exc:
        raise HTTPException(422, f"What-If override rejected: {exc}") from exc
    return RunRequest(
        files=files, entry=body.entry, stdin=body.stdin, seed=body.seed, filter=body.filter, limits=limits,
        overrides=overrides, allow_network=body.allow_network,
    )  # fmt: skip


@router.post("", response_model=RunCreated, status_code=201)
async def create_run(body: RunCreate, rt: Runtime = Depends(runtime)) -> RunCreated:
    files = validated_files(rt, body.files, body.entry)
    if not rt.try_acquire():
        raise HTTPException(429, _BUSY, headers={"Retry-After": "1"})
    try:
        record = rt.start_run(_request_from(body, files))
    except BaseException:
        rt.release()
        raise
    return RunCreated(run_id=record.run_id)


@router.get("/{run_id}", response_model=RunSummary)
async def get_run(run_id: str, rt: Runtime = Depends(runtime)) -> RunSummary:
    record = get_record(rt, run_id)
    return RunSummary(
        run_id=record.run_id, state=record.state,  # type: ignore[arg-type]
        entry=record.request.entry, events=len(record.events), created_at=record.created_at,
        run_finished=record.run_finished, error=record.error,
    )  # fmt: skip


@router.get("/{run_id}/trace")
async def get_trace(run_id: str, rt: Runtime = Depends(runtime)) -> Response:
    record = rt.store.get(run_id)
    if record is None:
        path = os.path.join(rt.settings.runs_dir, f"{run_id}.ndjson") if rt.settings.runs_dir else None
        if path and re.fullmatch(r"[0-9a-f]{32}", run_id) and os.path.isfile(path):
            return StreamingResponse(_file_chunks(path), media_type="application/x-ndjson")
        raise HTTPException(404, f"run {run_id!r} not found")
    if not record.done:
        raise HTTPException(409, "the run is still in progress; the trace can be downloaded once it has finished")

    def lines() -> Iterator[str]:
        for ev in record.events:
            yield json.dumps(ev, separators=(",", ":")) + "\n"

    return StreamingResponse(
        lines(), media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.ndjson"'},
    )  # fmt: skip


def _file_chunks(path: str) -> Iterator[bytes]:
    with open(path, "rb") as f:
        while chunk := f.read(64 * 1024):
            yield chunk


@router.get("/{run_id}/marksweep", response_model=MarkSweepReport)
async def get_marksweep(run_id: str, rt: Runtime = Depends(runtime)) -> MarkSweepReport:
    record = get_record(rt, run_id)
    if not record.done:
        raise HTTPException(409, "the run is still in progress; the report needs the finished trace")
    if record.marksweep is None:
        try:
            record.marksweep = await asyncio.to_thread(
                marksweep.build, record.request.files, record.request.entry, record.events
            )
        except SourceError as exc:
            raise HTTPException(422, str(exc)) from exc
    return record.marksweep


@router.post("/{run_id}/profile", response_model=ProfileReport)
async def profile_run(run_id: str, rt: Runtime = Depends(runtime)) -> ProfileReport:
    record = get_record(rt, run_id)
    if record.profile is not None:
        return record.profile
    if not rt.try_acquire():
        raise HTTPException(429, _BUSY, headers={"Retry-After": "1"})
    try:
        record.profile = await run_profile(rt.manager, record.request)
    finally:
        rt.release()
    return record.profile


@router.get("/{run_id}/rootcause", response_model=CausalChain)
async def root_cause(run_id: str, rt: Runtime = Depends(runtime)) -> CausalChain:
    record = get_record(rt, run_id)
    if not record.done:
        raise HTTPException(409, "the run is still in progress; the root cause needs the finished trace")
    try:
        return await asyncio.to_thread(backward_slice, record.events, record.request.files)
    except SliceError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{run_id}/compare", response_model=BranchComparison)
async def compare_runs(run_id: str, other: str, rt: Runtime = Depends(runtime)) -> BranchComparison:
    """Compare a base run with a What-If branch (``other``): first diverging step + outcome differences."""
    base, branch = get_record(rt, run_id), get_record(rt, other)
    if not (base.done and branch.done):
        raise HTTPException(409, "both runs must have finished before they can be compared")
    return await asyncio.to_thread(compare, base.run_id, base.events, branch.run_id, branch.events)
