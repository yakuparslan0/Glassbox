import Editor, { type OnMount } from "@monaco-editor/react";
import { useEffect, useMemo, useRef } from "react";
import "../../lib/monaco";
import { monaco } from "../../lib/monaco";
import { formatVal } from "../../lib/format";
import { usePlayback } from "../../store/playbackStore";
import { getRunData, useRunStore } from "../../store/runStore";
import { useUiStore } from "../../store/uiStore";
import { useViewStore } from "../../store/viewStore";

type Deco = monaco.editor.IModelDeltaDecoration;
const whole = (line: number, className: string, extra: Partial<monaco.editor.IModelDecorationOptions> = {}): Deco => ({
  range: new monaco.Range(line, 1, line, 1),
  options: { isWholeLine: true, className, ...extra },
});

const DEAD = new Set(["unreachable_code", "uncalled_function", "unused_import", "unused_variable"]);

export function CodeEditor(): React.ReactElement {
  const source = useRunStore((s) => s.source);
  const setSource = useRunStore((s) => s.setSource);
  const entry = useRunStore((s) => s.entry);
  const report = useRunStore((s) => s.report);
  const version = useRunStore((s) => s.version);
  const step = usePlayback((s) => s.step);
  const view = useViewStore((s) => s.state);
  const reveal = useUiStore((s) => s.reveal);
  const inline = useUiStore((s) => s.settings.inlineValues);

  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const cursor = useRef<monaco.editor.IEditorDecorationsCollection | null>(null);
  const heat = useRef<monaco.editor.IEditorDecorationsCollection | null>(null);
  const marks = useRef<monaco.editor.IEditorDecorationsCollection | null>(null);

  const onMount: OnMount = (editor) => {
    editorRef.current = editor;
    cursor.current = editor.createDecorationsCollection([]);
    heat.current = editor.createDecorationsCollection([]);
    marks.current = editor.createDecorationsCollection([]);
  };

  // active line, call-stack lines and inline values (change per step)
  useEffect(() => {
    const decos: Deco[] = [];
    if (view && step > 0) {
      const data = getRunData();
      view.stack.forEach((f, i) => {
        const top = i === view.stack.length - 1;
        decos.push(
          whole(f.line, top ? "gb-active-line" : "gb-stack-line", {
            glyphMarginClassName: top ? "gb-glyph-active" : "gb-glyph-stack",
          }),
        );
      });
      const ev = data.eventOfStep(step);
      const prev = data.eventOfStep(step - 1);
      if (inline && ev?.type === "line" && prev?.type === "line" && prev.frame === ev.frame) {
        const text = Object.entries(ev.delta.set ?? {})
          .map(([k, v]) => `${k} = ${formatVal(v, view.heap)}`)
          .join(", ");
        if (text) {
          decos.push({
            range: new monaco.Range(prev.line, 1, prev.line, 1),
            options: { after: { content: `  ${text}`, inlineClassName: "gb-inline-value" } },
          });
        }
      }
    }
    cursor.current?.set(decos);
    const top = view?.stack.at(-1);
    if (top && usePlayback.getState().playing) editorRef.current?.revealLineInCenterIfOutsideViewport(top.line);
  }, [view, step, inline]);

  // line-hit heat map in the gutter (shape = bar width, colour = orange scale)
  const hitsKey = version;
  useEffect(() => {
    const hits = getRunData().hits.get(entry);
    if (!hits || !hits.size) {
      heat.current?.set([]);
      return;
    }
    const max = Math.max(...hits.values());
    const decos: Deco[] = [];
    for (const [line, count] of hits) {
      const bin = 1 + Math.min(4, Math.floor((Math.log(count + 1) / Math.log(max + 1)) * 5));
      decos.push({
        range: new monaco.Range(line, 1, line, 1),
        options: { linesDecorationsClassName: `gb-heat gb-heat-${bin}`, hoverMessage: { value: `${count}×` } },
      });
    }
    heat.current?.set(decos);
  }, [hitsKey, entry]);

  // dead / cold decorations from the Mark & Sweep report
  const staticDecos = useMemo(() => {
    const out: Deco[] = [];
    for (const f of report?.findings ?? []) {
      if (f.file !== entry) continue;
      const dead = DEAD.has(f.category) && f.confidence !== "suspect";
      const cold = f.category === "cold_code";
      if (!dead && !cold) continue;
      out.push({
        range: new monaco.Range(f.start_line, 1, f.end_line, 1),
        options: {
          isWholeLine: true,
          className: dead ? "gb-dead" : "gb-cold",
          glyphMarginClassName: dead ? "gb-glyph-dead" : "gb-glyph-cold",
          hoverMessage: { value: f.title },
        },
      });
    }
    return out;
  }, [report, entry]);
  useEffect(() => {
    marks.current?.set(staticDecos);
  }, [staticDecos]);

  useEffect(() => {
    if (!reveal || !editorRef.current) return;
    editorRef.current.revealLinesInCenter(reveal.start, reveal.end);
    editorRef.current.setSelection(new monaco.Selection(reveal.start, 1, reveal.end + 1, 1));
  }, [reveal]);

  return (
    <Editor
      language="python"
      theme="vs-dark"
      value={source}
      onChange={(v) => setSource(v ?? "")}
      onMount={onMount}
      options={{
        glyphMargin: true,
        minimap: { enabled: false },
        fontSize: 14,
        scrollBeyondLastLine: false,
        automaticLayout: true,
        lineNumbersMinChars: 3,
      }}
    />
  );
}
