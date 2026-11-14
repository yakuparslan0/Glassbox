import { useT } from "../../i18n";
import type { Key } from "../../i18n";
import { useRunStore } from "../../store/runStore";
import { useUiStore } from "../../store/uiStore";

const ICON: Record<string, string> = { confirmed: "✕", likely: "?", suspect: "~" };

export function MarkSweepPanel(): React.ReactElement {
  const t = useT();
  const status = useRunStore((s) => s.status);
  const report = useRunStore((s) => s.report);
  const loading = useRunStore((s) => s.reportLoading);
  const analyze = useRunStore((s) => s.analyze);
  const reveal = useUiStore((s) => s.revealLines);

  return (
    <div className="h-full overflow-auto p-3 text-sm">
      <button className="gb-btn gb-btn-primary" disabled={status !== "finished" || loading} onClick={() => void analyze()}>
        {loading ? t("cleanup.loading") : t("cleanup.analyze")}
      </button>
      {status !== "finished" && !report && <p className="mt-3 opacity-60">{t("cleanup.needRun")}</p>}
      {report && (
        <>
          <p className="mt-3" data-testid="ms-summary">
            {t("cleanup.summary", { dead: report.summary.confirmed_dead, cold: report.summary.cold, suspect: report.summary.suspect, lines: report.summary.reclaimable_lines })}
          </p>
          <p className="text-xs opacity-60 mb-2">{t("cleanup.steps")}: {report.steps}</p>
          {report.findings.length === 0 && <p className="opacity-60">{t("cleanup.none")}</p>}
          <ul>
            {report.findings.map((f) => (
              <li key={f.id}>
                <button className="gb-row w-full text-left flex gap-2 items-baseline" onClick={() => reveal(f.start_line, f.end_line)}>
                  <span className={`gb-chip gb-conf-${f.confidence}`} title={t(`conf.${f.confidence}` as Key)}>
                    <span aria-hidden>{ICON[f.confidence]}</span> {t(`conf.${f.confidence}` as Key)}
                  </span>
                  <span className="font-mono opacity-70 shrink-0">{f.start_line === f.end_line ? f.start_line : `${f.start_line}–${f.end_line}`}</span>
                  <span>
                    <span className="font-semibold">{t(`cat.${f.category}` as Key)}</span>
                    <span className="opacity-80"> — {f.title}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
