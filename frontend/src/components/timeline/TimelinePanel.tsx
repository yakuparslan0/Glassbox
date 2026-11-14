import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useMemo, useRef, useState } from "react";
import { useT } from "../../i18n";
import { describeEvent } from "../../lib/format";
import { usePlayback } from "../../store/playbackStore";
import { getRunData, useRunStore } from "../../store/runStore";
import { useViewStore } from "../../store/viewStore";

type Filter = "all" | "call" | "line" | "return" | "exception";
const ICON: Record<string, string> = { call: "→", line: "·", return: "←", exception: "⚠" };

export function TimelinePanel(): React.ReactElement {
  const t = useT();
  const version = useRunStore((s) => s.version);
  const total = useRunStore((s) => s.totalSteps);
  const step = usePlayback((s) => s.step);
  const goTo = usePlayback((s) => s.goTo);
  const heap = useViewStore((s) => s.state?.heap);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const parent = useRef<HTMLDivElement>(null);

  const steps = useMemo(() => {
    const data = getRunData();
    const out: number[] = [];
    const q = query.trim().toLowerCase();
    for (let k = 1; k <= data.totalSteps; k++) {
      const ev = data.eventOfStep(k);
      if (!ev) continue;
      if (filter !== "all" && ev.type !== filter) continue;
      if (q && !describeEvent(ev, heap ?? {}).toLowerCase().includes(q)) continue;
      out.push(k);
    }
    return out;
    // `total` changes whenever new steps arrive
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, total, filter, query]);

  const virtual = useVirtualizer({ count: steps.length, getScrollElement: () => parent.current, estimateSize: () => 24, overscan: 12 });

  useEffect(() => {
    if (step < 1 || !steps.length) return;
    let lo = 0, hi = steps.length - 1, idx = 0;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (steps[mid] <= step) { idx = mid; lo = mid + 1; } else hi = mid - 1; }
    virtual.scrollToIndex(idx, { align: "auto" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, steps]);

  const data = getRunData();
  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex gap-2 p-2 border-b border-[var(--border)]">
        <select className="gb-input" value={filter} onChange={(e) => setFilter(e.target.value as Filter)} aria-label="filter">
          {(["all", "call", "line", "return", "exception"] as const).map((f) => (<option key={f} value={f}>{t(`tl.${f}`)}</option>))}
        </select>
        <input className="gb-input flex-1" placeholder={t("tl.search")} value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      <div ref={parent} className="flex-1 overflow-auto" data-testid="timeline">
        {steps.length === 0 ? (
          <p className="p-3 text-sm opacity-60">{t("tl.empty")}</p>
        ) : (
          <div style={{ height: virtual.getTotalSize(), position: "relative" }}>
            {virtual.getVirtualItems().map((row) => {
              const k = steps[row.index];
              const ev = data.eventOfStep(k);
              if (!ev) return null;
              const depth = Math.max(0, (data.depth[k] ?? 1) - 1);
              const boundary = (ev.type === "call" || ev.type === "return") && ev.kind === "boundary";
              return (
                <button
                  key={k}
                  onClick={() => goTo(k)}
                  className={`gb-row ${k === step ? "gb-row-active" : ""} ${ev.type === "exception" ? "gb-row-exception" : ""} ${boundary ? "gb-row-boundary" : ""}`}
                  style={{ position: "absolute", top: 0, left: 0, width: "100%", height: row.size, transform: `translateY(${row.start}px)`, paddingLeft: 8 + depth * 14 }}
                >
                  <span className="tabular-nums opacity-50 w-12 inline-block text-right mr-2">{k}</span>
                  <span className="mr-1" aria-hidden>{ICON[ev.type] ?? "·"}</span>
                  <span className="truncate">{describeEvent(ev, heap ?? {})}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
