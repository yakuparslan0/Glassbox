"""Helpers shared by the analysis modules."""

from __future__ import annotations

import ast
from typing import Any

from ..schemas.analysis import Category, Finding


class SourceError(ValueError):
    """A submitted file does not parse; the message is user-facing."""


def parse_files(files: dict[str, str]) -> dict[str, ast.Module]:
    trees: dict[str, ast.Module] = {}
    for path, text in files.items():
        if not path.endswith(".py"):
            continue
        try:
            trees[path] = ast.parse(text, filename=path)
        except SyntaxError as exc:
            raise SourceError(f"{path}: syntax error on line {exc.lineno}: {exc.msg}") from exc
    return trees


def make_finding(
    category: Category,
    severity: str,
    confidence: str,
    file: str,
    start: int,
    end: int,
    title: str,
    evidence: dict[str, Any] | None = None,
    autofixable: bool = False,
) -> Finding:
    return Finding(
        id=f"{category}:{file}:{start}",
        category=category,
        severity=severity,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        file=file,
        start_line=start,
        end_line=max(start, end),
        title=title,
        evidence=evidence or {},
        autofixable=autofixable,
    )


def finalize(findings: list[Finding]) -> list[Finding]:
    """Stable order and unique ids (a second finding with the same id gets a numeric suffix)."""
    findings = sorted(findings, key=lambda f: (f.file, f.start_line, f.category, f.title))
    seen: dict[str, int] = {}
    for f in findings:
        n = seen.get(f.id, 0)
        seen[f.id] = n + 1
        if n:
            f.id = f"{f.id}#{n + 1}"
    return findings


def end_line(node: ast.AST) -> int:
    return getattr(node, "end_lineno", None) or getattr(node, "lineno", 1)


def first_body_line(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> int:
    """Line of the first real statement of a body (a leading docstring is not code)."""
    body = node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
        and len(body) > 1
    ):
        return body[1].lineno
    return body[0].lineno


def def_start(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> int:
    """First line of a definition including its decorators."""
    return min([node.lineno, *(d.lineno for d in node.decorator_list)])


def const_truth(test: ast.expr) -> bool | None:
    """Truth value of a compile-time constant condition (``False``, ``0``, ``not 1``...), else None."""
    if isinstance(test, ast.Constant):
        return bool(test.value)
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = const_truth(test.operand)
        return None if inner is None else not inner
    return None


def overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start <= b_end and b_start <= a_end
