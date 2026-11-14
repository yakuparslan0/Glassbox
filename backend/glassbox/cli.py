"""GlassBox command line interface."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .sandbox.manager import RunRequest, SandboxManager


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="glassbox", description="GlassBox runtime execution visualizer")
    sub = parser.add_subparsers(dest="command", required=True)

    trace = sub.add_parser("trace", help="run a script under the tracer and write its events as NDJSON")
    trace.add_argument("script", help="entry script to run")
    trace.add_argument("--out", default="trace.ndjson", help="output file (default: trace.ndjson)")
    trace.add_argument("--include", action="append", default=[], metavar="FILE",
                       help="extra project file next to the script (repeatable), e.g. a module it imports")  # fmt: skip
    trace.add_argument("--stdin", default="", help="text fed to the program's input()")
    trace.add_argument("--seed", type=int, default=0, help="seed for random.seed() (default: 0)")
    trace.add_argument("--filter", choices=["user_only", "boundaries", "boundaries_verbose"], default="boundaries")
    trace.add_argument("--tracer", choices=["monitoring", "settrace"], default="monitoring")
    trace.add_argument("--max-steps", type=int, default=None)
    trace.add_argument("--timeout", type=int, default=None, help="wall-clock timeout in seconds")
    trace.add_argument("--allow-network", action="store_true", help="lift the sandbox network block")

    report = sub.add_parser("report", help="run a script and print its Mark & Sweep report")
    report.add_argument("script", help="entry script to run")
    report.add_argument("--include", action="append", default=[], metavar="FILE", help="extra project file (repeatable)")
    report.add_argument("--stdin", default="")
    report.add_argument("--seed", type=int, default=0)
    report.add_argument("--json", action="store_true", help="print the report as JSON instead of text")

    serve = sub.add_parser("serve", help="start the API server (127.0.0.1 unless GLASSBOX_ALLOW_REMOTE=true with docker)")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    return parser


def _load_files(script: str, include: list[str]) -> tuple[dict[str, str], str] | None:
    path = Path(script)
    if not path.is_file():
        print(f"error: script not found: {path}", file=sys.stderr)
        return None
    files = {path.name: path.read_text(encoding="utf-8")}
    for extra in include:
        extra_path = Path(extra)
        if not extra_path.is_file():
            print(f"error: included file not found: {extra_path}", file=sys.stderr)
            return None
        files[extra_path.name] = extra_path.read_text(encoding="utf-8")
    return files, path.name


async def _report(args: argparse.Namespace) -> int:
    from .analysis import marksweep
    from .analysis.common import SourceError

    loaded = _load_files(args.script, args.include)
    if loaded is None:
        return 2
    files, entry = loaded
    request = RunRequest(files=files, entry=entry, stdin=args.stdin, seed=args.seed)
    events = [event async for event in SandboxManager().run(request)]
    try:
        report = marksweep.build(files, entry, events)
    except SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(report.model_dump_json(indent=2))
        return 0
    s = report.summary
    print(f"Mark & Sweep: {entry} | run status={report.run_status}, steps={report.steps} (exact; traced run)")
    print(f"  confirmed dead: {s.confirmed_dead} | cold: {s.cold} | suspect: {s.suspect} | reclaimable lines: {s.reclaimable_lines}")
    for f in report.findings:
        span = f"{f.start_line}" if f.start_line == f.end_line else f"{f.start_line}-{f.end_line}"
        print(f"  [{f.confidence:9}] {f.file}:{span:<7} {f.category:<20} {f.title}")
    return 0


def _serve(args: argparse.Namespace) -> int:
    from .config import Settings, StartupError, bind_host, ensure_safe_startup

    settings = Settings()
    try:
        ensure_safe_startup(settings)
    except StartupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    import uvicorn

    from .api.app import create_app

    host = args.host or bind_host(settings)
    if host not in ("127.0.0.1", "localhost", "::1") and not settings.allow_remote:
        print("error: binding to a non-loopback address requires GLASSBOX_ALLOW_REMOTE=true and SANDBOX_MODE=docker", file=sys.stderr)
        return 2
    uvicorn.run(create_app(settings), host=host, port=args.port or settings.port)
    return 0


async def _trace(args: argparse.Namespace) -> int:
    loaded = _load_files(args.script, args.include)
    if loaded is None:
        return 2
    files, entry = loaded
    limits: dict[str, int] = {}
    if args.max_steps is not None:
        limits["max_steps"] = args.max_steps
    if args.timeout is not None:
        limits["timeout_s"] = args.timeout
    request = RunRequest(
        files=files, entry=entry, stdin=args.stdin, seed=args.seed, filter=args.filter,
        limits=limits, allow_network=args.allow_network, tracer=args.tracer,
    )  # fmt: skip
    finished: dict | None = None
    count = 0
    with open(args.out, "w", encoding="utf-8", newline="\n") as out:
        async for event in SandboxManager().run(request):
            out.write(json.dumps(event, separators=(",", ":")) + "\n")
            count += 1
            if event["type"] == "run_finished":
                finished = event
    if finished is None:
        print("error: the run ended without a run_finished event", file=sys.stderr)
        return 1
    print(
        f"{count} events -> {args.out} | status={finished['status']} steps={finished['steps']} "
        f"wall={finished['wall_ms']} ms (traced run: time is inflated by tracing, steps are exact)",
        file=sys.stderr,
    )
    return 0 if finished["status"] == "ok" else 1


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "trace":
        return asyncio.run(_trace(args))
    if args.command == "report":
        return asyncio.run(_report(args))
    if args.command == "serve":
        return _serve(args)
    return 2  # pragma: no cover - argparse enforces a known command


if __name__ == "__main__":
    raise SystemExit(main())
