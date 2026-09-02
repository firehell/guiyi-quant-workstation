from __future__ import annotations

from dataclasses import asdict, fields, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.newow.cup_handle import (
    CupBarSnapshot,
    CupHandleStateValue,
    CupMilestoneFact,
    CupPivotTrackerState,
    CupReadyWitness,
    WilderAtrState,
    calculate_cup_handle_series,
    initial_cup_handle_state,
    step_cup_handle,
)
from guiyi_quant.newow.engine import (
    NewowTrendD1Engine,
    NewowTrendD1EngineState,
    calculate_newow_trend_frames,
)
from guiyi_quant.newow.escape_d123 import (
    EscapeState,
    calculate_escape_series,
    initial_escape_state,
    step_escape_d123,
)
from guiyi_quant.newow.models import (
    CupPivot,
    NewowCupHandleOverlay,
    NewowDailyBar,
    NewowMarkerType,
    TrendBandState,
)
from guiyi_quant.newow.trend_band import (
    TrendBandStateValue,
    calculate_trend_band,
    initial_trend_band_state,
    step_trend_band,
)

from .fixtures import (
    bearish_true_cup_handle,
    breakout_then_weakened,
    breakout_volume_not_confirmed,
    bullish_true_cup_handle,
    downtrend_rebound_rejected,
    ready_and_breakout_same_bar,
    ready_then_expired,
    ready_then_invalidated,
    rollover_split_candidate,
)


def _run_incremental(bars: tuple[NewowDailyBar, ...]) -> tuple:
    engine = NewowTrendD1Engine.initial()
    return tuple(engine.step(bar) for bar in bars)


def _bar(index: int, close: int, *, eligible: bool = True) -> NewowDailyBar:
    day = date(2026, 1, 5) + timedelta(days=index)
    price = Decimal(close)
    return NewowDailyBar(
        product="rb",
        physical_contract="RB2701",
        segment_id="rb:RB2701:2026-01-01",
        trading_day=day,
        bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        open=price,
        high=price + Decimal("1"),
        low=price - Decimal("1"),
        close=price,
        volume=100,
        open_interest=200,
        source_identity=f"engine:{index}",
        observation_eligible=eligible,
        completed=True,
    )


_MARKER_FAMILY = {
    NewowMarkerType.BUILD: (0, 0),
    NewowMarkerType.CLEAR: (0, 1),
    NewowMarkerType.ESCAPE_D1: (1, 0),
    NewowMarkerType.ESCAPE_D2: (1, 1),
    NewowMarkerType.ESCAPE_D3: (1, 2),
    NewowMarkerType.CUP_HANDLE_READY: (2, 0),
    NewowMarkerType.CUP_HANDLE_BREAKOUT: (2, 1),
    NewowMarkerType.CUP_HANDLE_WEAKENED: (2, 2),
    NewowMarkerType.CUP_HANDLE_INVALIDATED: (2, 3),
    NewowMarkerType.CUP_HANDLE_EXPIRED: (2, 4),
}


def _expected_markers(trend_marker, escape_markers, cup_markers):
    source = (() if trend_marker is None else (trend_marker,)) + escape_markers + cup_markers
    return tuple(
        sorted(
            source,
            key=lambda marker: (
                _MARKER_FAMILY[marker.marker_type],
                marker.marker_type.value,
                marker.marker_id,
            ),
        )
    )


