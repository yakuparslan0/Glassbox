"""Aliasing findings: mutable default arguments and mutation through one name read through another."""

from __future__ import annotations

import ast
from typing import Any

from ..schemas.analysis import Finding
from .common import make_finding

_MUTATORS = frozenset(
    {"append", "extend", "insert", "remove", "pop", "clear", "sort", "reverse", "add", "discard", "update",
     "setdefault", "popitem", "appendleft", "extendleft"}
)  # fmt: skip
_MUTABLE_CALLS = frozenset({"list", "dict", "set", "bytearray", "deque", "defaultdict"})


def _is_mutable_default(node: ast.expr) -> bool:
    if isinstance(node, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)):
        return True
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _MUTABLE_CALLS


def _mutable_default_params(trees: dict[str, ast.Module]) -> dict[tuple[str, str], list[tuple[str, ast.arguments, int]]]:
    """(file, function name) -> [(param, args node, def line)] for parameters with a mutable default."""
    out: dict[tuple[str, str], list[tuple[str, ast.arguments, int]]] = {}
    for file, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            positional = [*node.args.posonlyargs, *node.args.args]
            pairs = list(zip(positional[len(positional) - len(node.args.defaults) :], node.args.defaults, strict=True))
            pairs += [(a, d) for a, d in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True) if d is not None]
            for arg, default in pairs:
                if _is_mutable_default(default):
                    out.setdefault((file, node.name), []).append((arg.arg, node.args, node.lineno))
    return out


def _mutated_names(stmt: ast.stmt) -> set[str]:
    """Names whose object a statement mutates in place (``x.append``, ``x[i] = ..``, ``x += ..`` on containers)."""
    names: set[str] = set()
    for node in ast.walk(stmt):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _MUTATORS:
            if isinstance(node.func.value, ast.Name):
                names.add(node.func.value.id)
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
            targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
            for t in targets:
                if isinstance(t, (ast.Subscript, ast.Attribute)) and isinstance(t.value, ast.Name):
                    names.add(t.value.id)
    return names


def _loaded_names(stmt: ast.stmt) -> set[str]:
    return {n.id for n in ast.walk(stmt) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def _statement_at(tree: ast.Module, line: int) -> ast.stmt | None:
    """Innermost simple statement starting on ``line``."""
    best: ast.stmt | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and node.lineno == line and not hasattr(node, "body"):
            best = node
    return best


def analyze(events: list[dict[str, Any]], sources: dict[str, ast.Module]) -> list[Finding]:
    findings: list[Finding] = []
    defaults = _mutable_default_params(sources)

    heap: dict[str, Any] = {}
    frames: dict[int, dict[str, Any]] = {}
    calls: dict[tuple[str, str], list[dict[str, Any]]] = {}
    reported_default: set[tuple[str, str, str]] = set()
    alias_seen: set[tuple[str, str]] = set()
    pending: dict[tuple[int, str], dict[str, Any]] = {}  # (frame, ref) -> mutation info

    for ev in events:
        typ = ev.get("type")
        changed = {} if typ == "keyframe" else (ev.get("heap") or {})
        if typ == "call" and ev.get("kind") == "user":
            frames[ev["frame"]] = {"file": ev["file"], "func": ev["func"], "locals": dict(ev.get("args") or {}), "prev": None}
            for ref_name, value in (ev.get("args") or {}).items():
                if isinstance(value, dict) and "ref" in value:
                    calls.setdefault((ev["file"], ev["func"]), []).append(
                        {"param": ref_name, "ref": value["ref"], "frame": ev["frame"], "step": ev["step"],
                         "snapshot": _fingerprint(heap, ev.get("heap") or {}, value["ref"])}
                    )  # fmt: skip
        mutated_refs = [ref for ref in changed if ref in heap]  # known object whose content changed
        heap.update(changed)
        if typ == "keyframe":
            heap.update(ev.get("heap") or {})
        frame = frames.get(ev.get("frame", -1))
        if typ == "line" and frame is not None:
            frame["locals"].update(ev["delta"]["set"])
            for name in ev["delta"]["del"]:
                frame["locals"].pop(name, None)
            tree = sources.get(frame["file"])
            # 1) a mutation shows up on the event AFTER the statement that caused it
            for ref in mutated_refs:
                names = sorted(n for n, v in frame["locals"].items() if isinstance(v, dict) and v.get("ref") == ref)
                if len(names) >= 2 and tree is not None and frame["prev"] is not None:
                    stmt = _statement_at(tree, frame["prev"])
                    mutators = (_mutated_names(stmt) & set(names)) if stmt else set()
                    if mutators:
                        pending[(ev["frame"], ref)] = {
                            "names": names, "mutator": sorted(mutators)[0], "mutation_line": frame["prev"],
                            "step": ev["step"], "ref": ref, "file": frame["file"],
                        }  # fmt: skip
            # 2) a later statement reads the object through another alias
            if tree is not None:
                stmt = _statement_at(tree, ev["line"])
                if stmt is not None:
                    loads = _loaded_names(stmt)
                    for key, info in list(pending.items()):
                        if key[0] != ev["frame"] or (info["file"], info["ref"]) in alias_seen:
                            continue
                        readers = (loads & set(info["names"])) - {info["mutator"]}
                        if readers:
                            alias_seen.add((info["file"], info["ref"]))
                            findings.append(
                                make_finding(
                                    "alias_mutation", "warn", "confirmed", info["file"], info["mutation_line"],
                                    ev["line"],
                                    f"'{info['mutator']}' changed an object that '{sorted(readers)[0]}' also refers to",
                                    {"object": info["ref"], "aliases": info["names"], "mutated_through": info["mutator"],
                                     "read_through": sorted(readers), "mutation_line": info["mutation_line"],
                                     "read_line": ev["line"], "mutation_step": info["step"], "read_step": ev["step"]},
                                )
                            )  # fmt: skip
            frame["prev"] = ev["line"]
        elif typ == "return":
            frames.pop(ev["frame"], None)

    # mutable default: same object passed to the same parameter in >= 2 calls AND its content grew/changed
    for (file, func), params in defaults.items():
        records = calls.get((file, func), [])
        for param, _args, def_line in params:
            same = [r for r in records if r["param"] == param]
            by_ref: dict[str, list[dict[str, Any]]] = {}
            for r in same:
                by_ref.setdefault(r["ref"], []).append(r)
            for ref, group in by_ref.items():
                if len(group) < 2 or len({g["snapshot"] for g in group}) < 2:
                    continue
                if (file, func, param) in reported_default:
                    continue
                reported_default.add((file, func, param))
                findings.append(
                    make_finding(
                        "mutable_default", "high", "confirmed", file, def_line, def_line,
                        f"Default value of parameter '{param}' in '{func}' is one shared, mutable object",
                        {"function": func, "parameter": param, "object": ref, "calls": [g["frame"] for g in group],
                         "contents_seen": sorted({g["snapshot"] for g in group})},
                    )
                )  # fmt: skip
    return findings


def _fingerprint(heap: dict[str, Any], delta: dict[str, Any], ref: str) -> str:
    """Compact, comparable text of a heap object as of this call (``delta`` holds entries sent with it)."""
    entry = delta.get(ref, heap.get(ref))
    if entry is None:
        return "?"
    items = entry.get("items") or entry.get("pairs") or entry.get("attrs") or entry.get("r")
    return f"{entry.get('t')}:{entry.get('len', '')}:{items}"
