"""Default tracer: sys.monitoring (PEP 669).

Locations outside user code return ``sys.monitoring.DISABLE`` (LINE and CALL only) so they cost nothing
afterwards. The API forbids DISABLE for RAISE / EXCEPTION_HANDLED / PY_UNWIND / C_RETURN / C_RAISE (verified:
"Cannot disable ... events"), and PY_START / PY_RETURN are deliberately not disabled in non-user code: they
open and close Python-level library boundaries (a disabled location would only report the first call).
"""

from __future__ import annotations

import bisect
import sys
import threading

from .noise import INTERNAL, USER
from .tracer_base import BUILTIN_FUNCTION_TYPE, NO_BOUNDARY_FLAGS, TracerBackend, c_callable_info

mon = sys.monitoring
E = mon.events
TOOL = mon.DEBUGGER_ID
DISABLE = mon.DISABLE


class MonitoringTracer(TracerBackend):
    name = "monitoring"

    def start(self) -> None:
        rec = self.rec
        classify = self.classifier.classify_code
        main = self.main_ident
        get_ident = threading.get_ident
        getframe = sys._getframe

        def py_start(code, offset):
            if get_ident() != main:
                return None
            kind = classify(code)
            if kind == USER:
                rec.on_call(getframe(1), code)
                return None
            if kind == INTERNAL or not rec.stack:
                return None
            top = rec.stack[-1]
            if top.kind != "user" or code.co_flags & NO_BOUNDARY_FLAGS:
                return None
            frame = getframe(1)
            if frame.f_back is top.frame:
                rec.boundary_py_start(frame, code, kind)
            return None

        def py_resume(code, offset):
            if get_ident() == main and classify(code) == USER:
                rec.on_call(getframe(1), code)

        def py_throw(code, offset, exc):
            # A generator is resumed through throw()/close(): same as a resume.
            if get_ident() == main and classify(code) == USER:
                rec.on_call(getframe(1), code)

        def py_return(code, offset, retval):
            if get_ident() != main:
                return
            kind = classify(code)
            if kind == USER:
                rec.on_return(getframe(1), retval)
            elif kind != INTERNAL and rec.stack:
                top = rec.stack[-1]
                if top.kind == "boundary" and not top.is_c:
                    frame = getframe(1)
                    if top.frame is frame:
                        rec.boundary_py_end(frame, retval, False)

        def py_yield(code, offset, retval):
            # A user generator suspends: reported as a return (see EVENT_SCHEMA.md).
            if get_ident() == main and classify(code) == USER:
                rec.on_return(getframe(1), retval)

        def py_unwind(code, offset, exc):
            if get_ident() != main:
                return
            kind = classify(code)
            if kind == USER:
                rec.on_return(getframe(1), None, True, exc)
            elif kind != INTERNAL and rec.stack:
                top = rec.stack[-1]
                if top.kind == "boundary" and not top.is_c:
                    frame = getframe(1)
                    if top.frame is frame:
                        rec.boundary_py_end(frame, None, True)

        line_tables: dict = {}

        def line_of(code, offset):
            table = line_tables.get(code)
            if table is None:
                starts, lines = [], []
                for start, _end, lineno in code.co_lines():
                    if lineno is not None:
                        starts.append(start)
                        lines.append(lineno)
                table = line_tables[code] = (starts, lines)
            starts, lines = table
            return lines[max(bisect.bisect_right(starts, offset) - 1, 0)]

        def jump(code, offset, destination):
            # sys.settrace also reports a backward jump that stays on the same line (one-line loops,
            # comprehensions); LINE does not. Re-create that so both backends agree.
            if get_ident() != main:
                return None
            if classify(code) != USER or destination > offset:
                return DISABLE  # forward jumps never go backward at the same location
            dest_line = line_of(code, destination)
            if dest_line == line_of(code, offset):
                rec.on_line(getframe(1), dest_line)
            return None

        def line(code, lineno):
            if get_ident() != main:
                return None
            if classify(code) == USER:
                rec.on_line(getframe(1), lineno)
                return None
            return DISABLE

        def raise_(code, offset, exc):
            if get_ident() != main:
                return None
            if classify(code) == USER:
                rec.exc_raised(getframe(1), exc)
            return None

        def handled(code, offset, exc):
            if get_ident() != main:
                return None
            if classify(code) == USER:
                rec.exc_handled(getframe(1))
            return None

        def call(code, offset, callable_, arg0):
            if get_ident() != main:
                return None
            if classify(code) != USER:
                return DISABLE
            if type(callable_) is BUILTIN_FUNCTION_TYPE and rec.stack:
                top = rec.stack[-1]
                if top.kind == "user":
                    frame = getframe(1)
                    if top.frame is frame:
                        info = c_callable_info(callable_)
                        if info is not None:
                            rec.boundary_c_call(frame, callable_, info)
            return None

        def c_return(code, offset, callable_, arg0):
            if get_ident() != main:
                return None
            if rec.stack and rec.stack[-1].kind == "boundary" and classify(code) == USER:
                rec.boundary_c_end(callable_, False)
            return None

        def c_raise(code, offset, callable_, arg0):
            if get_ident() != main:
                return None
            if rec.stack and rec.stack[-1].kind == "boundary" and classify(code) == USER:
                rec.boundary_c_end(callable_, True)
            return None

        mon.use_tool_id(TOOL, "glassbox")
        callbacks = {
            E.PY_START: py_start,
            E.PY_RESUME: py_resume,
            E.PY_THROW: py_throw,
            E.PY_RETURN: py_return,
            E.PY_YIELD: py_yield,
            E.PY_UNWIND: py_unwind,
            E.LINE: line,
            E.JUMP: jump,
            E.RAISE: raise_,
            E.EXCEPTION_HANDLED: handled,
            E.CALL: call,
            E.C_RETURN: c_return,
            E.C_RAISE: c_raise,
        }
        mask = 0
        for event, callback in callbacks.items():
            mon.register_callback(TOOL, event, callback)
            mask |= event
        self._events = list(callbacks)
        mon.set_events(TOOL, mask)

    def stop(self) -> None:
        if mon.get_tool(TOOL) is None:
            return
        mon.set_events(TOOL, 0)
        for event in self._events:
            mon.register_callback(TOOL, event, None)
        mon.free_tool_id(TOOL)

