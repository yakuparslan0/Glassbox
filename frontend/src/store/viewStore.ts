import { create } from "zustand";
import type { ViewState } from "../types/model";
import { usePlayback } from "./playbackStore";
import { getRunData, stateClient, useRunStore } from "./runStore";

interface ViewStore {
  state: ViewState | null;
  step: number;
}

/** The program state at the current step, rebuilt by the Web Worker. */
export const useViewStore = create<ViewStore>(() => ({ state: null, step: 0 }));

/** Wire playback -> worker -> view store (call once at startup). */
export function initViewSync(): void {
  const refresh = (): void => {
    const step = usePlayback.getState().step;
    if (step < 1) {
      useViewStore.setState({ state: null, step: 0 });
      return;
    }
    void stateClient.stateAtSeq(getRunData().endSeqOfStep(step)).then((state) => {
      if (state && usePlayback.getState().step === step) useViewStore.setState({ state, step });
    });
  };
  usePlayback.subscribe((s, prev) => s.step !== prev.step && refresh());
  // a finished run can change the end-of-step seq of the last step (trailing output/keyframe events)
  useRunStore.subscribe((s, prev) => s.status === "finished" && prev.status !== "finished" && refresh());
}
