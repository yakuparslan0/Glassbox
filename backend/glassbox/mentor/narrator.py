"""Layer A: deterministic, LLM-free narration of scenes (instant; works without any API key)."""

from __future__ import annotations

from .digest import Scene

T = {
    "tr": {
        "call": "`{func}({args})` çağrıldı",
        "calls": "{n} iç çağrı yaptı",
        "loop": "{line}. satır {n} kez çalıştı",
        "ret": "`{ret}` döndürdü",
        "changes": "Değişen değerler: {changes}",
        "out": "Ekrana yazdı: {out}",
        "module": "Modül düzeyindeki kod çalıştı ({steps} adım)",
        "exc": "{type}: {message} — {line}. satırda",
        "exc_values": "Bu satırdaki değerler: {values}",
        "title_call": "{func} çağrısı",
        "title_module": "Modül düzeyi kod",
        "title_exc": "{func} hatası",
    },
    "en": {
        "call": "`{func}({args})` was called",
        "calls": "it made {n} inner call(s)",
        "loop": "line {line} ran {n} times",
        "ret": "it returned `{ret}`",
        "changes": "Changed values: {changes}",
        "out": "It printed: {out}",
        "module": "Module-level code ran ({steps} steps)",
        "exc": "{type}: {message} — at line {line}",
        "exc_values": "Values on that line: {values}",
        "title_call": "Call to {func}",
        "title_module": "Module-level code",
        "title_exc": "{func} error",
    },
}


def scene_title(scene: Scene, lang: str) -> str:
    t = T.get(lang, T["en"])
    func = str(scene.facts.get("func", ""))
    if scene.kind == "call":
        return t["title_call"].format(func=func)
    if scene.kind == "exception":
        return t["title_exc"].format(func=func)
    return t["title_module"]


def narrate_scene(scene: Scene, lang: str) -> str:
    """One short paragraph built only from measured / recorded facts (nothing is guessed)."""
    t = T.get(lang, T["en"])
    f = scene.facts
    sentences: list[str] = []
    if scene.kind == "call":
        head = t["call"].format(func=f.get("func", ""), args=f.get("args", ""))
        extra = []
        inner = sum(f["calls"].values()) - 1  # the call itself is counted once
        if inner > 0:
            extra.append(t["calls"].format(n=inner))
        if f["repeat_line"]:
            extra.append(t["loop"].format(line=f["repeat_line"], n=f["repeat_count"]))
        if f["return"] is not None:
            extra.append(t["ret"].format(ret=f["return"]))
        sentences.append(head + (", " + ", ".join(extra) if extra else "") + ".")
    elif scene.kind == "exception":
        ex = f.get("exc")
        if ex:
            sentences.append(t["exc"].format(type=ex["type"], message=ex["message"], line=ex["line"]) + ".")
            if ex["values"]:
                sentences.append(t["exc_values"].format(values=", ".join(f"`{k}` = {v}" for k, v in ex["values"].items())) + ".")
    else:
        text = t["module"].format(steps=scene.measured.get("steps", 0))
        if f["repeat_line"]:
            text += ", " + t["loop"].format(line=f["repeat_line"], n=f["repeat_count"])
        sentences.append(text + ".")
    if f["changes"] and scene.kind != "call":
        sentences.append(t["changes"].format(changes=", ".join(f"`{k}` = {v}" for k, v in f["changes"].items())) + ".")
    if f["stdout"]:
        sentences.append(t["out"].format(out=f["stdout"].strip().replace("\n", " ⏎ ")) + ".")
    return " ".join(sentences)
