import { Group, Panel, Separator } from "react-resizable-panels";
import { useT } from "../../i18n";
import type { Key } from "../../i18n";
import { endMessage, useRunStore } from "../../store/runStore";
import { useUiStore, type CenterTab, type RightTab } from "../../store/uiStore";
import { MarkSweepPanel } from "../cleanup/MarkSweepPanel";
import { CodeEditor } from "../editor/CodeEditor";
import { CallGraphView } from "../graph/CallGraphView";
import { CallTreeView } from "../graph/CallTreeView";
import { HeapView } from "../graph/HeapView";
import { VariablesPanel } from "../state/VariablesPanel";
import { TimelinePanel } from "../timeline/TimelinePanel";
import { TopBar } from "./TopBar";
import { TransportBar } from "./TransportBar";

function Tabs<T extends string>({ value, items, onChange }: { value: T; items: readonly [T, Key][]; onChange: (v: T) => void }): React.ReactElement {
  const t = useT();
  return (
    <div role="tablist" className="flex border-b border-[var(--border)] bg-[var(--panel)]">
      {items.map(([id, label]) => (
        <button key={id} role="tab" aria-selected={value === id} className={`gb-tab ${value === id ? "gb-tab-active" : ""}`} onClick={() => onChange(id)}>
          {t(label)}
        </button>
      ))}
    </div>
  );
}

function Banner(): React.ReactElement | null {
  const status = useRunStore((s) => s.status);
  const errorText = useRunStore((s) => s.errorText);
  const finished = useRunStore((s) => s.finished);
  const limitDetail = useRunStore((s) => s.limitDetail);
  const end = endMessage({ finished, limitDetail });
  const text = errorText ?? end;
  if (!text) return null;
  const isError = status === "error" || errorText !== null;
  return (
    <div role="alert" className={`px-3 py-2 text-sm border-b border-[var(--border)] ${isError || finished?.status === "exception" ? "gb-banner-error" : "gb-banner-warn"}`}>
      {isError || finished?.status === "exception" ? "✖ " : "⚠ "}
      {text}
    </div>
  );
}

function Empty(): React.ReactElement {
  const t = useT();
  return (
    <div className="h-full grid place-items-center text-center p-6">
      <div>
        <p className="text-lg font-semibold">{t("empty.title")}</p>
        <p className="opacity-70 text-sm mt-1">{t("empty.hint")}</p>
      </div>
    </div>
  );
}

export function AppShell(): React.ReactElement {
  const t = useT();
  const { centerTab, setCenterTab, rightTab, setRightTab } = useUiStore();
  const status = useRunStore((s) => s.status);

  return (
    <div className="h-full flex flex-col">
      <TopBar />
      <Banner />
      <div className="flex-1 min-h-0">
        <Group orientation="horizontal">
          <Panel defaultSize="38%" minSize="20%">
            <CodeEditor />
          </Panel>
          <Separator className="gb-sep" />
          <Panel defaultSize="34%" minSize="15%">
            <div className="h-full flex flex-col min-h-0">
              <Tabs<CenterTab> value={centerTab} onChange={setCenterTab} items={[["graph", "tab.graph"], ["tree", "tab.tree"], ["heap", "tab.heap"]]} />
              <div className="flex-1 min-h-0 relative">
                {status === "idle" ? <Empty /> : centerTab === "graph" ? <CallGraphView /> : centerTab === "tree" ? <CallTreeView /> : <HeapView />}
              </div>
              <p className="px-3 py-1 text-xs opacity-60 border-t border-[var(--border)]">ⓘ {t("warn.untraced")}</p>
            </div>
          </Panel>
          <Separator className="gb-sep" />
          <Panel defaultSize="28%" minSize="15%">
            <div className="h-full flex flex-col min-h-0">
              <Tabs<RightTab> value={rightTab} onChange={setRightTab} items={[["timeline", "tab.timeline"], ["vars", "tab.vars"], ["cleanup", "tab.cleanup"]]} />
              <div className="flex-1 min-h-0">
                {rightTab === "timeline" ? <TimelinePanel /> : rightTab === "vars" ? <VariablesPanel /> : <MarkSweepPanel />}
              </div>
            </div>
          </Panel>
        </Group>
      </div>
      <TransportBar />
    </div>
  );
}
