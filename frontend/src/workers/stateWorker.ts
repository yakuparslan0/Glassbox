/// <reference lib="webworker" />
// Web Worker: keeps its own StateBuilder and answers "state at seq" requests (latest-wins on the client).
import { StateBuilder } from "../lib/stateBuilder";
import type { RunEvent } from "../types/generated";
import type { ViewState } from "../types/model";

export type WorkerIn =
  | { type: "reset" }
  | { type: "append"; events: RunEvent[] }
  | { type: "state"; id: number; seq: number };

export type WorkerOut = { type: "state"; id: number; state: ViewState } | { type: "error"; id: number; message: string };

let builder = new StateBuilder();
const post = (m: WorkerOut): void => (self as unknown as DedicatedWorkerGlobalScope).postMessage(m);

self.onmessage = (msg: MessageEvent<WorkerIn>) => {
  const m = msg.data;
  if (m.type === "reset") builder = new StateBuilder();
  else if (m.type === "append") builder.append(m.events);
  else {
    try {
      post({ type: "state", id: m.id, state: builder.stateAtSeq(m.seq) });
    } catch (e) {
      post({ type: "error", id: m.id, message: String(e) });
    }
  }
};
