// Call graph from call events: node = function (aggregated), edge = caller -> callee with a count.
import type { RunEvent } from "../types/generated";

export interface GraphNode {
  id: string;
  label: string;
  kind: "user" | "boundary";
  lib?: string; // boundary nodes are grouped by library name
  calls: number;
  firstStep: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  count: number;
}

export class GraphBuilder {
  readonly nodes = new Map<string, GraphNode>();
  readonly edges = new Map<string, GraphEdge>();
  private frameNode = new Map<number, string>();
  /** Bumps only when a node or edge is ADDED (layout depends on topology, not on counts). */
  topologyVersion = 0;

  append(batch: readonly RunEvent[]): void {
    for (const ev of batch) {
      if (ev.type !== "call") continue;
      const id = ev.kind === "boundary" ? `lib:${ev.module}.${ev.func}` : `fn:${ev.file}:${ev.qualname}`;
      this.frameNode.set(ev.frame, id);
      let node = this.nodes.get(id);
      if (!node) {
        node =
          ev.kind === "boundary"
            ? { id, label: `${ev.module}.${ev.func}`, kind: "boundary", lib: ev.module, calls: 0, firstStep: ev.step }
            : { id, label: ev.qualname, kind: "user", calls: 0, firstStep: ev.step };
        this.nodes.set(id, node);
        this.topologyVersion++;
      }
      node.calls++;
      const parent = ev.parent == null ? undefined : this.frameNode.get(ev.parent);
      if (parent) {
        const edgeId = `${parent}->${id}`;
        let edge = this.edges.get(edgeId);
        if (!edge) {
          edge = { id: edgeId, source: parent, target: id, count: 0 };
          this.edges.set(edgeId, edge);
          this.topologyVersion++;
        }
        edge.count++;
      }
    }
  }

  nodeOfFrame(frame: number): string | undefined {
    return this.frameNode.get(frame);
  }
}

export function buildGraph(events: readonly RunEvent[]): GraphBuilder {
  const g = new GraphBuilder();
  g.append(events);
  return g;
}
