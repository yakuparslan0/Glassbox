"""In-memory run store (LRU + TTL, optional NDJSON on disk) and the run producer task."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ..config import Settings
from ..llm.service import LlmService
from ..sandbox.manager import RunRequest, SandboxManager
from ..schemas.analysis import MarkSweepReport, ProfileReport
from ..schemas.events import validate_event

log = logging.getLogger("glassbox.api")
SAMPLE_EVERY = 100


@dataclass
class RunRecord:
    run_id: str
    request: RunRequest
    created_at: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)
    state: str = "running"  # running | finished | cancelled | error
    error: str | None = None
    task: asyncio.Task[None] | None = None
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    marksweep: MarkSweepReport | None = None
    profile: ProfileReport | None = None
    disk_path: str | None = None

    @property
    def done(self) -> bool:
        return self.state != "running"

    @property
    def run_finished(self) -> dict[str, Any] | None:
        for ev in reversed(self.events):
            if ev.get("type") == "run_finished":
                return ev
        return None

    def cancel(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()  # the producer task reports the final state once the process is dead


class RunStore:
    """LRU of at most ``capacity`` runs; entries older than ``ttl_s`` expire. Running runs are never evicted."""

    def __init__(self, capacity: int, ttl_s: int) -> None:
        self.capacity = capacity
        self.ttl_s = ttl_s
        self._runs: OrderedDict[str, RunRecord] = OrderedDict()

    def add(self, record: RunRecord) -> None:
        self._runs[record.run_id] = record
        self._evict()

    def get(self, run_id: str) -> RunRecord | None:
        self._evict()
        record = self._runs.get(run_id)
        if record is not None:
            self._runs.move_to_end(run_id)
        return record

    def _evict(self) -> None:
        now = time.time()
        for run_id, rec in list(self._runs.items()):
            if rec.done and now - rec.created_at > self.ttl_s:
                del self._runs[run_id]
        while len(self._runs) > self.capacity:
            victim = next((rid for rid, rec in self._runs.items() if rec.done), None)
            if victim is None:
                break
            del self._runs[victim]

    def __len__(self) -> int:
        return len(self._runs)


class Runtime:
    """Everything the routes share: settings, store, sandbox manager and the concurrency slots."""

    def __init__(self, settings: Settings, manager: SandboxManager, llm: LlmService | None = None) -> None:
        self.settings = settings
        self.manager = manager
        self.llm = llm or LlmService([])
        self.store = RunStore(settings.run_store_size, settings.run_ttl_s)
        self.active = 0

    def try_acquire(self) -> bool:
        if self.active >= self.settings.max_concurrent_runs:
            return False
        self.active += 1
        return True

    def release(self) -> None:
        self.active = max(0, self.active - 1)

    def start_run(self, request: RunRequest) -> RunRecord:
        """Register a run and start its producer task. The caller must already hold a slot."""
        record = RunRecord(run_id=uuid.uuid4().hex, request=request)
        if self.settings.runs_dir:
            os.makedirs(self.settings.runs_dir, exist_ok=True)
            record.disk_path = os.path.join(self.settings.runs_dir, f"{record.run_id}.ndjson")
        self.store.add(record)
        record.task = asyncio.get_running_loop().create_task(self._produce(record))
        return record

    async def _publish(self, record: RunRecord, event: dict[str, Any], sink: Any) -> None:
        mode = self.settings.validate_events
        if mode == "strict" or (mode == "sampled" and event.get("seq", 0) % SAMPLE_EVERY == 1):
            try:
                validate_event(event)
            except ValidationError as exc:
                if mode == "strict":
                    raise RuntimeError(f"runner event #{event.get('seq')} violates the schema: {exc.errors()[:2]}") from exc
                log.warning("sampled event #%s violates the schema: %s", event.get("seq"), exc.errors()[:2])
        if sink is not None:
            sink.write(json.dumps(event, separators=(",", ":")) + "\n")
        async with record.cond:
            record.events.append(event)
            record.cond.notify_all()

    async def _produce(self, record: RunRecord) -> None:
        sink = open(record.disk_path, "w", encoding="utf-8", newline="\n") if record.disk_path else None  # noqa: SIM115
        final_state = "finished"
        detail = ""
        try:
            async for event in self.manager.run(record.request):
                await self._publish(record, event, sink)
        except asyncio.CancelledError:
            final_state, detail = "cancelled", "cancelled by the client"
        except Exception as exc:  # the run itself failed (bad request files, schema violation, internal error)
            log.exception("run %s failed", record.run_id)
            final_state, detail = "error", str(exc)
        finally:
            try:
                if final_state != "finished" or record.run_finished is None:
                    await self._publish(record, self._synthetic_finish(record, detail or "run ended unexpectedly"), sink)
            finally:
                if sink is not None:
                    with contextlib.suppress(Exception):
                        sink.close()
                self.release()  # free the slot BEFORE announcing the final state: a client may start a new run at once
                record.state = final_state
                record.error = detail or None
                async with record.cond:
                    record.cond.notify_all()

    @staticmethod
    def _synthetic_finish(record: RunRecord, detail: str) -> dict[str, Any]:
        last = record.events[-1] if record.events else {}
        return {
            "v": 1, "seq": last.get("seq", 0) + 1, "t": last.get("t", 0), "type": "run_finished",
            "status": "killed", "exit_code": -1, "steps": last.get("step", 0), "wall_ms": 0, "line_hits": {},
            "func_stats": {}, "executed_lines": {}, "repeat_calls": [], "detail": detail,
        }  # fmt: skip
