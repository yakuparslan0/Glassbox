import "@xyflow/react/dist/style.css";
import { Background, Controls, MarkerType, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { useMemo } from "react";
import { useT } from "../../i18n";
import { layoutGraph, NODE_H, NODE_W } from "../../lib/layout";
import { usePlayback } from "../../store/playbackStore";
import { getRunData, useRunStore } from "../../store/runStore";
import { useViewStore } from "../../store/viewStore";

interface FnData extends Record<string, unknown> {
  label: string;
  calls: number;
  kind: "user" | "boundary";
  active: boolean;
  firstStep: number;
}

function FnNode({ data }: NodeProps<Node<FnData>>): React.ReactElement {
  const goTo = usePlayback((s) => s.goTo);
  return (
    <div
      className={`gb-node ${data.kind === "boundary" ? "gb-node-boundary" : ""} ${data.active ? "gb-node-active" : ""}`}
      style={{ width: NODE_W, height: NODE_H }}
      onClick={() => goTo(data.firstStep)}
      title={data.kind === "boundary" ? "library" : "function"}
    >
      <span aria-hidden className="mr-1">{data.kind === "boundary" ? "◆" : "ƒ"}</span>
      <span className="truncate">{data.label}</span>
      <span className="gb-chip ml-2">{data.calls}×</span>
    </div>
  );
}

const nodeTypes = { fn: FnNode };

export function CallGraphView(): React.ReactElement {
  const t = useT();
  useRunStore((s) => s.version); // re-render as the graph grows
  const view = useViewStore((s) => s.state);
  const graph = getRunData().graph;

  // layout depends on topology only; counts and highlights are cheap and update every step
  const positions = useMemo(
    () => layoutGraph([...graph.nodes.values()], [...graph.edges.values()]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [graph, graph.topologyVersion],
  );

  const top = view?.stack.at(-1);
  const below = view && view.stack.length > 1 ? view.stack[view.stack.length - 2] : undefined;
  const activeNode = top ? graph.nodeOfFrame(top.frame) : undefined;
  const activeEdge = top && below ? `${graph.nodeOfFrame(below.frame)}->${graph.nodeOfFrame(top.frame)}` : undefined;

  const nodes: Node<FnData>[] = [...graph.nodes.values()].map((n) => ({
    id: n.id,
    type: "fn",
    position: positions.get(n.id) ?? { x: 0, y: 0 },
    data: { label: n.label, calls: n.calls, kind: n.kind, active: n.id === activeNode, firstStep: n.firstStep },
  }));
  const edges: Edge[] = [...graph.edges.values()].map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: String(e.count),
    animated: e.id === activeEdge,
    markerEnd: { type: MarkerType.ArrowClosed },
    className: e.id === activeEdge ? "gb-edge-active" : "",
  }));

  if (!nodes.length) return <p className="p-4 text-sm opacity-60">{t("graph.empty")}</p>;
  return (
    <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} colorMode="dark" fitView nodesDraggable={false} minZoom={0.2}>
      <Background />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}
