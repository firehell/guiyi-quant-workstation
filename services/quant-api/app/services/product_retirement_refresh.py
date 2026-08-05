"""Build the fixed direct-data refresh targets for the retained universe."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from app.data_core.catalog import CanonicalMainContractMapping
from app.data_core.product_retirement import assert_products_active


DIRECT_FREQUENCIES = ("1m", "1d", "1w")
DERIVED_FREQUENCIES = ("5m", "15m", "30m", "60m")


@dataclass(frozen=True)
class RefreshTarget:
    dataset_kind: str
    symbol: str
    contract_or_series: str
    frequency: str
    start: datetime
    end: datetime


def build_refresh_targets(
    *,
    products: Sequence[str],
    mappings: Sequence[CanonicalMainContractMapping],
    start: datetime,
    end: datetime,
) -> tuple[RefreshTarget, ...]:
    active = assert_products_active(products)
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("PRODUCT_RETIREMENT_REFRESH_WINDOW_INVALID")
    mapping_by_symbol: dict[str, set[str]] = {symbol: set() for symbol in active}
    for row in mappings:
        if row.symbol not in mapping_by_symbol:
            raise ValueError("PRODUCT_RETIREMENT_REFRESH_MAPPING_OUTSIDE_UNIVERSE")
        mapping_by_symbol[row.symbol].add(row.actual_contract)
    missing = tuple(
        symbol for symbol, contracts in mapping_by_symbol.items() if not contracts
    )
    if missing:
        raise ValueError(
            "PRODUCT_RETIREMENT_REFRESH_MAPPING_MISSING:" + ",".join(missing)
        )
    targets: list[RefreshTarget] = []
    for symbol in active:
        for frequency in DIRECT_FREQUENCIES:
            targets.append(
                RefreshTarget(
                    "continuous",
                    symbol,
                    f"{symbol.upper()}.MAIN",
                    frequency,
                    start,
                    end,
                )
            )
        for contract in sorted(mapping_by_symbol[symbol]):
            for frequency in DIRECT_FREQUENCIES:
                targets.append(
                    RefreshTarget(
                        "actual_dominant", symbol, contract, frequency, start, end
                    )
                )
    return tuple(targets)
