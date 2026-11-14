"""Documentation hygiene: README links resolve, generated example artefacts stay offline-safe."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_relative_links_in_readme_and_docs_point_to_existing_files() -> None:
    for doc in [ROOT / "README.md", *(ROOT / "docs").glob("*.md")]:
        text = doc.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)#\s]+)\)", text):
            if "://" in target or target.startswith("mailto:"):
                continue
            assert (doc.parent / target).exists(), f"{doc.name}: broken link {target}"


def test_committed_replay_examples_are_self_contained() -> None:
    pages = sorted((ROOT / "docs" / "examples").glob("*.replay.html"))
    assert len(pages) >= 3
    for page in pages:
        text = page.read_text(encoding="utf-8")
        assert text.startswith("<!doctype html>") and 'id="gb-data"' in text
        assert not re.search(r"https?://|<link|<img|src=|href=", text), f"{page.name} references the network"


def test_ci_workflow_runs_the_documented_checks() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for needle in ("ruff check", "gen_types.py --check", "pytest backend/tests", "npm run build", "vitest run"):
        assert needle in ci
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^dev:\n\t.*scripts/dev.py", makefile, re.MULTILINE) and re.search(r"^test: ", makefile, re.MULTILINE)
