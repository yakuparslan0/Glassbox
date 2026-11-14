import { create } from "zustand";
import { narrateUrl } from "../api/http";
import { readSse } from "../lib/sseParser";
import { useRunStore } from "./runStore";
import { useUiStore } from "./uiStore";

export interface MentorScene {
  index: number;
  kind: string;
  title: string;
  from_step: number;
  to_step: number;
  text: string;
  source: "narrator" | "llm";
  done: boolean;
}

interface MentorState {
  runId: string | null;
  scenes: MentorScene[];
  loading: boolean;
  llmRequested: boolean;
  fellBack: boolean;
  error: string | null;
  load: (runId: string, llm: boolean) => Promise<void>;
  clear: () => void;
}

let abort: AbortController | null = null;

export const useMentorStore = create<MentorState>((set, get) => ({
  runId: null,
  scenes: [],
  loading: false,
  llmRequested: false,
  fellBack: false,
  error: null,

  clear: () => {
    abort?.abort();
    set({ runId: null, scenes: [], loading: false, fellBack: false, error: null });
  },

  /** Layer A text arrives instantly; with `llm` the scene text is replaced by the streamed LLM tokens. */
  load: async (runId, llm) => {
    abort?.abort();
    abort = new AbortController();
    set({ runId, scenes: [], loading: true, llmRequested: llm, fellBack: false, error: null });
    const patch = (index: number, fn: (s: MentorScene) => MentorScene): void =>
      set({ scenes: get().scenes.map((s) => (s.index === index ? fn(s) : s)) });
    try {
      await readSse(
        narrateUrl(runId, useUiStore.getState().lang, llm),
        ({ event, data }) => {
          const d = data as Record<string, unknown>;
          if (event === "meta") {
            set({
              scenes: (d.scenes as Omit<MentorScene, "text" | "source" | "done">[]).map((s) => ({
                ...s, text: "", source: "narrator", done: false,
              })),
            });
          } else if (event === "layer_a") {
            patch(d.scene as number, (s) => (s.source === "llm" ? s : { ...s, text: d.text as string }));
          } else if (event === "token") {
            patch(d.scene as number, (s) => ({ ...s, text: (s.source === "llm" ? s.text : "") + (d.text as string), source: "llm" }));
          } else if (event === "fallback") {
            set({ fellBack: true });
            patch(d.scene as number, (s) => ({ ...s, text: d.text as string, source: "narrator" }));
          } else if (event === "scene_done") {
            patch(d.scene as number, (s) => ({ ...s, done: true }));
          }
        },
        abort.signal,
      );
      set({ loading: false });
    } catch (e) {
      if ((e as Error).name !== "AbortError") set({ loading: false, error: (e as Error).message });
    }
  },
}));

/** Wire the run lifecycle to the narration: reset on a new run, Layer A (free, instant) as soon as it finishes. */
export function initMentorSync(): void {
  useRunStore.subscribe((s, prev) => {
    if (s.status === "starting" && prev.status !== "starting") useMentorStore.getState().clear();
    if (s.status === "finished" && prev.status !== "finished" && s.runId) void useMentorStore.getState().load(s.runId, false);
  });
}
