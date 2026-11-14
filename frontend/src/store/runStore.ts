import { create } from "zustand";
import { ApiError, createRun, getMarkSweep } from "../api/http";
import { connectRun, type RunConnection } from "../api/ws";
import { t } from "../i18n";
import { RunData } from "../lib/runData";
import { StateClient } from "../lib/stateClient";
import type { MarkSweepReport, RunEvent, RunFinished } from "../types/generated";
import { usePlayback } from "./playbackStore";
import { useUiStore } from "./uiStore";

// Events live in plain structures outside React state; the store only carries counters (spec section 8).
let data = new RunData();
export const getRunData = (): RunData => data;
export const stateClient = new StateClient();

export type Status = "idle" | "starting" | "running" | "finished" | "error";

interface RunState {
  entry: string;
  source: string;
  runSource: string | null; // the source the current trace belongs to
  runId: string | null;
  status: Status;
  version: number; // bumps once per flushed batch
  totalSteps: number;
  finished: RunFinished | null;
  limitDetail: { limit: string; detail: string } | null;
  errorText: string | null;
  report: MarkSweepReport | null;
  reportLoading: boolean;
  setSource: (source: string) => void;
  loadExample: (name: string, source: string) => void;
  start: () => Promise<void>;
  stop: () => void;
  analyze: () => Promise<void>;
}

let connection: RunConnection | null = null;
let token = 0;

export const useRunStore = create<RunState>((set, get) => ({
  entry: "main.py",
  source: "",
  runSource: null,
  runId: null,
  status: "idle",
  version: 0,
  totalSteps: 0,
  finished: null,
  limitDetail: null,
  errorText: null,
  report: null,
  reportLoading: false,

  setSource: (source) => set({ source }),
  loadExample: (name, source) => set({ source, entry: name }),

  start: async () => {
    connection?.close();
    const mine = ++token;
    data = new RunData();
    stateClient.reset();
    usePlayback.getState().reset();
    const source = get().source;
    set({
      status: "starting", runId: null, version: 0, totalSteps: 0, finished: null, limitDetail: null,
      errorText: null, report: null, reportLoading: false, runSource: source,
    });
    try {
      const { run_id } = await createRun(source, get().entry, useUiStore.getState().settings);
      if (mine !== token) return;
      set({ runId: run_id, status: "running" });
      connection = connectRun(
        run_id,
        (events: RunEvent[]) => {
          if (mine !== token) return;
          data.append(events);
          stateClient.append(events);
          const patch: Partial<RunState> = { version: get().version + 1, totalSteps: data.totalSteps };
          for (const ev of events) {
            if (ev.type === "limit_exceeded") patch.limitDetail = { limit: ev.limit, detail: ev.detail };
            if (ev.type === "run_finished") {
              patch.finished = ev;
              patch.status = "finished";
            }
          }
          set(patch);
          if (usePlayback.getState().follow && data.totalSteps > 0) usePlayback.setState({ step: data.totalSteps });
        },
        () => mine === token && set({ status: get().finished ? "finished" : "error" }),
        () => mine === token && set({ status: "error", errorText: t("err.ws") }),
      );
    } catch (e) {
      if (mine === token) set({ status: "error", errorText: e instanceof ApiError ? e.message : String(e) });
    }
  },

  stop: () => connection?.cancel(),

  analyze: async () => {
    const { runId, status } = get();
    if (!runId || status !== "finished") return;
    set({ reportLoading: true });
    try {
      const report = await getMarkSweep(runId);
      set({ report, reportLoading: false });
    } catch (e) {
      set({ reportLoading: false, errorText: e instanceof ApiError ? e.message : String(e) });
    }
  },
}));

/** Actionable message for how a run ended (limit / blocked / exception ...), or null when it simply succeeded. */
export function endMessage(s: Pick<RunState, "finished" | "limitDetail">): string | null {
  const f = s.finished;
  if (!f || f.status === "ok") return null;
  const detail = f.detail ?? "";
  switch (f.status) {
    case "limit": {
      const lim = s.limitDetail;
      const key = `err.limit.${lim?.limit ?? "max_steps"}` as const;
      return t(key as "err.limit.max_steps", { detail: lim?.detail ?? detail });
    }
    case "blocked":
      return t("err.blocked", { detail });
    case "exception":
      return t("err.exception", { detail });
    default:
      return t("err.killed", { detail: s.limitDetail?.detail ?? detail });
  }
}
