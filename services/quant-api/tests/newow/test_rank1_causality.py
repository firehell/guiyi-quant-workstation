from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.market_data.newow.rank1_causality import (
    Rank1AsKnownError,
    Rank1CausalInput,
    Rank1PhysicalFact,
    validate_rank1_as_known,
)


def _input(*, main_contract: str = "J2505", rule2_contract: str = "J2505") -> Rank1CausalInput:
    return Rank1CausalInput(
        product="j",
        decision_trading_day=date(2025, 1, 3),
        source_trading_day=date(2025, 1, 2),
        source_bar_end=datetime(2025, 1, 2, 15, tzinfo=UTC),
        decision_session_open=datetime(2025, 1, 2, 21, tzinfo=UTC),
        universe_contracts=("J2501", "J2505", "J2509"),
        physical_facts=(
            Rank1PhysicalFact("J2501", Decimal("90"), Decimal("100")),
            Rank1PhysicalFact("J2505", Decimal("120"), Decimal("140")),
            Rank1PhysicalFact("J2509", Decimal("110"), Decimal("130")),
        ),
        rqdata_rule2_contract=rule2_contract,
        main_contract_map_contract=main_contract,
    )


def test_rank1_as_known_requires_one_prior_completed_contract_to_win_both_measures() -> None:
    result = validate_rank1_as_known((_input(),))

    assert result[0].decision_trading_day == date(2025, 1, 3)
    assert result[0].source_trading_day == date(2025, 1, 2)
    assert result[0].contract == "J2505"


def test_rank1_as_known_rejects_a_volume_tie() -> None:
    source = _input()
    tied = replace(
        source,
        physical_facts=(
            Rank1PhysicalFact("J2501", Decimal("120"), Decimal("100")),
            Rank1PhysicalFact("J2505", Decimal("120"), Decimal("140")),
            Rank1PhysicalFact("J2509", Decimal("110"), Decimal("130")),
        ),
    )

    with pytest.raises(Rank1AsKnownError, match="NEWOW_RANK1_AS_KNOWN_INVALID"):
        validate_rank1_as_known((tied,))


def test_rank1_as_known_rejects_provider_or_catalog_disagreement() -> None:
    with pytest.raises(Rank1AsKnownError, match="NEWOW_RANK1_AS_KNOWN_INVALID"):
        validate_rank1_as_known((_input(main_contract="J2509"),))


def test_rank1_as_known_rejects_source_that_finished_after_the_decision_session_open() -> None:
    source = _input()
    with pytest.raises(Rank1AsKnownError, match="NEWOW_RANK1_AS_KNOWN_INVALID"):
        replace(source, source_bar_end=datetime(2025, 1, 2, 22, tzinfo=UTC))
