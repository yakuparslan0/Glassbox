import "@xyflow/react/dist/style.css";
import { Background, Controls, Handle, Position, ReactFlow, type Node, type NodeProps } from "@xyflow/react";
import { useMemo } from "react";
import { useT } from "../../i18n";
import { buildHeapGraph, type BoxData } from "../../lib/heapGraph";
import { useViewStore } from "../../store/viewStore";

function Box({ data }: NodeProps<Node<BoxData>>): React.ReactElement {
  const t = useT();
  return (
    <div className={`gb-box ${data.kind === "object" ? "gb-box-object" : ""} ${data.alias > 1 ? "gb-box-alias" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <div className="font-semibold text-xs mb-1">
        {data.alias > 1 && <span aria-hidden>⛓ </span>}
        {data.title}
      </div>
      {data.alias > 1 && <div className="text-xs gb-chip mb-1">{t("heap.alias", { n: data.alias })}</div>}
      {data.rows.map((r, i) => (<div key={i} className="font-mono text-xs truncate">{r}</div>))}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { box: Box };

export function HeapView(): React.ReactElement {
  const t = useT();
  const view = useViewStore((s) => s.state);
  const graph = useMemo(() => (view ? buildHeapGraph(view) : null), [view]);
  if (!graph || !graph.nodes.some((n) => n.data.kind === "object")) return <p className="p-4 text-sm opacity-60">{t("heap.empty")}</p>;
  return (
    <ReactFlow nodes={graph.nodes} edges={graph.edges} nodeTypes={nodeTypes} colorMode="dark" fitView nodesDraggable={false} minZoom={0.2}>
      <Background />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}