def _assert_real_kernel_parity(bars: tuple[NewowDailyBar, ...]):
    """Compare every Engine frame/state with a parallel run of the real kernels."""

    engine = NewowTrendD1Engine.initial()
    trend_state = initial_trend_band_state()
    escape_state = initial_escape_state()
    cup_state = initial_cup_handle_state()
    prior_identity = None
    frames = []
    steps = []
    for bar in bars:
        identity = (bar.physical_contract, bar.segment_id)
        rollover = prior_identity is not None and identity != prior_identity
        if rollover:
            trend_state = initial_trend_band_state()
            escape_state = initial_escape_state()
            cup_state = initial_cup_handle_state()
        trend = step_trend_band(trend_state, bar)
        escape = step_escape_d123(escape_state, bar)
        cup = step_cup_handle(cup_state, bar)
        step = engine.step(bar)

        assert step.frame.bar is bar
        assert step.frame.trend_band == trend.point
        assert step.frame.cup_handle == cup.active_overlay
        assert step.frame.diagnostics == cup.diagnostics
        assert step.state.trend_band_state == trend.state
        assert step.state.escape_state == escape.state
        assert step.state.cup_handle_state == cup.state
        assert step.state.last_bar_end == bar.bar_end
        assert step.state.last_trading_day == bar.trading_day
        assert step.state.physical_contract == bar.physical_contract
        assert step.state.segment_id == bar.segment_id
        assert step.state.eligibility_started == (
            cup_state.eligible_started or bar.observation_eligible
        )
        assert step.state.escape_state.previous_rsv9 == escape.rsv9
        assert step.state.escape_state.previous_var4 == escape.var4
        if escape.ma120 is not None:
            assert step.state.escape_state.ma120_values[-1] == escape.ma120
        expected = () if rollover else _expected_markers(
            trend.marker, escape.markers, cup.markers
        )
        assert step.frame.markers == expected
        assert [marker.trigger_facts for marker in step.frame.markers] == [
            marker.trigger_facts for marker in expected
        ]
        assert [_MARKER_FAMILY[marker.marker_type] for marker in step.frame.markers] == sorted(
            _MARKER_FAMILY[marker.marker_type] for marker in step.frame.markers
        )

        trend_state, escape_state, cup_state = trend.state, escape.state, cup.state
        prior_identity = identity
        frames.append(step.frame)
        steps.append(step)
    return tuple(frames), tuple(steps)


def _ohlc_bar(index: int, close: float, high: float, low: float) -> NewowDailyBar:
    close_value = Decimal(str(close))
    return replace(
        _bar(index, int(close_value)),
        open=close_value,
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=close_value,
    )


def _real_d123_sequences() -> tuple[tuple[tuple[NewowDailyBar, ...], NewowMarkerType], ...]:
    high_rsv_history = tuple(_ohlc_bar(index, 100.0, 100.0, 80.0) for index in range(129))
    d3_history = tuple(_ohlc_bar(index, 100.0, 100.0, 80.0) for index in range(120)) + tuple(
        _ohlc_bar(index, 90.0, 100.0, 1.0) for index in range(120, 128)
    )
    return (
        (
            high_rsv_history + (_ohlc_bar(129, 131.0, 150.0, 80.0),),
            NewowMarkerType.ESCAPE_D1,
        ),
        (
            high_rsv_history + (_ohlc_bar(129, 85.0, 120.0, 80.0),),
            NewowMarkerType.ESCAPE_D2,
        ),
        (
            d3_history + (_ohlc_bar(128, 80.0, 100.0, 1.0),),
            NewowMarkerType.ESCAPE_D3,
        ),
    )


def _restore_bar(data: dict[str, object]) -> NewowDailyBar:
    return NewowDailyBar(**data)  # type: ignore[arg-type]


def _restore_pivot(data: dict[str, object] | None) -> CupPivot | None:
    return None if data is None else CupPivot(**data)  # type: ignore[arg-type]


def _restore_snapshot(data: dict[str, object] | None) -> CupBarSnapshot | None:
    if data is None:
        return None
    return CupBarSnapshot(
        bar=_restore_bar(data["bar"]),  # type: ignore[arg-type]
        eligible_index=data["eligible_index"],  # type: ignore[arg-type]
        atr=data["atr"],  # type: ignore[arg-type]
    )


def _restore_ready_witness(data: dict[str, object] | None) -> CupReadyWitness | None:
    if data is None:
        return None
    return CupReadyWitness(
        **{
            **data,
            "left_rim": _restore_pivot(data["left_rim"]),
            "bottom": _restore_pivot(data["bottom"]),
            "right_rim": _restore_pivot(data["right_rim"]),
            "handle_extreme": _restore_pivot(data["handle_extreme"]),
            "score_breakdown": tuple(tuple(item) for item in data["score_breakdown"]),
            "volume_facts": tuple(tuple(item) for item in data["volume_facts"]),
        }
    )  # type: ignore[arg-type]


