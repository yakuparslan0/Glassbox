# Design decisions

Decisions the master spec left open (one paragraph each). Newest phase last within a topic.

## Phase 1

**Python and environment.** The dev interpreter is Python 3.14.5 (spec: >= 3.13). The virtualenv lives outside
the OneDrive-synced project tree (`%USERPROFILE%\.venvs\glassbox`) so that OneDrive does not lock/sync thousands
of small files; the Makefile takes `PYTHON=` so any interpreter works.

**`sys.monitoring` facts verified on 3.14.** `DISABLE` may only be returned for LINE and CALL (and PY_START /
PY_RETURN / PY_YIELD / PY_RESUME / PY_THROW); RAISE, EXCEPTION_HANDLED, PY_UNWIND and C_RETURN/C_RAISE raise
`ValueError: Cannot disable ... events`. So non-user locations are disabled for LINE/CALL only. PY_START /
PY_RETURN stay enabled for non-user code on purpose: they open and close Python-level library boundaries, and a
disabled location would only report the first call. Callback arities: PY_THROW/PY_UNWIND/RAISE/
EXCEPTION_HANDLED get `(code, offset, exception)`, CALL/C_RETURN/C_RAISE `(code, offset, callable, arg0)`,
JUMP `(code, offset, destination_offset)`.

**Backend parity.** `sys.settrace` reports a backward jump that stays on the same line (one-line loops,
comprehensions) as a `line` event, `LINE` does not; the monitoring backend therefore also registers JUMP and
re-creates those events. A settrace `return` event does not say whether a frame returned or is unwinding, so
the opcode at `f_lasti` decides (RETURN_VALUE/YIELD_VALUE = normal exit). Exceptions are tracked by one shared
state machine in the recorder (pending exception per frame; "last seen exception" for frames that unwind after
their `finally` handler already reported it), so both backends emit the same `exception` events.

**Boundaries.** `builtins` callables and builtin-type methods are never boundaries (they would drown the trace);
neither are class instantiations or non-user generators/coroutines. C boundaries carry no argument/return
summary because `CALL` only exposes the first argument and no backend exposes the result. A Python library
function counts as a boundary when its frame's caller is the top user frame (same rule in both backends, so it
also covers `map(json.dumps, xs)`-style C-mediated calls identically).

**Generators.** Each resume (PY_START/PY_RESUME/PY_THROW) is a `call` with a new frame id and each suspension a
`return`, in both backends; there is no separate "yield" flag because settrace cannot distinguish it cheaply.

**State model.** Module frames use `f_globals` as their locals mapping (inside an inlined module-level
comprehension `f_locals` hides every global). `globals_delta` is also sent on call and boundary events so that
globals are exact at every structural event. Keyframes are built from the recorder's mirror (no extra
serialization, deterministic); the optional `snapshot` debug event is the independent ground truth used by tests.
The serializer keeps a strong reference to every object it labels so `id()`-based labels never get reused; this
changes GC/`__del__` timing of traced objects slightly and bounds memory by the step limit.

**Limits and exit.** Step/output/event-byte limits emit `limit_exceeded` + `run_finished` and terminate the
runner with `os._exit` (clean for the protocol, user `finally`/`atexit` blocks do not run). `sys.exit(n)` is
`status: ok` with `exit_code: n`. A rejected What-If literal ends the run as `blocked` before any user code runs.
After normal completion user `atexit` handlers run untraced and user threads are not waited for.

**What-If.** `frame_depth` indexes the user frames of the stack (0 = entry module). An override is applied right
after the event of its target step; an override whose frame does not exist at that step is skipped and counted in
`run_finished.whatif_unapplied`.

**Output ordering.** `sys.stdout/stderr` writes become `output` events immediately. Raw fd 1/2 writes
(`os.write`) go to capture files (no reader threads) which are drained after every boundary return and at the
end, so they appear right after the call that produced them.

**Streaming.** A helper thread flushes the protocol buffer every 50 ms, so events stream live and are not lost
if the main thread hangs inside C code (the watchdog then kills the process).

**Timing fields.** `func_stats[*].self_ns/total_ns` and `dur_ns` come from the traced run: they are inflated by
tracing and non-deterministic (excluded from determinism/parity comparisons); `steps`/`calls`/`line_hits` are the
exact metrics. Real timings come from the untraced profile pass (Phase 2).

