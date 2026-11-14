import { DiffEditor } from "@monaco-editor/react";
import "../../lib/monaco";
import { useT } from "../../i18n";
import type { Key } from "../../i18n";
import { useRefactorStore } from "../../store/refactorStore";
import { useRunStore } from "../../store/runStore";
import { useUiStore } from "../../store/uiStore";

const GOOD = new Set(["verified_faster", "verified_equal"]);

export function RefactorPanel(): React.ReactElement {
  const t = useT();
  const run = useRunStore();
  const r = useRefactorStore();
  const reveal = useUiStore((s) => s.revealLines);
  const findings = run.report?.findings ?? [];
  const autofixable = findings.filter((f) => f.autofixable && f.confidence !== "suspect");
  const v = r.verification;
  const candidate = r.candidate;
  const num = (x: number): string => (x >= 10 ? x.toFixed(1) : x.toFixed(3));

  const onApply = (): void => {
    if (v?.verdict === "behavior_changed" && !window.confirm(t("refactor.applyConfirm"))) return;
    void r.apply();
  };

  return (
    <div className="h-full overflow-auto p-3 text-sm">
      {!run.report && <p className="opacity-70">{t("refactor.analyzeFirst")}</p>}
      {r.undoStack.length > 0 && <button className="gb-btn mb-2" onClick={() => void r.undo()}>↩ {t("refactor.undo")}</button>}
      {run.report && (
        <>
          <button className="gb-btn mb-2" disabled={!autofixable.length || r.busy !== null} onClick={() => void r.autofixAll()}>
            🧹 {t("refactor.autofixAll")} {autofixable.length ? `(${autofixable.length})` : `– ${t("refactor.autofixNone")}`}
          </button>
          <ul className="grid gap-1 mb-3">
            {findings.map((f) => (
              <li key={f.id} className="flex gap-2 items-baseline">
                <button className="gb-link font-mono" onClick={() => reveal(f.start_line, f.end_line)}>{f.start_line}</button>
                <span className="flex-1">{t(`cat.${f.category}` as Key)} — <span className="opacity-70">{f.title}</span></span>
                <button className="gb-btn" disabled={r.busy !== null} onClick={() => void r.suggest(f)}>{t("refactor.suggest")}</button>
              </li>
            ))}
          </ul>
        </>
      )}
      {r.busy === "suggest" && <p className="opacity-70">{t("mentor.loading")}</p>}
      {r.error && <p role="alert" className="gb-banner-error px-2 py-1 rounded mb-2">{r.error}</p>}
      {r.skipped > 0 && <p className="opacity-70">{t("refactor.skipped", { n: r.skipped })}</p>}

      {candidate && run.runSource !== null && (
        <section className="border border-[var(--border)] rounded p-2 grid gap-2" aria-label="proposal">
          <div className="flex gap-2 items-baseline">
            <span className="gb-chip">{t(candidate.proposal.source === "llm" ? "refactor.source.llm" : "refactor.source.autofix")}</span>
            <strong>{candidate.proposal.why}</strong>
            <button className="gb-link ml-auto" onClick={r.dismiss}>✕</button>
          </div>
          {candidate.proposal.explanation_md && <p className="whitespace-pre-wrap">{candidate.proposal.explanation_md}</p>}
          {candidate.proposal.expected_effect && !v && (
            <p><span className="gb-chip gb-conf-suspect">{t("refactor.expected")}</span> {candidate.proposal.expected_effect}</p>
          )}
          <div style={{ height: 260 }}>
            <DiffEditor
              original={run.runSource}
              modified={candidate.proposedSource}
              language="python"
              theme="vs-dark"
              options={{ readOnly: true, renderSideBySide: true, minimap: { enabled: false }, automaticLayout: true, scrollBeyondLastLine: false }}
            />
          </div>
          {v && (
            <div role="status" data-testid="verification">
              <span className={`gb-chip ${GOOD.has(v.verdict) ? "gb-conf-likely" : v.verdict === "no_measurable_change" ? "gb-conf-suspect" : "gb-conf-confirmed"}`}>
                {t(`verdict.${v.verdict}` as Key)}
              </span>
              {v.time_before_ms && v.time_after_ms && v.steps_before !== null && v.steps_after !== null && v.speedup !== null && (
                <p className="mt-1">
                  <strong>{t("refactor.measured")}:</strong>{" "}
                  {t("refactor.timing", {
                    before: num(v.time_before_ms.median), after: num(v.time_after_ms.median), speedup: v.speedup,
                    steps0: v.steps_before, steps1: v.steps_after,
                  })}
                </p>
              )}
              {v.diffs.map((d, i) => (<p key={i} className="gb-banner-error px-2 py-1 rounded mt-1">{d}</p>))}
            </div>
          )}
          <div className="flex gap-2">
            <button className="gb-btn" disabled={r.busy !== null} onClick={() => void r.verify()}>{r.busy === "verify" ? t("refactor.verifying") : `🔬 ${t("refactor.verify")}`}</button>
            <button
              className={`gb-btn ${v?.verdict === "behavior_changed" ? "gb-btn-danger" : "gb-btn-primary"}`}
              disabled={!v || v.verdict === "broken" || r.busy !== null}
              title={v ? undefined : t("refactor.applyNeedsVerify")}
              onClick={onApply}
            >
              ▶ {t("refactor.apply")}
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
