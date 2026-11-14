"""Runner entry point: ``python -s -P -X utf8 -m glassbox.runner <job.json>``.

Reads the job from a file OUTSIDE the working directory, sets up the protocol channel and the sandbox
guards, runs the entry module under the selected tracer and always ends with a ``run_finished`` event.
"""

from __future__ import annotations

import atexit
import builtins
import contextlib
import io
import json
import os
import random
import sys
import traceback
import types
from typing import Any

from . import guards, protocol
from .limits import apply_rlimits, effective_limits
from .noise import Classifier, lib_of_module
from .protocol import FdCapture, OutStream, ProtocolWriter, open_channel
from .recorder import Recorder
from .serializer import Serializer
from .whatif import OverrideError, load_overrides


def _make_tracer(name: str, recorder: Recorder, classifier: Classifier) -> Any:
    if name in ("profile_time", "profile_memory", "profile_timing"):
        from .profiler import ProfileHarness

        return ProfileHarness(name.removeprefix("profile_"), recorder, classifier)
    if name == "settrace":
        from .tracer_settrace import SettraceTracer

        return SettraceTracer(recorder, classifier)
    from .tracer_monitoring import MonitoringTracer

    return MonitoringTracer(recorder, classifier)


def _user_traceback(exc: BaseException, user_dir: str) -> str:
    """Traceback text restricted to the user's own frames (the runner's frames are noise)."""
    te = traceback.TracebackException.from_exception(exc)
    prefix = os.path.normcase(os.path.realpath(user_dir)) + os.sep
    frames = [f for f in te.stack if os.path.normcase(os.path.realpath(f.filename)).startswith(prefix)]
    text = ""
    if frames:
        text = "Traceback (most recent call last):\n" + "".join(traceback.StackSummary.from_list(frames).format())
    text += "".join(te.format_exception_only())
    return text.replace(user_dir + os.sep, "")


def _run(job: dict[str, Any]) -> int:
    work_dir = os.path.realpath(job["work_dir"])
    os.chdir(work_dir)
    proto_fd, out_path, err_path = open_channel(job["cap_dir"])
    writer = ProtocolWriter(proto_fd)
    writer.start_flusher()

    limits = effective_limits(job.get("limits"))
    rlimit = apply_rlimits(limits)
    classifier = Classifier(work_dir)
    captures = (FdCapture(out_path), FdCapture(err_path))
    rec = Recorder(job, limits, writer, Serializer(), classifier, captures)
    seed = int(job.get("seed", 0))
    profile_kind = job.get("profile")  # None | "time" | "memory": untraced measurement pass
    tracer_name = f"profile_{profile_kind}" if profile_kind else job.get("tracer", "monitoring")
    rec.run_started(sys.version.split()[0], tracer_name, seed, rlimit)

    try:
        rec.overrides = load_overrides(job.get("overrides"))
    except OverrideError as exc:
        rec.finish("blocked", 3, f"rejected What-If override: {exc}")
        return 3

    entry_path = os.path.join(work_dir, job["entry"])
    module = types.ModuleType("__main__")
    module.__dict__.update(__file__=entry_path, __builtins__=builtins)
    globals_ = module.__dict__
    sys.modules["__main__"] = module
    sys.path.insert(0, work_dir)
    rec.entry_globals = globals_
    rec.entry_rel = classifier.relpath(entry_path)

    sys.stdout = OutStream("stdout", rec.on_output)
    sys.stderr = OutStream("stderr", rec.on_output)
    sys.stdin = io.StringIO(job.get("stdin", ""))

    real_import = builtins.__import__

    def traced_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and globals is not None:
            importer = globals.get("__file__")
            if importer and classifier.is_user_file(importer):
                top = name.split(".")[0]
                if os.path.exists(os.path.join(work_dir, top + ".py")) or os.path.isdir(os.path.join(work_dir, top)):
                    lib = "user"
                else:
                    lib = lib_of_module(top)
                rec.on_import(name, lib)
        return real_import(name, globals, locals, fromlist, level)

    if not profile_kind:  # measurement passes must not pay for the runner's own import events
        builtins.__import__ = traced_import
    guards.install(work_dir, bool(job.get("allow_network", False)), rec.blocked)
    random.seed(seed)

    status, exit_code, detail = "ok", 0, None
    tracer = _make_tracer(tracer_name, rec, classifier)
    try:
        with open(entry_path, "rb") as f:
            source = f.read()
        code = compile(source, entry_path, "exec", dont_inherit=True)
        rec.entry_code = code
        tracer.start()
        try:
            exec(code, globals_)
        finally:
            tracer.stop()
    except SystemExit as exc:
        tracer.stop()
        arg = exc.code
        if arg is None or isinstance(arg, int):
            exit_code = arg or 0
        else:
            rec.on_output("stderr", f"{arg}\n")
            exit_code = 1
    except BaseException as exc:  # the user's uncaught exception (or a failed compile)
        tracer.stop()
        rec.on_output("stderr", _user_traceback(exc, work_dir))
        blocked = isinstance(exc, PermissionError) and bool(rec.blocked)
        status = "blocked" if blocked else "exception"
        exit_code = 3 if blocked else 1
        detail = f"{type(exc).__name__}: {exc}"[:300]
    else:
        tracer.stop()

    with contextlib.suppress(BaseException):
        atexit._run_exitfuncs()  # user atexit handlers run untraced
    rec.finish(status, exit_code, detail)
    writer.stop_flusher()
    writer.flush()
    return exit_code


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: python -m glassbox.runner <job.json>\n")
        return 64
    with open(argv[1], encoding="utf-8") as f:
        job = json.load(f)
    try:
        return _run(job)
    except BaseException:
        # Last resort: the runner itself failed. The parent sees the missing run_finished and reports
        # this text (fd 2 may already be the capture file, so use the saved copy of the real stderr).
        detail = ("glassbox runner internal error:\n" + traceback.format_exc()[-1500:]).encode("utf-8", "replace")
        with contextlib.suppress(OSError):
            os.write(protocol.real_stderr_fd if protocol.real_stderr_fd >= 0 else 2, detail)
        return 70


if __name__ == "__main__":
    code = main(sys.argv)
    with contextlib.suppress(Exception):
        sys.stdout.flush()
    os._exit(code)
