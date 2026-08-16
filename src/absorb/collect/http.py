"""Shared HTTP access with retries and polite pacing.

Collectors are long-running unattended jobs against free public endpoints. The two
failure modes that matter are (a) a transient error silently producing a missing day
and (b) hammering a free host. Both are handled here so no collector has to.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests

from absorb.config import (
    REQUEST_BACKOFF_SECONDS,
    REQUEST_MAX_ATTEMPTS,
    REQUEST_SPACING_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
)


class FetchError(RuntimeError):
    """Raised when a URL could not be retrieved after all attempts."""


@dataclass(frozen=True)
class FetchResult:
    """Immutable record of one successful fetch."""

    url: str
    status_code: int
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"})
    return session


def fetch(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, str] | None = None,
    max_attempts: int = REQUEST_MAX_ATTEMPTS,
) -> FetchResult:
    """GET a URL, retrying transient failures with exponential backoff.

    A 404 is treated as terminal (the resource does not exist), not transient, so a
    delisted symbol fails fast instead of burning the retry budget.
    """
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        if attempt:
            time.sleep(REQUEST_BACKOFF_SECONDS * (2 ** (attempt - 1)))
        try:
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            last_error = exc
            continue

        if response.status_code == 404:
            raise FetchError(f"{url} returned 404 (resource absent)")
        if response.ok:
            time.sleep(REQUEST_SPACING_SECONDS)
            return FetchResult(url=url, status_code=response.status_code, content=response.content)

        last_error = FetchError(f"{url} returned HTTP {response.status_code}")

    raise FetchError(f"Failed to fetch {url} after {max_attempts} attempts: {last_error}")
