import { useMemo, useState } from "react";
import { useT } from "../../i18n";
import { formatVal } from "../../lib/format";
import { usePlayback } from "../../store/playbackStore";
import { getRunData } from "../../store/runStore";
import { useViewStore } from "../../store/viewStore";
import type { Val } from "../../types/model";

const HISTORY_LIMIT = 40;

/** Steps at which `name` changed in `frame` (frame 1 deltas are the globals). Computed lazily, on demand. */
function historyOf(name: string, frame: number | "globals"): number[] {
  const out: number[] = [];
  for (const ev of getRunData().events) {
    if (ev.type !== "line") continue;
    const own = frame !== "globals" && ev.frame === frame && frame !== 1 && name in (ev.delta.set ?? {});
    const glob = (frame === "globals" || frame === 1) && (ev.frame === 1 ? name in (ev.delta.set ?? {}) : name in (ev.globals_delta?.set ?? {}));
    if (own || glob) out.push(ev.step);
    if (out.length >= HISTORY_LIMIT) break;
  }
  return out;
}

function Row({ name, value, frame, changed }: { name: string; value: Val; frame: number | "globals"; changed: boolean }): React.ReactElement {
  const t = useT();
  const heap = useViewStore((s) => s.state?.heap) ?? {};
  const goTo = usePlayback((s) => s.goTo);
  const [open, setOpen] = useState(false);
  const history = useMemo(() => (open ? historyOf(name, frame) : []), [open, name, frame]);
  return (
    <li className={changed ? "gb-changed" : ""}>
      <div className="flex gap-2 items-baseline py-0.5">
        <button className="gb-link font-mono text-sm" onClick={() => setOpen(!open)} title={t("vars.history")} aria-expanded={open}>{name}</button>
        <span className="font-mono text-sm opacity-90 break-all">{formatVal(value, heap)}</span>
        {changed && <span className="text-xs gb-chip" aria-label="changed">Δ</span>}
      </div>
      {open && (
        <div className="pl-4 pb-1 flex flex-wrap gap-1 items-center text-xs">
          <span className="opacity-60">{t("vars.history")}:</span>
          {history.map((s) => (<button key={s} className="gb-chip" onClick={() => goTo(s)}>{s}</button>))}
        </div>
      )}
    </li>
  );
}

export function VariablesPanel(): React.ReactElement {
  const t = useT();
  const view = useViewStore((s) => s.state);
  const step = usePlayback((s) => s.step);
  const [picked, setPicked] = useState<number | null>(null);
  if (!view || step < 1) return <p className="p-3 text-sm opacity-60">{t("vars.empty")}</p>;

  const data = getRunData();
  const ev = data.eventOfStep(step);
  const changedLocals = new Set(ev?.type === "line" ? Object.keys(ev.delta.set ?? {}) : []);
  const changedGlobals = new Set(
    ev && "globals_delta" in ev && ev.globals_delta ? Object.keys(ev.globals_delta.set ?? {}) : [],
  );
  const top = view.stack.at(-1);
  const selected = view.stack.find((f) => f.frame === picked) ?? top;
  const module = selected?.frame === 1;
  if (module && ev?.type === "line" && ev.frame === 1) for (const n of changedLocals) changedGlobals.add(n);

  return (
    <div className="h-full overflow-auto p-2 text-sm" data-testid="variables">
      <h3 className="gb-h">{t("vars.stack")}</h3>
      <ol className="mb-3">
        {[...view.stack].reverse().map((f) => (
          <li key={f.frame}>
            <button className={`gb-row w-full text-left ${f.frame === selected?.frame ? "gb-row-active" : ""}`} onClick={() => setPicked(f.frame)}>
              <span className="font-mono">{f.func}</span> <span className="opacity-60">:{f.line}</span>
            </button>
          </li>
        ))}
      </ol>
      {selected && !module && (
        <>
          <h3 className="gb-h">{t("vars.locals")}</h3>
          <ul className="mb-3">
            {Object.entries(selected.locals).map(([k, v]) => (
              <Row key={k} name={k} value={v} frame={selected.frame} changed={selected.frame === top?.frame && changedLocals.has(k)} />
            ))}
          </ul>
        </>
      )}
      <h3 className="gb-h">{t("vars.globals")}</h3>
      <ul className="mb-3">
        {Object.entries(view.globals).map(([k, v]) => (
          <Row key={k} name={k} value={v} frame="globals" changed={changedGlobals.has(k)} />
        ))}
      </ul>
      <h3 className="gb-h">{t("vars.output")}</h3>
      <pre className="gb-output" data-testid="output">{data.outputUpTo(step)}</pre>
    </div>
  );
}
