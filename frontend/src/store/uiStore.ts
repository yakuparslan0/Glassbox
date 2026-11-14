import { create } from "zustand";
import type { Lang } from "../i18n";

export type CenterTab = "graph" | "tree" | "heap";
export type RightTab = "timeline" | "vars" | "cleanup";

export interface RunSettings {
  maxSteps: number;
  timeoutS: number;
  filter: "user_only" | "boundaries" | "boundaries_verbose";
  stdin: string;
  seed: number;
  inlineValues: boolean;
}

export interface Reveal {
  start: number;
  end: number;
  nonce: number;
}

interface UiState {
  lang: Lang;
  centerTab: CenterTab;
  rightTab: RightTab;
  settings: RunSettings;
  showSettings: boolean;
  reveal: Reveal | null;
  setLang: (lang: Lang) => void;
  setCenterTab: (tab: CenterTab) => void;
  setRightTab: (tab: RightTab) => void;
  patchSettings: (patch: Partial<RunSettings>) => void;
  toggleSettings: () => void;
  revealLines: (start: number, end: number) => void;
}

const stored = (): Lang => {
  try {
    return localStorage.getItem("glassbox.lang") === "en" ? "en" : "tr";
  } catch {
    return "tr";
  }
};

export const useUiStore = create<UiState>((set) => ({
  lang: stored(),
  centerTab: "graph",
  rightTab: "timeline",
  settings: { maxSteps: 20000, timeoutS: 10, filter: "boundaries", stdin: "", seed: 0, inlineValues: true },
  showSettings: false,
  reveal: null,
  setLang: (lang) => {
    try {
      localStorage.setItem("glassbox.lang", lang);
    } catch {
      /* storage may be blocked; the language still switches for this session */
    }
    set({ lang });
  },
  setCenterTab: (centerTab) => set({ centerTab }),
  setRightTab: (rightTab) => set({ rightTab }),
  patchSettings: (patch) => set((s) => ({ settings: { ...s.settings, ...patch } })),
  toggleSettings: () => set((s) => ({ showSettings: !s.showSettings })),
  revealLines: (start, end) => set({ reveal: { start, end, nonce: Date.now() } }),
}));
