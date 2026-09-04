from __future__ import annotations

from datetime import date

import pytest

from app.market_data.newow.futures_evidence_plan import (
    FuturesEvidenceCandidate,
    build_natural_year_folds,
    select_futures_evidence_products,
)


def _candidate(
    product: str,
    sector: str,
    since: date,
    *,
    rollovers: int = 2,
    operational: bool = True,
) -> FuturesEvidenceCandidate:
    return FuturesEvidenceCandidate(
        product=product,
        sector=sector,
        common_since=since,
        common_through=date(2025, 12, 31),
        rollover_count=rollovers,
        operational=operational,
        frequencies=("1d", "1w", "60m"),
    )


def test_selects_one_product_per_frozen_sector_by_coverage_then_product() -> None:
    candidates = (
        _candidate("j", "black", date(2020, 1, 1)),
        _candidate("i", "black", date(2020, 1, 1)),
        _candidate("bu", "energy", date(2019, 1, 1)),
        _candidate("ma", "chemical", date(2018, 1, 1)),
        _candidate("m", "agriculture", date(2017, 1, 1)),
        _candidate("a", "agriculture", date(2017, 1, 1)),
    )

    selected = select_futures_evidence_products(candidates)

    assert tuple(item.product for item in selected) == ("i", "ma", "a")


def test_selection_does_not_relax_rollover_frequency_or_operational_gates() -> None:
    candidates = (
        _candidate("i", "black", date(2020, 1, 1), rollovers=1),
        _candidate("ma", "chemical", date(2020, 1, 1), operational=False),
        FuturesEvidenceCandidate(
            "a",
            "agriculture",
            date(2020, 1, 1),
            date(2025, 12, 31),
            2,
            True,
            ("1d", "1w"),
        ),
    )

    with pytest.raises(ValueError, match="NEWOW_EVIDENCE_PRODUCT_SELECTION_BLOCKED"):
        select_futures_evidence_products(candidates)


def test_builds_expanding_natural_year_folds_from_complete_years_only() -> None:
    folds = build_natural_year_folds(
        date(2020, 6, 1),
        date(2024, 8, 31),
        complete_years=(2021, 2022, 2023),
    )

    assert tuple(fold.name for fold in folds) == ("test-2022", "test-2023")
    assert folds[0].train_since == date(2020, 6, 1)
    assert folds[0].train_through == date(2021, 12, 31)
    assert folds[0].test_since == date(2022, 1, 1)
    assert folds[0].test_through == date(2022, 12, 31)
    assert folds[1].train_through == date(2022, 12, 31)


def test_fold_gate_requires_two_complete_nonoverlapping_test_years() -> None:
    with pytest.raises(ValueError, match="NEWOW_EVIDENCE_FOLD_COVERAGE_BLOCKED"):
        build_natural_year_folds(
            date(2022, 1, 4),
            date(2023, 12, 29),
            complete_years=(2022, 2023),
        )
