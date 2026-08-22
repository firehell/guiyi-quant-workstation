from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.market_data.domain import BarFrequency, CanonicalBar
from app.research.n_structure.n_structure_swing import (
    NSwingLeg,
    NSwingPivot,
    NSwingPivotKind,
    reduce_n_swings,
)


_CONTRACT = "JM2701"
_SEGMENT_START = date(2026, 8, 3)
_SEGMENT_END = date(2026, 8, 20)
_TRADING_DAY = date(2026, 8, 19)
_START = datetime(2026, 8, 19, 1, 5, tzinfo=UTC)


def _bar(
    index: int,
    *,
    high: str,
    low: str,
    trading_day: date = _TRADING_DAY,
) -> CanonicalBar:
    high_value = Decimal(high)
    low_value = Decimal(low)
    midpoint = (high_value + low_value) / Decimal(2)
    return CanonicalBar(
        bar_end=_START + timedelta(minutes=5 * index),
        trading_day=trading_day,
        open=midpoint,
        high=high_value,
        low=low_value,
        close=midpoint,
        volume=Decimal("100"),
        turnover=None,
        open_interest=None,
    )


def _reduce(
    bars: tuple[CanonicalBar, ...],
    *,
    source_timeframe: BarFrequency = BarFrequency.M5,
    contract: str = _CONTRACT,
    segment_start_trading_day: date = _SEGMENT_START,
    segment_end_trading_day: date = _SEGMENT_END,
):
    return reduce_n_swings(
        bars,
        source_timeframe=source_timeframe,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        segment_end_trading_day=segment_end_trading_day,
    )


def _valid_pivot() -> NSwingPivot:
    return NSwingPivot(
        pivot_id=(
            "JM2701:2026-08-03:5m:0:high:"
            "2026-08-19T01:05:00+00:00"
        ),
        epoch=0,
        kind=NSwingPivotKind.HIGH,
        source_timeframe=BarFrequency.M5,
        pivot_time=_START,
        confirmed_at=_START + timedelta(minutes=5),
        price=Decimal("100.5"),
        contract=_CONTRACT,
        segment_start_trading_day=_SEGMENT_START,
    )


@pytest.mark.parametrize(
    ("changes"),
    (
        {
            "pivot_id": (
                "JM2701:2026-08-03:5m:-1:high:"
                "2026-08-19T01:05:00+00:00"
            ),
            "epoch": -1,
        },
        {
            "pivot_id": (
                "JM2701:2026-08-03:5m:True:high:"
                "2026-08-19T01:05:00+00:00"
            ),
            "epoch": True,
        },
        {
            "pivot_id": (
                "JM2701:2026-08-03:15m:0:high:"
                "2026-08-19T01:05:00+00:00"
            ),
            "source_timeframe": BarFrequency.M15,
        },
        {"pivot_time": datetime(2026, 8, 19, 1, 5)},
        {"confirmed_at": datetime(2026, 8, 19, 1, 10)},
        {"price": Decimal("0")},
        {"price": Decimal("-1")},
        {"price": Decimal("NaN")},
        {"price": Decimal("Infinity")},
        {"price": 100},
        {
            "pivot_id": (
                "jm2701:2026-08-03:5m:0:high:"
                "2026-08-19T01:05:00+00:00"
            ),
            "contract": "jm2701",
        },
        {
            "pivot_id": (
                " JM2701 :2026-08-03:5m:0:high:"
                "2026-08-19T01:05:00+00:00"
            ),
            "contract": " JM2701 ",
        },
        {
            "pivot_id": (
                "JM2713:2026-08-03:5m:0:high:"
                "2026-08-19T01:05:00+00:00"
            ),
            "contract": "JM2713",
        },
        {
            "pivot_id": (
                "JM2701:2026-08-03T00:00:00+00:00:5m:0:high:"
                "2026-08-19T01:05:00+00:00"
            ),
            "segment_start_trading_day": datetime(2026, 8, 3, tzinfo=UTC),
        },
    ),
)
def test_pivot_requires_m5_aware_positive_decimal_and_epoch(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="N_STRUCTURE_CONTRACT_INVALID") as captured:
        replace(_valid_pivot(), **changes)

    assert getattr(captured.value, "code", None) == "N_STRUCTURE_CONTRACT_INVALID"
    assert str(captured.value) == "N_STRUCTURE_CONTRACT_INVALID"


