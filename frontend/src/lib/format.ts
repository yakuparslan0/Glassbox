// Value and event formatting shared by the panels.
import type { RunEvent } from "../types/generated";
import type { HeapMap, Val } from "../types/model";
import { t } from "../i18n";

const MAX = 90;

const clip = (s: string): string => (s.length > MAX ? s.slice(0, MAX - 1) + "…" : s);

/** One-line text for a value; heap objects are expanded one level (spec 4.2). */
export function formatVal(v: Val, heap: HeapMap, depth = 0): string {
  if ("ref" in v) {
    const e = heap[v.ref];
    if (!e) return `→${v.ref}`;
    if (depth >= 2) return `${e.t}…`;
    const inner = (x: Val) => formatVal(x, heap, depth + 1);
    switch (e.k) {
      case "seq": {
        const body = e.items.map(inner).join(", ") + (e.trunc ? ", …" : "");
        return clip(e.t === "tuple" ? `(${body})` : e.t === "set" || e.t === "frozenset" ? `{${body}}` : `[${body}]`);
      }
      case "map":
        return clip(`{${e.pairs.map(([a, b]) => `${inner(a)}: ${inner(b)}`).join(", ")}${e.trunc ? ", …" : ""}}`);
      case "obj":
        return clip(`${e.t}(${Object.entries(e.attrs).map(([k, x]) => `${k}=${inner(x)}`).join(", ")})`);
      default:
        return clip(e.r);
    }
  }
  return clip(v.r);
}

export function formatArgs(args: Record<string, Val>, heap: HeapMap): string {
  return Object.entries(args)
    .map(([k, v]) => `${k}=${formatVal(v, heap)}`)
    .join(", ");
}

/** Deterministic one-sentence description of a step event (no LLM; the mentor layer arrives in Phase 4). */
export function describeEvent(ev: RunEvent, heap: HeapMap = {}): string {
  switch (ev.type) {
    case "call":
      return ev.kind === "boundary"
        ? t("ev.boundary", { name: `${ev.module}.${ev.func}` })
        : t("ev.call", { name: ev.func === "<module>" ? t("ev.module") : `${ev.func}(${formatArgs(ev.args, heap)})` });
    case "line": {
      const changes = Object.entries(ev.delta.set ?? {}).map(([k, v]) => `${k} = ${formatVal(v, heap)}`);
      return changes.length ? t("ev.lineChanged", { line: ev.line, changes: changes.join(", ") }) : t("ev.line", { line: ev.line });
    }
    case "return":
      if (ev.kind === "boundary") return t("ev.boundaryReturn", { value: ev.value_summary ?? "" });
      return ev.unwound ? t("ev.unwound") : t("ev.return", { value: formatVal(ev.value, heap) });
    case "exception":
      return t(ev.handled ? "ev.exceptionHandled" : "ev.exception", { type: ev.exc_type, message: ev.message });
    default:
      return ev.type;
  }
}
