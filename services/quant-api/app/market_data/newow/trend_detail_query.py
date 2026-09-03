from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re


MAX_VISIBLE_TRADING_DAYS = 1500


@dataclass(frozen=True, slots=True)
class NewowTrendDetailQuery:
    """Read-only actual-dominant D1 detail intent."""

    product: str
    since: date
    through: date

    def __post_init__(self) -> None:
        if (
            not isinstance(self.product, str)
            or re.fullmatch(r"[a-z]+", self.product.strip()) is None
        ):
            raise ValueError("NEWOW_INVALID_PRODUCT")
        if (
            type(self.since) is not date
            or type(self.through) is not date
            or self.since > self.through
        ):
            raise ValueError("NEWOW_INVALID_RANGE")
        object.__setattr__(self, "product", self.product.strip())

    @classmethod
    def unchecked(
        cls,
        product: object,
        since: object,
        through: object,
    ) -> NewowTrendDetailQuery:
        """Test-only malformed-input carrier for the service boundary."""
        value = object.__new__(cls)
        object.__setattr__(value, "product", product)
        object.__setattr__(value, "since", since)
        object.__setattr__(value, "through", through)
        return value
