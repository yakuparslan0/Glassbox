# GlassBox

**See your Python code run.** GlassBox executes a Python program in an isolated process, records every step, and
lets you scrub back and forth through it: call graph, variables, heap and aliasing, dead and cold code, bottlenecks,
a rule-based (and optionally LLM-powered) mentor, measured refactorings, "what if I change this value?" branches,
root-cause tracing of crashes, and an empirical Big-O lab. The UI is Turkish by default (English included).

> ## Security warning
> The default `subprocess` sandbox is **not a security boundary**. It protects against runaway loops, memory and
> accidents, **not against malicious code**. The server therefore binds `127.0.0.1` only, and it **refuses to start**
> with `GLASSBOX_ALLOW_REMOTE=true` unless `SANDBOX_MODE=docker`. Do not expose GlassBox to other machines without the
> Docker mode. Details: [docs/SECURITY.md](docs/SECURITY.md).

## Run it in 30 seconds

Requirements: Python 3.13+ and Node.js 22+.

```bash
git clone https://github.com/yakuparslan0/glassbox.git && cd glassbox
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
make install                                          # pip install -e "backend[dev]" and npm ci
make dev                                              # API on 127.0.0.1:8000 + UI on http://localhost:5173
```

Open http://localhost:5173, pick an example, press **Run**. No API key is needed: the app is fully usable with the
built-in rule-based narration. (`make` missing? run `python scripts/dev.py`.)

Terminal only: `glassbox trace examples/fib_naive.py`, `glassbox report examples/dead_code_zoo.py`,
`glassbox export examples/crash_chain.py --html replay.html`.

## See it without installing anything

Real files produced by `glassbox export` (single HTML files, no network, no server):

- [fib_naive replay](docs/examples/fib_naive.replay.html) (thinned to 400 KB: jumps between snapshots)
- [alias_bug replay](docs/examples/alias_bug.replay.html) · [crash_chain replay](docs/examples/crash_chain.replay.html) · [bubble_sort replay](docs/examples/bubble_sort.replay.html)
- Call graph of `crash_chain`: [SVG](docs/examples/crash_chain.svg) · [Mermaid](docs/examples/crash_chain.mmd)

## What you get

| Area | What it does |
|---|---|
| Time travel | Back / forward / step over / step out / scrubber with exception, output, library-call and divergence markers; works live while the program is still running. |
| Views | Call graph (dagre), call tree, heap view with alias highlighting, virtualized timeline, variables with per-variable history. |
| Mark & Sweep | Static reachability + what actually ran: confirmed-dead, cold and suspect code, duplicate blocks, unused imports/variables, reclaimable lines. |
| Bottlenecks | Hot loops, repeated computation (memoization candidates), loop invariants, mutable defaults, alias mutation; untraced `cProfile` / `tracemalloc` passes for real time and memory. |
| Mentor | Scene-based narration. Layer A (rules, instant, no key) always works; Layer B (LLM via Groq/Gemini) is opt-in per click. |
| Verified refactoring | Safe auto-fixes without an LLM; LLM proposals are validated, never auto-applied, and speed claims are only shown after a measured comparison. |
| What-If | Change a value at any step, re-run deterministically, compare branches and see where they diverge. |
| Root cause | Backward trace from an uncaught exception to where the faulty value came from. |
| Big-O lab | Fits step counts for growing inputs to 1, log n, n, n log n, n², n³, 2ⁿ; compares with a static estimate and flags contradictions. |
| Export | Mermaid, SVG, single-file Replay HTML; presentation mode (`Space`, `←/→`, `Shift+←/→`, `[ ]`, `F`). |

Honest numbers: a traced run reports **step counts** (deterministic); real time and memory come from separate
**untraced** passes, and the UI labels which pass a number came from.

## Architecture

```mermaid
flowchart LR
  B["Browser<br/>React · Monaco · React Flow<br/>state rebuilt in a Web Worker"] -- "REST · WebSocket (events) · SSE (LLM tokens)" --> A["API process (FastAPI)<br/>never executes user code"]
  A -- "spawns, watchdog, NDJSON over a dup'ed fd" --> R["Runner subprocess<br/>stdlib only · sys.monitoring tracer"]
  A -. "optional" .-> D["Docker container<br/>--network none · read-only · cap-drop ALL"]
  R --> D
  A -- "OpenAI-compatible HTTP" --> L["Groq / Gemini (optional)"]
```

More in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); design decisions in [docs/DECISIONS.md](docs/DECISIONS.md); the original
specification in [docs/SPEC.md](docs/SPEC.md).

## LLM (optional)

Copy `.env.example` to `.env` and fill `GROQ_API_KEYS` / `GEMINI_API_KEYS`. A provider is active only when its keys,
model **and** base URL are set. Source code leaves your machine only when you click an LLM button.

## Development

```bash
make test        # backend (pytest) + frontend (vitest)
make lint        # ruff + tsc
make schema      # regenerate JSON Schema + frontend/src/types/generated.ts from the Pydantic models
```

Live acceptance checks against a running stack: `GLASSBOX_LIVE=http://127.0.0.1:5173 npx vitest run` in `frontend/`.
Items that need eyes on the UI are listed in [docs/MANUAL_CHECKLIST.md](docs/MANUAL_CHECKLIST.md).

## Known limitations

- Traced: main thread, synchronous code and generators. `asyncio` and extra threads are not traced (the UI says so).
- The tracer is slow (it records every step); the default limits are 20,000 steps and 10 s.
- The POSIX `rlimit` protections are implemented but have **never been run**: the development machine is Windows (the CI workflow will be their first execution).
- The Docker mode and the Docker images were written without a Docker installation at hand and have not been run end to end.
- Groq/Gemini calls were verified against faked HTTP only (no live keys); model ids in `.env.example` are suggestions.
- The GitHub Actions workflow has not been run yet; nothing here claims a green CI.
- `make` itself was not available on the development machine; the Makefile targets were checked by running their commands directly.
- What-If shows the main run and one branch at a time with a divergence marker on the scrubber (not two overlaid tracks).

## Roadmap

Multi-file projects in the UI, asyncio/thread tracing, live narration while a run is in progress, shareable replays
with embedded What-If branches, a hosted demo with the Docker sandbox.

## License

MIT
