import { create } from "zustand";
import { ApiError, getComparison } from "../api/http";
import type { BranchComparison } from "../types/generated";
import { t } from "../i18n";
import { useRunStore } from "./runStore";

export interface Branch {
  runId: string;
  name: string;
  comparison: BranchComparison | null;
}

interface BranchState {
  baseRunId: string | null;
  branches: Branch[];
  activeRunId: string | null;
  pending: string | null; // name of the branch that is running right now
  error: string | null;
  create: (override: { name: string; depth: number; step: number; literal: string }) => Promise<void>;
  switchTo: (runId: string) => void;
  clear: () => void;
}

export const useBranchStore = create<BranchState>((set, get) => ({
  baseRunId: null,
  branches: [],
  activeRunId: null,
  pending: null,
  error: null,

  clear: () => set({ baseRunId: null, branches: [], activeRunId: null, pending: null, error: null }),

  create: async ({ name, depth, step, literal }) => {
    const run = useRunStore.getState();
    const base = get().baseRunId ?? run.runId;
    if (!base) return;
    const label = t("branch.name", { n: get().branches.length + 1 });
    set({ baseRunId: base, pending: label, error: null });
    await run.start([{ step, frame_depth: depth, name, value_literal: literal }]);
    const started = useRunStore.getState();
    if (started.status === "error" || !started.runId) {
      set({ pending: null, error: started.errorText });
      return;
    }
    set({ branches: [...get().branches, { runId: started.runId, name: label, comparison: null }], activeRunId: started.runId });
  },

  switchTo: (runId) => {
    set({ activeRunId: runId });
    useRunStore.getState().attach(runId);
  },
}));

/** When a branch run finishes, fetch its comparison with the base run. */
export function initBranchSync(): void {
  useRunStore.subscribe((s, prev) => {
    const b = useBranchStore.getState();
    if (s.status === "starting" && prev.status !== "starting" && !b.pending) {
      // a plain (non-branch) run starts a new experiment: forget old branches
      if (b.branches.length) b.clear();
    }
    if (s.status === "finished" && prev.status !== "finished" && s.runId && b.baseRunId && s.runId !== b.baseRunId) {
      const branch = b.branches.find((x) => x.runId === s.runId);
      if (!branch || branch.comparison) {
        useBranchStore.setState({ pending: null });
        return;
      }
      void getComparison(b.baseRunId, s.runId)
        .then((comparison) =>
          useBranchStore.setState({
            pending: null,
            branches: useBranchStore.getState().branches.map((x) => (x.runId === s.runId ? { ...x, comparison } : x)),
          }),
        )
        .catch((e: unknown) => useBranchStore.setState({ pending: null, error: e instanceof ApiError ? e.message : String(e) }));
    }
  });
}
