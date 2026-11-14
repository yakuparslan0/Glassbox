import { useVirtualizer } from "@tanstack/react-virtual";
import { useMemo, useRef } from "react";
import { useT } from "../../i18n";
import { formatArgs } from "../../lib/format";
import { usePlayback } from "../../store/playbackStore";
import { getRunData, useRunStore } from "../../store/runStore";
import { useViewStore } from "../../store/viewStore";

interface CallRow {
  step: number;
  frame: number;
  depth: number;
  text: string;
  boundary: boolean;
}

export function CallTreeView(): React.ReactElement {
  const t = useT();
  const version = useRunStore((s) => s.version);
  const goTo = usePlayback((s) => s.goTo);
  const view = useViewStore((s) => s.state);
  const parent = useRef<HTMLDivElement>(null);

  const rows = useMemo<CallRow[]>(() => {
    const out: CallRow[] = [];
    const depthOf = new Map<number, number>();
    for (const ev of getRunData().events) {
      if (ev.type !== "call") continue;
      const depth = ev.parent == null ? 0 : (depthOf.get(ev.parent) ?? 0) + 1;
      depthOf.set(ev.frame, depth);
      const text =
        ev.kind === "boundary"
          ? `${ev.module}.${ev.func}${ev.args_summary ?? ""}`
          : ev.func === "<module>"
            ? "<module>"
            : `${ev.func}(${formatArgs(ev.args, ev.heap ?? {})})`;
      out.push({ step: ev.step, frame: ev.frame, depth, text, boundary: ev.kind === "boundary" });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  const live = new Set(view?.stack.map((f) => f.frame));
  const virtual = useVirtualizer({ count: rows.length, getScrollElement: () => parent.current, estimateSize: () => 24, overscan: 12 });
  if (!rows.length) return <p className="p-4 text-sm opacity-60">{t("graph.empty")}</p>;
  return (
    <div ref={parent} className="h-full overflow-auto" data-testid="calltree">
      <div style={{ height: virtual.getTotalSize(), position: "relative" }}>
        {virtual.getVirtualItems().map((v) => {
          const r = rows[v.index];
          return (
            <button
              key={r.frame}
              onClick={() => goTo(r.step)}
              className={`gb-row ${live.has(r.frame) ? "gb-row-active" : ""} ${r.boundary ? "gb-row-boundary" : ""}`}
              style={{ position: "absolute", top: 0, left: 0, width: "100%", height: v.size, transform: `translateY(${v.start}px)`, paddingLeft: 8 + r.depth * 14 }}
            >
              <span aria-hidden className="mr-1">{r.boundary ? "◆" : "ƒ"}</span>
              <span className="font-mono text-sm truncate">{r.text}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
