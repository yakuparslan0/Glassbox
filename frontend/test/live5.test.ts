// Phase 5 acceptance against a RUNNING stack:  GLASSBOX_LIVE=http://127.0.0.1:5173 npx vitest run test/live5.test.ts
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { plot } from "../src/lib/chart";

const BASE = process.env.GLASSBOX_LIVE;
const example = (name: string): string => readFileSync(join(__dirname, "..", "..", "examples", name), "utf-8");

async function post(path: string, body: unknown): Promise<Response> {
  return fetch(`${BASE}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

async function finishedRun(source: string, overrides: unknown[] = []): Promise<string> {
  const res = await post("/api/runs", { files: [{ path: "main.py", content: source }], entry: "main.py", overrides });
  expect(res.status).toBe(201);
  const { run_id } = (await res.json()) as { run_id: string };
  for (let i = 0; i < 200; i++) {
    const s = (await (await fetch(`${BASE}/api/runs/${run_id}`)).json()) as { state: string };
    if (s.state !== "running") return run_id;
    await new Promise((r) => setTimeout(r, 50));
  }
  throw new Error("run did not finish");
}

describe.skipIf(!BASE)("phase 5 live stack", () => {
  it("what-if: fixing count makes the branch succeed and the divergence step is reported", async () => {
    const src = example("crash_chain.py");
    const base = await finishedRun(src);
    const trace = (await (await fetch(`${BASE}/api/runs/${base}/trace`)).text()).split("\n").filter(Boolean).map((l) => JSON.parse(l) as { type: string; line?: number; step: number });
    const step = trace.find((e) => e.type === "line" && e.line === 14)?.step as number;
    const branch = await finishedRun(src, [{ step, frame_depth: 2, name: "count", value_literal: "1" }]);
    const cmp = (await (await fetch(`${BASE}/api/runs/${base}/compare?other=${branch}`)).json()) as {
      first_divergence_step: number;
      base: { status: string };
      branch: { status: string };
    };
    expect([cmp.base.status, cmp.branch.status]).toEqual(["exception", "ok"]);
    expect(cmp.first_divergence_step).toBeGreaterThanOrEqual(step);
    const bad = await post("/api/runs", { files: [{ path: "main.py", content: src }], entry: "main.py", overrides: [{ step, frame_depth: 2, name: "count", value_literal: "__import__('os')" }] });
    expect(bad.status).toBe(422);
  });

  it("root cause: the chain runs from the data to the failing line and the exports download", async () => {
    const id = await finishedRun(example("crash_chain.py"));
    const chain = (await (await fetch(`${BASE}/api/runs/${id}/rootcause`)).json()) as { links: { kind: string; name: string; line: number }[] };
    expect(chain.links.at(-1)?.kind).toBe("error");
    expect(chain.links.some((l) => l.kind === "return" && l.name === "load_count")).toBe(true);
    for (const [kind, type] of [["mermaid", "text/plain"], ["svg", "image/svg+xml"], ["html", "text/html"]] as const) {
      const r = await fetch(`${BASE}/api/export/${id}/${kind}`);
      expect(r.status).toBe(200);
      expect(r.headers.get("content-type")).toContain(type);
    }
    const html = await (await fetch(`${BASE}/api/export/${id}/html`)).text();
    expect(html).not.toMatch(/https?:\/\//);
  });

  it("big-o lab through the proxy: bubble sort is quadratic and the chart geometry covers every point", async () => {
    const res = await post("/api/lab/bigo", { files: [{ path: "main.py", content: example("bubble_sort.py") }], entry: "main.py", func: "bubble_sort", generator: "random_ints", sizes: [8, 16, 32, 64, 128] });
    expect(res.status).toBe(200);
    const report = (await res.json()) as { best: { model: string; r2: number; predicted: number[] }; points: { n: number; steps: number }[]; note: string };
    expect(report.best.model).toBe("n^2");
    expect(report.best.r2).toBeGreaterThan(0.99);
    expect(report.note).toContain("not a proof");
    const p = plot(report.points, report.best.predicted, 360, 200);
    expect(p.points).toHaveLength(report.points.length);
    expect(p.points.every((pt) => pt.x >= 0 && pt.x <= 360 && pt.y >= 0 && pt.y <= 200)).toBe(true);
  });
});