def _restore_cup_state(data: dict[str, object]) -> CupHandleStateValue:
    tracker = data["pivot_tracker"]
    active = data["active_candidate"]
    return CupHandleStateValue(
        atr_state=WilderAtrState(**data["atr_state"]),  # type: ignore[arg-type]
        pivot_tracker=CupPivotTrackerState(
            leg=tracker["leg"],  # type: ignore[index,arg-type]
            extreme_high=_restore_snapshot(tracker["extreme_high"]),  # type: ignore[index,arg-type]
            extreme_low=_restore_snapshot(tracker["extreme_low"]),  # type: ignore[index,arg-type]
            last_pivot=_restore_pivot(tracker["last_pivot"]),  # type: ignore[index,arg-type]
            eligible_index=tracker["eligible_index"],  # type: ignore[index,arg-type]
        ),
        eligible_bars=tuple(
            _restore_snapshot(item) for item in data["eligible_bars"]  # type: ignore[arg-type]
        ),
        confirmed_pivots=tuple(
            _restore_pivot(item) for item in data["confirmed_pivots"]  # type: ignore[arg-type]
        ),
        active_candidate=(
            None
            if active is None
            else NewowCupHandleOverlay(
                **{
                    **active,
                    "left_rim": _restore_pivot(active["left_rim"]),
                    "bottom": _restore_pivot(active["bottom"]),
                    "right_rim": _restore_pivot(active["right_rim"]),
                    "handle_extreme": _restore_pivot(active["handle_extreme"]),
                    "score_breakdown": dict(active["score_breakdown"]),
                    "volume_facts": dict(active["volume_facts"]),
                }
            )
        ),
        emitted_milestones=tuple(data["emitted_milestones"]),  # type: ignore[arg-type]
        recent_terminal_candidate_ids=tuple(data["recent_terminal_candidate_ids"]),  # type: ignore[arg-type]
        physical_contract=data["physical_contract"],  # type: ignore[arg-type]
        segment_id=data["segment_id"],  # type: ignore[arg-type]
        eligible_started=data["eligible_started"],  # type: ignore[arg-type]
        emitted_milestone_facts=tuple(
            CupMilestoneFact(**item) for item in data["emitted_milestone_facts"]  # type: ignore[arg-type]
        ),
        ready_witness=_restore_ready_witness(data["ready_witness"]),  # type: ignore[arg-type]
    )


def _restore_engine_state_from_dict(data: dict[str, object]) -> NewowTrendD1EngineState:
    return NewowTrendD1EngineState(
        trend_band_state=TrendBandStateValue(**data["trend_band_state"]),  # type: ignore[arg-type]
        escape_state=EscapeState(**data["escape_state"]),  # type: ignore[arg-type]
        cup_handle_state=_restore_cup_state(data["cup_handle_state"]),  # type: ignore[arg-type]
        physical_contract=data["physical_contract"],  # type: ignore[arg-type]
        segment_id=data["segment_id"],  # type: ignore[arg-type]
        last_bar_end=data["last_bar_end"],  # type: ignore[arg-type]
        last_trading_day=data["last_trading_day"],  # type: ignore[arg-type]
        eligibility_started=data["eligibility_started"],  # type: ignore[arg-type]
    )


def test_engine_state_contract_has_exactly_the_approved_eight_fields() -> None:
    """Adding provenance or replay state would make Engine more than an orchestrator."""

    assert tuple(field.name for field in fields(NewowTrendD1EngineState)) == (
        "trend_band_state",
        "escape_state",
        "cup_handle_state",
        "physical_contract",
        "segment_id",
        "last_bar_end",
        "last_trading_day",
        "eligibility_started",
    )


def test_engine_preserves_slice_a_and_cup_same_bar_results() -> None:
    """Replacing a kernel result or its input bar would break exact frame parity."""

    bars = ready_and_breakout_same_bar()
    steps = _run_incremental(bars)
    trend = calculate_trend_band(bars)
    escape = calculate_escape_series(bars)
    cup = calculate_cup_handle_series(bars)

    assert tuple(step.frame.trend_band for step in steps) == trend
    assert tuple(step.frame.cup_handle for step in steps) == tuple(
        result.active_overlay for result in cup
    )
    assert all(step.frame.bar is bar for step, bar in zip(steps, bars, strict=True))
    assert all(
        step.frame.trend_band.bar_end == bar.bar_end
        for step, bar in zip(steps, bars, strict=True)
    )
    assert steps[-1].frame.markers[-2:] == cup[-1].markers
    assert {marker.marker_type for marker in steps[-1].frame.markers}.issuperset(
        {marker.marker_type for marker in escape[-1].markers}
    )


