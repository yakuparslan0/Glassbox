# Architecture

## Three processes

| Process | Role | Rules |
|---|---|---|
| **API** (`backend/glassbox/api`) | FastAPI. Validates requests, manages runs, runs analyses, talks to LLMs. | Never `exec`s user code. Binds `127.0.0.1`. |
| **Runner** (`backend/glassbox/runner`) | One subprocess per run. Traces the user program and writes events. | **Standard library only** (a test enforces it). Started with `-s -P -X utf8` (never `-I`), scrubbed environment, own process group. |
| **Browser** (`frontend/`) | Receives events, rebuilds state locally. | Time travel never calls the server; a Web Worker rebuilds state from keyframe + deltas. |

## Run lifecycle

1. `POST /api/runs` validates the files (size, count, paths) and takes a run slot (429 when busy).
2. `SandboxManager` writes the sources and a `job.json` OUTSIDE the working directory and starts the backend
   (`SubprocessBackend`, or `DockerBackend` with the same protocol).
3. The runner duplicates the real stdout fd as the protocol channel, redirects fd 1/2 to capture files, installs the
   audit hook and limits, then runs the program under a `TracerBackend` (`sys.monitoring` by default, `sys.settrace` as
   the reference). Both must produce the same event sequence (tested).
4. Events are NDJSON lines (`seq`, `t`, `type`, ...). The API validates them against the Pydantic models
   (`strict` in tests, sampled in production), stores them once in the run record, and fans them out over WebSocket in
   batches of up to 200 events / 50 ms. A slow client lags behind its own cursor; reconnecting uses `?from_seq=`.
5. A parent watchdog enforces the wall-clock timeout and kills the process tree even if the runner is silent.

## State model

Per step only changed locals are sent (`delta.set` / `delta.del`); every 200 steps a full `keyframe`. Compound values
live in a `heap` map referenced as `{"ref": "oN"}` with stable small labels, which makes aliasing visible. The browser's
`StateBuilder` (`frontend/src/lib/stateBuilder.ts`) mirrors the reference reducer of the backend tests and is checked
against ground-truth `snapshot` events on shared fixtures.

## Analysis and mentor (API process, pure functions over the trace)

- `analysis/static_dead.py`, `clones.py`, `complexity.py`: AST facts.
- `analysis/marksweep.py`: static reachability (MARK-1) combined with executed lines (MARK-2) -> confirmed / cold / suspect.
- `analysis/dynamic_profile.py`: hot loops, repeated computation, loop invariants from the trace; untraced profile passes.
- `analysis/aliasing.py`, `slicing.py` (root cause), `branches.py` (What-If), `bigo.py` (empirical growth fits).
- `mentor/digest.py` (scenes) -> `narrator.py` (rules) or `llm/` (optional); `autofix.py`, `refactor.py`, `verify.py`.
- `export/`: Mermaid, SVG, Replay HTML.

## Single source of truth for schemas

`backend/glassbox/schemas/*.py` (Pydantic) -> `scripts/gen_types.py` -> `docs/schema/glassbox.schema.json` and
`frontend/src/types/generated.ts`. A test fails when the generated files are stale.

## Where to look

- Decisions and trade-offs per phase: [DECISIONS.md](DECISIONS.md)
- Event semantics: [EVENT_SCHEMA.md](EVENT_SCHEMA.md)
- Threat model and sandbox: [SECURITY.md](SECURITY.md)
