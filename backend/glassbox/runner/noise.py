"""Smart noise filter: classify every code object once as user / stdlib / third_party / internal."""

from __future__ import annotations

import os
import sys
import sysconfig
from types import CodeType

USER = "user"
STDLIB = "stdlib"
THIRD_PARTY = "third_party"
INTERNAL = "internal"  # the runner itself; never traced, never a boundary

_PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the `glassbox` package


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _with_sep(path: str) -> str:
    return path if path.endswith(os.sep) else path + os.sep


class Classifier:
    def __init__(self, user_dir: str) -> None:
        self.user_dir = _norm(user_dir)
        self._user_prefix = _with_sep(self.user_dir)
        self._runner_prefix = _with_sep(_norm(_PACKAGE_DIR))
        paths = sysconfig.get_paths()
        self._stdlib_prefixes = tuple(
            {_with_sep(_norm(p)) for p in (paths.get("stdlib"), paths.get("platstdlib")) if p}
        )
        self._by_file: dict[str, str] = {}
        self._by_code: dict[CodeType, str] = {}

    def classify_code(self, code: CodeType) -> str:
        kind = self._by_code.get(code)
        if kind is None:
            kind = self.classify_file(code.co_filename)
            self._by_code[code] = kind
        return kind

    def classify_file(self, filename: str) -> str:
        kind = self._by_file.get(filename)
        if kind is None:
            kind = self._classify_uncached(filename)
            self._by_file[filename] = kind
        return kind

    def _classify_uncached(self, filename: str) -> str:
        if filename.startswith("<"):
            # <frozen importlib._bootstrap>, <string> (exec'd or generated code), <stdin> ...
            return STDLIB
        norm = _norm(filename)
        if norm.startswith(self._user_prefix):
            return USER
        if norm.startswith(self._runner_prefix):
            return INTERNAL
        parts = norm.split(os.sep)
        if "site-packages" in parts or "dist-packages" in parts:
            return THIRD_PARTY
        if norm.startswith(self._stdlib_prefixes):
            return STDLIB
        return THIRD_PARTY

    def is_user_file(self, filename: str) -> bool:
        return self.classify_file(filename) == USER

    def relpath(self, filename: str) -> str:
        """Path of a user file relative to the run's working directory, with forward slashes."""
        try:
            rel = os.path.relpath(_norm(filename), self.user_dir)
        except ValueError:
            return filename
        return rel.replace(os.sep, "/")


def lib_of_module(name: str | None) -> str:
    """Library class of a module name (used for C callables, where there is no code object)."""
    if not name:
        return STDLIB
    top = name.split(".")[0]
    if top in sys.stdlib_module_names or top in sys.builtin_module_names:
        return STDLIB
    return THIRD_PARTY
