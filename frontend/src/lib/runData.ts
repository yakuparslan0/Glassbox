// Flat, non-reactive storage of one run's events plus step indexes (no React state per event, spec section 8).
import type { RunEvent } from "../types/generated";
import { GraphBuilder } from "./graphBuilder";

const STEP_TYPES = new Set(["call", "line", "return", "exception"]);

export interface OutputChunk {
  step: number;
  stream: "stdout" | "stderr";
  text: string;
}

export class RunData {
  events: RunEvent[] = [];
  /** stepIndex[k] = index in `events` of the event that created step k (k >= 1; slot 0 unused). */
  stepIndex: number[] = [0];
  /** user call depth AFTER step k */
  depth: number[] = [0];
  outputs: OutputChunk[] = [];
  exceptionSteps: number[] = [];
  outputSteps: number[] = [];
  boundarySteps: number[] = [];
  readonly graph = new GraphBuilder();
  /** Executed-line hit counts per file (heat map), accumulated from line events. */
  readonly hits = new Map<string, Map<number, number>>();
  private level = 0;
  private frameFile = new Map<number, string>();

  get totalSteps(): number {
    return this.stepIndex.length - 1;
  }

  append(batch: readonly RunEvent[]): void {
    this.graph.append(batch);
    for (const ev of batch) {
      const idx = this.events.length;
      this.events.push(ev);
      if (ev.type === "output") {
        this.outputs.push({ step: ev.step, stream: ev.stream, text: ev.text });
        if (this.outputSteps[this.outputSteps.length - 1] !== ev.step) this.outputSteps.push(ev.step);
        continue;
      }
      if (!STEP_TYPES.has(ev.type)) continue;
      const step = (ev as { step: number }).step;
      if (ev.type === "call") {
        if (ev.kind === "user") {
          this.level++;
          this.frameFile.set(ev.frame, ev.file);
        } else this.boundarySteps.push(step);
      } else if (ev.type === "return" && ev.kind !== "boundary") {
        this.level = Math.max(0, this.level - 1);
      } else if (ev.type === "exception" && !ev.handled) {
        this.exceptionSteps.push(step);
      } else if (ev.type === "line") {
        const file = this.frameFile.get(ev.frame);
        if (file) {
          let m = this.hits.get(file);
          if (!m) this.hits.set(file, (m = new Map()));
          m.set(ev.line, (m.get(ev.line) ?? 0) + 1);
        }
      }
      this.stepIndex[step] = idx;
      this.depth[step] = this.level;
    }
  }

  /** Seq of the last event that still belongs to step k (state of step k = state after this seq). */
  endSeqOfStep(k: number): number {
    const next = this.stepIndex[k + 1];
    const end = next === undefined ? this.events.length - 1 : next - 1;
    return this.events[end]?.seq ?? 0;
  }

  eventOfStep(k: number): RunEvent | undefined {
    const i = this.stepIndex[k];
    return i === undefined ? undefined : this.events[i];
  }

  /** Next step after k whose call depth is <= depth(k) (step over) or < depth(k) (step out). */
  nextStep(k: number, mode: "over" | "out"): number {
    const total = this.totalSteps;
    const here = this.depth[k] ?? 0;
    for (let j = k + 1; j <= total; j++) {
      if (mode === "over" ? this.depth[j] <= here : this.depth[j] < here) return j;
    }
    return total;
  }

  outputUpTo(step: number): string {
    let text = "";
    for (const o of this.outputs) {
      if (o.step > step) break;
      text += o.text;
    }
    return text;
  }
}
