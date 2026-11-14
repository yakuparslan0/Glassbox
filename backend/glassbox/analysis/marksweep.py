"""Mark & Sweep: combine static reachability (MARK-1) with what actually ran (MARK-2).

Classes: ``confirmed`` dead (statically unreachable AND did not run), ``cold`` (reachable but did not run in
this run), ``suspect`` (dynamic access possible: informational only).
"""

from __future__ import annotations

import ast
from collections import defaultdict
from typing import Any

from ..schemas.analysis import Finding, MarkSweepReport, MarkSweepSummary
from . import aliasing, clones, complexity, dynamic_profile, static_dead
from .common import (
    def_start,
    end_line,
    finalize,
    first_body_line,
    make_finding,
    overlaps,
    parse_files,
)

_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
_DEAD_CATEGORIES = {"uncalled_function", "unreachable_code", "unused_import", "unused_variable"}


# ------------------------------------------------------------------------------------------ MARK-1
def _definitions(trees: dict[str, ast.Module]) -> dict[tuple[str, str], ast.AST]:
    """(file, qualname) -> def node for every function / class (qualname without ``<locals>``)."""
    out: dict[tuple[str, str], ast.AST] = {}

    def visit(file: str, body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, (*_FUNC, ast.ClassDef)):
                qual = prefix + node.name
                out[(file, qual)] = node
                visit(file, node.body, qual + ".")
            else:
                for attr in ("body", "orelse", "finalbody"):
                    inner = getattr(node, attr, None)
                    if isinstance(inner, list) and inner and isinstance(inner[0], ast.stmt):
                        visit(file, inner, prefix)
                for handler in getattr(node, "handlers", []):
                    visit(file, handler.body, prefix)

    for file, tree in trees.items():
        visit(file, tree.body, "")
    return out


def _own_references(node: ast.AST) -> set[str]:
    """Names referenced by ``node`` without descending into nested defs (they are graph nodes themselves)."""
    refs: set[str] = set()
    stack: list[ast.AST] = []
    if isinstance(node, ast.Module):
        stack = list(node.body)
    elif isinstance(node, _FUNC):
        stack = list(node.body) + list(node.decorator_list) + _default_exprs(node)
    else:  # class body executes when the class is defined; methods are separate nodes
        assert isinstance(node, ast.ClassDef)
        stack = [*node.body, *node.decorator_list, *node.bases]
    while stack:
        cur = stack.pop()
        if isinstance(cur, (*_FUNC, ast.ClassDef)):
            stack.extend(cur.decorator_list)
            stack.extend(_default_exprs(cur) if isinstance(cur, _FUNC) else cur.bases)
            continue
        if isinstance(cur, ast.Name) and isinstance(cur.ctx, ast.Load):
            refs.add(cur.id)
        elif isinstance(cur, ast.Attribute) and isinstance(cur.ctx, ast.Load):
            refs.add(cur.attr)
        elif isinstance(cur, ast.ImportFrom):
            refs.update(a.name for a in cur.names)
        elif isinstance(cur, ast.Constant) and isinstance(cur.value, str) and len(cur.value) < 100:
            refs.add(cur.value)  # getattr(obj, "name") / dispatch tables keyed by name
        stack.extend(ast.iter_child_nodes(cur))
    return refs


