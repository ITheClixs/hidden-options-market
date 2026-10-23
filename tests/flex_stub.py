"""Test double for OCC's FLEX endpoint, shared by the runner and backfill tests."""

from __future__ import annotations

from datetime import date

import pandas as pd

from hidden_options.collect import occ_flex


def flex_report(report_date: date, kind: str) -> occ_flex.FlexReport:
    frame = pd.DataFrame(
        {
            "report_date": [report_date],
            "kind": [kind],
            "root": ["1AAL"],
            "open_interest": [100],
        }
    )
    return occ_flex.FlexReport(
        report_date=report_date,
        kind=kind,
        frame=frame,
        payload_sha256="f" * 64,
        class_totals_checked=1,
        class_totals_matched=1,
    )


class FlexStub:
    """Stands in for OCC: records every request and answers from a script.

    ``answers`` maps a requested date to the report date OCC answers with, or to
    ``None`` for "no report available". Unlisted dates answer with their own report.
    """

    def __init__(self, monkeypatch, answers=None):
        self.calls: list[tuple[date, str]] = []
        self.answers = answers or {}
        monkeypatch.setattr(occ_flex, "fetch_report", self._fetch)

    def _fetch(self, _session, requested, kind="equity"):
        self.calls.append((requested, kind))
        answer = self.answers.get(requested, requested)
        if answer is None:
            raise occ_flex.FlexReportAbsent(f"{kind} {requested}: no report available")
        if isinstance(answer, Exception):
            raise answer
        return flex_report(answer, kind)
