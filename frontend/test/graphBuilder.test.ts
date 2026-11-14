import { describe, expect, it } from "vitest";
import { buildGraph } from "../src/lib/graphBuilder";
import { RunData } from "../src/lib/runData";
import { loadFixture } from "./fixtures";

const summary = (name: string) => {
  const g = buildGraph(loadFixture(name));
  return {
    nodes: [...g.nodes.values()].map((n) => [n.label, n.kind, n.calls]).sort(),
    edges: [...g.edges.values()].map((e) => [e.source, e.target, e.count]).sort(),
  };
};

describe("graphBuilder", () => {
  it("fib_naive: <module> -> fib once, fib -> fib for every recursive call", () => {
    // the fixture is capped at 600 steps, so compare against the call events themselves
    const events = loadFixture("fib_naive");
    const fibCalls = events.filter((e) => e.type === "call" && e.kind === "user" && e.func === "fib");
    const s = summary("fib_naive");
    expect(s.nodes).toEqual([["<module>", "user", 1], ["fib", "user", fibCalls.length]]);
    expect(s.edges).toEqual([
      ["fn:main.py:<module>".replace("main.py", "fib_naive.py"), "fn:fib_naive.py:fib", 1],
      ["fn:fib_naive.py:fib", "fn:fib_naive.py:fib", fibCalls.length - 1],
    ]);
  });

  it("json_boundary: library calls become boundary nodes attached to their caller", () => {
    const s = summary("json_boundary");
    const labels = s.nodes.map((n) => n[0]);
    expect(labels).toContain("json.dumps");
    expect(s.nodes.find((n) => n[0] === "json.dumps")?.[1]).toBe("boundary");
    // the lambda called back from sorted() is a user node
    expect(labels).toContain("<lambda>");
  });

  it("topologyVersion changes only when a node or edge is added, not when counts grow", () => {
    const events = loadFixture("fib_naive");
    const g = buildGraph(events.slice(0, 40));
    const v = g.topologyVersion;
    g.append(events.slice(40));
    const calls = events.filter((e) => e.type === "call").length;
    expect(g.topologyVersion).toBeGreaterThanOrEqual(v);
    expect([...g.edges.values()].reduce((a, e) => a + e.count, 0)).toBe(calls - 1);
  });
});

describe("RunData step indexes", () => {
  it("indexes every step and computes step over / step out by call depth", () => {
    const data = new RunData();
    data.append(loadFixture("alias_bug"));
    const total = data.totalSteps;
    expect(total).toBeGreaterThan(10);
    for (let k = 1; k <= total; k++) expect((data.eventOfStep(k) as { step: number }).step).toBe(k);
    // find the call into add_item; step over from it must land after the matching return (same depth as the call line)
    const call = [...Array(total).keys()].map((i) => i + 1).find((k) => {
      const e = data.eventOfStep(k);
      return e?.type === "call" && e.kind === "user" && e.func === "add_item";
    }) as number;
    const over = data.nextStep(call - 1, "over");
    expect(over).toBeGreaterThan(call);
    expect(data.depth[over]).toBeLessThanOrEqual(data.depth[call - 1]);
    const out = data.nextStep(call + 1, "out");
    expect(data.depth[out]).toBeLessThan(data.depth[call + 1]);
  });
});