def _default_exprs(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    return [*func.args.defaults, *(d for d in func.args.kw_defaults if d is not None)]


def reachable_definitions(trees: dict[str, ast.Module]) -> tuple[set[tuple[str, str]], dict[tuple[str, str], ast.AST]]:
    """Definitions reachable from the roots by name-based call graph (over-approximation by simple name)."""
    defs = _definitions(trees)
    by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in defs:
        by_name[key[1].rsplit(".", 1)[-1]].append(key)

    reached: set[tuple[str, str]] = set()
    work: list[tuple[str, str]] = []

    def reach_name(name: str) -> None:
        for key in by_name.get(name, ()):
            if key not in reached:
                reached.add(key)
                work.append(key)

    for tree in trees.values():
        for name in _own_references(tree):
            reach_name(name)
        for name in static_dead._all_names(tree):
            reach_name(name)
    for key, node in defs.items():  # decorated definitions may be registered somewhere: treat as roots
        if getattr(node, "decorator_list", None):
            reach_name(key[1].rsplit(".", 1)[-1])
    while work:
        key = work.pop()
        node = defs[key]
        for name in _own_references(node):
            reach_name(name)
        if isinstance(node, ast.ClassDef):  # a live class keeps its dunder methods alive (__init__, __repr__ ...)
            for child_key, child in defs.items():
                direct_child = (
                    child_key[0] == key[0]
                    and child_key[1].startswith(key[1] + ".")
                    and child_key[1].count(".") == key[1].count(".") + 1
                )
                if direct_child and isinstance(child, _FUNC) and child.name.startswith("__") and child.name.endswith("__"):
                    reach_name(child.name)
    return reached, defs


# ------------------------------------------------------------------------------------------ MARK-2
def _executed(executed: dict[str, set[int]], file: str, start: int, end: int) -> bool:
    lines = executed.get(file, set())
    return any(start <= n <= end for n in lines)


def _cold_blocks(
    file: str,
    tree: ast.Module,
    executed: set[int],
    skip: list[tuple[int, int]],
    is_entry: bool,
    dead_defs: set[int],
) -> list[Finding]:
    out: list[Finding] = []

    def blocked(start: int, end: int) -> bool:
        return any(overlaps(start, end, s, e) for s, e in skip)

    def hit(start: int, end: int) -> bool:
        return any(start <= n <= end for n in executed)

    def add_block(stmts: list[ast.stmt], why: str) -> None:
        if not stmts:
            return
        start, end = stmts[0].lineno, end_line(stmts[-1])
        if blocked(start, end) or hit(start, end):
            return
        out.append(
            make_finding(
                "cold_code", "info", "likely", file, start, end, f"Not executed in this run ({why})",
                {"scope": "block", "reason": why, "note": "reachable code that this input never exercised"},
            )
        )  # fmt: skip

    def visit(stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            if isinstance(stmt, (*_FUNC, ast.ClassDef)):
                start = def_start(stmt)
                if not hit(start, stmt.lineno):  # the def itself did not run: nothing to say
                    continue
                if stmt.lineno in dead_defs:
                    continue
                if isinstance(stmt, ast.ClassDef):
                    visit(stmt.body)
                elif not hit(first_body_line(stmt), end_line(stmt)):
                    if not blocked(start, end_line(stmt)):
                        out.append(
                            make_finding(
                                "cold_code", "info", "likely", file, start, end_line(stmt),
                                f"Function '{stmt.name}' is reachable but was never called in this run",
                                {"scope": "function", "name": stmt.name,
                                 "note": "reachable code that this input never exercised"},
                            )
                        )  # fmt: skip
                else:
                    visit(stmt.body)
                continue
            if not hit(stmt.lineno, stmt.lineno):
                continue  # the statement itself never ran; an enclosing block is reported instead
            if (
                isinstance(stmt, ast.If)
                and not is_entry
                and isinstance(stmt.test, ast.Compare)
                and isinstance(stmt.test.left, ast.Name)
                and stmt.test.left.id == "__name__"
            ):
                continue
            blocks: list[tuple[list[ast.stmt], str]] = []
            if isinstance(stmt, ast.If):
                blocks = [(stmt.body, "branch"), (stmt.orelse, "else branch")]
            elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
                blocks = [(stmt.body, "loop body never entered"), (stmt.orelse, "loop else")]
            elif isinstance(stmt, (ast.Try, ast.TryStar)):
                blocks = [(stmt.body, "try body"), *((h.body, "except handler") for h in stmt.handlers),
                          (stmt.orelse, "try else"), (stmt.finalbody, "finally")]  # fmt: skip
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                blocks = [(stmt.body, "with body")]
            elif isinstance(stmt, ast.Match):
                blocks = [(case.body, "match case") for case in stmt.cases]
            for block, why in blocks:
                if not block:
                    continue
                if hit(block[0].lineno, end_line(block[-1])):
                    visit(block)
                else:
                    add_block(block, why)

    visit(tree.body)
    return out


# ------------------------------------------------------------------------------------------ report
def static_with_transitive(trees: dict[str, ast.Module]) -> list[Finding]:
    """Direct static findings plus functions that are only reachable from dead code (no run needed)."""
    static = static_dead.analyze(trees)
    reached, defs = reachable_definitions(trees)

    # transitive dead code: unreachable definitions that static_dead did not flag (only used by dead code)
    flagged = {(f.file, f.start_line) for f in static if f.category == "uncalled_function"}
    for (file, qual), node in defs.items():
        if (file, qual) in reached or isinstance(node, ast.ClassDef):
            continue
        start = def_start(node)  # type: ignore[arg-type]
        if (file, start) in flagged or "." in qual:
            continue
        static.append(
            make_finding(
                "uncalled_function", "warn", "likely", file, start, end_line(node),
                f"Function '{node.name}' is only reachable from dead code",  # type: ignore[attr-defined]
                {"name": node.name, "kind": "function", "qualname": qual, "reason": "transitively unreachable"},  # type: ignore[attr-defined]
                autofixable=not getattr(node, "decorator_list", None),
            )
        )  # fmt: skip
    return static


def build(files: dict[str, str], entry: str, events: list[dict[str, Any]]) -> MarkSweepReport:
    trees = parse_files(files)
    finished = next((e for e in reversed(events) if e.get("type") == "run_finished"), {})
    executed = {f: set(map(int, lines)) for f, lines in (finished.get("executed_lines") or {}).items()}
    ran = bool(executed)

    findings: list[Finding] = []
    static = static_with_transitive(trees)

    # classify dead findings with MARK-2
    skip_ranges: dict[str, list[tuple[int, int]]] = defaultdict(list)
    dead_def_lines: dict[str, set[int]] = defaultdict(set)
    for f in static:
        if f.category in {"uncalled_function", "unreachable_code"}:
            skip_ranges[f.file].append((f.start_line, f.end_line))
        if f.category == "uncalled_function":
            dead_def_lines[f.file].add(f.start_line)
        if f.category in {"uncalled_function", "unreachable_code"} and ran:
            body_start = f.start_line + 1 if f.category == "uncalled_function" else f.start_line
            if _executed(executed, f.file, body_start, f.end_line):
                f.confidence = "suspect"
                f.evidence["executed_anyway"] = True
                f.evidence["note"] = "statically unreachable, but this run executed it (dynamic access?)"
                f.autofixable = False
            elif f.confidence == "likely":
                f.confidence = "confirmed"  # statically unreachable AND did not run
        elif f.category == "uncalled_function" and f.confidence == "likely":
            f.confidence = "confirmed" if ran else "likely"
    findings += static

    if ran:
        for file, tree in trees.items():
            lines = executed.get(file)
            if not lines:
                continue
            findings += _cold_blocks(file, tree, lines, skip_ranges[file], file == entry, dead_def_lines[file])

    findings += clones.find(trees)
    findings += dynamic_profile.analyze_trace(events, trees)
    findings += aliasing.analyze(events, trees)
    findings = finalize(findings)

    reclaim: set[tuple[str, int]] = set()
    for f in findings:
        if f.category in _DEAD_CATEGORIES and f.confidence == "confirmed":
            reclaim.update((f.file, n) for n in range(f.start_line, f.end_line + 1))
    summary = MarkSweepSummary(
        confirmed_dead=sum(1 for f in findings if f.category in _DEAD_CATEGORIES and f.confidence == "confirmed"),
        cold=sum(1 for f in findings if f.category == "cold_code"),
        suspect=sum(1 for f in findings if f.confidence == "suspect"),
        reclaimable_lines=len(reclaim),
    )
    return MarkSweepReport(
        run_status=str(finished.get("status", "unknown")),
        steps=int(finished.get("steps", 0)),
        findings=findings,
        functions=complexity.analyze(trees),
        summary=summary,
    )


def build_static(files: dict[str, str]) -> tuple[list[Finding], list[Any]]:
    """Static-only report body (no run): findings from static_dead + clones, plus complexity."""
    trees = parse_files(files)
    return finalize([*static_dead.analyze(trees), *clones.find(trees)]), complexity.analyze(trees)
