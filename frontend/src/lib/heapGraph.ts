// Pure heap/alias graph construction (frames on the left, heap objects on the right, references as arrows).
import { MarkerType, type Edge, type Node } from "@xyflow/react";
import type { HeapMap, ViewState } from "../types/model";
import { formatVal } from "./format";
import { refsOf } from "./stateBuilder";

export interface BoxData extends Record<string, unknown> {
  title: string;
  rows: string[];
  alias: number; // how many different names point here (>= 2 = aliasing)
  kind: "frame" | "object";
}

export function buildHeapGraph(view: ViewState): { nodes: Node<BoxData>[]; edges: Edge[] } {
  const heap: HeapMap = view.heap;
  const frames = [
    { id: "g", title: "globals", vars: view.globals },
    ...view.stack.filter((f) => f.frame !== 1).map((f) => ({ id: `f${f.frame}`, title: `${f.func}:${f.line}`, vars: f.locals })),
  ];
  const incoming = new Map<string, Set<string>>(); // object -> distinct "frame.name" referrers
  const edges: Edge[] = [];
  const objects: string[] = [];
  const seen = new Set<string>();
  const visit = (label: string): void => {
    if (seen.has(label) || !heap[label]) return;
    seen.add(label);
    objects.push(label);
    for (const r of refsOf(heap[label])) {
      visit(r);
    }
  };
  for (const f of frames) {
    for (const [name, v] of Object.entries(f.vars)) {
      if (!("ref" in v)) continue;
      visit(v.ref);
      if (!incoming.has(v.ref)) incoming.set(v.ref, new Set());
      incoming.get(v.ref)?.add(`${f.id}.${name}`);
      edges.push({ id: `${f.id}.${name}`, source: f.id, target: v.ref, label: name, markerEnd: { type: MarkerType.ArrowClosed } });
    }
  }
  for (const label of objects) {
    for (const r of refsOf(heap[label])) {
      edges.push({ id: `${label}->${r}`, source: label, target: r, markerEnd: { type: MarkerType.ArrowClosed } });
      if (!incoming.has(r)) incoming.set(r, new Set());
      incoming.get(r)?.add(`${label}->`);
    }
  }
  const nodes: Node<BoxData>[] = [];
  let y = 0;
  for (const f of frames) {
    const rows = Object.entries(f.vars).map(([k, v]) => `${k} = ${"ref" in v ? `→ ${v.ref}` : formatVal(v, heap)}`);
    nodes.push({ id: f.id, type: "box", position: { x: 0, y }, data: { title: f.title, rows, alias: 0, kind: "frame" } });
    y += 36 + rows.length * 16 + 24;
  }
  objects.forEach((label, i) => {
    const e = heap[label];
    const named = [...(incoming.get(label) ?? [])].filter((s) => !s.endsWith("->"));
    nodes.push({
      id: label,
      type: "box",
      position: { x: 360, y: i * 110 },
      data: { title: `${label} · ${e.t}`, rows: [formatVal({ ref: label }, heap)], alias: named.length, kind: "object" },
    });
  });
  for (const ed of edges) {
    const count = incoming.get(ed.target)?.size ?? 0;
    const aliased = [...(incoming.get(ed.target) ?? [])].filter((s) => !s.endsWith("->")).length > 1;
    ed.className = aliased ? "gb-edge-alias" : "";
    ed.animated = aliased && count > 1;
  }
  return { nodes, edges };
}
