"""Shared test setup.

Loaders that compare prices with strikes read split events from SPLITS_PATH. Tests build
their own bars, so they read an empty splits file instead of the collected one; a test of
the un-adjustment itself passes its splits explicitly.
"""

from __future__ import annotations

import pandas as pd
import pytest

from hidden_options.collect import splits


@pytest.fixture(autouse=True)
def no_collected_splits(tmp_path_factory, monkeypatch):
    path = tmp_path_factory.getbasetemp() / "splits.parquet"
    if not path.exists():
        pd.DataFrame(
            {
                "symbol": pd.Series(dtype=str),
                "session": pd.Series(dtype="datetime64[ns]"),
                "ratio": pd.Series(dtype=float),
            }
        ).to_parquet(path, index=False)
    monkeypatch.setattr(splits, "SPLITS_PATH", path)
