from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.indicators import ema_series

import app.research.jdj.jdj_context as context_module
from app.market_data.domain import CanonicalBar
from app.research.jdj.jdj_context import (
    JdjBarContext,
    JdjContextError,
    build_jdj_context_series,
)
from app.research.jdj.jdj_policy import load_jdj_policy
from app.research.n_structure.n_structure_policy import load_n_structure_policy
from app.research.n_structure.n_structure_segment import NStructureSegmentTrace
from app.research.n_structure.n_structure_state import (
    NStructureKind,
    NStructureTrace,
)
from app.research.n_structure.n_structure_swing import NSwingPivotKind


_CONTRACT = "JM2701"
_SEGMENT_START = date(2026, 8, 3)
_TRADING_DAY = date(2026, 8, 19)
_NEXT_TRADING_DAY = date(2026, 8, 20)
_M5_START = datetime(2026, 8, 19, 1, 5, tzinfo=UTC)


def _bar(
    bar_end: datetime,
    *,
    high: str,
    low: str,
    close: str | None = None,
    trading_day: date = _TRADING_DAY,
) -> CanonicalBar:
    high_value = Decimal(high)
    low_value = Decimal(low)
    close_value = (
        Decimal(close)
        if close is not None
        else (high_value + low_value) / Decimal(2)
    )
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=trading_day,
        open=close_value,
        high=high_value,
        low=low_value,
        close=close_value,
        volume=Decimal("100"),
        turnover=None,
        open_interest=None,
    )


def _m1_bars(
    start: datetime,
    count: int,
    *,
    trading_day: date = _TRADING_DAY,
) -> tuple[CanonicalBar, ...]:
    return tuple(
        _bar(
            start + timedelta(minutes=index),
            high=str(101 + index),
            low=str(99 + index),
            close=str(100 + index),
            trading_day=trading_day,
        )
        for index in range(count)
    )


def _m5_bars(
    values: tuple[tuple[str, str], ...],
    *,
    start: datetime = _M5_START,
    trading_day: date = _TRADING_DAY,
) -> tuple[CanonicalBar, ...]:
    return tuple(
        _bar(
            start + timedelta(minutes=5 * index),
            high=high,
            low=low,
            trading_day=trading_day,
        )
        for index, (high, low) in enumerate(values)
    )


def _build(
    bars_1m: tuple[CanonicalBar, ...],
    bars_5m: tuple[CanonicalBar, ...],
    **changes: object,
) -> tuple[JdjBarContext, ...]:
    arguments: dict[str, object] = {
        "contract": _CONTRACT,
        "segment_start_trading_day": _SEGMENT_START,
        "segment_end_trading_day": _NEXT_TRADING_DAY,
        "jdj_policy": load_jdj_policy(),
        "n_policy": load_n_structure_policy(),
    }
    arguments.update(changes)
    return build_jdj_context_series(
        bars_1m,
        bars_5m,
        **arguments,  # type: ignore[arg-type]
    )


def _by_time(
    contexts: tuple[JdjBarContext, ...],
) -> dict[datetime, JdjBarContext]:
    return {context.bar.bar_end: context for context in contexts}


def _assert_context_error(call) -> JdjContextError:  # type: ignore[no-untyped-def]
    with pytest.raises(JdjContextError) as captured:
        call()
    error = captured.value
    assert error.code == "JDJ_CONTEXT_INVALID"
    assert str(error) == "JDJ_CONTEXT_INVALID"
    assert error.__cause__ is None
    return error


def test_context_matches_exact_ema20_at_every_boundary() -> None:
    bars_1m = _m1_bars(datetime(2026, 8, 19, 1, 1, tzinfo=UTC), 25)

    contexts = _build(bars_1m, ())
    direct = ema_series(
        [float(bar.close) for bar in bars_1m],
        20,
        bar_ends=[bar.bar_end.isoformat() for bar in bars_1m],
        seed_policy="sma_window",
        indicator_code="ema20",
        round_digits=6,
    )

    assert len(contexts) == len(bars_1m)
    assert tuple(context.bar for context in contexts) == bars_1m
    assert tuple(context.ema20 for context in contexts) == tuple(
        Decimal(str(point.value))
        if point.ready and point.valid and point.value is not None
        else None
        for point in direct.points
    )
    assert all(context.ema20 is None for context in contexts[:19])
    assert contexts[19].ema20 == Decimal("109.5")


