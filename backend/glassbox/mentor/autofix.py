"""LLM-free, safe automatic fixes: unused imports, side-effect-free unused assignments, unreachable blocks and
never-referenced top-level functions. Every single fix must leave parseable code or it is skipped."""

from __future__ import annotations

import ast

from ..analysis import marksweep
from ..analysis.common import def_start, end_line, finalize, parse_files
from ..schemas.analysis import Finding
from ..schemas.llm import Edit
from .edits import EditError, apply_edits

FIXABLE = {"unused_import", "unused_variable", "unreachable_code", "uncalled_function"}


def findings_for(files: dict[str, str]) -> list[Finding]:
    """The findings autofix understands (static + transitive; confirmed/likely only, never ``suspect``)."""
    trees = parse_files(files)
    return finalize(
        [
            f
            for f in marksweep.static_with_transitive(trees)
            if f.category in FIXABLE and f.autofixable and f.confidence != "suspect"
        ]
    )


def _stmt_index(tree: ast.Module) -> dict[tuple[int, int], tuple[ast.stmt, list[ast.stmt]]]:
    """(start, end) line range -> (statement, the statement list that contains it)."""
    index: dict[tuple[int, int], tuple[ast.stmt, list[ast.stmt]]] = {}

    def walk(body: list[ast.stmt]) -> None:
        for stmt in body:
            start = def_start(stmt) if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else stmt.lineno
            index[(start, end_line(stmt))] = (stmt, body)
            for attr in ("body", "orelse", "finalbody"):
                inner = getattr(stmt, attr, None)
                if isinstance(inner, list) and inner and isinstance(inner[0], ast.stmt):
                    walk(inner)
            for handler in getattr(stmt, "handlers", []):
                walk(handler.body)
            for case in getattr(stmt, "cases", []):
                walk(case.body)

    walk(tree.body)
    return index


def _import_text(node: ast.Import | ast.ImportFrom, keep: list[ast.alias]) -> str:
    names = ", ".join(f"{a.name} as {a.asname}" if a.asname else a.name for a in keep)
    if isinstance(node, ast.Import):
        return f"import {names}"
    return f"from {'.' * node.level}{node.module or ''} import {names}"


def _edit_for(finding: Finding, source: str, tree: ast.Module) -> Edit | None:
    """The edit that fixes ``finding`` against the ORIGINAL source (None = not safely fixable)."""
    lines = source.splitlines()
    start, end = finding.start_line, finding.end_line
    stmt_info = _stmt_index(tree).get((start, end))
    indent = lines[start - 1][: len(lines[start - 1]) - len(lines[start - 1].lstrip())]

    if finding.category == "unused_import":
        if stmt_info is None or not isinstance(stmt_info[0], (ast.Import, ast.ImportFrom)):
            return None
        node = stmt_info[0]
        name = finding.evidence["name"]
        keep = [a for a in node.names if (a.asname or a.name.split(".")[0]) != name]
        if keep:
            return Edit(file=finding.file, start_line=start, end_line=end, new_code=indent + _import_text(node, keep))
    elif finding.category == "unused_variable":
        if stmt_info is None or not finding.evidence.get("side_effect_free"):
            return None
    elif finding.category == "uncalled_function" and stmt_info is None:
        return None
    # removal: a statement that is the only one of its block is replaced by `pass`. An unreachable RUN of statements
    # (no single matching statement) is deleted; if that would empty a block the parse check rejects it.
    if stmt_info is not None and len(stmt_info[1]) == 1:
        return Edit(file=finding.file, start_line=start, end_line=end, new_code=indent + "pass")
    if finding.category == "uncalled_function":  # swallow the blank lines after a removed definition
        while end < len(lines) and not lines[end].strip():
            end += 1
    return Edit(file=finding.file, start_line=start, end_line=end, new_code="")


def apply_autofix(files: dict[str, str], finding_ids: list[str]) -> tuple[dict[str, str], list[str], list[dict[str, str]]]:
    """Returns (new files, applied ids, skipped [{id, reason}])."""
    available = {f.id: f for f in findings_for(files)}
    trees = parse_files(files)
    current = dict(files)
    applied: list[str] = []
    skipped: list[dict[str, str]] = []
    wanted = []
    for fid in finding_ids:
        if fid in available:
            wanted.append(available[fid])
        else:
            skipped.append({"id": fid, "reason": "not an auto-fixable finding for these files"})
    # bottom-up per file: earlier line numbers stay valid while later code is removed
    covered: list[tuple[str, int, int]] = []
    for f in sorted(wanted, key=lambda x: (x.file, -x.start_line)):
        if any(f.file == cf and f.start_line <= ce and cs <= f.end_line for cf, cs, ce in covered):
            skipped.append({"id": f.id, "reason": "overlaps another fix that was already applied"})
            continue
        edit = _edit_for(f, files[f.file], trees[f.file])
        if edit is None:
            skipped.append({"id": f.id, "reason": "the statement cannot be removed safely"})
            continue
        try:
            current = apply_edits(current, [edit])
        except EditError as exc:
            skipped.append({"id": f.id, "reason": str(exc)})
            continue
        covered.append((f.file, f.start_line, f.end_line))
        applied.append(f.id)
    return current, applied, skipped

