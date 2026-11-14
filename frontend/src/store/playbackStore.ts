import { create } from "zustand";
import { getRunData } from "./runStore";

export const SPEEDS = [0.25, 0.5, 1, 2, 4, 8, 16] as const;

interface PlaybackState {
  step: number; // 0 = nothing selected yet
  follow: boolean; // live: playhead sticks to the newest step until the user scrubs back
  playing: boolean;
  speed: number;
  goTo: (step: number) => void;
  prev: () => void;
  next: () => void;
  over: () => void;
  out: () => void;
  toStart: () => void;
  togglePlay: () => void;
  setSpeed: (speed: number) => void;
  reset: () => void;
}

export const usePlayback = create<PlaybackState>((set, get) => {
  const clamp = (k: number): number => Math.max(1, Math.min(k, getRunData().totalSteps));
  const jump = (k: number): void => {
    const total = getRunData().totalSteps;
    if (total === 0) return;
    const step = clamp(k);
    set({ step, follow: step >= total && get().follow });
  };
  return {
    step: 0,
    follow: true,
    playing: false,
    speed: 1,
    goTo: (k) => {
      const total = getRunData().totalSteps;
      if (total === 0) return;
      const step = clamp(k);
      set({ step, follow: false }); // scrubbing leaves live-follow mode (spec section 8)
    },
    prev: () => set({ follow: false, step: clamp(get().step - 1) }),
    next: () => jump(get().step + 1),
    over: () => jump(getRunData().nextStep(get().step, "over")),
    out: () => jump(getRunData().nextStep(get().step, "out")),
    toStart: () => set({ step: getRunData().totalSteps ? 1 : 0, follow: false, playing: false }),
    togglePlay: () => set({ playing: !get().playing }),
    setSpeed: (speed) => set({ speed }),
    reset: () => set({ step: 0, follow: true, playing: false }),
  };
});
