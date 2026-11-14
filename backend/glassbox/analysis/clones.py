"""Type-1/Type-2 clone detection: hash normalized AST subtrees and group equal hashes."""

from __future__ import annotations

import ast
import builtins
import hashlib
from collections import defaultdict
from dataclasses import dataclass

from ..schemas.analysis import Finding
from .common import end_line, make_finding

MIN_STATEMENTS = 5
MIN_NODES = 40
_BUILTIN_NAMES = frozenset(dir(builtins))


def _normalized(node: ast.AST) -> str:
    """Canonical text of a subtree: identifiers and constants are erased, structure and operators stay."""

    def walk(n: ast.AST) -> str:
        if isinstance(n, ast.Name):
            return f"Name({n.id if n.id in _BUILTIN_NAMES else '_'},{type(n.ctx).__name__})"
        if isinstance(n, ast.arg):
            return "arg"
        if isinstance(n, ast.Constant):
            return f"Const({type(n.value).__name__})"
        parts = [type(n).__name__]
        for field, value in ast.iter_fields(n):
            if field in {"name", "type_comment", "lineno", "end_lineno", "col_offset", "end_col_offset"}:
                continue
            if isinstance(value, ast.AST):
                parts.append(f"{field}={walk(value)}")
            elif isinstance(value, list):
                parts.append(f"{field}=[{','.join(walk(v) if isinstance(v, ast.AST) else repr(v) for v in value)}]")
            elif field not in {"id", "arg", "asname"}:
                parts.append(f"{field}={value!r}")
        return "(" + " ".join(parts) + ")"

    return walk(node)


@dataclass
class _Candidate:
    file: str
    start: int
    end: int
    name: str


def _sizes(node: ast.AST) -> tuple[int, int]:
    statements = nodes = 0
    for child in ast.walk(node):
        nodes += 1
        if isinstance(child, ast.stmt):
            statements += 1
    return statements, nodes


def find(trees: dict[str, ast.Module]) -> list[Finding]:
    groups: dict[str, list[_Candidate]] = defaultdict(list)
    for file, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.stmt) or isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            statements, nodes = _sizes(node)
            if statements < MIN_STATEMENTS and nodes < MIN_NODES:
                continue
            digest = hashlib.sha1(_normalized(node).encode()).hexdigest()
            start = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
            groups[digest].append(_Candidate(file, start, end_line(node), getattr(node, "name", type(node).__name__)))

    kept: list[list[_Candidate]] = []
    for members in groups.values():
        members = sorted(members, key=lambda c: (c.file, c.start, -c.end))
        distinct: list[_Candidate] = []
        for m in members:  # drop members nested in another member of the same group
            if not any(d.file == m.file and d.start <= m.start and m.end <= d.end for d in distinct):
                distinct.append(m)
        if len(distinct) >= 2:
            kept.append(distinct)

    def inside(a: _Candidate, b: _Candidate) -> bool:
        return a.file == b.file and b.start <= a.start and a.end <= b.end and (a.start, a.end) != (b.start, b.end)

    # Keep maximal groups only: a group whose members all sit inside members of another group is a sub-clone.
    maximal = [
        g for g in kept if not any(other is not g and all(any(inside(m, o) for o in other) for m in g) for other in kept)
    ]
    findings: list[Finding] = []
    for group in maximal:
        first = group[0]
        spots = [{"file": c.file, "start_line": c.start, "end_line": c.end, "name": c.name} for c in group]
        findings.append(
            make_finding(
                "duplicate_block", "info", "likely", first.file, first.start, first.end,
                f"Duplicate of {len(group) - 1} other block(s) (structure identical, names differ)",
                {"locations": spots, "lines_each": first.end - first.start + 1},
            )
        )  # fmt: skip
    return findings
