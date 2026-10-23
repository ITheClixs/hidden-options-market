"""Results registry and the generated paper numbers, tables and README."""

from hidden_options.publish.build import check_drift, publish
from hidden_options.publish.latex import Column, render_macros, render_table
from hidden_options.publish.readme import render_readme
from hidden_options.publish.results import (
    RESULTS_DIR,
    Result,
    now_iso,
    read_results,
    write_result,
)

__all__ = [
    "RESULTS_DIR",
    "Column",
    "Result",
    "check_drift",
    "now_iso",
    "publish",
    "read_results",
    "render_macros",
    "render_readme",
    "render_table",
    "write_result",
]
