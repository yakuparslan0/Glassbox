"""Replay HTML: ONE file with the trace, the source and a read-only mini player. No network, no external URLs.

If the embedded trace would exceed ``max_bytes`` it is thinned by growing the keyframe stride (spec 7.7): only every
k-th keyframe is kept and the player then jumps between those snapshots instead of replaying every step.
"""

from __future__ import annotations

import json
from typing import Any

DEFAULT_MAX_BYTES = 1_500_000
_KEEP = ("run_started", "call", "line", "return", "exception", "keyframe", "output", "limit_exceeded", "run_finished")
_DROP_KEYS = {"t", "v", "dur_ns", "trunc"}


def _compact(ev: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in ev.items() if k not in _DROP_KEYS}


def _size(events: list[dict[str, Any]]) -> int:
    return len(json.dumps(events, separators=(",", ":")))


def thin(events: list[dict[str, Any]], max_bytes: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(events to embed, info). Full trace when it fits; otherwise keyframes only, with the stride doubled until it fits."""
    kept = [_compact(e) for e in events if e["type"] in _KEEP]
    full = _size(kept)
    if full <= max_bytes:
        return kept, {"thinned": False, "full_bytes": full}
    frames = [e for e in kept if e["type"] == "keyframe"]
    head = [e for e in kept if e["type"] in ("run_started",)]
    tail = [e for e in kept if e["type"] in ("limit_exceeded", "run_finished")]
    outputs = [e for e in kept if e["type"] == "output"]
    stride = 1
    while stride <= max(len(frames), 1):
        chosen = frames[::stride]
        candidate = sorted([*head, *chosen, *outputs, *tail], key=lambda e: e["seq"])
        if _size(candidate) <= max_bytes or len(chosen) <= 1:
            return candidate, {"thinned": True, "full_bytes": full, "keyframe_stride": stride, "keyframes": len(chosen)}
        stride *= 2
    return [*head, *tail], {"thinned": True, "full_bytes": full, "keyframe_stride": stride, "keyframes": 0}


PLAYER_JS = r"""
(function () {
  var el = typeof document !== "undefined" ? document.getElementById("gb-data") : null;
  var DATA = JSON.parse(el ? el.textContent : globalThis.__GB_DATA__);
  var STEP = {call: 1, line: 1, "return": 1, exception: 1};
  var events = DATA.events;
  function assign(t, d) { if (!d) return; var k; for (k in (d.set || {})) t[k] = d.set[k]; (d.del || []).forEach(function (n) { delete t[n]; }); }
  function fresh() { return {stack: [], globals: {}, heap: {}}; }
  function apply(s, ev) {
    if (ev.heap) for (var h in ev.heap) s.heap[h] = ev.heap[h];
    if (ev.type === "keyframe") {
      s.stack = ev.stack.map(function (f) { return {frame: f.frame, func: f.func, line: f.line, locals: Object.assign({}, f.locals)}; });
      s.globals = Object.assign({}, ev.globals); s.heap = Object.assign({}, ev.heap);
    } else if (ev.type === "call") {
      if (ev.kind === "user") s.stack.push({frame: ev.frame, func: ev.func, line: ev.line, locals: Object.assign({}, ev.args)});
      assign(s.globals, ev.globals_delta);
    } else if (ev.type === "line") {
      var f = s.stack.filter(function (x) { return x.frame === ev.frame; })[0];
      if (f) { f.line = ev.line; assign(ev.frame === 1 ? s.globals : f.locals, ev.delta); }
      assign(s.globals, ev.globals_delta);
    } else if (ev.type === "return") {
      assign(s.globals, ev.globals_delta);
      if (ev.kind !== "boundary") s.stack = s.stack.filter(function (x) { return x.frame !== ev.frame; });
    } else if (ev.type === "exception") { assign(s.globals, ev.globals_delta); }
  }
  // step k -> state after the last event BEFORE the next step event (same rule as the app)
  var stepEvents = []; // indexes of step-creating events (or of keyframes when the trace was thinned)
  events.forEach(function (e, i) { if (DATA.info.thinned ? e.type === "keyframe" : STEP[e.type]) stepEvents.push(i); });
  function stateAt(k) {
    var end = k + 1 < stepEvents.length ? stepEvents[k + 1] - 1 : events.length - 1;
    var start = 0, i;
    for (i = end; i >= 0; i--) if (events[i].type === "keyframe") { start = i; break; }
    var s = fresh();
    for (i = start; i <= end; i++) apply(s, events[i]);
    return s;
  }
  function outputAt(k) {
    var end = k + 1 < stepEvents.length ? stepEvents[k + 1] - 1 : events.length - 1, t = "", i;
    for (i = 0; i <= end; i++) if (events[i].type === "output") t += events[i].text;
    return t;
  }
  function show(v, heap, d) {
    if (v.ref) { var e = heap[v.ref]; if (!e) return "<" + v.ref + ">"; if ((d || 0) > 1) return e.t + "…";
      if (e.k === "seq") return "[" + e.items.map(function (x) { return show(x, heap, (d || 0) + 1); }).join(", ") + "]";
      if (e.k === "map") return "{" + e.pairs.map(function (p) { return show(p[0], heap, (d || 0) + 1) + ": " + show(p[1], heap, (d || 0) + 1); }).join(", ") + "}";
      if (e.k === "obj") return e.t + "(" + Object.keys(e.attrs).map(function (k) { return k + "=" + show(e.attrs[k], heap, (d || 0) + 1); }).join(", ") + ")";
      return e.r || e.t; }
    return v.r;
  }
  if (typeof module !== "undefined") module.exports = {stateAt: stateAt, outputAt: outputAt, steps: function () { return stepEvents.length; }, show: show};
  if (typeof document === "undefined" || !document.getElementById("gb-slider")) return;
  var slider = document.getElementById("gb-slider"), cur = 0, timer = null;
  var srcLines = DATA.source.split("\n");
  var srcEl = document.getElementById("gb-source");
  srcEl.innerHTML = "";
  srcLines.forEach(function (l, i) { var d = document.createElement("div"); d.className = "ln"; d.id = "ln" + (i + 1); d.textContent = (i + 1 + "    ").slice(0, 4) + l; srcEl.appendChild(d); });
  slider.max = Math.max(stepEvents.length - 1, 0);
  function render(k) {
    cur = k; slider.value = k;
    var s = stateAt(k), top = s.stack[s.stack.length - 1];
    Array.prototype.forEach.call(document.querySelectorAll(".ln.on"), function (n) { n.classList.remove("on"); });
    if (top) { var n = document.getElementById("ln" + top.line); if (n) { n.classList.add("on"); n.scrollIntoView({block: "nearest"}); } }
    var rows = s.stack.map(function (f) { return "<b>" + f.func + "</b>:" + f.line + "<br>" + Object.keys(f.locals).map(function (n) { return "&nbsp;&nbsp;" + n + " = " + esc(show(f.locals[n], s.heap)); }).join("<br>"); });
    document.getElementById("gb-stack").innerHTML = rows.reverse().join("<hr>");
    document.getElementById("gb-globals").innerHTML = Object.keys(s.globals).filter(function (n) { return String(s.globals[n].r || "").indexOf("<function") !== 0; }).map(function (n) { return n + " = " + esc(show(s.globals[n], s.heap)); }).join("<br>");
    document.getElementById("gb-out").textContent = outputAt(k);
    document.getElementById("gb-label").textContent = "step " + (k + 1) + " / " + stepEvents.length;
  }
  function esc(t) { return String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;"); }
  slider.oninput = function () { render(Number(slider.value)); };
  document.getElementById("gb-prev").onclick = function () { render(Math.max(0, cur - 1)); };
  document.getElementById("gb-next").onclick = function () { render(Math.min(stepEvents.length - 1, cur + 1)); };
  document.getElementById("gb-play").onclick = function () {
    if (timer) { clearInterval(timer); timer = null; this.textContent = "▶"; return; }
    this.textContent = "⏸"; var b = this;
    timer = setInterval(function () { if (cur >= stepEvents.length - 1) { clearInterval(timer); timer = null; b.textContent = "▶"; return; } render(cur + 1); }, 120);
  };
  document.addEventListener("keydown", function (e) { if (e.key === "ArrowRight") render(Math.min(stepEvents.length - 1, cur + 1)); if (e.key === "ArrowLeft") render(Math.max(0, cur - 1)); });
  if (stepEvents.length) render(0);
})();
"""

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GlassBox replay: __TITLE__</title>
<style>
body{margin:0;font:14px system-ui,sans-serif;background:#11141a;color:#dde3ee;display:grid;grid-template-rows:auto 1fr auto;height:100vh}
header{padding:8px 12px;background:#181c24;border-bottom:1px solid #2a303c} main{display:grid;grid-template-columns:1.2fr 1fr;min-height:0}
#gb-source,#gb-side{overflow:auto;padding:8px;font:13px ui-monospace,Consolas,monospace} #gb-source .ln{white-space:pre;padding:0 4px} #gb-source .on{background:#1b3550;border-left:3px solid #4cc2ff}
#gb-side h4{margin:8px 0 2px;font:11px system-ui;text-transform:uppercase;opacity:.6} #gb-out{white-space:pre-wrap;background:#0c0e13;padding:6px;min-height:2em}
footer{display:flex;gap:8px;align-items:center;padding:8px 12px;background:#181c24;border-top:1px solid #2a303c} footer input{flex:1} button{background:#232938;color:#dde3ee;border:1px solid #2a303c;border-radius:6px;padding:2px 10px}
.note{background:#3a2f17;color:#ffd98a;padding:4px 12px}
</style></head><body>
<header><b>GlassBox replay</b> &middot; __TITLE__ &middot; read-only, works offline</header>
<main><div id="gb-source"><noscript>This replay needs JavaScript.</noscript></div>
<div id="gb-side"><h4>Call stack</h4><div id="gb-stack"></div><h4>Globals</h4><div id="gb-globals"></div><h4>Output</h4><pre id="gb-out"></pre></div></main>
<footer><button id="gb-prev">◀</button><button id="gb-play">▶</button><button id="gb-next">▶|</button>
<input id="gb-slider" type="range" min="0" max="0" value="0"><span id="gb-label"></span></footer>
__NOTE__
<script id="gb-data" type="application/json">__DATA__</script>
<script>__PLAYER__</script>
</body></html>
"""


def _safe_json(obj: Any) -> str:
    # "</" would let the data close its own <script> element; U+2028/2029 break some JS parsers
    return json.dumps(obj, separators=(",", ":")).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def build_replay(events: list[dict[str, Any]], source: str, title: str, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
    embedded, info = thin(events, max_bytes)
    note = ""
    if info["thinned"]:
        note = (
            f'<div class="note">The trace was thinned to fit {max_bytes // 1000} KB: the player jumps between every '
            f'{info.get("keyframe_stride", 1)}-th snapshot instead of replaying every step.</div>'
        )
    data = _safe_json({"events": embedded, "source": source, "title": title, "info": info})
    return (
        TEMPLATE.replace("__TITLE__", _escape(title)).replace("__NOTE__", note)
        .replace("__DATA__", data).replace("__PLAYER__", PLAYER_JS)
    )  # fmt: skip


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
