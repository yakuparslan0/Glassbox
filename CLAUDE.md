# GlassBox — project memory for Claude Code

AI-powered runtime execution visualizer & code mentor. It runs user Python in an isolated
subprocess, records every step, and visualizes / analyzes / explains it.
Code, identifiers and commit messages are English. UI strings and mentor output default to Turkish
(i18n dictionary, `en` also provided).

## Working rules
- Build in 5 phases, in order. At the end of each phase: run acceptance tests + ruff, commit, write a
  <=10 line "Phase N report", then STOP and wait for the user to say "devam".
- No stubs, no `TODO`, no fake-data endpoints. Do not write what the current phase does not deliver.
- Never claim "works" before running it. Verify library APIs (sys.monitoring, React Flow, Groq/Gemini
  endpoints, model names) against official docs/the installed interpreter before coding.
- Undocumented design decisions: pick the simplest safe option, record it in `docs/DECISIONS.md`.
- Keep this file's "Status" section current.

## Immutable architecture (spec section 2)
- Backend Python 3.13+ (PEP 667 writable `frame.f_locals` powers What-If), FastAPI, Pydantic v2.
  Frontend React+TS+Vite, Tailwind, Zustand, Monaco, React Flow, dagre. WebSocket for run events, SSE for LLM tokens.
- Three processes: API (never `exec`s user code) / Runner subprocess per run (**stdlib only**, no third-party
  import, not even pydantic) / Browser (rebuilds state client-side from keyframe+delta in a Web Worker).
- Tracing: `TracerBackend` with `MonitoringTracer` (sys.monitoring, default; return `DISABLE` for non-user
  locations) and `SettraceTracer` (fallback). Both MUST produce the same event sequence (time fields excluded).
  Scope v1: main thread, sync code, generators. asyncio/threads untraced (reported in `capabilities`).
- Noise filter: code objects classified once (`user`/`stdlib`/`third_party`), cached. Only `user` code is traced
  line by line; calls out of user code become ONE boundary call/return pair. Filter levels:
  `user_only` | `boundaries` (default) | `boundaries_verbose`.
- Protocol channel: runner `os.dup`s the real stdout fd as the protocol channel, then redirects fd 1/2 to its own
  capture and replaces `sys.stdout/stderr/stdin`. NDJSON, one JSON per line, UTF-8. Job comes from a `job.json`
  OUTSIDE the cwd (stdin belongs to the user's `input()`).
- State: per step only changed locals (`delta.set` / `delta.del`); full `keyframe` every `KEYFRAME_INTERVAL`
  (200) steps. Change detection by deep fingerprint of the serialized value (catches in-place `list.append`).
- Serializer: tracing off while serializing, never calls user `__repr__`; depth 3, 50 items/collection,
  200 chars/string, 64 KB/event; compound objects go to a `heap` map and are referenced as `{"ref":"oN"}`
  (stable small labels for `id()`), which exposes aliasing.
- Determinism: each run has a `seed`; runner calls `random.seed(seed)`; child runs with `PYTHONHASHSEED=0`.
  Child is started with `-s -P -X utf8` and a scrubbed env — NEVER `-I`.
- Honest timing: traced runs report STEP COUNT and line hits as the primary metric; real time/memory come from a
  separate untraced profile pass (cProfile + tracemalloc). UI labels which pass a number came from.
- Single source of schemas: Pydantic models in `backend/glassbox/schemas/`; `scripts/gen_types.py` emits JSON
  Schema and `frontend/src/types/generated.ts`. No hand-written event types on the frontend.

## Event schema summary (spec section 4)
Envelope: `{"v":1,"seq":N,"t":ns,"type":...}`; `step` increments only on call/line/return/exception.
Types: run_started, import, call (user | boundary), line, return, exception, output, keyframe, whatif_applied,
limit_exceeded, run_finished (+ `snapshot`, a debug-only event, see docs/EVENT_SCHEMA.md).
Values: prim `{"k":"prim","t":"int","r":"42"}`, ref `{"ref":"o12"}`, heap entries `seq|map|obj|other`.
API: POST /api/runs, WS /ws/runs/{id}, GET /api/runs/{id}[/trace], static/profile/marksweep/rootcause/bigo,
mentor narrate (SSE) / refactor, refactor verify/autofix, export mermaid|svg|html, /api/health.
Findings: `{id,category,severity,confidence,file,start_line,end_line,title,evidence,autofixable}`.

## Security rules (spec section 5 — no negotiation)
1. `subprocess` mode is NOT a security boundary. Server binds 127.0.0.1 only; `GLASSBOX_ALLOW_REMOTE=true`
   without `SANDBOX_MODE=docker` => refuse to start. Say so in README and docs/SECURITY.md.
2. Child spawn: `[sys.executable,"-s","-P","-X","utf8","-m","glassbox.runner",job_path]`, new session/process
   group, cwd = per-run temp dir, env built FROM SCRATCH (PYTHONHASHSEED=0, PYTHONDONTWRITEBYTECODE=1, LANG,
   SYSTEMROOT on Windows). API keys / parent env never reach the child (tested).
3. Layered limits: runner (`max_steps` 20000, `max_output_kb` 256, 64 KB/event, 50 MB total events);
   OS (POSIX `resource.setrlimit`: CPU/AS/FSIZE/NOFILE; Windows reports `capabilities.rlimit=false`);
   parent watchdog (wall timeout 10 s, kill process group/tree; works even if runner emits nothing).
4. Hot-loop finding after N (5000) identical-state repeats of one line.
5. Audit hook blocks `socket.connect`, `subprocess.Popen`, `os.system`, `os.exec*`, ctypes loads, writes outside
   the cwd (`PermissionError`, `status:"blocked"`). Network opt-in via `allow_network`.
6. Docker mode: `--network none --read-only --tmpfs /tmp --memory 512m --cpus 1 --pids-limit 64
   --cap-drop ALL --security-opt no-new-privileges --user 65534:65534`.
7. API hardening: sources <=200 KB, <=20 files, reject `..`/absolute paths, run semaphore (4), CORS only for
   configured origins, delete temp dir after run, LRU(20)+TTL for in-memory runs.
8. LLM: user code goes to the LLM as DATA inside explicit delimiters; LLM output is never auto-applied
   (schema -> ast.parse -> sandbox verification -> user click). Never log keys (last 4 chars only).
9. What-If values are parsed ONLY with `ast.literal_eval`. `eval` is forbidden.

## Status
- Phase 1 (tracing core, sandbox, CLI): DONE (see docs/DECISIONS.md; POSIX rlimit path untested on the Windows dev box)
- Phases 2-5: not started

## Dev environment notes
- Python venv lives outside the OneDrive-synced tree: `%USERPROFILE%\.venvs\glassbox` (Python 3.14).
- Run tests: `<venv>\Scripts\python -m pytest backend/tests`; lint: `<venv>\Scripts\python -m ruff check backend`.
