"""Empirical Big-O laboratory: deterministic STEP counts for growing inputs, least-squares fit to 7 growth models."""

from __future__ import annotations

import ast
import math

from ..sandbox.manager import RunRequest, SandboxManager
from ..schemas.analysis import BigOFit, BigOPoint, BigOReport, StaticEstimate
from .common import SourceError, parse_files
from .complexity import analyze as complexity_analyze

MODELS: list[tuple[str, str]] = [
    ("1", "O(1)"), ("log n", "O(log n)"), ("n", "O(n)"), ("n log n", "O(n log n)"),
    ("n^2", "O(n²)"), ("n^3", "O(n³)"), ("2^n", "O(2ⁿ)"),
]  # fmt: skip
ORDER = {m: i for i, (m, _label) in enumerate(MODELS)}
DEFAULT_SIZES = [8, 16, 32, 64, 128, 256]  # n^2 at 512 would need ~330k traced steps (> the 10 s budget)
DEFAULT_SIZES_INT_N = [4, 6, 8, 10, 12, 14, 16, 18]
MIN_POINTS = 4
R2_TIE = 0.001  # within this of the best R² the simpler model wins
MAX_STEPS = 400_000
GENERATORS = {
    "random_ints": "[__gb_random.randint(0, 10 * n) for _ in range(n)]",
    "sorted_ints": "list(range(n))",
    "reversed_ints": "list(range(n, 0, -1))",
    "int_n": "n",
    "string_n": '"".join(chr(97 + i % 26) for i in range(n))',
}
_PLACEHOLDERS = {"$n": "n", "$last": "data[-1]", "$first": "data[0]", "$missing": "-1"}


def _f(model: str, n: int) -> float:
    if model == "1":
        return 1.0
    if model == "log n":
        return math.log2(n)
    if model == "n":
        return float(n)
    if model == "n log n":
        return n * math.log2(n)
    if model == "n^2":
        return float(n * n)
    if model == "n^3":
        return float(n**3)
    return 2.0**n if n < 1000 else math.inf


def fit_models(points: list[tuple[int, int]]) -> list[BigOFit]:
    """Fit y = a*f(n) + b for every model; sorted best first (R² desc, then simpler first)."""
    ns = [p[0] for p in points]
    ys = [float(p[1]) for p in points]
    mean_y = sum(ys) / len(ys)
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    fits: list[BigOFit] = []
    for model, label in MODELS:
        xs = [_f(model, n) for n in ns]
        if any(math.isinf(x) for x in xs):
            continue
        mean_x = sum(xs) / len(xs)
        sxx = sum((x - mean_x) ** 2 for x in xs)
        a = 0.0 if sxx == 0 else sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / sxx
        b = mean_y - a * mean_x
        pred = [a * x + b for x in xs]
        ss_res = sum((y - p) ** 2 for y, p in zip(ys, pred, strict=True))
        r2 = 1.0 if ss_tot == 0 else max(0.0, 1.0 - ss_res / ss_tot)
        if a < 0:  # a shrinking cost is not a growth model for this data
            r2 = 0.0
        fits.append(BigOFit(model=model, label=label, r2=round(r2, 6), a=a, b=b, predicted=pred))  # type: ignore[arg-type]
    best_r2 = max(f.r2 for f in fits)
    contenders = sorted((f for f in fits if f.r2 >= best_r2 - R2_TIE), key=lambda f: ORDER[f.model])
    rest = sorted((f for f in fits if f not in contenders), key=lambda f: (-f.r2, ORDER[f.model]))
    return [*contenders, *rest]


# ------------------------------------------------------------------------------------------ static estimate
def _self_calls(func: ast.FunctionDef) -> list[ast.Call]:
    return [n for n in ast.walk(func) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == func.name]


def static_estimate(source: str, func: str) -> StaticEstimate:
    """Loop depth / recursion shape; deliberately naive (it is shown NEXT TO the measurement, never instead of it)."""
    tree = parse_files({"main.py": source})["main.py"]
    node = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == func), None)
    if node is None:
        return StaticEstimate(model=None, label="?", basis=f"function {func!r} not found")
    calls = _self_calls(node)
    if len(calls) >= 2:
        return StaticEstimate(model="2^n", label="O(2ⁿ)", basis=f"{len(calls)} recursive calls per call")
    if len(calls) == 1:
        text = ast.unparse(calls[0])
        halves = "// 2" in text or "/ 2" in text or ">> 1" in text or "mid" in text
        return StaticEstimate(
            model="log n" if halves else "n", label="O(log n)" if halves else "O(n)",
            basis="one recursive call on a halved argument" if halves else "one recursive call per level",
        )  # fmt: skip
    info = next((f for f in complexity_analyze({"main.py": ast.parse(source)}) if f.qualname == func), None)
    depth = info.max_loop_depth if info else 0
    model = {0: "1", 1: "n", 2: "n^2", 3: "n^3"}.get(depth, "n^3")
    label = dict(MODELS)[model]
    return StaticEstimate(model=model, label=label, basis=f"loop nesting depth {depth}")