@pytest.mark.parametrize(
    ("pivot_time", "confirmed_at"),
    (
        (_START, _START),
        (_START + timedelta(minutes=5), _START),
    ),
)
def test_pivot_time_must_strictly_precede_confirmation(
    pivot_time: datetime,
    confirmed_at: datetime,
) -> None:
    with pytest.raises(ValueError, match="N_STRUCTURE_CONTRACT_INVALID"):
        replace(
            _valid_pivot(),
            pivot_id=(
                f"JM2701:2026-08-03:5m:0:high:"
                f"{pivot_time.astimezone(UTC).isoformat()}"
            ),
            pivot_time=pivot_time,
            confirmed_at=confirmed_at,
        )


def test_pivot_requires_canonical_id_including_epoch() -> None:
    with pytest.raises(ValueError, match="N_STRUCTURE_CONTRACT_INVALID"):
        replace(
            _valid_pivot(),
            pivot_id=(
                "JM2701:2026-08-03:5m:high:"
                "2026-08-19T01:05:00+00:00"
            ),
        )

    epoch_one = replace(
        _valid_pivot(),
        pivot_id=(
            "JM2701:2026-08-03:5m:1:high:"
            "2026-08-19T01:05:00+00:00"
        ),
        epoch=1,
    )
    assert epoch_one.epoch == 1


def test_pivot_normalizes_aware_times_to_utc_and_is_frozen() -> None:
    beijing = timezone(timedelta(hours=8))
    pivot = NSwingPivot(
        pivot_id=(
            "JM2701:2026-08-03:5m:0:high:"
            "2026-08-19T01:05:00+00:00"
        ),
        epoch=0,
        kind=NSwingPivotKind.HIGH,
        source_timeframe=BarFrequency.M5,
        pivot_time=datetime(2026, 8, 19, 9, 5, tzinfo=beijing),
        confirmed_at=datetime(2026, 8, 19, 9, 10, tzinfo=beijing),
        price=Decimal("100.5"),
        contract=_CONTRACT,
        segment_start_trading_day=_SEGMENT_START,
    )

    assert pivot.pivot_time == _START
    assert pivot.confirmed_at == _START + timedelta(minutes=5)
    with pytest.raises(FrozenInstanceError):
        pivot.epoch = 2  # type: ignore[misc]


def test_golden_previous_bar_direction_changes_confirm_exact_extremes() -> None:
    bars = (
        _bar(0, high="10", low="5"),
        _bar(1, high="12", low="6"),
        _bar(2, high="14", low="7"),
        _bar(3, high="13", low="6"),
        _bar(4, high="12", low="4"),
        _bar(5, high="13", low="5"),
    )

    trace = _reduce(bars)

    assert trace.final_leg is NSwingLeg.UP
    assert tuple(pivot.kind for pivot in trace.pivots) == (
        NSwingPivotKind.HIGH,
        NSwingPivotKind.LOW,
    )
    assert tuple(pivot.pivot_time for pivot in trace.pivots) == (
        bars[2].bar_end,
        bars[4].bar_end,
    )
    assert tuple(pivot.confirmed_at for pivot in trace.pivots) == (
        bars[3].bar_end,
        bars[5].bar_end,
    )
    assert tuple(pivot.price for pivot in trace.pivots) == (
        Decimal("14"),
        Decimal("4"),
    )
    assert tuple(pivot.epoch for pivot in trace.pivots) == (0, 0)
    assert trace.ambiguous_outside_reset_at == ()


def test_equal_extreme_keeps_first_pivot_time() -> None:
    bars = (
        _bar(0, high="10", low="5"),
        _bar(1, high="12", low="6"),
        _bar(2, high="12", low="7"),
        _bar(3, high="11", low="5"),
    )

    trace = _reduce(bars)

    assert len(trace.pivots) == 1
    assert trace.pivots[0].kind is NSwingPivotKind.HIGH
    assert trace.pivots[0].pivot_time == bars[1].bar_end
    assert trace.pivots[0].price == Decimal("12")
    assert trace.pivots[0].confirmed_at == bars[3].bar_end


def test_inside_bar_does_not_reverse() -> None:
    bars = (
        _bar(0, high="10", low="5"),
        _bar(1, high="12", low="6"),
        _bar(2, high="11", low="7"),
        _bar(3, high="10", low="5"),
    )

    before_reversal = _reduce(bars[:3])
    after_reversal = _reduce(bars)

    assert before_reversal.final_leg is NSwingLeg.UP
    assert before_reversal.pivots == ()
    assert after_reversal.final_leg is NSwingLeg.DOWN
    assert len(after_reversal.pivots) == 1
    assert after_reversal.pivots[0].pivot_time == bars[1].bar_end
    assert after_reversal.pivots[0].confirmed_at == bars[3].bar_end


