// Rebuilds the program state at any point of a trace from "nearest keyframe + deltas" (spec 2.6).
// Pure and DOM-free: used by the Web Worker and by the vitest suite (against the backend's ground truth).
import type { RunEvent } from "../types/generated";
import type { FrameState, HeapEntry, HeapMap, Val, ViewState } from "../types/model";

const STRUCTURAL = new Set(["call", "line", "return", "exception", "keyframe"]);

interface Delta {
  set?: Record<string, Val>;
  del?: string[];
}

function applyDelta(target: Record<string, Val>, delta: Delta | null | undefined): void {
  if (!delta) return;
  if (delta.set) Object.assign(target, delta.set);
  if (delta.del) for (const name of delta.del) delete target[name];
}

function emptyState(): ViewState {
  return { stack: [], globals: {}, heap: {} };
}

function fromKeyframe(ev: Extract<RunEvent, { type: "keyframe" }>): ViewState {
  return {
    stack: ev.stack.map((f) => ({ frame: f.frame, func: f.func, line: f.line, locals: { ...f.locals } })),
    globals: { ...ev.globals },
    heap: { ...ev.heap },
  };
}

/** Apply one structural event to a mutable state (containers are mutated, values are shared and never mutated). */
export function applyEvent(state: ViewState, ev: RunEvent): void {
  if ("heap" in ev && ev.heap && ev.type !== "snapshot") Object.assign(state.heap, ev.heap);
  switch (ev.type) {
    case "call":
      if (ev.kind === "user") {
        state.stack.push({ frame: ev.frame, func: ev.func, line: ev.line, locals: { ...ev.args } });
      }
      applyDelta(state.globals, ev.globals_delta);
      break;
    case "line": {
      const frame = state.stack.find((f) => f.frame === ev.frame);
      if (!frame) throw new Error(`line event for unknown frame ${ev.frame}`);
      frame.line = ev.line;
      // The entry module's locals ARE the globals (frame 1): its delta is the globals delta.
      applyDelta(ev.frame === 1 ? state.globals : frame.locals, ev.delta);
      applyDelta(state.globals, ev.globals_delta);
      break;
    }
    case "return":
      applyDelta(state.globals, ev.globals_delta);
      if (ev.kind !== "boundary") state.stack = state.stack.filter((f) => f.frame !== ev.frame);
      break;
    case "exception":
      applyDelta(state.globals, ev.globals_delta);
      break;
    case "keyframe": {
      const kf = fromKeyframe(ev);
      state.stack = kf.stack;
      state.globals = kf.globals;
      state.heap = kf.heap;
      break;
    }
    default:
      break;
  }
}

function clone(state: ViewState): ViewState {
  return {
    stack: state.stack.map((f: FrameState) => ({ ...f, locals: { ...f.locals } })),
    globals: { ...state.globals },
    heap: { ...state.heap },
  };
}

export class StateBuilder {
  private events: RunEvent[] = []; // structural events only, ascending seq
  private keyframes: number[] = []; // indexes into `events`
  private cache: { idx: number; state: ViewState } | null = null;

  append(batch: readonly RunEvent[]): void {
    for (const ev of batch) {
      if (!STRUCTURAL.has(ev.type)) continue;
      if (ev.type === "keyframe") this.keyframes.push(this.events.length);
      this.events.push(ev);
    }
  }

  get size(): number {
    return this.events.length;
  }

  /** Index of the last structural event with seq <= seq (-1 if none). */
  private indexAt(seq: number): number {
    let lo = 0;
    let hi = this.events.length - 1;
    let found = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (this.events[mid].seq <= seq) {
        found = mid;
        lo = mid + 1;
      } else hi = mid - 1;
    }
    return found;
  }

  private keyframeAtOrBefore(idx: number): number {
    let lo = 0;
    let hi = this.keyframes.length - 1;
    let found = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (this.keyframes[mid] <= idx) {
        found = this.keyframes[mid];
        lo = mid + 1;
      } else hi = mid - 1;
    }
    return found;
  }

  /** State after all events with seq <= `seq`. `fromKeyframeOnly` bypasses the sequential cache (tests). */
  stateAtSeq(seq: number, fromKeyframeOnly = false): ViewState {
    const idx = this.indexAt(seq);
    if (idx < 0) return emptyState();
    const kf = this.keyframeAtOrBefore(idx);
    let state: ViewState;
    let from: number;
    if (!fromKeyframeOnly && this.cache && this.cache.idx <= idx && this.cache.idx >= kf) {
      state = this.cache.state;
      from = this.cache.idx + 1;
    } else {
      state = emptyState();
      from = Math.max(kf, 0);
    }
    for (let i = from; i <= idx; i++) applyEvent(state, this.events[i]);
    this.cache = { idx, state };
    return clone(state);
  }
}

/** Heap objects reachable from the roots (used to compare against ground-truth snapshots). */
export function reachableHeap(state: ViewState): HeapMap {
  const roots: Val[] = [...Object.values(state.globals)];
  for (const f of state.stack) roots.push(...Object.values(f.locals));
  const out: HeapMap = {};
  const todo = roots.filter((v): v is Extract<Val, { ref: string }> => "ref" in v).map((v) => v.ref);
  while (todo.length) {
    const label = todo.pop() as string;
    const entry = state.heap[label];
    if (label in out || !entry) continue;
    out[label] = entry;
    todo.push(...refsOf(entry));
  }
  return out;
}

export function refsOf(entry: HeapEntry): string[] {
  let values: Val[] = [];
  if (entry.k === "seq") values = entry.items;
  else if (entry.k === "map") values = entry.pairs.flat();
  else if (entry.k === "obj") values = Object.values(entry.attrs);
  return values.filter((v): v is Extract<Val, { ref: string }> => "ref" in v).map((v) => v.ref);
}
