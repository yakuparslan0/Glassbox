"""Cyclomatic complexity and loop depth per function."""

from __future__ import annotations

import ast

from ..schemas.analysis import FunctionComplexity
from .common import end_line

_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
_LOOPS = (ast.For, ast.AsyncFor, ast.While)
_BRANCHES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.match_case)


def _own_nodes(func: ast.AST):
    """Nodes of a function body without descending into nested functions / classes."""
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (*_FUNC, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _cyclomatic(func: ast.AST) -> int:
    total = 1
    for node in _own_nodes(func):
        if isinstance(node, _BRANCHES):
            total += 1
        elif isinstance(node, ast.BoolOp):
            total += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            total += 1 + len(node.ifs)
    return total


def _loop_depth(node: ast.AST, depth: int = 0) -> int:
    best = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (*_FUNC, ast.ClassDef, ast.Lambda)):
            continue
        best = max(best, _loop_depth(child, depth + 1 if isinstance(child, _LOOPS) else depth))
    return best


def analyze(trees: dict[str, ast.Module]) -> list[FunctionComplexity]:
    out: list[FunctionComplexity] = []

    def visit(file: str, node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _FUNC):
                qual = f"{prefix}{child.name}"
                out.append(
                    FunctionComplexity(
                        file=file,
                        qualname=qual,
                        start_line=child.lineno,
                        end_line=end_line(child),
                        cyclomatic=_cyclomatic(child),
                        max_loop_depth=_loop_depth(child),
                    )
                )
                visit(file, child, qual + ".")
            elif isinstance(child, ast.ClassDef):
                visit(file, child, f"{prefix}{child.name}.")
            else:
                visit(file, child, prefix)

    for file, tree in trees.items():
        visit(file, tree, "")
    return sorted(out, key=lambda f: (f.file, f.start_line))