def test_outside_bar_increments_epoch_and_emits_no_pivot() -> None:
    bars = (
        _bar(0, high="10", low="5"),
        _bar(1, high="12", low="6"),
        _bar(2, high="13", low="4"),
        _bar(3, high="14", low="5"),
        _bar(4, high="13", low="4"),
    )

    at_reset = _reduce(bars[:3])
    trace = _reduce(bars)

    assert at_reset.pivots == ()
    assert at_reset.ambiguous_outside_reset_at == (bars[2].bar_end,)
    assert at_reset.final_epoch == 1
    assert at_reset.final_leg is NSwingLeg.UNRESOLVED
    assert len(trace.pivots) == 1
    assert trace.pivots[0].epoch == 1
    assert trace.pivots[0].pivot_time == bars[3].bar_end
    assert trace.pivots[0].confirmed_at == bars[4].bar_end


def test_same_contract_segment_may_confirm_across_trading_day() -> None:
    next_trading_day = date(2026, 8, 20)
    bars = (
        _bar(0, high="10", low="5"),
        _bar(1, high="12", low="6"),
        _bar(2, high="11", low="5", trading_day=next_trading_day),
    )

    trace = _reduce(bars)

    assert len(trace.pivots) == 1
    assert trace.pivots[0].pivot_time == bars[1].bar_end
    assert trace.pivots[0].confirmed_at == bars[2].bar_end
    assert trace.final_epoch == 0


@pytest.mark.parametrize(
    "trading_day",
    (_SEGMENT_START - timedelta(days=1), _SEGMENT_END + timedelta(days=1)),
)
def test_bar_outside_supplied_segment_fails_closed(trading_day: date) -> None:
    bars = (_bar(0, high="10", low="5", trading_day=trading_day),)

    with pytest.raises(ValueError, match="N_STRUCTURE_SERIES_INVALID") as captured:
        _reduce(bars)

    assert getattr(captured.value, "code", None) == "N_STRUCTURE_SERIES_INVALID"
    assert str(captured.value) == "N_STRUCTURE_SERIES_INVALID"


def test_unsorted_or_duplicate_bars_fail_closed() -> None:
    b0 = _bar(0, high="10", low="5")
    b1 = _bar(1, high="12", low="6")

    for bars in ((b1, b0), (b0, b0)):
        with pytest.raises(ValueError, match="N_STRUCTURE_SERIES_INVALID"):
            _reduce(bars)


@pytest.mark.parametrize(
    "changes",
    (
        {"source_timeframe": BarFrequency.M15},
        {"contract": "jm2701"},
        {"contract": " JM2701 "},
        {"contract": "JM2713"},
        {"segment_start_trading_day": date(2026, 8, 21)},
        {"segment_start_trading_day": datetime(2026, 8, 3, tzinfo=UTC)},
        {"segment_end_trading_day": datetime(2026, 8, 20, tzinfo=UTC)},
    ),
)
def test_reducer_rejects_invalid_series_identity(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="N_STRUCTURE_SERIES_INVALID"):
        _reduce((), **changes)  # type: ignore[arg-type]


def test_empty_and_single_bar_prefixes_are_unresolved() -> None:
    empty = _reduce(())
    single = _reduce((_bar(0, high="10", low="5"),))

    assert empty.pivots == single.pivots == ()
    assert empty.ambiguous_outside_reset_at == ()
    assert single.ambiguous_outside_reset_at == ()
    assert empty.final_epoch == single.final_epoch == 0
    assert empty.final_leg is NSwingLeg.UNRESOLVED
    assert single.final_leg is NSwingLeg.UNRESOLVED
    assert empty.contract == single.contract == _CONTRACT
    assert empty.segment_start_trading_day == _SEGMENT_START


def test_reducer_is_prefix_invariant_for_confirmed_facts() -> None:
    bars = (
        _bar(0, high="10", low="5"),
        _bar(1, high="12", low="6"),
        _bar(2, high="14", low="7"),
        _bar(3, high="13", low="6"),
        _bar(4, high="12", low="4"),
        _bar(5, high="15", low="3"),  # outside: epoch barrier
        _bar(6, high="16", low="4"),
        _bar(7, high="15", low="3"),
        _bar(8, high="14", low="2"),
        _bar(9, high="15", low="3"),
    )
    full = _reduce(bars)

    for length in range(2, len(bars) + 1):
        prefix = _reduce(bars[:length])
        boundary = bars[length - 1].bar_end
        assert prefix.pivots == tuple(
            pivot for pivot in full.pivots if pivot.confirmed_at <= boundary
        )
        assert prefix.ambiguous_outside_reset_at == tuple(
            reset_at
            for reset_at in full.ambiguous_outside_reset_at
            if reset_at <= boundary
        )
        assert prefix.final_epoch == len(prefix.ambiguous_outside_reset_at)
