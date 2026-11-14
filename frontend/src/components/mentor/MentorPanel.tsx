import { useT } from "../../i18n";
import { useMentorStore } from "../../store/mentorStore";
import { usePlayback } from "../../store/playbackStore";
import { useRunStore } from "../../store/runStore";

export function MentorPanel(): React.ReactElement {
  const t = useT();
  const status = useRunStore((s) => s.status);
  const runId = useRunStore((s) => s.runId);
  const { scenes, loading, llmRequested, fellBack, error, load } = useMentorStore();
  const step = usePlayback((s) => s.step);
  const goTo = usePlayback((s) => s.goTo);
  const ready = status === "finished" && runId !== null;

  return (
    <div className="h-full overflow-auto p-3 text-sm">
      <div className="flex gap-2 flex-wrap">
        <button className="gb-btn" disabled={!ready || loading} onClick={() => runId && void load(runId, false)}>{t("mentor.explain")}</button>
        <button className="gb-btn gb-btn-primary" disabled={!ready || loading} onClick={() => runId && void load(runId, true)}>✨ {t("mentor.explainLlm")}</button>
      </div>
      {!ready && scenes.length === 0 && <p className="mt-3 opacity-60">{t("mentor.needRun")}</p>}
      {loading && <p className="mt-3 opacity-70">{t("mentor.loading")}</p>}
      {llmRequested && fellBack && <p role="status" className="mt-3 gb-banner-warn px-2 py-1 rounded">{t("mentor.fallback")}</p>}
      {error && <p role="alert" className="mt-3 gb-banner-error px-2 py-1 rounded">{error}</p>}
      <ol className="mt-3 grid gap-2">
        {scenes.map((s) => {
          const current = step >= s.from_step && step <= s.to_step;
          return (
            <li key={s.index}>
              <button className={`gb-card w-full text-left ${current ? "gb-card-active" : ""}`} onClick={() => goTo(s.from_step)}>
                <div className="flex justify-between gap-2 text-xs opacity-70">
                  <span>{t("mentor.scene", { n: s.index + 1, from: s.from_step, to: s.to_step })}</span>
                  <span className="gb-chip">{t(s.source === "llm" ? "mentor.source.llm" : "mentor.source.narrator")}</span>
                </div>
                <div className="font-semibold">{s.title}</div>
                <p className="mt-1 whitespace-pre-wrap">{s.text}</p>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
