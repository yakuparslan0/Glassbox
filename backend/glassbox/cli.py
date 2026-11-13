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
    return parser


async def _trace(args: argparse.Namespace) -> int:
    script = Path(args.script)
    if not script.is_file():
        print(f"error: script not found: {script}", file=sys.stderr)
        return 2
    files = {script.name: script.read_text(encoding="utf-8")}
    for extra in args.include:
        path = Path(extra)
        if not path.is_file():
            print(f"error: included file not found: {path}", file=sys.stderr)
            return 2
        files[path.name] = path.read_text(encoding="utf-8")
    limits: dict[str, int] = {}
    if args.max_steps is not None:
        limits["max_steps"] = args.max_steps
    if args.timeout is not None:
        limits["timeout_s"] = args.timeout
    request = RunRequest(
        files=files, entry=script.name, stdin=args.stdin, seed=args.seed, filter=args.filter,
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
    return 2  # pragma: no cover - argparse enforces a known command


if __name__ == "__main__":
    raise SystemExit(main())
