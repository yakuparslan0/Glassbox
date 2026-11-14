import { useT } from "../../i18n";
import { useBranchStore } from "../../store/branchStore";
import { usePlayback } from "../../store/playbackStore";

/** Lists the main run and its What-If branches; shows where the active branch first diverges from main. */
export function BranchBar(): React.ReactElement | null {
  const t = useT();
  const { baseRunId, branches, activeRunId, pending, error, switchTo } = useBranchStore();
  const goTo = usePlayback((s) => s.goTo);
  if (!baseRunId) return null;
  const active = branches.find((b) => b.runId === activeRunId);
  const cmp = active?.comparison;
  return (
    <div className="flex flex-wrap items-center gap-2 px-3 py-1 text-sm border-b border-[var(--border)] bg-[#161b26]" data-testid="branchbar">
      <button className={`gb-chip ${activeRunId === baseRunId || !activeRunId ? "gb-chip-on" : ""}`} onClick={() => switchTo(baseRunId)}>● {t("branch.base")}</button>
      {branches.map((b) => (
        <button key={b.runId} className={`gb-chip ${b.runId === activeRunId ? "gb-chip-on" : ""}`} onClick={() => switchTo(b.runId)}>⑂ {b.name}</button>
      ))}
      {pending && <span className="opacity-70">… {pending}</span>}
      {cmp && (
        <>
          <span className="opacity-60">{t("branch.vs")}:</span>
          {cmp.first_divergence_step === null ? (
            <span>{t("branch.identical")}</span>
          ) : (
            <button className="gb-link" onClick={() => goTo(cmp.first_divergence_step as number)}>◆ {t("branch.diverge", { step: cmp.first_divergence_step })} — {t("branch.goto")}</button>
          )}
          <span className="opacity-80 truncate" title={cmp.summary.join(" · ")}>{cmp.summary.slice(1).join(" · ")}</span>
        </>
      )}
      {error && <span role="alert" className="gb-banner-error px-2 rounded">{error}</span>}
    </div>
  );
}