def test_engine_uses_fixed_marker_family_order_including_same_bar_cup_milestones() -> None:
    """Sorting only by global marker priority would put D1/D2/D3 ahead of BUILD/CLEAR."""

    frame = _run_incremental(ready_and_breakout_same_bar())[-1].frame
    cup_types = [
        marker.marker_type
        for marker in frame.markers
        if marker.marker_type
        in {
            NewowMarkerType.CUP_HANDLE_READY,
            NewowMarkerType.CUP_HANDLE_BREAKOUT,
            NewowMarkerType.CUP_HANDLE_WEAKENED,
            NewowMarkerType.CUP_HANDLE_INVALIDATED,
            NewowMarkerType.CUP_HANDLE_EXPIRED,
        }
    ]

    assert cup_types == [
        NewowMarkerType.CUP_HANDLE_READY,
        NewowMarkerType.CUP_HANDLE_BREAKOUT,
    ]
    family = {
        NewowMarkerType.BUILD: 1,
        NewowMarkerType.CLEAR: 1,
        NewowMarkerType.ESCAPE_D1: 2,
        NewowMarkerType.ESCAPE_D2: 2,
        NewowMarkerType.ESCAPE_D3: 2,
        NewowMarkerType.CUP_HANDLE_READY: 3,
        NewowMarkerType.CUP_HANDLE_BREAKOUT: 3,
        NewowMarkerType.CUP_HANDLE_WEAKENED: 3,
        NewowMarkerType.CUP_HANDLE_INVALIDATED: 3,
        NewowMarkerType.CUP_HANDLE_EXPIRED: 3,
    }
    assert [family[marker.marker_type] for marker in frame.markers] == sorted(
        family[marker.marker_type] for marker in frame.markers
    )


def test_rollover_resets_all_substates_and_suppresses_current_bar_markers() -> None:
    """Keeping any prior state across a contract segment can create a false cross-contract signal."""

    bars = rollover_split_candidate()
    steps = _run_incremental(bars)
    rollover_index = next(
        index
        for index, bar in enumerate(bars)
        if index > 0 and bar.physical_contract != bars[index - 1].physical_contract
    )
    step = steps[rollover_index]

    assert step.frame.rollover_started is True
    assert step.frame.markers == ()
    assert step.state.trend_band_state.weighted_window == (
        float(bars[rollover_index].close),
    )
    assert step.state.escape_state.history_count == 1
    assert step.state.cup_handle_state.atr_state.count == 1
    assert step.state.cup_handle_state.confirmed_pivots == ()


def test_engine_rejects_duplicate_out_of_order_trading_day_and_eligibility_regression() -> None:
    """Accepting replayed or regressed observations makes the state non-causal."""

    engine = NewowTrendD1Engine.initial()
    first = _bar(0, 100, eligible=True)
    engine.step(first)

    with pytest.raises(ValueError) as duplicate:
        engine.step(first)
    assert duplicate.value.args == ("NEWOW_BAR_DUPLICATE",)
    with pytest.raises(ValueError) as out_of_order:
        engine.step(replace(first, bar_end=first.bar_end - timedelta(days=1), trading_day=first.trading_day - timedelta(days=1)))
    assert out_of_order.value.args == ("NEWOW_BAR_OUT_OF_ORDER",)
    with pytest.raises(ValueError) as trading_day:
        engine.step(replace(first, bar_end=first.bar_end + timedelta(days=1)))
    assert trading_day.value.args == ("NEWOW_TRADING_DAY_OUT_OF_ORDER",)
    with pytest.raises(ValueError) as eligibility:
        engine.step(_bar(1, 101, eligible=False))
    assert eligibility.value.args == ("NEWOW_OBSERVATION_ELIGIBILITY_REGRESSION",)


def test_duplicate_bar_preflight_wins_before_kernel_arithmetic_and_preserves_state() -> None:
    """A duplicate invocation error must not be hidden by hostile but valid Decimal OHLC."""

    engine = NewowTrendD1Engine.initial()
    first = _bar(0, 100, eligible=True)
    engine.step(first)
    state_before = engine.state
    huge = Decimal("1e1000")
    duplicate = replace(
        first,
        open=huge,
        high=huge,
        low=huge,
        close=huge,
        source_identity="fixture:duplicate:float-overflow",
    )

    with pytest.raises(ValueError) as error:
        engine.step(duplicate)

    assert error.value.args == ("NEWOW_BAR_DUPLICATE",)
    assert engine.state == state_before


def test_false_to_true_is_allowed_but_false_bars_only_warm_cup_atr() -> None:
    """Letting ineligible bars enter cup geometry would manufacture observations before rank-1 eligibility."""

    bars = tuple(_bar(index, 100 + index, eligible=index >= 14) for index in range(16))
    steps = _run_incremental(bars)

    assert all(step.state.cup_handle_state.eligible_bars == () for step in steps[:14])
    assert steps[13].state.cup_handle_state.atr_state.count == 14
    assert steps[14].state.cup_handle_state.eligible_bars[0].eligible_index == 0
    assert steps[14].state.eligibility_started is True


