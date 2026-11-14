import { Group, Panel, Separator } from "react-resizable-panels";
import { useT } from "../../i18n";
import type { Key } from "../../i18n";
import { usePlayback } from "../../store/playbackStore";
import { endMessage, useRunStore } from "../../store/runStore";
import { useUiStore, type CenterTab, type RightTab } from "../../store/uiStore";
import { MarkSweepPanel } from "../cleanup/MarkSweepPanel";
import { BranchBar } from "../lab/BranchBar";
import { LabPanel } from "../lab/LabPanel";
import { WhatIfDialog } from "../lab/WhatIfDialog";
import { MentorPanel } from "../mentor/MentorPanel";
import { NarrationStrip } from "../mentor/NarrationStrip";
import { RefactorPanel } from "../refactor/RefactorPanel";
import { CodeEditor } from "../editor/CodeEditor";
import { CallGraphView } from "../graph/CallGraphView";
import { CallTreeView } from "../graph/CallTreeView";
import { HeapView } from "../graph/HeapView";
import { VariablesPanel } from "../state/VariablesPanel";
import { TimelinePanel } from "../timeline/TimelinePanel";
import { TopBar } from "./TopBar";
import { TransportBar } from "./TransportBar";
import { usePlayer } from "./usePlayer";

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
  const { centerTab, setCenterTab, rightTab, setRightTab, presenting, setPresenting } = useUiStore();
  const status = useRunStore((s) => s.status);
  usePlayer();
  const step = usePlayback((s) => s.step);
  const total = useRunStore((s) => s.totalSteps);
  const pct = total ? (step / total) * 100 : 0;

  if (presenting) {
    return (
      <div className="h-full flex flex-col gb-present">
        <div className="flex items-center gap-3 px-4 py-1 text-sm border-b border-[var(--border)] bg-[var(--panel)]">
          <strong>🔍 {t("app.title")}</strong>
          <span className="opacity-70 truncate">{t("present.help")}</span>
          <span className="flex-1" />
          <button className="gb-btn" onClick={() => setPresenting(false)}>✕ {t("present.exit")}</button>
        </div>
        <div className="flex-1 min-h-0">
          <Group orientation="horizontal">
            <Panel defaultSize="50%" minSize="25%"><CodeEditor /></Panel>
            <Separator className="gb-sep" />
            <Panel defaultSize="50%" minSize="25%"><div className="h-full relative"><CallGraphView /></div></Panel>
          </Group>
        </div>
        <NarrationStrip />
        <div className="h-1 bg-[#222]"><div className="h-full bg-[var(--accent)]" style={{ width: `${pct}%` }} /></div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <TopBar />
      <Banner />
      <BranchBar />
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
              <Tabs<RightTab> value={rightTab} onChange={setRightTab} items={[["timeline", "tab.timeline"], ["vars", "tab.vars"], ["mentor", "tab.mentor"], ["cleanup", "tab.cleanup"], ["refactor", "tab.refactor"], ["lab", "tab.lab"]]} />
              <div className="flex-1 min-h-0">
                {rightTab === "timeline" ? <TimelinePanel /> : rightTab === "vars" ? <VariablesPanel /> : rightTab === "mentor" ? <MentorPanel /> : rightTab === "refactor" ? <RefactorPanel /> : rightTab === "lab" ? <LabPanel /> : <MarkSweepPanel />}
              </div>
            </div>
          </Panel>
        </Group>
      </div>
      <NarrationStrip />
      <TransportBar />
      <WhatIfDialog />
    </div>
  );
}
