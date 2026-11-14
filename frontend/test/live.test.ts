// Live acceptance checks against a RUNNING stack (vite dev server proxying to `glassbox serve`).
//   GLASSBOX_LIVE=http://127.0.0.1:5173 npx vitest run test/live.test.ts
// Skipped when GLASSBOX_LIVE is not set. It drives the same modules the UI uses (RunData, StateBuilder, GraphBuilder,
// heap graph), so it checks the data path end to end; it does NOT render pixels.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { buildHeapGraph } from "../src/lib/heapGraph";
import { RunData } from "../src/lib/runData";
import { StateBuilder } from "../src/lib/stateBuilder";
import type { RunEvent } from "../src/types/generated";

const BASE = process.env.GLASSBOX_LIVE;
const example = (name: string): string => readFileSync(join(__dirname, "..", "..", "examples", name), "utf-8");

interface LiveRun {
  batches: RunEvent[][];
  events: RunEvent[];
}

async function runLive(source: string, limits: Record<string, number> = {}): Promise<LiveRun> {
  const res = await fetch(`${BASE}/api/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ files: [{ path: "main.py", content: source }], entry: "main.py", limits }),
  });
  expect(res.status).toBe(201);
  const { run_id } = (await res.json()) as { run_id: string };
  const wsUrl = `${(BASE as string).replace("http", "ws")}/ws/runs/${run_id}`;
  const batches: RunEvent[][] = [];
  await new Promise<void>((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    ws.onmessage = (m) => batches.push((JSON.parse(String(m.data)) as { batch: RunEvent[] }).batch);
    ws.onclose = () => resolve();
    ws.onerror = () => reject(new Error("websocket error"));
  });
  return { batches, events: batches.flat() };
}

describe.skipIf(!BASE)("live stack", () => {
  it("fib_naive: the graph grows batch by batch and ends with the expected counts", async () => {
    const { batches, events } = await runLive(example("fib_naive.py"));
    expect(events.map((e) => e.seq)).toEqual(events.map((_, i) => i + 1));
    const data = new RunData();
    let lastNodes = 0;
    let lastCalls = 0;
    for (const b of batches) {
      data.append(b);
      expect(data.graph.nodes.size).toBeGreaterThanOrEqual(lastNodes);
      const calls = [...data.graph.nodes.values()].reduce((a, n) => a + n.calls, 0);
      expect(calls).toBeGreaterThanOrEqual(lastCalls);
      lastNodes = data.graph.nodes.size;
      lastCalls = calls;
    }
    const fib = [...data.graph.nodes.values()].find((n) => n.label === "fib");
    expect(fib?.calls).toBe(177);
    expect(data.graph.edges.get("fn:main.py:fib->fn:main.py:fib")?.count).toBe(176);
  });

  it("random jumps (back/forward/step over/out) land on the right line with the right stack", async () => {
    const { events } = await runLive(example("fib_naive.py"));
    const data = new RunData();
    data.append(events);
    const builder = new StateBuilder();
    builder.append(events);
    let seed = 12345;
    const rnd = (): number => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
    for (let i = 0; i < 300; i++) {
      const k = 1 + Math.floor(rnd() * data.totalSteps);
      const ev = data.eventOfStep(k) as RunEvent;
      const state = builder.stateAtSeq(data.endSeqOfStep(k));
      if (ev.type === "line") {
        const top = state.stack.at(-1);
        expect([top?.frame, top?.line]).toEqual([ev.frame, ev.line]);
      }
      expect(state.stack.length).toBe(data.depth[k]);
      if (ev.type === "line" && ev.frame !== 1) {
        const frame = state.stack.find((f) => f.frame === ev.frame);
        expect(frame?.locals.n).toBeDefined(); // fib(n): n is visible in every recursive frame
      }
    }
    // step over from a recursive call lands at the same depth, step out one level up
    const callStep = [...Array(data.totalSteps).keys()].map((i) => i + 1).find((k) => data.eventOfStep(k)?.type === "call" && data.depth[k] === 3) as number;
    expect(data.depth[data.nextStep(callStep - 1, "over")]).toBeLessThanOrEqual(data.depth[callStep - 1]);
    expect(data.depth[data.nextStep(callStep, "out")]).toBeLessThan(data.depth[callStep]);
  });

  it("20,000 steps: indexing and 500 random scrubs stay fast", async () => {
    const { events } = await runLive("total = 0\nfor i in range(30000):\n    total += i\n");
    const data = new RunData();
    const builder = new StateBuilder();
    const t0 = performance.now();
    data.append(events);
    builder.append(events);
    expect(data.totalSteps).toBe(20000);
    let seed = 7;
    const rnd = (): number => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
    for (let i = 0; i < 500; i++) {
      const k = 1 + Math.floor(rnd() * data.totalSteps);
      const state = builder.stateAtSeq(data.endSeqOfStep(k));
      expect(state.stack.length).toBeGreaterThan(0);
    }
    const ms = performance.now() - t0;
    console.log(`20k steps: index + 500 random scrubs took ${ms.toFixed(0)} ms`);
    expect(ms).toBeLessThan(3000);
  });

  it("infinite_loop: ends with a step-limit event and status 'limit'", async () => {
    const { events } = await runLive(example("infinite_loop.py"), { max_steps: 2000 });
    const limit = events.find((e) => e.type === "limit_exceeded");
    expect(limit && limit.type === "limit_exceeded" && limit.limit).toBe("max_steps");
    expect(events.at(-1)).toMatchObject({ type: "run_finished", status: "limit" });
  });

  it("alias_bug: the shared list shows up as ONE object with two names pointing at it", async () => {
    const { events } = await runLive(example("alias_bug.py"));
    const data = new RunData();
    data.append(events);
    const builder = new StateBuilder();
    builder.append(events);
    const last = builder.stateAtSeq(data.endSeqOfStep(data.totalSteps - 1));
    const refs = (["original", "copy"] as const).map((n) => (last.globals[n] as { ref: string }).ref);
    expect(refs[0]).toBe(refs[1]);
    const { nodes, edges } = buildHeapGraph(last);
    const shared = nodes.find((n) => n.id === refs[0]);
    expect(shared?.data.alias).toBe(2);
    expect(edges.filter((e) => e.target === refs[0]).map((e) => e.label).sort()).toEqual(["copy", "original"]);
    // the earlier module-level pair first/second also alias the mutable-default list
    const firstSecond = (["first", "second"] as const).map((n) => (last.globals[n] as { ref: string }).ref);
    expect(firstSecond[0]).toBe(firstSecond[1]);
  });
});
