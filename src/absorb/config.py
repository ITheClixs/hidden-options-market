"""Project paths and collection constants.

Every tunable lives here rather than being embedded in call sites, so a change of
vendor endpoint or retention policy is a one-line edit with a single blast radius.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_ROOT = Path(os.environ.get("ABSORB_DATA_ROOT", PROJECT_ROOT / "data"))
RAW_DIR = DATA_ROOT / "raw"
INTERIM_DIR = DATA_ROOT / "interim"
CONFIG_DIR = PROJECT_ROOT / "configs"
UNIVERSE_FILE = CONFIG_DIR / "universe.json"
FUNDS_FILE = CONFIG_DIR / "funds.json"

# Cboe publishes a free, unauthenticated, 15-minute-delayed full option chain per
# symbol. Index symbols are prefixed with an underscore (e.g. "_SPX").
CBOE_CHAIN_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"

# OCC series search returns authoritative per-series open interest for one underlying.
OCC_SERIES_URL = "https://marketdata.theocc.com/series-search"

# SEC EDGAR asks automated clients to declare a contact address. Set ABSORB_USER_AGENT
# to include one before running the N-PORT collectors.
_DEFAULT_USER_AGENT = (
    "absorb-research/0.1 (academic study of FLEX option data; "
    "+https://github.com/ITheClixs/known-flow-alpha)"
)
USER_AGENT = os.environ.get("ABSORB_USER_AGENT", _DEFAULT_USER_AGENT)

REQUEST_TIMEOUT_SECONDS = 45
REQUEST_MAX_ATTEMPTS = 4
REQUEST_BACKOFF_SECONDS = 2.0
# Politeness delay between successive requests to the same host.
REQUEST_SPACING_SECONDS = float(os.environ.get("ABSORB_REQUEST_SPACING", "0.6"))


@dataclass(frozen=True)
class Universe:
    """Immutable snapshot of the symbols to collect."""

    treated_single_name: tuple[str, ...]
    treated_index_and_etf: tuple[str, ...]
    control_single_name: tuple[str, ...]

    @property
    def all_symbols(self) -> tuple[str, ...]:
        """Deduplicated collection order: treated first, so a truncated run still
        captures the symbols the study depends on."""
        seen: dict[str, None] = {}
        for group in (
            self.treated_single_name,
            self.treated_index_and_etf,
            self.control_single_name,
        ):
            for symbol in group:
                seen.setdefault(symbol, None)
        return tuple(seen)

    @property
    def occ_symbols(self) -> tuple[str, ...]:
        """OCC series search keys off the equity root, so index pseudo-symbols
        (leading underscore) are excluded."""
        return tuple(s for s in self.all_symbols if not s.startswith("_"))


def load_universe(path: Path | None = None) -> Universe:
    """Read the universe config.

    Raises FileNotFoundError or ValueError with an actionable message rather than
    letting a malformed config surface as a KeyError deep inside a collector.
    """
    target = path or UNIVERSE_FILE
    if not target.exists():
        raise FileNotFoundError(f"Universe config not found at {target}")

    try:
        payload = json.loads(target.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Universe config at {target} is not valid JSON: {exc}") from exc

    try:
        treated = payload["treated_underlyings"]
        control = payload["control_underlyings"]
        universe = Universe(
            treated_single_name=tuple(treated["single_name"]),
            treated_index_and_etf=tuple(treated["index_and_etf"]),
            control_single_name=tuple(control["single_name"]),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Universe config at {target} is missing required keys: {exc}") from exc

    if not universe.all_symbols:
        raise ValueError(f"Universe config at {target} lists no symbols")
    return universe


@dataclass(frozen=True)
class Programme:
    """One fund whose disclosed option flow is tracked."""

    fund: str
    underlying: str
    issuer: str
    url_template: str


def load_programmes(path: Path | None = None) -> tuple[Programme, ...]:
    """Read the fund registry into a flat, immutable tuple of programmes."""
    target = path or FUNDS_FILE
    if not target.exists():
        raise FileNotFoundError(f"Fund registry not found at {target}")

    try:
        payload = json.loads(target.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Fund registry at {target} is not valid JSON: {exc}") from exc

    issuers = payload.get("issuers")
    if not isinstance(issuers, dict) or not issuers:
        raise ValueError(f"Fund registry at {target} defines no issuers")

    programmes: list[Programme] = []
    for issuer_name, spec in issuers.items():
        try:
            template = spec["url_template"]
            funds = spec["funds"]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Issuer {issuer_name!r} in {target} is malformed: {exc}") from exc
        for fund, underlying in funds.items():
            programmes.append(
                Programme(
                    fund=fund.upper(),
                    underlying=underlying,
                    issuer=issuer_name,
                    url_template=template,
                )
            )

    if not programmes:
        raise ValueError(f"Fund registry at {target} lists no funds")
    return tuple(programmes)