**Audit hook.** Beyond the spec list it also blocks `os.fork*`, `os.spawn*`/`posix_spawn`, DNS lookups
(`socket.getaddrinfo`, `gethostbyname`) and `os.remove/rmdir/mkdir/rename` outside the working directory.
Loopback is not exempt, so asyncio on Windows (its self-pipe is a loopback socket pair) needs `allow_network`;
asyncio is out of scope in v1 anyway.

**Process management.** POSIX: new session + `killpg(SIGKILL)`. Windows: `CREATE_NEW_PROCESS_GROUP` and
`taskkill /T /F` (the venv `python.exe` is a launcher that starts the real interpreter as a child, so killing
the tree matters). Windows has no `resource`, so `capabilities.rlimit` is `false` there. If the runner dies
without `run_finished`, the parent synthesizes `limit_exceeded(timeout)` (if its watchdog fired) and
`run_finished(status: killed)`.

**Deferred.** The `hot_loop` finding (5000 identical-state repeats of a line) is derived from the trace and is
produced by `analysis/dynamic_profile.py` in Phase 2. Docker backend, API, config and the other analysis
modules are Phase 2+.

## Phase 2

**Spec storage.** The full original spec lives in `docs/SPEC.md`; `CLAUDE.md` imports it with `@docs/SPEC.md`
(loaded every session) instead of pasting ~12k tokens into the file itself.

**Profile pass.** `job.profile = "time" | "memory"` runs the program UNTRACED in the runner (`runner/profiler.py`):
cProfile and tracemalloc run in two SEPARATE processes because each distorts the other. The result travels in
`run_finished.profile`. tracemalloc reports what is still allocated at the end of the run per line, plus the
process-wide traced peak; the report labels it that way (per-line peaks are not available from tracemalloc).

**Finding semantics.** `static_dead` reports direct facts (never referenced, unused, unreachable) with confidence
`confirmed`/`likely`/`suspect`; `marksweep` adds transitive dead code (call graph by simple name, an
over-approximation that only errs towards "reachable") and upgrades `likely` -> `confirmed` only when the lines also
did not run. Static-dead code that DID run is downgraded to `suspect` (dynamic access). Dynamic findings
(hot_loop, repeated_computation, loop_invariant, mutable_default, alias_mutation) and clones are part of the same
`MarkSweepReport.findings` list; `high_memory` lives in the `ProfileReport`.

**hot_loop** = one line ran N (5000) times in one frame with no local/global/heap change anywhere in that frame since
its counters were last reset (alternating lines of `while True: pass` count). **repeated_computation** is `likely`
(it assumes purity). **mutable_default** needs a static mutable default AND the same object passed in >= 2 calls with
different contents; **alias_mutation** needs one object bound to >= 2 names in a frame, mutated through one name
(attributed from the source line before the event that shows the change) and later read through another.

**Clones.** A statement subtree qualifies with >= 5 statements OR >= 40 nodes (OR, because a 3-statement function with
a loop is already a useful clone); identifiers (except builtins) and constants are normalized; only maximal groups are
reported.

**API.** Status codes: illegal path/duplicate path/missing entry/syntax error 422; too many files or too many bytes 413;
all run slots busy 429 + `Retry-After`; unknown run 404; report/trace requested while running 409. Slots are counted
(not queued) and released BEFORE the final state becomes visible. WebSocket backpressure: events are stored once per
run, each connection holds only a cursor and one batch (<= 200 events, flushed every 50 ms), so a slow client lags
behind its cursor instead of growing server memory; a send blocked for 30 s closes the socket. `?from_seq=N` resumes
after event N. Browser `Origin` headers must be in `GLASSBOX_CORS_ORIGINS` (CORS does not cover WebSockets).
Evicted/expired runs: `/trace` falls back to `GLASSBOX_RUNS_DIR/<run_id>.ndjson` when persistence is on.

**Validation.** `GLASSBOX_VALIDATE_EVENTS`: `strict` (every event; a violation fails the run), `sampled` (default:
every 100th event, logged only), `off`. The test-suite uses `strict`.

**Docker.** `DockerBackend` reuses the subprocess backend (watchdog, synthesized `run_finished`, cleanup) and only
changes argv/env/kill. Paths in a copy of `job.json` are rewritten to the container mounts (`/work`, `/cap`).
`--network none` becomes `bridge` only when the run opts in with `allow_network`. NOT verified end-to-end: Docker is not
installed on the development machine, only the generated command line is unit-tested.

**Deferred.** Export routes (Phase 5), mentor/refactor routes (Phase 4), rootcause and bigo routes (Phase 5).
Docker `API`/frontend images arrive with the Dockerfiles of Phase 5; `docker-compose.yml` only builds the runner image.
