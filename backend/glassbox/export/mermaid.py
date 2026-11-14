"""Call graph from a trace as Mermaid text and as a standalone SVG (no external tools or fonts)."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from html import escape
from typing import Any


@dataclass
class Graph:
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)  # key -> {label, kind, calls}
    edges: dict[tuple[str, str], int] = field(default_factory=dict)


def build_graph(events: list[dict[str, Any]]) -> Graph:
    g = Graph()
    frame_node: dict[int, str] = {}
    for ev in events:
        if ev["type"] != "call":
            continue
        if ev["kind"] == "boundary":
            key, label, kind = f"lib:{ev['module']}.{ev['func']}", f"{ev['module']}.{ev['func']}", "boundary"
        else:
            key, label, kind = f"fn:{ev['file']}:{ev['qualname']}", ev["qualname"], "user"
        frame_node[ev["frame"]] = key
        node = g.nodes.setdefault(key, {"label": label, "kind": kind, "calls": 0})
        node["calls"] += 1
        parent = frame_node.get(ev["parent"]) if ev.get("parent") is not None else None
        if parent:
            g.edges[(parent, key)] = g.edges.get((parent, key), 0) + 1
    return g


def escape_label(text: str) -> str:
    """Mermaid entity codes for everything that could end a quoted label or be read as markup."""
    table = {"&": "#38;", '"': "#34;", "<": "#60;", ">": "#62;", "|": "#124;", "`": "#96;", "\\": "#92;", "#": "#35;"}
    return "".join(table.get(c, c) for c in text if c not in "\r\n")[:80]


def to_mermaid(events: list[dict[str, Any]]) -> str:
    """``flowchart TD`` text. Node ids are generated (``n0``, ``n1`` ...), so names can never break the syntax."""
    g = build_graph(events)
    ids = {key: f"n{i}" for i, key in enumerate(g.nodes)}
    lines = ["flowchart TD"]
    for key, node in g.nodes.items():
        label = escape_label(f"{node['label']} ({node['calls']}x)")
        lines.append(f'    {ids[key]}("{label}")' if node["kind"] == "boundary" else f'    {ids[key]}["{label}"]')
    for (src, dst), count in g.edges.items():
        lines.append(f"    {ids[src]} -->|{count}| {ids[dst]}")
    boundary = [ids[k] for k, n in g.nodes.items() if n["kind"] == "boundary"]
    if boundary:
        lines.append("    classDef lib stroke-dasharray: 4 3")
        lines.append(f"    class {','.join(boundary)} lib")
    return "\n".join(lines) + "\n"


def to_svg(events: list[dict[str, Any]]) -> str:
    """Layered drawing: rank = shortest call distance from the roots; boxes + arrows with call counts."""
    g = build_graph(events)
    if not g.nodes:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="40"><text x="10" y="25">no calls</text></svg>\n'
    incoming = {dst for _src, dst in g.edges}
    roots = [k for k in g.nodes if k not in incoming] or list(g.nodes)[:1]
    rank: dict[str, int] = {r: 0 for r in roots}
    children: dict[str, list[str]] = defaultdict(list)
    for (src, dst), _c in g.edges.items():
        children[src].append(dst)
    queue = deque(roots)
    while queue:
        cur = queue.popleft()
        for nxt in children[cur]:
            if nxt not in rank:
                rank[nxt] = rank[cur] + 1
                queue.append(nxt)
    for k in g.nodes:
        rank.setdefault(k, 0)
    per_rank: dict[int, list[str]] = defaultdict(list)
    for k in g.nodes:
        per_rank[rank[k]].append(k)
    w, h, gx, gy = 190, 40, 30, 60
    pos: dict[str, tuple[int, int]] = {}
    for r, keys in per_rank.items():
        for i, k in enumerate(keys):
            pos[k] = (20 + i * (w + gx), 20 + r * (h + gy))
    width = max(x for x, _ in pos.values()) + w + 20
    height = max(y for _, y in pos.values()) + h + 20
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="sans-serif" font-size="12">',
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#555"/></marker></defs>',
    ]  # fmt: skip
    for (src, dst), count in g.edges.items():
        (x1, y1), (x2, y2) = pos[src], pos[dst]
        if src == dst:
            out.append(f'<path d="M{x1 + w},{y1 + h / 2} C{x1 + w + 40},{y1 - 10} {x1 + w + 40},{y1 + h + 10} {x1 + w},{y1 + h / 2 + 8}" fill="none" stroke="#555" marker-end="url(#arrow)"/>')
            out.append(f'<text x="{x1 + w + 44}" y="{y1 + h / 2}">{count}</text>')
            continue
        sx, sy, tx, ty = x1 + w / 2, y1 + h, x2 + w / 2, y2
        out.append(f'<line x1="{sx}" y1="{sy}" x2="{tx}" y2="{ty}" stroke="#555" marker-end="url(#arrow)"/>')
        out.append(f'<text x="{(sx + tx) / 2 + 4}" y="{(sy + ty) / 2}">{count}</text>')
    for k, node in g.nodes.items():
        x, y = pos[k]
        dash = ' stroke-dasharray="4 3"' if node["kind"] == "boundary" else ""
        fill = "#efe9ff" if node["kind"] == "boundary" else "#e8f4ff"
        label = escape(f"{node['label']} ({node['calls']}x)")[:40]
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="#333"{dash}/>')
        out.append(f'<text x="{x + w / 2}" y="{y + h / 2 + 4}" text-anchor="middle">{label}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"
