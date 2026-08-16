"""Tests for the shared fetch layer.

Retry semantics matter more here than usual: these are unattended captures of
snapshot endpoints, so a transient failure that is not retried costs a day of data
permanently, while a 404 that *is* retried wastes the budget that the recoverable
symbols need.
"""

from __future__ import annotations

import pytest
import requests

from absorb.collect import http
from absorb.collect.http import FetchError, build_session, fetch


class _Response:
    def __init__(self, status_code: int, content: bytes = b"ok"):
        self.status_code = status_code
        self.content = content

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class _Session:
    """Replays a scripted sequence of responses or exceptions."""

    def __init__(self, script: list[object]):
        self.script = list(script)
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url, params=None, timeout=None):  # noqa: ARG002
        self.calls.append((url, params))
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    """Backoff is correct behaviour but makes the suite slow; assert on calls instead."""
    monkeypatch.setattr(http.time, "sleep", lambda _seconds: None)


class TestFetch:
    def test_returns_content_on_success(self):
        session = _Session([_Response(200, b"payload")])
        result = fetch(session, "https://example.test/a")
        assert result.content == b"payload"
        assert result.status_code == 200

    def test_decodes_text(self):
        session = _Session([_Response(200, b"hello")])
        assert fetch(session, "https://example.test/a").text == "hello"

    def test_passes_query_parameters(self):
        session = _Session([_Response(200)])
        fetch(session, "https://example.test/a", params={"symbol": "MSTR"})
        assert session.calls[0][1] == {"symbol": "MSTR"}

    def test_retries_transient_network_errors(self):
        session = _Session([requests.ConnectionError("reset"), _Response(200, b"late")])
        assert fetch(session, "https://example.test/a").content == b"late"
        assert len(session.calls) == 2

    def test_retries_server_errors(self):
        session = _Session([_Response(503), _Response(503), _Response(200, b"third")])
        assert fetch(session, "https://example.test/a").content == b"third"
        assert len(session.calls) == 3

    def test_gives_up_after_max_attempts(self):
        session = _Session([_Response(503)] * 4)
        with pytest.raises(FetchError, match="after 4 attempts"):
            fetch(session, "https://example.test/a")
        assert len(session.calls) == 4

    def test_404_is_terminal_and_not_retried(self):
        """A missing resource will not appear on retry; spending the budget hurts
        the symbols that could still be recovered."""
        session = _Session([_Response(404)])
        with pytest.raises(FetchError, match="404"):
            fetch(session, "https://example.test/gone")
        assert len(session.calls) == 1

    def test_attempt_budget_is_configurable(self):
        session = _Session([_Response(500)] * 2)
        with pytest.raises(FetchError):
            fetch(session, "https://example.test/a", max_attempts=2)
        assert len(session.calls) == 2

    def test_error_message_names_the_url(self):
        session = _Session([requests.Timeout("slow")] * 4)
        with pytest.raises(FetchError, match="https://example.test/slow"):
            fetch(session, "https://example.test/slow")


class TestBuildSession:
    def test_sets_an_identifying_user_agent(self):
        """Free public endpoints deserve an identifiable, contactable client."""
        session = build_session()
        assert "absorb-research" in session.headers["User-Agent"]

    def test_requests_compression(self):
        assert "gzip" in build_session().headers["Accept-Encoding"]