def test_snapshot_confirmed_at_0935_is_visible_only_from_0936() -> None:
    bars_1m = _m1_bars(datetime(2026, 8, 19, 1, 16, tzinfo=UTC), 21)
    bars_5m = _m5_bars(
        (("10", "5"), ("11", "6"), ("12", "7")),
        start=datetime(2026, 8, 19, 1, 25, tzinfo=UTC),
    )

    contexts = _by_time(_build(bars_1m, bars_5m))
    at_0935 = contexts[datetime(2026, 8, 19, 1, 35, tzinfo=UTC)]
    at_0936 = contexts[datetime(2026, 8, 19, 1, 36, tzinfo=UTC)]

    assert at_0935.trend_snapshot_observed_at == datetime(
        2026, 8, 19, 1, 30, tzinfo=UTC
    )
    assert at_0936.trend_snapshot_observed_at == datetime(
        2026, 8, 19, 1, 35, tzinfo=UTC
    )


def test_outside_reset_removes_old_epoch_pivot_until_new_epoch_confirms() -> None:
    bars_5m = _m5_bars(
        (
            ("10", "5"),
            ("12", "6"),
            ("14", "7"),
            ("13", "6"),
            ("12", "4"),
            ("15", "3"),
            ("16", "4"),
            ("15", "3"),
            ("14", "2"),
            ("15", "3"),
        )
    )
    bars_1m = _m1_bars(datetime(2026, 8, 19, 1, 4, tzinfo=UTC), 48)

    contexts = _by_time(_build(bars_1m, bars_5m))
    before_reset = contexts[datetime(2026, 8, 19, 1, 26, tzinfo=UTC)]
    after_reset = contexts[datetime(2026, 8, 19, 1, 31, tzinfo=UTC)]
    after_new_pivot = contexts[datetime(2026, 8, 19, 1, 41, tzinfo=UTC)]

    assert before_reset.trend_epoch == 0
    assert before_reset.eligible_high_pivot is not None
    assert before_reset.eligible_high_pivot.epoch == 0
    assert after_reset.trend_epoch == 1
    assert after_reset.eligible_high_pivot is None
    assert after_reset.eligible_low_pivot is None
    assert after_new_pivot.trend_epoch == 1
    assert after_new_pivot.eligible_high_pivot is not None
    assert after_new_pivot.eligible_high_pivot.epoch == 1
    assert after_new_pivot.eligible_high_pivot.kind is NSwingPivotKind.HIGH


def test_latest_same_epoch_pivot_is_selected_deterministically() -> None:
    bars_5m = _m5_bars(
        (
            ("10", "5"),
            ("12", "6"),
            ("11", "5"),
            ("13", "7"),
            ("12", "6"),
        )
    )
    bars_1m = _m1_bars(datetime(2026, 8, 19, 1, 4, tzinfo=UTC), 23)

    context = _by_time(_build(bars_1m, bars_5m))[
        datetime(2026, 8, 19, 1, 26, tzinfo=UTC)
    ]

    assert context.eligible_high_pivot is not None
    assert context.eligible_high_pivot.confirmed_at == datetime(
        2026, 8, 19, 1, 25, tzinfo=UTC
    )
    assert context.eligible_high_pivot.pivot_time == datetime(
        2026, 8, 19, 1, 20, tzinfo=UTC
    )


def test_new_trading_day_does_not_inherit_prior_context() -> None:
    day_one_5m = _m5_bars(
        (("10", "5"), ("11", "6")),
        start=datetime(2026, 8, 19, 1, 0, tzinfo=UTC),
    )
    day_two_5m = _m5_bars(
        (("12", "7"),),
        start=datetime(2026, 8, 20, 1, 0, tzinfo=UTC),
        trading_day=_NEXT_TRADING_DAY,
    )
    bars_1m = (
        *_m1_bars(datetime(2026, 8, 19, 1, 4, tzinfo=UTC), 2),
        *_m1_bars(
            datetime(2026, 8, 20, 1, 0, tzinfo=UTC),
            2,
            trading_day=_NEXT_TRADING_DAY,
        ),
    )

    contexts = _by_time(_build(bars_1m, (*day_one_5m, *day_two_5m)))
    prior_day = contexts[datetime(2026, 8, 19, 1, 5, tzinfo=UTC)]
    first_new_day = contexts[datetime(2026, 8, 20, 1, 0, tzinfo=UTC)]
    second_new_day = contexts[datetime(2026, 8, 20, 1, 1, tzinfo=UTC)]

    assert prior_day.trend_snapshot_observed_at == datetime(
        2026, 8, 19, 1, 0, tzinfo=UTC
    )
    assert first_new_day.trend_kind is NStructureKind.UNDEFINED
    assert first_new_day.trend_snapshot_observed_at is None
    assert first_new_day.trend_epoch is None
    assert first_new_day.eligible_high_pivot is None
    assert first_new_day.eligible_low_pivot is None
    assert second_new_day.trend_snapshot_observed_at == datetime(
        2026, 8, 20, 1, 0, tzinfo=UTC
    )


