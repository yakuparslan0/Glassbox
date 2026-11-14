"""Request validation shared by the routes."""

from __future__ import annotations

from fastapi import HTTPException, Request

from ..sandbox.manager import validate_files
from ..schemas.api import SourceFile
from .store import RunRecord, Runtime


def runtime(request: Request) -> Runtime:
    rt: Runtime = request.app.state.runtime
    return rt


def validated_files(rt: Runtime, files: list[SourceFile], entry: str) -> dict[str, str]:
    """Return {path: content}; 413 for size / count limits, 422 for illegal paths."""
    settings = rt.settings
    if len(files) > settings.max_files:
        raise HTTPException(413, f"too many files: {len(files)} submitted, the limit is {settings.max_files}")
    total = sum(len(f.content.encode("utf-8")) for f in files)
    if total > settings.max_source_kb * 1024:
        raise HTTPException(
            413, f"sources are {total // 1024} KB in total, the limit is {settings.max_source_kb} KB"
        )
    mapping = {f.path: f.content for f in files}
    if len(mapping) != len(files):
        raise HTTPException(422, "duplicate file paths in the submission")
    try:
        validate_files(mapping, entry)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return mapping


def get_record(rt: Runtime, run_id: str) -> RunRecord:
    record = rt.store.get(run_id)
    if record is None:
        raise HTTPException(404, f"run {run_id!r} not found (unknown id, expired, or evicted from the run store)")
    return record