@pytest.mark.parametrize("scenario", ("zero_seed", "nonfinite_update"))
def test_unusable_current_atr_is_cup_only_unavailable_in_engine(
    scenario: str,
) -> None:
    """Zero or non-finite current ATR cannot invalidate the whole Engine frame."""

    flat = tuple(
        replace(
            _bar(index, 100),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
        )
        for index in range(13)
    )
    engine = NewowTrendD1Engine.initial()
    for bar in flat:
        engine.step(bar)
    current = _bar(13, 100)
    if scenario == "zero_seed":
        current = replace(
            current,
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
        )
    else:
        prior = engine.state
        engine = NewowTrendD1Engine(
            state=replace(
                prior,
                cup_handle_state=replace(
                    prior.cup_handle_state,
                    atr_state=replace(
                        prior.cup_handle_state.atr_state,
                        tr_total=1.7e308,
                        previous_close=Decimal("1e308"),
                    ),
                ),
            )
        )

    result = engine.step(current)

    assert result.frame.diagnostics == ("CUP_ATR_UNAVAILABLE",)
    assert "NEWOW_ENGINE_STATE_INVALID" not in result.frame.diagnostics
    assert result.state.physical_contract == current.physical_contract
    assert result.state.last_bar_end == current.bar_end


def test_invalid_restored_substate_fails_closed_to_initial_state() -> None:
    """Continuing from one malformed substate can mix incompatible historical identities."""

    prior = _run_incremental(bullish_true_cup_handle()[:20])[-1].state
    malformed_states = (
        replace(
            prior,
            trend_band_state=replace(
                prior.trend_band_state, weighted_window=(float("nan"),)
            ),
        ),
        replace(prior, escape_state=replace(prior.escape_state, history_count=0)),
        replace(
            prior,
            cup_handle_state=replace(
                prior.cup_handle_state,
                atr_state=replace(prior.cup_handle_state.atr_state, count=-1),
            ),
        ),
        replace(
            prior,
            physical_contract="RB2705",
            segment_id="rb:RB2705:2026-05-01",
        ),
    )

    for malformed in malformed_states:
        engine = NewowTrendD1Engine(state=malformed)
        result = engine.step(bullish_true_cup_handle()[20])

        assert result.frame.trend_band.state is TrendBandState.UNAVAILABLE
        assert result.frame.markers == ()
        assert result.frame.diagnostics == ("NEWOW_ENGINE_STATE_INVALID",)
        assert result.state == NewowTrendD1Engine.initial().state


@pytest.mark.parametrize("substate", ("trend", "escape", "cup"))
def test_rollover_cannot_hide_an_invalid_restored_substate(substate: str) -> None:
    """Identity rollover cannot erase corruption before Engine restore validation."""

    bars = bullish_true_cup_handle()
    prior = _run_incremental(bars[:20])[-1].state
    if substate == "trend":
        malformed = replace(
            prior,
            trend_band_state=replace(
                prior.trend_band_state,
                weighted_window=(float("nan"),),
            ),
        )
    elif substate == "escape":
        malformed = replace(
            prior,
            escape_state=replace(prior.escape_state, history_count=0),
        )
    else:
        malformed = replace(
            prior,
            cup_handle_state=replace(
                prior.cup_handle_state,
                atr_state=replace(prior.cup_handle_state.atr_state, count=-1),
            ),
        )
    incoming = replace(
        bars[20],
        physical_contract="RB2705",
        segment_id="rb:RB2705:2026-05-01",
        source_identity="fixture:rollover:invalid-restored-substate",
    )

    result = NewowTrendD1Engine(state=malformed).step(incoming)

    assert result.frame.trend_band.state is TrendBandState.UNAVAILABLE
    assert result.frame.rollover_started is False
    assert result.frame.markers == ()
    assert result.frame.diagnostics == ("NEWOW_ENGINE_STATE_INVALID",)
    assert result.state == NewowTrendD1Engine.initial().state


