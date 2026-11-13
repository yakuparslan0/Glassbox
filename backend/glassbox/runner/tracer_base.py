"""Common interface of the tracer backends and the helpers they share."""

from __future__ import annotations

import threading
import types
from typing import Any

from .noise import Classifier, lib_of_module
from .recorder import Recorder

CO_GENERATOR = 0x20
CO_COROUTINE = 0x80
CO_ASYNC_GENERATOR = 0x200
# Non-user generators/coroutines are never boundaries: they run in slices, not as one call.
NO_BOUNDARY_FLAGS = CO_GENERATOR | CO_COROUTINE | CO_ASYNC_GENERATOR

BUILTIN_FUNCTION_TYPE = types.BuiltinFunctionType


def c_callable_info(callable_: Any) -> tuple[str, str, str] | None:
    """(module, name, lib) if a C callable counts as a library boundary, else None.

    Callables of the ``builtins`` module and methods of builtin types (``len``, ``print``,
    ``list.append`` ...) are never boundaries: they would drown the trace in noise.
    """
    module = getattr(callable_, "__module__", None)
    if not module or module == "builtins":
        return None
    if module in ("posix", "nt"):
        module = "os"
    name = getattr(callable_, "__qualname__", None) or getattr(callable_, "__name__", "?")
    return module, name, lib_of_module(module)


class TracerBackend:
    """Translates native tracing callbacks into Recorder calls.

    Subclasses implement ``start`` and ``stop``. Only the thread that calls ``start`` is traced.
    """

    name = ""

    def __init__(self, recorder: Recorder, classifier: Classifier) -> None:
        self.rec = recorder
        self.classifier = classifier
        self.main_ident = threading.get_ident()

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError
