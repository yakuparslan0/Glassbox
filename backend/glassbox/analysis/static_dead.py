"""Static dead-code detection: unused imports / variables, never-referenced functions, unreachable code."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from ..schemas.analysis import Finding
from .common import const_truth, def_start, end_line, make_finding

_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
_DYNAMIC_CALLS = frozenset({"globals", "locals", "vars", "eval", "exec", "__import__"})
_ATTR_CALLS = frozenset({"getattr", "hasattr", "setattr", "delattr"})
_PURE_NODES = (ast.Constant, ast.Name, ast.Attribute, ast.BinOp, ast.UnaryOp, ast.Tuple, ast.List, ast.Dict, ast.Set, ast.Compare)


@dataclass
class ProjectIndex:
    """Name usage across ALL submitted files (a name used anywhere counts as used)."""

    loads: dict[str, list[tuple[str, int]]] = field(default_factory=dict)  # name -> [(file, line)]
    strings: set[str] = field(default_factory=set)
    exported: dict[str, set[str]] = field(default_factory=dict)  # file -> names in __all__
    dynamic: bool = False

    def add_load(self, name: str, file: str, line: int) -> None:
        self.loads.setdefault(name, []).append((file, line))


def build_index(trees: dict[str, ast.Module]) -> ProjectIndex:
    idx = ProjectIndex()
    for file, tree in trees.items():
        idx.exported[file] = _all_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                idx.add_load(node.id, file, node.lineno)
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                idx.add_load(node.attr, file, node.lineno)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    idx.add_load(alias.name, file, node.lineno)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 200:
                idx.strings.add(node.value)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                name = node.func.id
                constant_attr = (
                    len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)
                )
                if name in _DYNAMIC_CALLS or (name in _ATTR_CALLS and not constant_attr):
                    idx.dynamic = True
    return idx


def _all_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets) and isinstance(
                node.value, (ast.List, ast.Tuple, ast.Set)
            ):
                names.update(e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str))
    return names


def _is_pure(node: ast.expr | None) -> bool:
    return node is None or all(isinstance(n, (*_PURE_NODES, ast.expr_context, ast.operator, ast.unaryop, ast.cmpop)) for n in ast.walk(node))


def _used_outside(idx: ProjectIndex, name: str, file: str, start: int, end: int) -> bool:
    """Is ``name`` loaded anywhere except inside its own definition (plain recursion does not count)?"""
    return any(f != file or not (start <= line <= end) for f, line in idx.loads.get(name, ()))


# ---------------------------------------------------------------------------------------------- imports
def _unused_imports(file: str, tree: ast.Module, idx: ProjectIndex) -> list[Finding]:
    file_loads = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    reexported = {name for name, sites in idx.loads.items() if any(f != file for f, _ in sites)}
    out: list[Finding] = []
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ImportFrom) and (node.module == "__future__" or any(a.name == "*" for a in node.names)):
            continue
        for alias in node.names:
            bound = alias.asname or alias.name.split(".")[0]
            if bound in file_loads or bound in idx.exported[file] or (bound in reexported and file.endswith("__init__.py")):
                continue
            out.append(
                make_finding(
                    "unused_import", "info", "confirmed", file, node.lineno, end_line(node),
                    f"Import '{bound}' is never used",
                    {"name": bound, "statement_names": [a.asname or a.name for a in node.names]},
                    autofixable=True,
                )
            )  # fmt: skip
    return out


# ---------------------------------------------------------------------------------------------- variables
def _function_unused(file: str, func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[Finding]:
    params = {a.arg for a in [*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs]}
    params.update(a.arg for a in (func.args.vararg, func.args.kwarg) if a)
    declared: set[str] = set()
    loaded: set[str] = set()
    dynamic = False
    for node in ast.walk(func):
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            declared.update(node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            loaded.add(node.id)
            if node.id in _DYNAMIC_CALLS:
                dynamic = True
    if dynamic:
        return []
    out: list[Finding] = []
    seen: set[str] = set()
    for stmt in ast.walk(func):
        if isinstance(stmt, ast.Assign):
            pairs = [(t, stmt.value) for t in stmt.targets if isinstance(t, ast.Name)]
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            pairs = [(stmt.target, stmt.value)]
        else:
            continue
        for target, value in pairs:
            name = target.id
            if name in seen or name in params or name in declared or name in loaded or name.startswith("_"):
                continue
            seen.add(name)
            out.append(
                make_finding(
                    "unused_variable", "info", "confirmed", file, stmt.lineno, end_line(stmt),
                    f"Local variable '{name}' is assigned but never used",
                    {"name": name, "function": func.name, "side_effect_free": _is_pure(value)},
                    autofixable=_is_pure(value),
                )
            )  # fmt: skip
    return out


def _module_unused(file: str, tree: ast.Module, idx: ProjectIndex) -> list[Finding]:
    out: list[Finding] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            pairs = [(t, stmt.value) for t in stmt.targets if isinstance(t, ast.Name)]
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            pairs = [(stmt.target, stmt.value)]
        else:
            continue
        for target, value in pairs:
            name = target.id
            if (name.startswith("__") and name.endswith("__")) or name in idx.exported[file] or idx.loads.get(name):
                continue
            if name in idx.strings:
                continue  # possibly reached through globals()/getattr by name
            out.append(
                make_finding(
                    "unused_variable", "info", "suspect" if idx.dynamic else "likely", file, stmt.lineno, end_line(stmt),
                    f"Module variable '{name}' is never used in the submitted files",
                    {"name": name, "scope": "module", "side_effect_free": _is_pure(value)},
                    autofixable=_is_pure(value),
                )
            )  # fmt: skip
    return out


# ---------------------------------------------------------------------------------------------- functions
def _uncalled(file: str, tree: ast.Module, idx: ProjectIndex) -> list[Finding]:
    out: list[Finding] = []

    def visit(body: list[ast.stmt], owner: ast.ClassDef | None, nested: bool) -> None:
        for node in body:
            if isinstance(node, (*_FUNC, ast.ClassDef)):
                check(node, owner, nested)
                if isinstance(node, ast.ClassDef):
                    visit(node.body, node, nested)
                else:
                    visit(node.body, None, True)
            else:
                for attr in ("body", "orelse", "finalbody"):
                    inner = getattr(node, attr, None)
                    if isinstance(inner, list) and inner and isinstance(inner[0], ast.stmt):
                        visit(inner, owner, nested)

    def check(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, owner: ast.ClassDef | None, nested: bool) -> None:
        name = node.name
        if (name.startswith("__") and name.endswith("__")) or name in idx.exported[file] or name in idx.strings:
            return
        start, end = def_start(node), end_line(node)
        if _used_outside(idx, name, file, start, end):
            return
        kind = "class" if isinstance(node, ast.ClassDef) else ("method" if owner else "function")
        confidence = "likely"
        reason = None
        if node.decorator_list:
            confidence, reason = "suspect", "decorated: a decorator may register or wrap it"
        elif owner is not None and owner.bases:
            confidence, reason = "suspect", "method of a subclass: it may override a base-class hook"
        elif idx.dynamic:
            confidence, reason = "suspect", "the project uses dynamic name lookup (getattr/globals/eval...)"
        out.append(
            make_finding(
                "uncalled_function", "warn", confidence, file, start, end,
                f"{kind.capitalize()} '{name}' is never referenced",
                {"name": name, "kind": kind, "qualname": f"{owner.name}.{name}" if owner else name,
                 **({"reason": reason} if reason else {})},
                autofixable=(owner is None and not nested and not node.decorator_list and not isinstance(node, ast.ClassDef)),
            )
        )  # fmt: skip

    visit(tree.body, None, False)
    return out


# ---------------------------------------------------------------------------------------------- unreachable
def _has_break(body: list[ast.stmt]) -> bool:
    for stmt in body:
        if isinstance(stmt, ast.Break):
            return True
        if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
            if _has_break(stmt.orelse):
                return True
            continue
        if isinstance(stmt, (*_FUNC, ast.ClassDef)):
            continue
        for attr in ("body", "orelse", "finalbody"):
            inner = getattr(stmt, attr, None)
            if isinstance(inner, list) and _has_break([s for s in inner if isinstance(s, ast.stmt)]):
                return True
        for handler in getattr(stmt, "handlers", []):
            if _has_break(handler.body):
                return True
        for case in getattr(stmt, "cases", []):
            if _has_break(case.body):
                return True
    return False


def _block_unreachable(file: str, stmts: list[ast.stmt], reason: str) -> Finding | None:
    if not stmts or all(isinstance(s, ast.Pass) for s in stmts):
        return None  # a bare `pass` is the minimal valid body (and what autofix leaves behind)
    start, end = stmts[0].lineno, end_line(stmts[-1])
    return make_finding(
        "unreachable_code", "warn", "confirmed", file, start, end, f"Unreachable code ({reason})",
        {"reason": reason}, autofixable=True,
    )  # fmt: skip


def _unreachable(file: str, tree: ast.Module) -> list[Finding]:
    out: list[Finding] = []

    def add(finding: Finding | None) -> None:
        if finding:
            out.append(finding)

    def scan(stmts: list[ast.stmt]) -> None:
        for i, stmt in enumerate(stmts):
            rest = stmts[i + 1 :]
            if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)) and rest:
                add(_block_unreachable(file, rest, f"after '{type(stmt).__name__.lower()}'"))
                break
            if isinstance(stmt, ast.While) and (const_truth(stmt.test) is True) and not _has_break(stmt.body) and rest:
                add(_block_unreachable(file, rest, "after an endless loop without break"))
                scan_children(stmt)
                break
            if isinstance(stmt, ast.If):
                truth = const_truth(stmt.test)
                if truth is False:
                    add(_block_unreachable(file, stmt.body, "condition is always false"))
                elif truth is True and stmt.orelse:
                    add(_block_unreachable(file, stmt.orelse, "condition is always true"))
            if isinstance(stmt, ast.While) and const_truth(stmt.test) is False:
                add(_block_unreachable(file, stmt.body, "loop condition is always false"))
            scan_children(stmt)

    def scan_children(stmt: ast.stmt) -> None:
        for attr in ("body", "orelse", "finalbody"):
            inner = getattr(stmt, attr, None)
            if isinstance(inner, list) and inner and isinstance(inner[0], ast.stmt):
                scan(inner)
        for handler in getattr(stmt, "handlers", []):
            scan(handler.body)
        for case in getattr(stmt, "cases", []):
            scan(case.body)

    scan(tree.body)
    # `scan` stops at the first dead block of a list, nested findings inside dead blocks are not reported twice.
    return out


# ---------------------------------------------------------------------------------------------- entry point
def analyze(trees: dict[str, ast.Module]) -> list[Finding]:
    idx = build_index(trees)
    findings: list[Finding] = []
    for file, tree in trees.items():
        findings += _unused_imports(file, tree, idx)
        findings += _module_unused(file, tree, idx)
        findings += _uncalled(file, tree, idx)
        findings += _unreachable(file, tree)
        for node in ast.walk(tree):
            if isinstance(node, _FUNC):
                findings += _function_unused(file, node)
    return _drop_nested_unreachable(findings)


def _drop_nested_unreachable(findings: list[Finding]) -> list[Finding]:
    """An unreachable block inside another unreachable block is not worth a second finding."""
    dead = [f for f in findings if f.category == "unreachable_code"]

    def nested(f: Finding) -> bool:
        return any(
            o is not f and o.file == f.file and o.start_line <= f.start_line and f.end_line <= o.end_line
            and (o.start_line, o.end_line) != (f.start_line, f.end_line)
            for o in dead
        )

    return [f for f in findings if f.category != "unreachable_code" or not nested(f)]
