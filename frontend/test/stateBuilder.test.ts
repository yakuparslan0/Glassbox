import { describe, expect, it } from "vitest";
import { reachableHeap, StateBuilder } from "../src/lib/stateBuilder";
import type { RunEvent } from "../src/types/generated";
import { fixtureNames, loadFixture } from "./fixtures";

type Snapshot = Extract<RunEvent, { type: "snapshot" }>;

function check(name: string, events: RunEvent[], sequential: boolean): number {
  const snapshots = events.filter((e): e is Snapshot => e.type === "snapshot");
  const builder = new StateBuilder();
  builder.append(events);
  // random order exercises the keyframe jump path; sorted order exercises the sequential cache
  const order = sequential ? snapshots : [...snapshots].sort((a, b) => ((a.seq * 7919) % 101) - ((b.seq * 7919) % 101));
  for (const snap of order) {
    const where = `${name} step ${snap.step} (${sequential ? "sequential" : "random"})`;
    const state = builder.stateAtSeq(snap.seq, !sequential);
    expect(state.stack.map((f) => [f.frame, f.func, f.line]), where).toEqual(snap.stack.map((f) => [f.frame, f.func, f.line]));
    expect(state.globals, where).toEqual(snap.globals);
    if (snap.locals !== null) {
      const frame = state.stack.find((f) => f.frame === snap.frame);
      expect(frame?.locals, where).toEqual(snap.locals);
    }
    const reachable = reachableHeap(state);
    for (const [label, entry] of Object.entries(snap.heap)) expect(reachable[label], `${where} heap ${label}`).toEqual(entry);
  }
  return snapshots.length;
}

describe("StateBuilder reproduces the backend's ground-truth snapshots", () => {
  for (const name of fixtureNames()) {
    it(`${name}: keyframe + delta state equals the live snapshot at every step`, () => {
      const events = loadFixture(name);
      expect(events.some((e) => e.type === "keyframe")).toBe(true);
      const a = check(name, events, true);
      const b = check(name, events, false);
      expect(a).toBeGreaterThan(5);
      expect(b).toBe(a);
    });
  }

  it("works while events are still streaming in (append after a query)", () => {
    const events = loadFixture("fib_naive");
    const builder = new StateBuilder();
    const half = Math.floor(events.length / 2);
    builder.append(events.slice(0, half));
    builder.stateAtSeq(events[half - 1].seq);
    builder.append(events.slice(half));
    const snap = events.filter((e): e is Snapshot => e.type === "snapshot").at(-1) as Snapshot;
    expect(builder.stateAtSeq(snap.seq).globals).toEqual(snap.globals);
  });
});
