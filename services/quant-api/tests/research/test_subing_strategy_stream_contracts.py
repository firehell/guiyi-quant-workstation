from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.market_data.domain import CanonicalBar
from app.market_data.subing_strategy.contracts import (
    SubingStrategyActionKind,
    SubingStrategyContractError,
)
from app.market_data.subing_strategy.engine import SubingStrategyPendingCancellation
from app.market_data.subing_strategy.stream_contracts import (
    AuthoritativeSegmentTerminal,
    Completed1mBar,
    Completed5mBar,
    Completed15mBar,
    SubingStrategyStepOutput,
)


SEGMENT_START = date(2026, 1, 5)


def _bar(
    *,
    bar_end: datetime = datetime(2026, 1, 5, 2, 15, tzinfo=UTC),
    trading_day: date = SEGMENT_START,
) -> CanonicalBar:
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=trading_day,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("1"),
        turnover=None,
        open_interest=None,
    )


@pytest.mark.parametrize("wrapper", (Completed1mBar, Completed5mBar, Completed15mBar))
def test_completed_bar_inputs_are_immutable_and_keep_canonical_bar(
    wrapper: type,
) -> None:
    bar = _bar(
        bar_end=datetime(2026, 1, 5, 10, 15, tzinfo=timezone(timedelta(hours=8)))
    )

    event = wrapper(bar=bar)

    assert event.bar.bar_end == datetime(2026, 1, 5, 2, 15, tzinfo=UTC)
    with pytest.raises(FrozenInstanceError):
        event.bar = _bar()  # type: ignore[misc]


def test_completed_bar_rejects_wrong_frequency_wrapper() -> None:
    with pytest.raises(SubingStrategyContractError):
        Completed1mBar(bar=Completed5mBar(bar=_bar()))  # type: ignore[arg-type]


@pytest.mark.parametrize("value", (True, object()))
def test_completed_bar_rejects_boolean_or_arbitrary_input(value: object) -> None:
    with pytest.raises(SubingStrategyContractError):
        Completed15mBar(bar=value)  # type: ignore[arg-type]


def test_completed_bar_rejects_naive_timestamp_even_if_bar_was_forged() -> None:
    bar = object.__new__(CanonicalBar)
    object.__setattr__(bar, "bar_end", datetime(2026, 1, 5, 2, 15))
    object.__setattr__(bar, "trading_day", SEGMENT_START)

    with pytest.raises(SubingStrategyContractError):
        Completed5mBar(bar=bar)


@pytest.mark.parametrize(
    ("symbol", "contract"),
    (("JM", "JM2605"), ("jm", "jm2605"), ("jm ", "JM2605")),
)
def test_terminal_rejects_non_normalized_symbol_or_contract(
    symbol: str,
    contract: str,
) -> None:
    with pytest.raises(SubingStrategyContractError):
        AuthoritativeSegmentTerminal(
            symbol=symbol,
            contract=contract,
            segment_start_trading_day=SEGMENT_START,
            terminal_bar=_bar(),
        )


def test_terminal_rejects_bar_before_segment_start() -> None:
    with pytest.raises(SubingStrategyContractError):
        AuthoritativeSegmentTerminal(
            symbol="jm",
            contract="JM2605",
            segment_start_trading_day=SEGMENT_START,
            terminal_bar=_bar(trading_day=date(2026, 1, 2)),
        )


def test_step_output_rejects_non_enum_cancellation_kind() -> None:
    cancellation = SubingStrategyPendingCancellation(
        kind="open_long",  # type: ignore[arg-type]
        decision_at=datetime(2026, 1, 5, 2, 15, tzinfo=UTC),
        opportunity_id="subing-opportunity:test",
        reason_code="NEXT_BAR_UNAVAILABLE",
    )
    with pytest.raises(SubingStrategyContractError):
        SubingStrategyStepOutput(
            actions=(),
            cancellations=(cancellation,),
            state_changed=True,
        )


def test_step_output_requires_exact_boolean_state() -> None:
    cancellation = SubingStrategyPendingCancellation(
        kind=SubingStrategyActionKind.OPEN_LONG,
        decision_at=datetime(2026, 1, 5, 2, 15, tzinfo=UTC),
        opportunity_id="subing-opportunity:test",
        reason_code="NEXT_BAR_UNAVAILABLE",
    )
    with pytest.raises(SubingStrategyContractError):
        SubingStrategyStepOutput(
            actions=(),
            cancellations=(cancellation,),
            state_changed=1,  # type: ignore[arg-type]
        )
