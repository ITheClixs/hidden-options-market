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

import numpy as np

from hidden_options.config import PROJECT_ROOT

RESULTS_DIR = PROJECT_ROOT / "results"

# A name becomes a file stem (`results/<name>.json`, `paper/tables/<name>.tex`), so it must
# not be able to leave its directory. Anything that names an output file uses this rule.
NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
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
    if not NAME_PATTERN.fullmatch(result.name):
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
    try:
        text = json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            default=_numpy_to_python,
        )
    except (TypeError, ValueError) as exc:
        where = _unserialisable_path(payload, "")
        place = f" at {where}" if where else ""
        raise ValueError(f"Result {result.name!r} cannot be written as JSON{place}: {exc}") from exc
    return f"{text}\n"


def _numpy_to_python(value: object) -> object:
    """`json.dumps` hook: numpy booleans, integers and floats become Python ones.

    Analyses compute with numpy, so a count or coefficient reaches `values` as a numpy
    scalar, which `json` refuses. Anything else it cannot write (a date, an array, a
    complex number) is left to raise, so the caller learns about it rather than getting a
    guessed representation.
    """
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    raise TypeError(f"{type(value).__name__} is not JSON serialisable")


def _unserialisable_path(node: object, path: str) -> str | None:
    """Where in the payload the first value `json` cannot write sits, e.g. `values['beta']`.

    None when no single value is to blame (a key that cannot be sorted against its
    siblings, say), in which case the caller reports the error without a location.
    """
    if isinstance(node, dict):
        for key, child in node.items():
            if not (key is None or isinstance(key, str | int | float | bool)):
                return f"{path}[{key!r}]"
            found = _unserialisable_path(child, f"{path}[{key!r}]" if path else str(key))
            if found:
                return found
        return None
    if isinstance(node, list | tuple):
        for position, child in enumerate(node):
            found = _unserialisable_path(child, f"{path}[{position}]")
            if found:
                return found
        return None
    try:
        json.dumps(node, allow_nan=False, default=_numpy_to_python)
    except (TypeError, ValueError):
        return path
    return None


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
