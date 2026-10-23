"""Result files: the single place every published number is computed.

An analysis ends by writing one small JSON file to `results/`. The paper's macros, its
tables and the README are all rendered from those files and nothing else, so CI can
re-render them without the raw data and a number that was typed by hand shows up as
drift.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hidden_options.config import PROJECT_ROOT

RESULTS_DIR = PROJECT_ROOT / "results"

# The name becomes `results/<name>.json`, so it must not be able to leave the directory.
_NAME = re.compile(r"[A-Za-z0-9_-]+")
_FIELDS = ("name", "values", "macros", "inputs", "generated_at")


@dataclass(frozen=True)
class Result:
    """What one analysis found.

    `values` holds the raw figures for tables and later code. `macros` maps a LaTeX
    macro name to the string the paper and README print; the analysis formats it, so
    rounding is decided where the number is computed and never again downstream.
    `inputs` records what the result was computed from (date range, row counts), so a
    reader can tell which data a committed number belongs to.
    """

    name: str
    values: Mapping[str, Any]
    macros: Mapping[str, str]
    inputs: Mapping[str, Any]
    generated_at: str


def now_iso() -> str:
    """A UTC timestamp for `Result.generated_at`, to the second."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def write_result(result: Result, root: Path = RESULTS_DIR) -> Path:
    """Write `result` to `<root>/<name>.json` and return the path.

    Keys are sorted and the layout fixed so a re-run that finds the same numbers
    produces the same bytes. A re-run also gets a fresh `generated_at`, which would
    dirty every file on every run, so when the stored file differs only in its
    timestamp it is left untouched: the stamp then says when the content last changed.
    """
    if not _NAME.fullmatch(result.name):
        raise ValueError(f"Result name {result.name!r} must be letters, digits, _ or -")

    path = root / f"{result.name}.json"
    text = _serialise(result)
    if path.exists() and _stored_equals(path, result):
        return path

    root.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def read_results(root: Path = RESULTS_DIR) -> dict[str, Result]:
    """Load every `*.json` under `root`, keyed by result name and sorted by it.

    A missing directory means no results yet. A file that is not valid JSON, lacks a
    field, or is filed under a different name than it carries raises ValueError naming
    the file, because a renamed result would silently publish under the wrong name.
    """
    if not root.is_dir():
        return {}
    results = (_load(path) for path in sorted(root.glob("*.json")))
    return {result.name: result for result in results}


def _serialise(result: Result) -> str:
    payload = {field: getattr(result, field) for field in _FIELDS}
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return f"{text}\n"


def _load(path: Path) -> Result:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        result = Result(**{field: payload[field] for field in _FIELDS})
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"Result file {path} is not a valid result: {exc!r}") from exc
    if result.name != path.stem:
        raise ValueError(f"Result file {path.name} carries the name {result.name!r}")
    return result


def _stored_equals(path: Path, result: Result) -> bool:
    """True when `path` already holds `result`, ignoring only the timestamp."""
    try:
        stored = _load(path)
    except ValueError:
        return False
    same_stamp = replace(result, generated_at=stored.generated_at)
    return path.read_bytes() == _serialise(same_stamp).encode("utf-8")
