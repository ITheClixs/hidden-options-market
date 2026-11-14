"""The `holders` result's figures as the paper and README print them."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from hidden_options.measure.anatomy_macros import dollars
from hidden_options.publish import formats

UNDERLYINGS = ("SPY", "QQQ")
PROFILE_DROP = -0.1


def millions(value: float) -> str:
    r"""Dollars in whole millions with the escaped sign: `\$412m`, `-\$27m`."""
    sign = "-" if value < 0 else ""
    return f"{sign}\\${formats.count(abs(value) / 1e6)}m"


def holders_macros(values: Mapping[str, Any]) -> dict[str, str]:
    family, found, box = values["family"], values["matching"], values["box"]
    recall, shares, design = values["rule_recall"], values["category_shares"], values["design"]
    gamma = values["dealer_gamma"]
    macros = {
        "HoldFileDate": formats.long_date(pd.Timestamp(values["file_date"])),
        "HoldReportDate": formats.long_date(pd.Timestamp(values["report_date"])),
        "HoldFunds": formats.count(family["funds"]),
        "HoldFlexFunds": formats.count(found["funds"]),
        "HoldNetAssets": dollars(family["net_assets"]),
        "HoldStockValue": dollars(family["stock_leg_value"]),
        "HoldLines": formats.count(found["lines"]),
        "HoldFoundLines": formats.percent(found["found_lines_share"], 1),
        "HoldFoundContracts": formats.percent(found["found_contracts_share"], 1),
        "HoldSeries": formats.count(found["series"]),
        "HoldMedianShare": formats.percent(found["median_share_of_open_interest"]),
        "HoldFullSeries": formats.percent(found["series_at_least_95"]),
        "HoldHeldShare": formats.percent(found["held_share_of_their_open_interest"]),
        "HoldStockRecall": formats.percent(recall["stock_leg"]),
        "HoldPackageRecall": formats.percent(recall["package_leg"]),
        "HoldStockCategoryShare": formats.percent(shares["stock_leg"]),
        "HoldPackageCategoryShare": formats.percent(shares["package_leg"]),
        "HoldDesign": formats.percent(design["all"], 1),
        "HoldDesignUpperPut": formats.percent(design["upper_put"], 1),
        "HoldDesignLowerPut": formats.percent(design["lower_put"], 1),
        "HoldDesignCall": formats.percent(design["call"], 1),
        "HoldDesignContracts": formats.count(design["contracts"]),
        "HoldPricedShare": formats.percent(values["priced_share"]),
        "HoldBoxContracts": formats.count(box["lent_contracts"]),
        "HoldBoxFace": dollars(box["lent_face"]),
        "HoldBoxBorrowedFace": dollars(box["borrowed_face"]),
        "HoldBoxShareOfItsBox": formats.percent(box["share_of_its_box"]),
        "HoldBoxMarketShare": formats.percent(box["share_of_box_face"]),
        "HoldBoxMarketFace": dollars(box["market_face"]),
    }
    macros.update(_profile(values["profile"]))
    macros.update(_coverage(values))
    for name in ("all", *UNDERLYINGS):
        if name not in gamma:
            continue
        stem = "HoldGamma" + ("" if name == "all" else name)
        row = gamma[name]
        macros.update(
            {
                f"{stem}Long": millions(row["dealer_long"]),
                f"{stem}Short": millions(row["dealer_short"]),
                f"{stem}Net": millions(row["net"]),
                f"{stem}ConventionNet": millions(row["convention_net"]),
                f"{stem}Wrong": formats.percent(row["convention_wrong_share"]),
                f"{stem}Share": formats.percent(row["share_of_flex_gamma"]),
            }
        )
    return macros


def _coverage(values: Mapping[str, Any]) -> dict[str, str]:
    """What share of the matched holdings could be priced, and the dealer's gamma in the
    package legs alone. Added after the first figures."""
    coverage = values.get("coverage")
    package = values.get("dealer_gamma_package", {})
    if not coverage or "all" not in package:
        return {}
    missing = coverage["unpriced_underlyings"]
    return {
        "HoldCoverageFunds": formats.count(coverage["priced_funds"]),
        "HoldCoverageContracts": formats.percent(coverage["priced_contracts_share"]),
        "HoldUnpriced": " and ".join(missing) if missing else "none",
        "HoldPackageGammaNet": millions(package["all"]["net"]),
        "HoldPackageGammaConventionNet": millions(package["all"]["convention_net"]),
        "HoldPackageGammaWrong": formats.percent(package["all"]["convention_wrong_share"]),
        "HoldPackageGammaSPYNet": millions(package["SPY"]["net"]) if "SPY" in package else "n/a",
    }


def _profile(profile: Mapping[str, Any]) -> dict[str, str]:
    """The dealer's net gamma and the convention's at PROFILE_DROP below spot, and the
    falls from spot between which the dealer's net is negative."""
    moves = list(profile["moves"])
    if PROFILE_DROP not in moves or not profile["dealer"]:
        return {}
    place = moves.index(PROFILE_DROP)
    below = sorted(-move for move in profile["flips"] if move < 0)
    macros = {
        "HoldProfileDrop": formats.percent(-PROFILE_DROP),
        "HoldProfileDropDealer": millions(profile["dealer"][place]),
        "HoldProfileDropConvention": millions(profile["convention"][place]),
    }
    if len(below) >= 2:
        macros["HoldProfileShortFrom"] = formats.percent(below[0])
        macros["HoldProfileShortTo"] = formats.percent(below[1])
    return macros


__all__ = ["holders_macros", "millions"]
