"""WebSocket event stream: batched, backpressured by the client's own pace, resumable with ``?from_seq=``.

Design: events live once in the run record. Every connection only keeps a cursor and the batch it is sending
(<= BATCH_MAX events), so a slow client cannot grow server memory; it simply lags behind its cursor.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .store import RunRecord, Runtime

router = APIRouter()
BATCH_MAX = 200
BATCH_WINDOW_S = 0.05
SEND_TIMEOUT_S = 30.0


def _cursor_for(record: RunRecord, from_seq: int) -> int:
    """Index of the first event with seq > from_seq (seq is contiguous from 1, but verify rather than assume)."""
    events = record.events
    idx = max(0, min(from_seq, len(events)))
    while idx > 0 and events[idx - 1]["seq"] > from_seq:
        idx -= 1
    while idx < len(events) and events[idx]["seq"] <= from_seq:
        idx += 1
    return idx


async def _sender(ws: WebSocket, record: RunRecord, cursor: int) -> None:
    while True:
        async with record.cond:
            await record.cond.wait_for(lambda at=cursor: len(record.events) > at or record.done)
            drained = len(record.events) <= cursor and record.done
        if drained:
            return
        if len(record.events) - cursor < BATCH_MAX and not record.done:
            await asyncio.sleep(BATCH_WINDOW_S)  # let a batch fill up: one frame per 50 ms or 200 events
        batch = record.events[cursor : cursor + BATCH_MAX]
        cursor += len(batch)
        await asyncio.wait_for(ws.send_json({"batch": batch}), SEND_TIMEOUT_S)


def _origin_allowed(ws: WebSocket, rt: Runtime) -> bool:
    origin = ws.headers.get("origin")
    return origin is None or origin in rt.settings.cors_origins  # browsers always send Origin; CLI clients do not


@router.websocket("/ws/runs/{run_id}")
async def run_stream(ws: WebSocket, run_id: str, from_seq: int = 0) -> None:
    rt: Runtime = ws.app.state.runtime
    if not _origin_allowed(ws, rt):
        await ws.close(code=4403, reason="origin not allowed")
        return
    record = rt.store.get(run_id)
    if record is None:
        await ws.close(code=4404, reason="unknown or expired run")
        return
    await ws.accept()
    sender = asyncio.create_task(_sender(ws, record, _cursor_for(record, from_seq)))
    receiver = asyncio.create_task(_receiver(ws, record))
    try:
        await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        if sender.done() and not sender.cancelled() and sender.exception() is None:
            with contextlib.suppress(Exception):
                await ws.close()
    finally:
        for task in (sender, receiver):
            task.cancel()
        for task in (sender, receiver):
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError, Exception):
                await task


async def _receiver(ws: WebSocket, record: RunRecord) -> None:
    while True:
        try:
            message = await ws.receive_json()
        except WebSocketDisconnect:
            return  # the run keeps going: the client may reconnect with from_seq
        except ValueError:
            continue
        if isinstance(message, dict) and message.get("cmd") == "cancel":
            record.cancel()
