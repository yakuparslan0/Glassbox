import { useState } from "react";
import { ApiError, getRootCause, runBigO } from "../../api/http";
import { useT } from "../../i18n";
import type { Key } from "../../i18n";
import { plot } from "../../lib/chart";
import { usePlayback } from "../../store/playbackStore";
import { useRunStore } from "../../store/runStore";
import { useUiStore } from "../../store/uiStore";
import type { BigOReport, CausalChain } from "../../types/generated";

const GENERATORS = ["random_ints", "sorted_ints", "reversed_ints", "int_n", "string_n"] as const;
const KIND_ICON: Record<string, string> = { error: "✖", assignment: "＝", argument: "→", global: "◎", return: "↩" };

function RootCause(): React.ReactElement {
  const t = useT();
  const { runId, status, finished } = useRunStore();
  const goTo = usePlayback((s) => s.goTo);
  const reveal = useUiStore((s) => s.revealLines);
  const [chain, setChain] = useState<CausalChain | null>(null);
  const [error, setError] = useState<string | null>(null);
  const failed = finished?.status === "exception";

  const find = async (): Promise<void> => {
    if (!runId) return;
    setError(null);
    try {
      setChain(await getRootCause(runId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };
  return (
    <section className="mb-5">
      <h3 className="gb-h">{t("lab.rootcause")}</h3>
      <button className="gb-btn" disabled={status !== "finished" || !failed} onClick={() => void find()}>🔎 {t("lab.rootcauseBtn")}</button>
      {status === "finished" && !failed && <p className="opacity-60 mt-1">{t("lab.noException")}</p>}
      {error && <p role="alert" className="gb-banner-error px-2 py-1 rounded mt-2">{error}</p>}
      {chain && (
        <>
          <p className="text-xs opacity-60 mt-2">{t("lab.rootcauseHint")}</p>
          <ol className="flex flex-wrap gap-1 mt-1 items-center" aria-label="causal chain" data-testid="causal-chain">
            {chain.links.map((l, i) => (
              <li key={`${l.step}-${l.name}-${l.kind}`} className="flex items-center gap-1">
                {i > 0 && <span aria-hidden className="opacity-40">›</span>}
                <button
                  className={`gb-chip ${l.kind === "error" ? "gb-conf-confirmed" : ""}`}
                  title={l.text}
                  onClick={() => { goTo(l.step); reveal(l.line, l.line); }}
                >
                  <span aria-hidden>{KIND_ICON[l.kind]}</span> {l.name}{l.value && l.kind !== "error" ? `=${l.value}` : ""} <span className="opacity-60">:{l.line}</span>
                </button>
              </li>
            ))}
          </ol>
          {chain.truncated && <p className="text-xs opacity-60 mt-1">{t("lab.truncated")}</p>}
        </>
      )}
    </section>
  );
}

function BigOChart({ report }: { report: BigOReport }): React.ReactElement {
  const p = plot(report.points, report.best.predicted, 360, 200);
  return (
    <svg viewBox="0 0 360 200" role="img" aria-label={`${report.best.label} fit`} className="w-full max-w-[420px] bg-[#0f121a] rounded">
      {p.xTicks.map((tk) => (<text key={`x${tk.x}`} x={tk.x} y={192} fontSize="10" fill="#8a93a6" textAnchor="middle">{tk.label}</text>))}
      {p.yTicks.map((tk) => (<text key={`y${tk.y}`} x={30} y={tk.y + 3} fontSize="10" fill="#8a93a6" textAnchor="end">{tk.label}</text>))}
      <path d={p.curve} fill="none" stroke="#4cc2ff" strokeWidth="2" strokeDasharray="5 3" />
      {p.points.map((pt, i) => (<circle key={i} cx={pt.x} cy={pt.y} r="4" fill="#ffb04a" stroke="#11141a" />))}
    </svg>
  );
}

function BigO(): React.ReactElement {
  const t = useT();
  const { report, runSource, entry } = useRunStore();
  const seed = useUiStore((s) => s.settings.seed);
  const funcs = [...new Set((report?.functions ?? []).filter((f) => !f.qualname.includes(".")).map((f) => f.qualname))];
  const [func, setFunc] = useState("");
  const [generator, setGenerator] = useState<(typeof GENERATORS)[number]>("random_ints");
  const [extra, setExtra] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<BigOReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const chosen = func || funcs[0] || "";

  const measure = async (): Promise<void> => {
    if (runSource === null || !chosen) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await runBigO(entry, runSource, chosen, generator, extra.split(",").map((x) => x.trim()).filter(Boolean), seed));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section>
      <h3 className="gb-h">{t("lab.bigo")}</h3>
      {funcs.length === 0 ? (
        <p className="opacity-60">{t("lab.noFuncs")}</p>
      ) : (
        <div className="grid gap-2 max-w-md">
          <label className="grid gap-1">{t("lab.func")}
            <select className="gb-input" value={chosen} onChange={(e) => setFunc(e.target.value)}>
              {funcs.map((f) => (<option key={f} value={f}>{f}</option>))}
            </select>
          </label>
          <label className="grid gap-1">{t("lab.generator")}
            <select className="gb-input" value={generator} onChange={(e) => setGenerator(e.target.value as typeof generator)}>
              {GENERATORS.map((g) => (<option key={g} value={g}>{t(`gen.${g}` as Key)}</option>))}
            </select>
          </label>
          <label className="grid gap-1">{t("lab.extra")}
            <input className="gb-input font-mono" value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="$missing" />
          </label>
          <button className="gb-btn gb-btn-primary" disabled={busy} onClick={() => void measure()}>{busy ? t("lab.running") : `📈 ${t("lab.run")}`}</button>
        </div>
      )}
      {error && <p role="alert" className="gb-banner-error px-2 py-1 rounded mt-2">{error}</p>}
      {result && (
        <div className="mt-3 grid gap-2" data-testid="bigo-result">
          <BigOChart report={result} />
          <p><strong>{t("lab.best")}:</strong> {result.best.label} <span className="opacity-70">(R² = {result.best.r2.toFixed(4)})</span></p>
          {result.runner_up && <p className="opacity-80"><strong>{t("lab.second")}:</strong> {result.runner_up.label} <span className="opacity-70">(R² = {result.runner_up.r2.toFixed(4)})</span></p>}
          <p className={result.conflict ? "gb-banner-error px-2 py-1 rounded" : "opacity-80"}>
            <strong>{t("lab.static")}:</strong> {result.static.label} <span className="opacity-70">({result.static.basis})</span>{" "}
            {result.conflict ? <b>⚠ {t("lab.conflict")}</b> : t("lab.agree")}
          </p>
          {result.stopped_early && <p className="opacity-70">{t("lab.stopped", { why: result.stopped_early })}</p>}
          <p className="text-xs opacity-70">{t("lab.empirical")}</p>
        </div>
      )}
    </section>
  );
}

export function LabPanel(): React.ReactElement {
  return (
    <div className="h-full overflow-auto p-3 text-sm">
      <RootCause />
      <BigO />
    </div>
  );
}