@pytest.mark.parametrize(
    "malformation",
    ("engine_mapping", "cup_bars_mapping", "cup_bars_wrong_item"),
)
def test_malformed_restored_state_shape_fails_closed_without_raising(
    malformation: str,
) -> None:
    """Malformed reconstructed mappings must not escape as lookup/type errors."""

    bars = bullish_true_cup_handle()
    prior = _run_incremental(bars[:20])[-1].state
    malformed: object
    if malformation == "engine_mapping":
        malformed = {"cup_handle_state": asdict(prior.cup_handle_state)}
    elif malformation == "cup_bars_mapping":
        malformed = replace(
            prior,
            cup_handle_state=replace(
                prior.cup_handle_state,
                eligible_bars={"unexpected": object()},  # type: ignore[arg-type]
            ),
        )
    else:
        malformed = replace(
            prior,
            cup_handle_state=replace(
                prior.cup_handle_state,
                eligible_bars=(object(),),  # type: ignore[arg-type]
            ),
        )

    result = NewowTrendD1Engine(state=malformed).step(bars[20])  # type: ignore[arg-type]

    assert result.frame.trend_band.state is TrendBandState.UNAVAILABLE
    assert result.frame.markers == ()
    assert result.frame.diagnostics == ("NEWOW_ENGINE_STATE_INVALID",)
    assert result.state == NewowTrendD1Engine.initial().state


def test_engine_fails_closed_when_cup_rejects_observable_restored_facts() -> None:
    """A Cup restore-integrity failure invalidates the whole current Engine frame."""

    bars = bullish_true_cup_handle()
    prior = _run_incremental(bars[:30])[-1].state
    previous_close = prior.cup_handle_state.atr_state.previous_close
    assert previous_close is not None
    malformed = replace(
        prior,
        cup_handle_state=replace(
            prior.cup_handle_state,
            atr_state=replace(
                prior.cup_handle_state.atr_state,
                previous_close=previous_close + Decimal("7"),
            ),
        ),
    )

    result = NewowTrendD1Engine(state=malformed).step(bars[30])

    assert result.frame.trend_band.state is TrendBandState.UNAVAILABLE
    assert result.frame.markers == ()
    assert result.frame.diagnostics == ("NEWOW_ENGINE_STATE_INVALID",)
    assert result.state == NewowTrendD1Engine.initial().state


def test_restore_accepts_independently_valid_same_identity_substates() -> None:
    """Engine must not invent hidden-prefix provenance beyond its eight-field contract."""

    bars = bullish_true_cup_handle()
    current = _run_incremental(bars[:30])[-1].state
    older_trend = _run_incremental(bars[:25])[-1].state.trend_band_state

    result = NewowTrendD1Engine(
        state=replace(current, trend_band_state=older_trend)
    ).step(bars[30])

    assert "NEWOW_ENGINE_STATE_INVALID" not in result.frame.diagnostics
    assert result.state.physical_contract == current.physical_contract
    assert result.state.last_bar_end == bars[30].bar_end


def test_restore_rejects_stale_engine_watermark_visible_in_retained_cup_state() -> None:
    """A retained Cup Bar makes a forged old Engine watermark directly observable."""

    bars = bullish_true_cup_handle()
    current = _run_incremental(bars[:20])[-1].state
    restored = NewowTrendD1Engine(
        state=replace(
            current,
            last_bar_end=bars[10].bar_end,
            last_trading_day=bars[10].trading_day,
        )
    )

    result = restored.step(bars[20])

    assert result.frame.trend_band.state is TrendBandState.UNAVAILABLE
    assert result.frame.markers == ()
    assert result.frame.diagnostics == ("NEWOW_ENGINE_STATE_INVALID",)
    assert result.state == NewowTrendD1Engine.initial().state


@pytest.mark.parametrize("eligible", (False, True))
def test_snapshot_free_typed_and_plain_dict_restore_resume_exactly(eligible: bool) -> None:
    """Eight-field state resumes both pre-eligibility and early-eligible cuts."""

    bars = tuple(_bar(index, 100 + index, eligible=eligible) for index in range(8))
    full_steps = _run_incremental(bars)
    full_frames = tuple(step.frame for step in full_steps)
    for cut in (1, 5):
        state = full_steps[cut - 1].state
        assert state.cup_handle_state.eligible_bars == ()
        assert state.cup_handle_state.atr_state.atr is None
        assert state.eligibility_started is eligible
        assert state.cup_handle_state.eligible_started is eligible
        dataclass_state = NewowTrendD1EngineState(
            trend_band_state=state.trend_band_state,
            escape_state=state.escape_state,
            cup_handle_state=state.cup_handle_state,
            physical_contract=state.physical_contract,
            segment_id=state.segment_id,
            last_bar_end=state.last_bar_end,
            last_trading_day=state.last_trading_day,
            eligibility_started=state.eligibility_started,
        )
        plain_dict_state = _restore_engine_state_from_dict(asdict(state))

        for restored_state in (dataclass_state, plain_dict_state):
            restored = NewowTrendD1Engine(state=restored_state)
            assert tuple(restored.step(bar).frame for bar in bars[cut:]) == full_frames[cut:]
            assert restored.state == full_steps[-1].state


