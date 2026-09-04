"""Deterministic selection and fold rules for the later evidence run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from guiyi_quant.newow import WalkForwardFold


_FREQUENCIES = ("1d", "1w", "60m")
_SECTOR_BUCKETS = (
    ("black", frozenset({"black"})),
    ("energy_chemical", frozenset({"energy", "chemical"})),
    ("agriculture", frozenset({"agriculture"})),
)


@dataclass(frozen=True, slots=True)
class FuturesEvidenceCandidate:
    product: str
    sector: str
    common_since: date
    common_through: date
    rollover_count: int
    operational: bool
    frequencies: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not self.product
            or self.product != self.product.lower()
            or not self.sector
            or type(self.common_since) is not date
            or type(self.common_through) is not date
            or self.common_since > self.common_through
            or type(self.rollover_count) is not int
            or self.rollover_count < 0
            or type(self.operational) is not bool
            or len(self.frequencies) != len(set(self.frequencies))
        ):
            raise ValueError("NEWOW_EVIDENCE_PRODUCT_CANDIDATE_INVALID")


def select_futures_evidence_products(
    candidates: tuple[FuturesEvidenceCandidate, ...],
) -> tuple[FuturesEvidenceCandidate, ...]:
    """Select by frozen eligibility, longest coverage, then product code."""

    selected: list[FuturesEvidenceCandidate] = []
    for _, sectors in _SECTOR_BUCKETS:
        eligible = tuple(
            candidate
            for candidate in candidates
            if isinstance(candidate, FuturesEvidenceCandidate)
            and candidate.sector in sectors
            and candidate.operational
            and candidate.rollover_count >= 2
            and candidate.frequencies == _FREQUENCIES
        )
        if not eligible:
            raise ValueError("NEWOW_EVIDENCE_PRODUCT_SELECTION_BLOCKED")
        selected.append(
            sorted(
                eligible,
                key=lambda item: (
                    -(item.common_through - item.common_since).days,
                    item.product,
                ),
            )[0]
        )
    return tuple(selected)


def build_natural_year_folds(
    common_since: date,
    common_through: date,
    *,
    complete_years: tuple[int, ...],
) -> tuple[WalkForwardFold, ...]:
    """Use Calendar-proven complete years, not Jan-1/Dec-31 Bar dates."""

    if (
        type(common_since) is not date
        or type(common_through) is not date
        or common_since > common_through
        or len(complete_years) < 3
        or complete_years != tuple(sorted(set(complete_years)))
        or any(
            current != previous + 1
            for previous, current in zip(
                complete_years, complete_years[1:], strict=False
            )
        )
        or complete_years[0] < common_since.year
        or complete_years[-1] > common_through.year
    ):
        raise ValueError("NEWOW_EVIDENCE_FOLD_COVERAGE_BLOCKED")
    test_years = complete_years[1:]
    return tuple(
        WalkForwardFold(
            name=f"test-{year}",
            train_since=common_since,
            train_through=date(year - 1, 12, 31),
            test_since=date(year, 1, 1),
            test_through=date(year, 12, 31),
        )
        for year in test_years
    )
