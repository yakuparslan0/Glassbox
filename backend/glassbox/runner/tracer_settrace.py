"""Fallback tracer: sys.settrace (+ sys.setprofile for C-level boundary calls).

Frames outside user code get no local trace function (``None``), so their lines cost nothing; the one
exception is a library function called directly from user code, which gets a tiny local tracer so its
return can close the boundary pair.
"""

from __future__ import annotations

import opcode
import sys
import threading

from .noise import INTERNAL, USER
from .tracer_base import BUILTIN_FUNCTION_TYPE, NO_BOUNDARY_FLAGS, TracerBackend, c_callable_info

_NORMAL_EXIT = frozenset(
    opcode.opmap[name] for name in ("RETURN_VALUE", "RETURN_CONST", "YIELD_VALUE") if name in opcode.opmap
)


class SettraceTracer(TracerBackend):
    name = "settrace"

    def start(self) -> None:
        rec = self.rec
        classify = self.classifier.classify_code
        main = self.main_ident
        get_ident = threading.get_ident
        raised_in_boundary: set[int] = set()
        code_bytes: dict = {}

        def left_by_exception(frame):
            """A 'return' event does not say whether the frame returned or is unwinding: ask the opcode."""
            code = frame.f_code
            raw = code_bytes.get(code)
            if raw is None:
                raw = code_bytes[code] = code.co_code
            return raw[frame.f_lasti] not in _NORMAL_EXIT

        def local_user(frame, event, arg):
            if event == "line":
                rec.on_line(frame, frame.f_lineno)
            elif event == "return":
                rec.on_return(frame, arg, left_by_exception(frame))
            elif event == "exception":
                rec.exc_raised(frame, arg[1])
            return local_user

        def local_boundary(frame, event, arg):
            if event == "return":
                raised = id(frame) in raised_in_boundary
                raised_in_boundary.discard(id(frame))
                rec.boundary_py_end(frame, None if raised else arg, raised)
            elif event == "exception":
                raised_in_boundary.add(id(frame))
            elif event == "line":
                raised_in_boundary.discard(id(frame))
            return local_boundary

        def global_trace(frame, event, arg):
            if get_ident() != main:
                return None
            code = frame.f_code
            kind = classify(code)
            if kind == USER:
                rec.on_call(frame, code)
                return local_user
            if kind == INTERNAL or not rec.stack:
                return None
            top = rec.stack[-1]
            if top.kind == "user" and not code.co_flags & NO_BOUNDARY_FLAGS and frame.f_back is top.frame:
                rec.boundary_py_start(frame, code, kind)
                return local_boundary
            return None

        def profile(frame, event, arg):
            if event == "c_call":
                if type(arg) is BUILTIN_FUNCTION_TYPE and rec.stack:
                    top = rec.stack[-1]
                    if top.kind == "user" and top.frame is frame:
                        info = c_callable_info(arg)
                        if info is not None:
                            rec.boundary_c_call(frame, arg, info)
            elif event == "c_return":
                if rec.stack and rec.stack[-1].kind == "boundary":
                    rec.boundary_c_end(arg, False)
            elif event == "c_exception" and rec.stack and rec.stack[-1].kind == "boundary":
                rec.boundary_c_end(arg, True)

        sys.setprofile(profile)
        sys.settrace(global_trace)

    def stop(self) -> None:
        sys.settrace(None)
        sys.setprofile(None)