def test_dataclass_and_plain_dict_reconstruction_resume_same_shared_state() -> None:
    """Both explicit dataclass and plain-dict reconstructions preserve a genuine shared cut."""

    bars = bullish_true_cup_handle()
    full = calculate_newow_trend_frames(bars)
    for cut in (1, 5, 14, 20, 45, len(bars) - 1):
        state = _run_incremental(bars[:cut])[-1].state
        dataclass_state = NewowTrendD1EngineState(
            trend_band_state=state.trend_band_state,
            escape_state=state.escape_state,
            cup_handle_state=state.cup_handle_state,
            physical_contract=state.physical_contract,
            segment_id=state.segment_id,
            last_bar_end=state.last_bar_end,
            last_trading_day=state.last_trading_day,
            eligibility_started=state.eligibility_started,
        )
        plain_dict_state = _restore_engine_state_from_dict(asdict(state))

        for restored_state in (dataclass_state, plain_dict_state):
            restored = NewowTrendD1Engine(state=restored_state)
            resumed = tuple(restored.step(bar).frame for bar in bars[cut:])
            assert resumed == full[cut:]


def test_batch_incremental_prefix_restore_and_future_tail_are_invariant() -> None:
    """Recomputing history or restoring at a cut point must not change a completed prefix."""

    bars = bullish_true_cup_handle()
    full = calculate_newow_trend_frames(bars)
    incremental = tuple(result.frame for result in _run_incremental(bars))

    assert incremental == full
    for cut in (1, 14, 45, len(bars) - 1):
        assert calculate_newow_trend_frames(bars[:cut]) == full[:cut]
        state = _run_incremental(bars[:cut])[-1].state
        restored = NewowTrendD1Engine(
            state=NewowTrendD1EngineState(
                trend_band_state=state.trend_band_state,
                escape_state=state.escape_state,
                cup_handle_state=state.cup_handle_state,
                physical_contract=state.physical_contract,
                segment_id=state.segment_id,
                last_bar_end=state.last_bar_end,
                last_trading_day=state.last_trading_day,
                eligibility_started=state.eligibility_started,
            )
        )
        resumed = tuple(restored.step(bar).frame for bar in bars[cut:])
        assert resumed == full[cut:]

    mutated_tail = tuple(
        replace(
            bar,
            close=bar.close + Decimal("20"),
            high=bar.high + Decimal("20"),
            low=bar.low + Decimal("20"),
            open=bar.open + Decimal("20"),
        )
        for bar in bars[40:]
    )
    assert calculate_newow_trend_frames(bars[:40] + mutated_tail)[:40] == full[:40]


def test_real_kernel_harness_matches_all_fields_across_bull_bear_negative_and_rollover() -> None:
    """The Engine must not drift from any real Kernel on positive or negative paths."""

    for bars in (
        bullish_true_cup_handle(),
        bearish_true_cup_handle(),
        downtrend_rebound_rejected(),
        rollover_split_candidate(),
    ):
        frames, steps = _assert_real_kernel_parity(bars)
        assert frames == calculate_newow_trend_frames(bars)
        assert tuple(step.frame for step in _run_incremental(bars)) == frames
        assert tuple(
            tuple(marker.marker_id for marker in frame.markers) for frame in frames
        ) == tuple(
            tuple(marker.marker_id for marker in frame.markers)
            for frame in calculate_newow_trend_frames(bars)
        )
        assert steps[-1].state == _run_incremental(bars)[-1].state


