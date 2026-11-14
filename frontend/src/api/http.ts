import type { MarkSweepReport, RunCreated, RunSummary } from "../types/generated";
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
