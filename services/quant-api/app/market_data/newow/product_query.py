"""Validated read intent for the completed Newow product; no market access."""

from dataclasses import dataclass
from datetime import date, datetime
import re

from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
from guiyi_quant.newow.product_identity import utc_timestamp


@dataclass(frozen=True, slots=True)
class ProductReadWindow:
    since: date
    through: date

    def __post_init__(self) -> None:
        if (
            type(self.since) is not date
            or type(self.through) is not date
            or self.since > self.through
        ):
            raise ValueError("NEWOW_INVALID_RANGE")


@dataclass(frozen=True, slots=True)
class NewowProductQuery:
    product: str
    strategy: ProductStrategy
    frequency: ProductFrequency
    since: date
    through: date
    performance_since: date | None = None
    performance_through: date | None = None
    as_of: datetime | None = None
    series_kind: str = "actual_dominant"
    history_limit: int = 50
    history_before: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.product, str)
            or re.fullmatch(r"[a-z]+", self.product) is None
        ):
            raise ValueError("NEWOW_INVALID_PRODUCT")
        object.__setattr__(self, "strategy", ProductStrategy(self.strategy))
        object.__setattr__(self, "frequency", ProductFrequency(self.frequency))
        if self.series_kind != "actual_dominant":
            raise ValueError("NEWOW_INVALID_SERIES")
        ProductReadWindow(self.since, self.through)
        if (self.performance_since is None) != (self.performance_through is None):
            raise ValueError("NEWOW_INVALID_PERFORMANCE_WINDOW")
        if self.performance_since is not None and self.performance_through is not None:
            ProductReadWindow(self.performance_since, self.performance_through)
        if type(self.history_limit) is not int or not 1 <= self.history_limit <= 200:
            raise ValueError("NEWOW_INVALID_HISTORY_LIMIT")
        # Cursor binding/decoding belongs to the reference-history service, not
        # this market reader. Retain the opaque value without interpreting it.
        if self.history_before is not None and (
            not isinstance(self.history_before, str) or not self.history_before.strip()
        ):
            raise ValueError("NEWOW_INVALID_HISTORY_CURSOR")
        if self.as_of is not None:
            object.__setattr__(self, "as_of", utc_timestamp(self.as_of))