def test_every_prefix_and_genuine_dataclass_plain_dict_restore_matches_full_run() -> None:
    """Every named sequence preserves prefixes, both restore forms, and immutable history."""

    for bars in (
        bullish_true_cup_handle(),
        bearish_true_cup_handle(),
        downtrend_rebound_rejected(),
        rollover_split_candidate(),
    ):
        full, full_steps = _assert_real_kernel_parity(bars)
        assert calculate_newow_trend_frames(bars) == full
        assert tuple(step.frame for step in _run_incremental(bars)) == full
        for cut in range(1, len(bars) + 1):
            assert calculate_newow_trend_frames(bars[:cut]) == full[:cut]
        cut_points = sorted({1, min(5, len(bars) - 1), min(14, len(bars) - 1), len(bars) // 2, len(bars) - 1})
        for cut in cut_points:
            state = _run_incremental(bars[:cut])[-1].state
            dataclass_state = NewowTrendD1EngineState(
                trend_band_state=state.trend_band_state,
                escape_state=state.escape_state,
                cup_handle_state=state.cup_handle_state,
                physical_contract=state.physical_contract,
                segment_id=state.segment_id,
                last_bar_end=state.last_bar_end,
                last_trading_day=state.last_trading_day,
                eligibility_started=state.eligibility_started,
            )
            plain_dict_state = _restore_engine_state_from_dict(asdict(state))
            for restored_state in (dataclass_state, plain_dict_state):
                restored = NewowTrendD1Engine(state=restored_state)
                assert tuple(restored.step(bar).frame for bar in bars[cut:]) == full[cut:]
                assert restored.state == full_steps[-1].state
        mutation_start = len(bars) // 2
        mutated_tail = tuple(
            replace(
                bar,
                open=bar.open + Decimal("20"),
                high=bar.high + Decimal("20"),
                low=bar.low + Decimal("20"),
                close=bar.close + Decimal("20"),
            )
            for bar in bars[mutation_start:]
        )
        assert calculate_newow_trend_frames(bars[:mutation_start] + mutated_tail)[:mutation_start] == full[:mutation_start]


@pytest.mark.parametrize(
    ("bars", "terminal_type"),
    (
        (breakout_then_weakened(), NewowMarkerType.CUP_HANDLE_WEAKENED),
        (ready_then_invalidated(), NewowMarkerType.CUP_HANDLE_INVALIDATED),
        (ready_then_expired(), NewowMarkerType.CUP_HANDLE_EXPIRED),
    ),
)
def test_engine_orders_all_real_cup_terminal_markers(
    bars: tuple[NewowDailyBar, ...], terminal_type: NewowMarkerType
) -> None:
    """Terminal cup facts remain real Kernel facts and preserve family ordering in Engine frames."""

    frames, _ = _assert_real_kernel_parity(bars)
    emitted = [
        marker.marker_type for frame in frames for marker in frame.markers
    ]

    assert NewowMarkerType.CUP_HANDLE_READY in emitted
    assert terminal_type in emitted
    for frame in frames:
        assert [_MARKER_FAMILY[marker.marker_type] for marker in frame.markers] == sorted(
            _MARKER_FAMILY[marker.marker_type] for marker in frame.markers
        )


def test_cup_diagnostic_coexists_with_valid_slice_a_frame() -> None:
    """A rejected cup breakout must not erase an otherwise valid trend-band/D123 result."""

    frames, _ = _assert_real_kernel_parity(breakout_volume_not_confirmed())
    frame = next(
        item for item in frames if "BREAKOUT_VOLUME_UNCONFIRMED" in item.diagnostics
    )

    assert frame.trend_band.state is not TrendBandState.UNAVAILABLE
    assert frame.bar.completed is True


def test_real_kernel_family_coverage_keeps_d123_facts_and_cup_lifecycle_ordered() -> None:
    """Every Engine marker family is exercised by real Kernel output, never a mock marker."""

    observed = set()
    for bars, marker_type in _real_d123_sequences():
        frames, steps = _assert_real_kernel_parity(bars)
        engine_escape = tuple(
            marker
            for frame in frames
            for marker in frame.markers
            if marker.marker_type
            in {
                NewowMarkerType.ESCAPE_D1,
                NewowMarkerType.ESCAPE_D2,
                NewowMarkerType.ESCAPE_D3,
            }
        )

        assert marker_type in {marker.marker_type for marker in engine_escape}
        assert steps[-1].state.escape_state.previous_var4 == engine_escape[-1].trigger_facts["var4"]
        observed.add(marker_type)

    for bars in (
        bearish_true_cup_handle(),
        breakout_then_weakened(),
        ready_then_invalidated(),
        ready_then_expired(),
    ):
        frames, _ = _assert_real_kernel_parity(bars)
        observed.update(
            marker.marker_type for frame in frames for marker in frame.markers
        )

    assert observed.issuperset(
        {
            NewowMarkerType.BUILD,
            NewowMarkerType.CLEAR,
            NewowMarkerType.ESCAPE_D1,
            NewowMarkerType.ESCAPE_D2,
            NewowMarkerType.ESCAPE_D3,
            NewowMarkerType.CUP_HANDLE_READY,
            NewowMarkerType.CUP_HANDLE_BREAKOUT,
            NewowMarkerType.CUP_HANDLE_WEAKENED,
            NewowMarkerType.CUP_HANDLE_INVALIDATED,
            NewowMarkerType.CUP_HANDLE_EXPIRED,
        }
    )