def test_cross_day_newly_confirmed_pivot_obeys_reset_and_strict_before() -> None:
    bars_5m = (
        *_m5_bars(
            (("10", "5"), ("12", "6")),
            start=datetime(2026, 8, 19, 1, 0, tzinfo=UTC),
        ),
        *_m5_bars(
            (("11", "5"),),
            start=datetime(2026, 8, 20, 1, 0, tzinfo=UTC),
            trading_day=_NEXT_TRADING_DAY,
        ),
    )
    bars_1m = _m1_bars(
        datetime(2026, 8, 20, 1, 0, tzinfo=UTC),
        2,
        trading_day=_NEXT_TRADING_DAY,
    )

    contexts = _by_time(_build(bars_1m, bars_5m))
    first_new_day = contexts[datetime(2026, 8, 20, 1, 0, tzinfo=UTC)]
    second_new_day = contexts[datetime(2026, 8, 20, 1, 1, tzinfo=UTC)]

    assert first_new_day.trend_snapshot_observed_at is None
    assert first_new_day.eligible_high_pivot is None
    assert second_new_day.trend_snapshot_observed_at == datetime(
        2026, 8, 20, 1, 0, tzinfo=UTC
    )
    assert second_new_day.eligible_high_pivot is not None
    assert second_new_day.eligible_high_pivot.pivot_time == datetime(
        2026, 8, 19, 1, 5, tzinfo=UTC
    )
    assert second_new_day.eligible_high_pivot.confirmed_at == datetime(
        2026, 8, 20, 1, 0, tzinfo=UTC
    )


def test_future_m1_and_m5_suffixes_do_not_change_existing_contexts() -> None:
    bars_1m = _m1_bars(datetime(2026, 8, 19, 1, 1, tzinfo=UTC), 50)
    bars_5m = _m5_bars(
        (
            ("10", "5"),
            ("12", "6"),
            ("14", "7"),
            ("13", "6"),
            ("12", "4"),
            ("15", "3"),
            ("16", "4"),
            ("15", "3"),
            ("14", "2"),
            ("15", "3"),
        )
    )

    prefix = _build(bars_1m[:30], bars_5m[:6])
    full = _build(bars_1m, bars_5m)

    assert full[: len(prefix)] == prefix


def test_empty_inputs_are_conservative_and_deterministic() -> None:
    assert _build((), ()) == ()

    bars_1m = _m1_bars(datetime(2026, 8, 19, 1, 1, tzinfo=UTC), 21)
    contexts = _build(bars_1m, ())

    assert all(context.trend_kind is NStructureKind.UNDEFINED for context in contexts)
    assert all(context.trend_snapshot_observed_at is None for context in contexts)
    assert all(context.trend_epoch is None for context in contexts)
    assert contexts[-1].ema20 is not None


