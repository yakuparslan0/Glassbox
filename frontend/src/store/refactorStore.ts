import { create } from "zustand";
import { ApiError, requestAutofix, requestRefactor, verifyRefactor } from "../api/http";
import type { Finding, RefactorProposal, VerificationReport } from "../types/generated";
import { useRunStore } from "./runStore";
import { useUiStore } from "./uiStore";

interface Candidate {
  proposal: Pick<RefactorProposal, "finding_id" | "explanation_md" | "why" | "expected_effect" | "source">;
  proposedSource: string;
}

interface RefactorState {
  busy: "suggest" | "verify" | null;
  candidate: Candidate | null;
  verification: VerificationReport | null;
  error: string | null;
  skipped: number;
  undoStack: string[];
  suggest: (finding: Finding) => Promise<void>;
  autofixAll: () => Promise<void>;
  verify: () => Promise<void>;
  apply: () => Promise<void>;
  undo: () => Promise<void>;
  dismiss: () => void;
}

const fail = (e: unknown): string => (e instanceof ApiError ? e.message : String(e));

export const useRefactorStore = create<RefactorState>((set, get) => ({
  busy: null,
  candidate: null,
  verification: null,
  error: null,
  skipped: 0,
  undoStack: [],

  suggest: async (finding) => {
    const { runId, entry } = useRunStore.getState();
    if (!runId) return;
    set({ busy: "suggest", error: null, candidate: null, verification: null, skipped: 0 });
    try {
      const p = await requestRefactor(runId, finding.id, useUiStore.getState().lang);
      const proposedSource = p.proposed_files[entry];
      if (proposedSource === undefined) throw new Error("the proposal does not change the entry file");
      set({ candidate: { proposal: p, proposedSource }, busy: null });
    } catch (e) {
      set({ busy: null, error: fail(e) });
    }
  },

  autofixAll: async () => {
    const { report, entry, runSource } = useRunStore.getState();
    const ids = (report?.findings ?? []).filter((f) => f.autofixable && f.confidence !== "suspect").map((f) => f.id);
    if (runSource === null || !ids.length) return;
    set({ busy: "suggest", error: null, candidate: null, verification: null });
    try {
      const result = await requestAutofix(entry, runSource, ids);
      const file = result.files.find((f) => f.path === entry);
      if (!file) throw new Error("autofix returned no entry file");
      set({
        busy: null,
        skipped: result.skipped.length,
        candidate: {
          proposal: { finding_id: ids.join(","), explanation_md: "", why: `${result.applied.length} fix(es)`, expected_effect: "", source: "autofix" },
          proposedSource: file.content,
        },
      });
    } catch (e) {
      set({ busy: null, error: fail(e) });
    }
  },

  verify: async () => {
    const { candidate } = get();
    const { entry, runSource } = useRunStore.getState();
    if (!candidate || runSource === null) return;
    set({ busy: "verify", error: null, verification: null });
    try {
      const v = await verifyRefactor(entry, runSource, candidate.proposedSource, useUiStore.getState().settings);
      set({ verification: v, busy: null });
    } catch (e) {
      set({ busy: null, error: fail(e) });
    }
  },

  apply: async () => {
    const { candidate, verification, undoStack } = get();
    if (!candidate || !verification || verification.verdict === "broken") return;
    const run = useRunStore.getState();
    set({ undoStack: [...undoStack, run.source], candidate: null, verification: null });
    run.setSource(candidate.proposedSource);
    await run.start();
  },

  undo: async () => {
    const { undoStack } = get();
    const previous = undoStack.at(-1);
    if (previous === undefined) return;
    set({ undoStack: undoStack.slice(0, -1), candidate: null, verification: null });
    const run = useRunStore.getState();
    run.setSource(previous);
    await run.start();
  },

  dismiss: () => set({ candidate: null, verification: null, error: null }),
}));
