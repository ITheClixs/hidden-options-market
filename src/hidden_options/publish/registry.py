"""Name -> callable registries for analyses, figure builders and table specs.

An analysis module registers its pieces with a decorator when it is imported:

    @ANALYSES.register("panel_census")
    def panel_census() -> Result: ...

    @FIGURES.register("growth")
    def growth() -> None: ...

    @TABLES.register("predictive")
    def predictive(results: Mapping[str, Result]) -> str: ...

`hidden-options results`, `figures` and `publish` run whatever is registered, so a
new analysis is wired in by listing its module in REGISTRATION_MODULES and nothing
else. Registration modules are named explicitly rather than discovered, so what the
paper depends on can be read off one tuple.

Figure modules have a list of their own, FIGURE_MODULES, which only the `figures`
command loads. Drawing needs matplotlib and publishing does not: `publish`, `check` and
`results` read and write results and text, and must run on a checkout without the
plotting extra. A module in REGISTRATION_MODULES must therefore not import matplotlib.

A table name becomes `paper/tables/<name>.tex`, so TABLES accepts only the characters a
result name may use: letters, digits, `_` and `-`.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Generic, TypeVar

from hidden_options.publish.results import NAME_PATTERN, Result, write_result

T = TypeVar("T")

AnalysisFn = Callable[[], Result]
FigureFn = Callable[[], None]
TableFn = Callable[[Mapping[str, Result]], str]

# Modules whose import registers analyses and tables. Each analysis task adds its module
# here. None of them may import matplotlib.
REGISTRATION_MODULES: tuple[str, ...] = (
    "hidden_options.measure.market_result",
    "hidden_options.measure.hidden_share_result",
    "hidden_options.measure.hidden_share_table",
    "hidden_options.measure.identification_result",
    "hidden_options.measure.identification_table",
    "hidden_options.predict.result",
    "hidden_options.predict.tables",
)

# Modules whose import registers figure builders, loaded only to draw figures.
FIGURE_MODULES: tuple[str, ...] = (
    "hidden_options.figures.market",
    "hidden_options.figures.measurement",
    "hidden_options.figures.predictive",
)


class Registry(Generic[T]):  # noqa: UP046 - PEP 695 syntax needs Python 3.12
    """An insertion-ordered name -> callable map that refuses duplicate names.

    With a `name_pattern`, a name must match it in full, which is how a registry whose
    names become file names keeps them inside their folder.
    """

    def __init__(self, kind: str, *, name_pattern: re.Pattern[str] | None = None) -> None:
        self.kind = kind
        self.name_pattern = name_pattern
        self._entries: dict[str, T] = {}

    def register(self, name: str) -> Callable[[T], T]:
        if self.name_pattern is not None and not self.name_pattern.fullmatch(name):
            raise ValueError(
                f"Invalid {self.kind} name {name!r}: must match {self.name_pattern.pattern}"
            )

        def decorator(fn: T) -> T:
            if name in self._entries:
                raise ValueError(f"A {self.kind} named {name!r} is already registered")
            self._entries[name] = fn
            return fn

        return decorator

    def select(self, only: str | None = None) -> dict[str, T]:
        """Everything registered, or just `only`. Raises ValueError for an unknown name."""
        if only is None:
            return dict(self._entries)
        if only not in self._entries:
            known = ", ".join(self._entries) or "none"
            raise ValueError(f"No {self.kind} named {only!r} (registered: {known})")
        return {only: self._entries[only]}


ANALYSES: Registry[AnalysisFn] = Registry("analysis")
FIGURES: Registry[FigureFn] = Registry("figure builder")
# A table name becomes `paper/tables/<name>.tex`.
TABLES: Registry[TableFn] = Registry("table", name_pattern=NAME_PATTERN)


def load_registrations() -> None:
    """Import every analysis and table registration module so its decorators run."""
    for module in REGISTRATION_MODULES:
        importlib.import_module(module)


def load_figure_registrations() -> None:
    """Import every figure module so its builders register. Needs matplotlib."""
    for module in FIGURE_MODULES:
        importlib.import_module(module)


def run_analyses(analyses: Registry[AnalysisFn], results_dir: Path, only: str | None) -> list[Path]:
    """Run the selected analyses and write each result, returning the files.

    A result must carry the name it was registered under, because the reader finds it
    by file name and a mismatch would publish it under the wrong one.
    """
    written = []
    for name, analysis in analyses.select(only).items():
        result = analysis()
        if result.name != name:
            raise ValueError(f"Analysis {name!r} returned a result named {result.name!r}")
        written.append(write_result(result, results_dir))
    return written


def run_figures(figures: Registry[FigureFn], only: str | None) -> list[str]:
    """Run the selected figure builders, returning their names."""
    selected = figures.select(only)
    for builder in selected.values():
        builder()
    return list(selected)
