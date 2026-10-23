"""Render the committed outputs from `results/`, write them, and detect drift.

Nothing here touches raw data, so CI can run it on a bare checkout: the outputs are a
pure function of `results/` and the README template.
"""

from __future__ import annotations

from pathlib import Path

from hidden_options.config import PROJECT_ROOT
from hidden_options.publish import registry
from hidden_options.publish.latex import collect_macros, render_macros
from hidden_options.publish.readme import render_readme
from hidden_options.publish.registry import Registry, TableFn
from hidden_options.publish.results import read_results

README = "README.md"
README_TEMPLATE = "docs/readme.template.md"
NUMBERS = "paper/numbers.tex"
TABLES_DIR = "paper/tables"


def render_outputs(root: Path, tables: Registry[TableFn]) -> dict[str, str]:
    """Every generated file as {path relative to root: contents}."""
    results = read_results(root / "results")
    template_path = root / README_TEMPLATE
    if not template_path.is_file():
        raise FileNotFoundError(f"README template not found at {template_path}")

    outputs = {
        NUMBERS: render_macros(results),
        README: render_readme(template_path.read_text(encoding="utf-8"), collect_macros(results)),
    }
    for name, spec in tables.select().items():
        outputs[f"{TABLES_DIR}/{name}.tex"] = spec(results)
    return outputs


def check_drift(root: Path = PROJECT_ROOT, *, tables: Registry[TableFn] | None = None) -> list[str]:
    """Paths (relative to root) whose committed content differs from a fresh render.

    A generated file that is missing counts, and so does a table file that no spec
    produces any more, since a stale table would keep printing numbers that no result
    backs.
    """
    tables = registry.TABLES if tables is None else tables
    expected = render_outputs(root, tables)
    drifted = [path for path, text in expected.items() if _read(root / path) != text]
    drifted += sorted(set(_table_files(root)) - set(expected))
    return sorted(drifted)


def publish(root: Path = PROJECT_ROOT, *, tables: Registry[TableFn] | None = None) -> list[str]:
    """Write the generated files and remove stale tables, returning what changed.

    Files already holding the right content are not touched, so an up-to-date
    checkout stays clean and the return value says exactly what a commit will contain.
    """
    tables = registry.TABLES if tables is None else tables
    expected = render_outputs(root, tables)
    changed = []
    for path, text in expected.items():
        target = root / path
        if _read(target) != text:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode("utf-8"))
            changed.append(path)
    for path in sorted(set(_table_files(root)) - set(expected)):
        (root / path).unlink()
        changed.append(path)
    return sorted(changed)


def _read(path: Path) -> str | None:
    """File text exactly as stored (no newline translation), or None if absent."""
    return path.read_bytes().decode("utf-8") if path.is_file() else None


def _table_files(root: Path) -> list[str]:
    return [p.relative_to(root).as_posix() for p in (root / TABLES_DIR).glob("*.tex")]