def test_n_structure_segment_is_evaluated_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars_1m = _m1_bars(datetime(2026, 8, 19, 1, 1, tzinfo=UTC), 25)
    bars_5m = _m5_bars((("10", "5"), ("12", "6"), ("11", "5")))
    calls = 0
    original = context_module.evaluate_n_structure_segment

    def counted(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(context_module, "evaluate_n_structure_segment", counted)

    contexts = _build(bars_1m, bars_5m)

    assert len(contexts) == len(bars_1m)
    assert calls == 1


@pytest.mark.parametrize(
    "call",
    (
        lambda: _build(
            tuple(
                reversed(
                    _m1_bars(datetime(2026, 8, 19, 1, 1, tzinfo=UTC), 2)
                )
            ),
            (),
        ),
        lambda: _build(
            (),
            (
                _m5_bars((("10", "5"),))[0],
                _m5_bars((("10", "5"),))[0],
            ),
        ),
        lambda: _build((), (), contract="jm2701"),
        lambda: _build(
            (),
            (),
            segment_start_trading_day=_NEXT_TRADING_DAY,
            segment_end_trading_day=_SEGMENT_START,
        ),
        lambda: _build(
            _m1_bars(
                datetime(2026, 8, 22, 1, 1, tzinfo=UTC),
                1,
                trading_day=date(2026, 8, 22),
            ),
            (),
        ),
        lambda: _build(
            (),
            (),
            jdj_policy=replace(load_jdj_policy(), research_only=False),
        ),
        lambda: _build(
            (),
            (),
            n_policy=replace(load_n_structure_policy(), research_only=False),
        ),
    ),
)
def test_invalid_series_identity_and_policy_fail_closed(call) -> None:  # type: ignore[no-untyped-def]
    _assert_context_error(call)


def test_impossible_snapshot_time_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars_1m = _m1_bars(datetime(2026, 8, 19, 1, 1, tzinfo=UTC), 10)
    bars_5m = _m5_bars((("10", "5"), ("12", "6")))
    exact = context_module.evaluate_n_structure_segment(
        bars_5m,
        contract=_CONTRACT,
        segment_start_trading_day=_SEGMENT_START,
        segment_end_trading_day=_NEXT_TRADING_DAY,
        policy=load_n_structure_policy(),
    )
    impossible_snapshot = replace(
        exact.structures.snapshots[0],
        observed_at=exact.structures.snapshots[0].observed_at + timedelta(minutes=1),
    )
    impossible = NStructureSegmentTrace(
        swings=exact.swings,
        patterns=exact.patterns,
        structures=NStructureTrace(
            snapshots=(impossible_snapshot, *exact.structures.snapshots[1:]),
            transitions=exact.structures.transitions,
        ),
    )
    monkeypatch.setattr(
        context_module,
        "evaluate_n_structure_segment",
        lambda *_args, **_kwargs: impossible,
    )

    _assert_context_error(lambda: _build(bars_1m, bars_5m))


def test_impossible_pivot_identity_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars_1m = _m1_bars(datetime(2026, 8, 19, 1, 1, tzinfo=UTC), 20)
    bars_5m = _m5_bars((("10", "5"), ("12", "6"), ("11", "5")))
    policy = load_n_structure_policy()
    exact = context_module.evaluate_n_structure_segment(
        bars_5m,
        contract=_CONTRACT,
        segment_start_trading_day=_SEGMENT_START,
        segment_end_trading_day=_NEXT_TRADING_DAY,
        policy=policy,
    )
    other = context_module.evaluate_n_structure_segment(
        bars_5m,
        contract="JM2705",
        segment_start_trading_day=_SEGMENT_START,
        segment_end_trading_day=_NEXT_TRADING_DAY,
        policy=policy,
    )
    assert other.swings.pivots
    impossible = replace(
        exact,
        swings=replace(exact.swings, pivots=other.swings.pivots),
    )
    monkeypatch.setattr(
        context_module,
        "evaluate_n_structure_segment",
        lambda *_args, **_kwargs: impossible,
    )

    _assert_context_error(lambda: _build(bars_1m, bars_5m))


def test_unexpected_programming_error_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> NStructureSegmentTrace:
        raise RuntimeError("programming failure")

    monkeypatch.setattr(context_module, "evaluate_n_structure_segment", fail)

    with pytest.raises(RuntimeError, match="programming failure"):
        _build((), ())


def test_context_value_object_is_frozen_and_rejects_impossible_identity() -> None:
    bar = _m1_bars(datetime(2026, 8, 19, 1, 1, tzinfo=UTC), 1)[0]
    context = JdjBarContext(
        bar=bar,
        ema20=None,
        trend_kind=NStructureKind.UNDEFINED,
        trend_snapshot_observed_at=None,
        trend_epoch=None,
        eligible_high_pivot=None,
        eligible_low_pivot=None,
    )

    with pytest.raises(FrozenInstanceError):
        context.trend_epoch = 1  # type: ignore[misc]
    with pytest.raises(JdjContextError):
        replace(context, ema20=Decimal("NaN"))
    with pytest.raises(JdjContextError):
        replace(
            context,
            trend_snapshot_observed_at=bar.bar_end,
            trend_epoch=None,
        )
