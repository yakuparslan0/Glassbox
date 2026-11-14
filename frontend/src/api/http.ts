import type { AutofixResult, MarkSweepReport, RefactorProposal, RunCreated, RunSummary, VerificationReport } from "../types/generated";
import type { RunSettings } from "../store/uiStore";
import { t } from "../i18n";

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(t("err.backend"));
  }
  if (res.status === 429) throw new ApiError(t("err.busy"));
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(t("err.http", { code: res.status, detail }));
  }
  return (await res.json()) as T;
}

export function createRun(source: string, entry: string, s: RunSettings): Promise<RunCreated> {
  return request<RunCreated>("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      files: [{ path: entry, content: source }],
      entry,
      stdin: s.stdin,
      seed: s.seed,
      filter: s.filter,
      limits: { max_steps: s.maxSteps, timeout_s: s.timeoutS },
    }),
  });
}

export const getRun = (id: string): Promise<RunSummary> => request<RunSummary>(`/api/runs/${id}`);
export const getMarkSweep = (id: string): Promise<MarkSweepReport> => request<MarkSweepReport>(`/api/runs/${id}/marksweep`);

export const requestRefactor = (runId: string, findingId: string, lang: string): Promise<RefactorProposal> =>
  request<RefactorProposal>(`/api/mentor/refactor?lang=${lang}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId, finding_id: findingId }),
  });

export const requestAutofix = (path: string, content: string, findingIds: string[]): Promise<AutofixResult> =>
  request<AutofixResult>("/api/refactor/autofix", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ files: [{ path, content }], entry: path, finding_ids: findingIds }),
  });

export const verifyRefactor = (
  path: string,
  original: string,
  proposed: string,
  s: RunSettings,
): Promise<VerificationReport> =>
  request<VerificationReport>("/api/refactor/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      original_files: [{ path, content: original }],
      proposed_files: [{ path, content: proposed }],
      entry: path,
      stdin: s.stdin,
      seed: s.seed,
    }),
  });

export const narrateUrl = (runId: string, lang: string, llm: boolean): string =>
  `/api/mentor/narrate?run_id=${runId}&lang=${lang}&llm=${llm}`;
