# Phase 3 manual verification checklist

Start the stack: `make serve` (terminal 1) and `cd frontend && npm run dev` (terminal 2), open http://localhost:5173.

**How this was applied:** the development session had no browser tool, so items that need to SEE the UI could not be
ticked by the author. They are marked `UI` below and still have to be walked through once by a human. What was
automated against a live stack (`GLASSBOX_LIVE=http://127.0.0.1:5173 npx vitest run test/live.test.ts`) drives the same
modules the UI uses (RunData, StateBuilder, GraphBuilder, heap graph) through the real vite proxy, WebSocket and runner.

| # | Check | How | Result |
|---|-------|-----|--------|
| 1 | `fib_naive.py`: the call graph grows live while it runs | live test: node/edge/call counts never shrink batch by batch; final `fib` node = 1973 calls, `fib->fib` edge = 1972 | data path PASS · rendering `UI` |
| 2 | Back / forward / step over / step out / slider jump show the right line and variables | live test: 300 random steps: top frame + line equal the step's event, stack depth equals the recorded depth, `n` visible in recursive frames; step over/out depth rules | data path PASS · highlight/gutter `UI` |
| 3 | A 20,000-step trace scrubs smoothly | live test: 20,000 steps indexed and 500 random state rebuilds in 13 ms total | logic PASS (13 ms) · frame rate `UI` |
| 4 | `infinite_loop.py` gives an understandable limit message | live test: `limit_exceeded(max_steps)` + `run_finished(status=limit)`; the banner text comes from `err.limit.max_steps` (tr/en) | events PASS · banner text `UI` |
| 5 | `alias_bug.py`: the shared object shows up with two arrows in the Heap view | live test: `original` and `copy` resolve to ONE heap label; the heap graph marks it `alias=2` and has two edges (`original`, `copy`) into it | graph model PASS · arrows/highlight `UI` |
| 6 | Mark & Sweep: findings listed, click navigates the editor, dead code struck through, cold code dotted | backend suite covers the report; client wiring typed and built | `UI` |
| 7 | Language switch tr/en, settings popover (limits, filter, stdin, seed), stale-code warning, empty state | built and type-checked; dictionary keys enforced equal by the compiler | `UI` |
| 8 | Keyboard: Space plays/pauses, ←/→ step (editor focus is ignored) | implemented in `TransportBar` | `UI` |

| 9 | Mentor tab / narration strip: Layer A text appears after a run, scenes follow the playhead, "Explain with the LLM" streams and falls back with a notice | backend SSE tests (mock LLM, exhausted keys) + live test through the proxy + SSE parser unit tests | stream PASS · rendering `UI` |
| 10 | Refactor tab: suggestion -> diff -> Verify -> badge -> Apply and re-run -> Undo; broken disables Apply; behaviour change asks for confirmation | backend tests for every verdict; store/panel typed and built | `UI` |

Run the `UI` rows once in a browser before relying on Phase 3.
