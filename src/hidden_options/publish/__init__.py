r"""Results registry and the generated paper numbers, tables and README.

Macro value convention. A result's `macros` map a LaTeX macro name to the string that the
paper and the README both print, so a value must be ASCII text that is valid in LaTeX and
in Markdown at once:

* Escape a dollar sign or a percent sign with a backslash: `\$596bn`, `42\%`. A bare `%`
  or `#`, and a trailing backslash, are rejected because they break the `\newcommand`.
* Write signed numbers with an ASCII hyphen-minus (`-0.03`), never a Unicode minus.
* Never wrap a value in math mode (`$-0.03$`). Math-mode wrapping belongs in the `.tex`,
  around the macro, so the same value stays plain text in the README.
"""

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
