"""Historical backfill of the OCC FLEX open-interest report.

OCC retains roughly twenty months of daily FLEX reports. Unlike the snapshot sources
elsewhere in this project, which cannot be recovered once they age out, this one can be
obtained retrospectively, and that is what makes a panel of hidden inventory possible.

The backfill is the nightly collector run over an arbitrary span. It shares that
collector's per-report path (fetch, file under the report's own activity date, write
atomically), so the two cannot disagree about what a stored file means, and it skips any
date already held, so a long walk can be interrupted and repeated at no cost.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from hidden_options.collect import occ_flex
from hidden_options.collect.http import build_session
from hidden_options.collect.runner import SymbolOutcome, collect_flex_report, weekdays

logger = logging.getLogger(__name__)

DEFAULT_KINDS = tuple(occ_flex.REPORT_KINDS)


@dataclass(frozen=True)
class BackfillSummary:
    """What one backfill walk did, with every request's outcome kept for audit."""

    skipped: int
    outcomes: tuple[SymbolOutcome, ...]

    def _count(self, *statuses: str) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status in statuses)

    @property
    def saved(self) -> int:
        return self._count("ok")

    @property
    def absent(self) -> int:
        """Requests for a date OCC holds no report for: not published, or a holiday."""
        return self._count("absent")

    @property
    def failed(self) -> int:
        """Requests that went wrong, as opposed to ones OCC had nothing to answer."""
        return len(self.outcomes) - self.saved - self.absent

    def describe(self) -> str:
        return (
            f"saved={self.saved} absent={self.absent} skipped={self.skipped} failed={self.failed}"
        )


def _log_outcome(outcome: SymbolOutcome) -> None:
    if outcome.status in ("ok", "absent"):
        logger.info("%s %s %s", outcome.symbol, outcome.status, outcome.detail)
    else:
        logger.warning("%s %s %s", outcome.symbol, outcome.status, outcome.detail)


def backfill_flex(
    start: date,
    end: date,
    root: Path,
    kinds: tuple[str, ...] = DEFAULT_KINDS,
    *,
    session: requests.Session | None = None,
) -> BackfillSummary:
    """Fetch every missing FLEX report for the weekdays in ``[start, end]``, newest first.

    A date already on disk is neither fetched nor rewritten. An unpublished date is
    recorded as absent rather than failed, and a request that fails is recorded and the
    walk goes on, so the summary, not an exception, is how a caller learns what is
    missing. Reports are filed under the activity date they state; a request that OCC
    answers with another day's report never puts that report under the requested date.
    """
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    unknown = sorted(set(kinds) - set(occ_flex.REPORT_KINDS))
    if unknown:
        raise ValueError(f"unknown report kind {unknown}; use {sorted(occ_flex.REPORT_KINDS)}")

    http = session or build_session()
    skipped = 0
    outcomes: list[SymbolOutcome] = []

    for day in weekdays(end, (end - start).days):
        for kind in kinds:
            if (root / occ_flex.snapshot_path_for(day, kind)).exists():
                skipped += 1
                continue
            for outcome in collect_flex_report(http, day, kind, root):
                _log_outcome(outcome)
                outcomes.append(outcome)

    return BackfillSummary(skipped=skipped, outcomes=tuple(outcomes))


__all__ = ["DEFAULT_KINDS", "BackfillSummary", "backfill_flex"]
