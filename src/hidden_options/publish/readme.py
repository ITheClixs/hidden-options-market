"""README rendering: `docs/readme.template.md` plus the macros of the results."""

from __future__ import annotations

import re
from collections.abc import Mapping

_PLACEHOLDER = re.compile(r"\{\{([A-Za-z]+)\}\}")


def render_readme(template: str, macros: Mapping[str, str]) -> str:
    """Replace every `{{Name}}` with the macro of that name.

    The same strings feed the paper, so the two cannot disagree. A placeholder with no
    macro raises KeyError rather than leaving `{{Name}}` in the published page. Text
    without placeholders, including single braces, passes through byte for byte.
    """

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in macros:
            raise KeyError(f"README template uses {{{{{name}}}}} but no result defines it")
        return macros[name]

    return _PLACEHOLDER.sub(substitute, template)