# ------------------------------------------------------------------------------------------ measurement
def _arg_expr(raw: str) -> str:
    if raw in _PLACEHOLDERS:
        return _PLACEHOLDERS[raw]
    try:
        return repr(ast.literal_eval(raw))
    except (ValueError, SyntaxError) as exc:
        raise SourceError(f"extra argument {raw!r} must be a Python literal or one of {sorted(_PLACEHOLDERS)}") from exc


def build_driver(source: str, func: str, generator: str, n: int, extra_args: list[str], seed: int) -> tuple[str, int]:
    """(program text, line number of the measured call)."""
    args = ", ".join(["data", *(_arg_expr(a) for a in extra_args)])
    head = source.rstrip("\n") + "\n\n# --- GlassBox Big-O driver ---\nimport random as __gb_random\n"
    lines = [f"__gb_random.seed({seed})", f"n = {n}", f"data = {GENERATORS[generator]}", f"__gb_result = {func}({args})"]
    text = head + "\n".join(lines) + "\n"
    return text, text.count("\n")  # the call is the last line


async def _measure(manager: SandboxManager, source: str, entry: str, func: str, call_line: int, seed: int) -> tuple[int | None, str]:
    request = RunRequest(files={entry: source}, entry=entry, seed=seed, filter="user_only", limits={"max_steps": MAX_STEPS, "timeout_s": 10})
    call_step: int | None = None
    frame: int | None = None
    steps: int | None = None
    status = "unknown"
    detail = ""
    async for ev in manager.run(request):
        typ = ev["type"]
        if typ == "call" and ev.get("kind") == "user" and ev["func"] == func and ev.get("call_line") == call_line and frame is None:
            call_step, frame = ev["step"], ev["frame"]
        elif typ == "return" and ev["frame"] == frame and steps is None and call_step is not None:
            steps = ev["step"] - call_step
        elif typ == "run_finished":
            status, detail = ev["status"], str(ev.get("detail") or "")
    return steps, (status if steps is not None else f"{status}: {detail}")


async def run_bigo(
    manager: SandboxManager, files: dict[str, str], entry: str, func: str, generator: str,
    sizes: list[int] | None, extra_args: list[str], seed: int = 0,
) -> BigOReport:  # fmt: skip
    if not func.isidentifier():
        raise SourceError(f"{func!r} is not a valid function name")
    source = files[entry]
    parse_files({entry: source})
    sizes = sorted(set(sizes or (DEFAULT_SIZES_INT_N if generator == "int_n" else DEFAULT_SIZES)))
    if any(n < 2 or n > 100_000 for n in sizes):
        raise SourceError("sizes must be between 2 and 100000")
    points: list[tuple[int, int]] = []
    stopped: str | None = None
    for n in sizes:
        program, call_line = build_driver(source, func, generator, n, extra_args, seed)
        steps, status = await _measure(manager, program, entry, func, call_line, seed)
        if steps is None:
            stopped = f"n={n}: {status}"
            break
        points.append((n, steps))
    if len(points) < MIN_POINTS:
        raise SourceError(f"only {len(points)} measurement(s) succeeded (need {MIN_POINTS}); {stopped or 'the call never returned'}")
    fits = fit_models(points)
    est = static_estimate(source, func)
    best = fits[0]
    conflict = est.model is not None and est.model != best.model
    note = (
        "Empirical estimate for THIS input family, from deterministic step counts (not wall-clock time); "
        "it is not a proof of the algorithm's complexity."
    )
    return BigOReport(
        func=func, generator=generator, points=[BigOPoint(n=n, steps=s) for n, s in points], best=best,
        runner_up=fits[1] if len(fits) > 1 else None, fits=fits, static=est, conflict=conflict, note=note,
        stopped_early=stopped,
    )  # fmt: skip

