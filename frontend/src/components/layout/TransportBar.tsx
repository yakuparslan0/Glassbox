import { useEffect, useMemo, useRef } from "react";
import { useT } from "../../i18n";
import { SPEEDS, usePlayback } from "../../store/playbackStore";
import { getRunData, useRunStore } from "../../store/runStore";

const BASE_STEPS_PER_SECOND = 6;
const MAX_MARKERS = 150;

/** One marker per ~pixel bucket so 20k steps never create 20k DOM nodes. */
function bucketed(steps: number[], total: number): number[] {
  const seen = new Set<number>();
  const out: number[] = [];
  for (const s of steps) {
    const bucket = Math.floor((s / Math.max(total, 1)) * MAX_MARKERS);
    if (!seen.has(bucket)) {
      seen.add(bucket);
      out.push(s);
    }
  }
  return out;
}

function Scrubber({ total }: { total: number }): React.ReactElement {
  const t = useT();
  const step = usePlayback((s) => s.step);
  const goTo = usePlayback((s) => s.goTo);
  const version = useRunStore((s) => s.version);
  const markers = useMemo(() => {
    const d = getRunData();
    return {
      exception: bucketed(d.exceptionSteps, total),
      output: bucketed(d.outputSteps, total),
      boundary: bucketed(d.boundarySteps, total),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, total]);
  const pos = (s: number): string => `${total > 1 ? ((s - 1) / (total - 1)) * 100 : 0}%`;
  return (
    <div className="relative flex-1 h-8 flex items-center" data-testid="scrubber">
      <input
        type="range"
        min={1}
        max={Math.max(total, 1)}
        value={Math.max(step, 1)}
        disabled={total === 0}
        aria-label={t("tr.step", { step, total })}
        onChange={(e) => goTo(Number(e.target.value))}
        className="w-full"
      />
      <div className="pointer-events-none absolute inset-x-2 top-0 h-full" aria-hidden>
        {markers.exception.map((s) => (
          <span key={`e${s}`} className="gb-marker gb-marker-exception" style={{ left: pos(s) }} title="exception">▲</span>
        ))}
        {markers.output.map((s) => (
          <span key={`o${s}`} className="gb-marker gb-marker-output" style={{ left: pos(s) }}>▪</span>
        ))}
        {markers.boundary.map((s) => (
          <span key={`b${s}`} className="gb-marker gb-marker-boundary" style={{ left: pos(s) }}>◆</span>
        ))}
      </div>
    </div>
  );
}

export function TransportBar(): React.ReactElement {
  const t = useT();
  const { step, playing, speed, follow } = usePlayback();
  const total = useRunStore((s) => s.totalSteps);
  const status = useRunStore((s) => s.status);
  const api = usePlayback.getState;
  const acc = useRef(0);

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      acc.current += BASE_STEPS_PER_SECOND * usePlayback.getState().speed * 0.05;
      const whole = Math.floor(acc.current);
      if (whole < 1) return;
      acc.current -= whole;
      const { step: cur } = usePlayback.getState();
      const max = getRunData().totalSteps;
      if (cur >= max) {
        if (useRunStore.getState().status !== "running") usePlayback.setState({ playing: false });
        return;
      }
      usePlayback.setState({ step: Math.min(cur + whole, max), follow: false });
    }, 50);
    return () => window.clearInterval(id);
  }, [playing]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "TEXTAREA" || tag === "INPUT" || tag === "SELECT" || (e.target as HTMLElement).closest(".monaco-editor")) return;
      if (e.key === " ") { e.preventDefault(); api().togglePlay(); }
      else if (e.key === "ArrowRight") api().next();
      else if (e.key === "ArrowLeft") api().prev();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [api]);

  const btn = "gb-btn disabled:opacity-40";
  const none = total === 0;
  return (
    <div className="flex items-center gap-2 px-3 border-t border-[var(--border)] bg-[var(--panel)] h-12" role="toolbar">
      <button className={btn} disabled={none} onClick={() => api().toStart()} title={t("tr.start")} aria-label={t("tr.start")}>⏮</button>
      <button className={btn} disabled={none} onClick={() => api().prev()} title={t("tr.back")} aria-label={t("tr.back")}>◀</button>
      <button className={`${btn} gb-btn-primary`} disabled={none} onClick={() => api().togglePlay()} title={playing ? t("tr.pause") : t("tr.play")} aria-label={playing ? t("tr.pause") : t("tr.play")}>
        {playing ? "⏸" : "▶"}
      </button>
      <button className={btn} disabled={none} onClick={() => api().next()} title={t("tr.forward")} aria-label={t("tr.forward")}>▶|</button>
      <button className={btn} disabled={none} onClick={() => api().over()} title={t("tr.over")}>⤼ over</button>
      <button className={btn} disabled={none} onClick={() => api().out()} title={t("tr.out")}>⤴ out</button>
      <Scrubber total={total} />
      <span className="text-xs tabular-nums w-36 text-right" data-testid="step-label">{t("tr.step", { step, total })}</span>
      {status === "running" && <span className={`text-xs px-2 py-0.5 rounded ${follow ? "gb-live" : "gb-live-off"}`}>● {t("tr.live")}</span>}
      <label className="text-xs flex items-center gap-1">
        {t("tr.speed")}
        <select className="gb-input" value={speed} onChange={(e) => api().setSpeed(Number(e.target.value))}>
          {SPEEDS.map((s) => (<option key={s} value={s}>{s}×</option>))}
        </select>
      </label>
    </div>
  );
}
