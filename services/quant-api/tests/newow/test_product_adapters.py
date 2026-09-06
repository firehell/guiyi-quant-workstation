"""Typed wrappers over the original Newow primitives, without formula mirrors."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

import guiyi_quant.newow.product_adapters as adapters
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.oscillation_channel import (
    OscillationAction,
    OscillationSignal,
    OscillationState,
    OscillationStepResult,
    step_oscillation,
)
from guiyi_quant.newow.product_adapters import replay_strategy
from guiyi_quant.newow.product_contracts import (
    ActionKind,
    ProductBar,
    ProductFrequency,
    TradeEligibility,
)
from guiyi_quant.newow.product_identity import build_segment_id
from guiyi_quant.newow.profile import NEWOW_TREND_D1_PAGE_V2
from guiyi_quant.newow.trend_band import initial_trend_band_state


@pytest.mark.parametrize("strategy", ["trend", "oscillation", "main_rise"])
@pytest.mark.parametrize("frequency", ["1w", "1d", "60m"])
def test_adapter_preserves_every_primitive_prefix_value(
    product_cases, strategy, frequency
):
    case = product_cases.primitive_input(strategy, frequency)
    for end in range(1, len(case.bars) + 1):
        prefix = replace(case, bars=case.bars[:end])
        actual = replay_strategy(prefix.identity, prefix.bars)
        assert actual.main_values == prefix.run_original_primitive().main_values


@pytest.mark.parametrize("strategy", ["trend", "oscillation", "main_rise"])
@pytest.mark.parametrize("frequency", ["1w", "1d", "60m"])
def test_adapter_preserves_direct_primitive_hints_without_quantity_effect(
    product_cases, strategy, frequency
):
    case = product_cases.primitive_input(strategy, frequency)
    replay = replay_strategy(case.identity, case.bars)
    expected = case.run_original_primitive().hint_facts

    assert (
        tuple((hint.bar_end, hint.kind, hint.anchor_price) for hint in replay.hints)
        == expected
    )
    assert all(hint.quantity_effect == "none" for hint in replay.hints)
    assert all(hint.retrospective is False for hint in replay.hints)
    if strategy == "oscillation":
        assert replay.hints == ()
    elif strategy == "main_rise":
        assert {kind.split(":", 1)[0] for _, kind, _ in expected} >= {
            "J",
            "MAGIC11",
            "NEWOW_ESCAPE_D2",
        }


@pytest.mark.parametrize("frequency", ["1w", "1d", "60m"])
def test_main_rise_d456_outputs_remain_non_quantity_hints(product_cases, frequency):
    case = product_cases.primitive_input("main_rise", frequency)
    bars = tuple(
        replace(bar, bar=replace(bar.bar, observation_eligible=True))
        for bar in case.bars[:30]
    )
    replay = replay_strategy(case.identity, bars)

    assert tuple(hint.kind for hint in replay.hints if hint.kind.startswith("D")) == (
        "D5",
    )
    assert all(hint.quantity_effect == "none" for hint in replay.hints)
    assert replay.actions == ()


@pytest.mark.parametrize("strategy", ["trend", "oscillation", "main_rise"])
def test_main_actions_keep_semantic_prices_and_same_segment_references(
    product_cases, strategy
):
    case = product_cases.primitive_input(strategy, "1d")
    replay = replay_strategy(case.identity, case.bars)
    by_id = {action.signal_id: action for action in replay.actions}
    frame_by_end = {frame.bar.bar.bar_end: frame for frame in replay.frames}

    assert {action.kind for action in replay.actions} == {
        ActionKind.BUILD,
        ActionKind.CLEAR,
    }
    for action in replay.actions:
        frame = frame_by_end[action.bar_end]
        if strategy == "trend":
            assert action.reference_price == dict(frame.main_values)["b"]
            assert action.source_marker_id is not None
        elif strategy == "oscillation":
            expected = (
                frame.bar.bar.low
                if action.kind is ActionKind.BUILD
                else frame.bar.bar.high
            )
            assert action.reference_price == expected
            assert action.source_marker_id is None
        else:
            assert action.reference_price == dict(frame.main_values)["ma45"]
            assert action.source_marker_id is None
        assert action.anchor_price == action.reference_price
        if action.kind is ActionKind.CLEAR:
            entry = by_id[action.related_build_id]
            assert entry.kind is ActionKind.BUILD
            assert (entry.identity, entry.physical_contract, entry.segment_id) == (
                action.identity,
                action.physical_contract,
                action.segment_id,
            )


def test_yellow_without_segment_entry_is_hold_and_does_not_manufacture_build(
    product_cases,
):
    case = product_cases.primitive_input("trend", "1d")
    replay = replay_strategy(case.identity, case.bars[:1])

    assert replay.frames[0].main_state == "HOLD"
    assert replay.actions == ()


def test_frequency_replays_do_not_share_recursive_or_pairing_state(product_cases):
    daily = product_cases.primitive_input("oscillation", "1d")
    hourly = product_cases.primitive_input("oscillation", "60m")

    replay_strategy(daily.identity, daily.bars)
    after_daily = replay_strategy(hourly.identity, hourly.bars)
    fresh_hourly = replay_strategy(hourly.identity, hourly.bars)

    assert after_daily == fresh_hourly
    assert all(action.identity.frequency == "60m" for action in after_daily.actions)


def _product_bar(
    index: int,
    values: tuple[str, str, str, str],
    *,
    segment_id: str,
    eligible: bool = True,
    bar_end: datetime | None = None,
) -> ProductBar:
    open_, high, low, close = map(Decimal, values)
    day = date(2026, 5, 4) + timedelta(days=index)
    return ProductBar(
        NewowDailyBar(
            product="rb",
            physical_contract="RB2710",
            segment_id=segment_id,
            trading_day=day,
            bar_end=bar_end
            or datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=7),
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=100,
            open_interest=200,
            source_identity=f"owned:adapter:{segment_id}:{index}",
            observation_eligible=eligible,
            completed=True,
        ),
        ProductFrequency.DAILY,
    )


def _same_bar_oscillation_case(product_cases, *, prewarm: bool = False):
    base = product_cases.primitive_input("oscillation", "1d")
    segment = build_segment_id("rb", "RB2710", datetime(2026, 5, 4, tzinfo=UTC))
    bars = [
        _product_bar(i, ("95", "100", "90", "95"), segment_id=segment) for i in range(9)
    ]
    bars.append(
        _product_bar(
            9,
            ("90", "95", "80", "85"),
            segment_id=segment,
            eligible=not prewarm,
        )
    )
    bars.append(
        _product_bar(
            10,
            ("100", "110", "95" if prewarm else "70", "100"),
            segment_id=segment,
        )
    )
    return replace(base, bars=tuple(bars))


def test_oscillation_keeps_source_clear_then_build_order_on_the_same_bar(product_cases):
    case = _same_bar_oscillation_case(product_cases)
    replay = replay_strategy(case.identity, case.bars)
    actions = replay.frames[-1].actions

    assert [(action.kind, action.sequence) for action in actions] == [
        (ActionKind.CLEAR, 0),
        (ActionKind.BUILD, 1),
    ]
    assert actions[0].related_build_id == replay.frames[-2].actions[0].signal_id
    assert actions[1].related_build_id is None


def test_prewarm_build_witness_classifies_later_clear_without_eligible_entry(
    product_cases,
):
    case = _same_bar_oscillation_case(product_cases, prewarm=True)
    replay = replay_strategy(case.identity, case.bars)
    warmup_build = replay.frames[-2].actions[0]
    clear = replay.frames[-1].actions[0]

    assert warmup_build.kind is ActionKind.BUILD
    assert warmup_build.trade_eligibility is TradeEligibility.WARMUP_ONLY
    assert clear.kind is ActionKind.CLEAR
    assert clear.trade_eligibility is TradeEligibility.NO_ELIGIBLE_ENTRY
    assert clear.related_build_id == warmup_build.signal_id
    assert "NO_ELIGIBLE_ENTRY" in replay.diagnostics


def test_main_rise_requires_a_real_prewarm_build_witness_for_an_isolated_clear(
    product_cases,
):
    case = product_cases.primitive_input("main_rise", "1d")
    all_eligible = tuple(
        replace(bar, bar=replace(bar.bar, observation_eligible=True))
        for bar in case.bars[:50]
    )
    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        replay_strategy(case.identity, all_eligible)

    prewarm_then_clear = tuple(
        replace(bar, bar=replace(bar.bar, observation_eligible=index >= 71))
        for index, bar in enumerate(case.bars[:72])
    )
    replay = replay_strategy(case.identity, prewarm_then_clear)
    warmup_build = replay.frames[58].actions[0]
    clear = replay.frames[71].actions[0]
    assert warmup_build.trade_eligibility is TradeEligibility.WARMUP_ONLY
    assert clear.trade_eligibility is TradeEligibility.NO_ELIGIBLE_ENTRY
    assert clear.related_build_id == warmup_build.signal_id


def test_trend_prewarm_clear_expires_its_build_witness(product_cases, monkeypatch):
    case = product_cases.primitive_input("trend", "1d")
    original = adapters.step_trend_band
    state = initial_trend_band_state()
    build_marker = None
    expired_clear = None
    for product_bar in case.bars[:40]:
        result = original(
            state,
            replace(product_bar.bar, observation_eligible=True),
            profile=NEWOW_TREND_D1_PAGE_V2,
        )
        state = result.state
        if result.marker is not None:
            if result.marker.marker_type == ActionKind.BUILD:
                build_marker = result.marker
            else:
                expired_clear = result.marker
    assert build_marker is not None
    assert expired_clear is not None

    bars = tuple(
        replace(bar, bar=replace(bar.bar, observation_eligible=False))
        for bar in case.bars[:40]
    ) + (case.bars[40],)

    def repeat_expired_clear(state, raw_bar, *, profile):
        result = original(state, raw_bar, profile=profile)
        if raw_bar.bar_end == bars[-1].bar.bar_end:
            return replace(
                result,
                marker=replace(
                    expired_clear,
                    marker_id="expired-clear-replayed",
                    bar_end=raw_bar.bar_end,
                    related_marker_ids=(build_marker.marker_id,),
                ),
            )
        return result

    monkeypatch.setattr(adapters, "step_trend_band", repeat_expired_clear)
    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        replay_strategy(case.identity, bars)


def test_bare_clear_without_a_prewarm_witness_fails_closed(product_cases, monkeypatch):
    case = product_cases.primitive_input("oscillation", "1d")
    bar = case.bars[0]
    original = step_oscillation

    def emit_bare_clear(state, raw_bar):
        result = original(state, raw_bar)
        signal = OscillationSignal(
            OscillationAction.CLEAR,
            raw_bar.high,
            0,
            "owned",
            # A real primitive score object from the unmodified BUILD signal.
            _same_bar_signal_score(product_cases),
        )
        return OscillationStepResult(result.state, result.channel, (signal,))

    monkeypatch.setattr(adapters, "step_oscillation", emit_bare_clear)
    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        replay_strategy(case.identity, (bar,))


def _same_bar_signal_score(product_cases):
    case = _same_bar_oscillation_case(product_cases)
    state = None
    for product_bar in case.bars:
        result = step_oscillation(state or OscillationState(), product_bar.bar)
        state = result.state
    return result.signals[-1].facts


@pytest.mark.parametrize("related_id", ["damaged-related-id", "other-domain-build-id"])
def test_trend_rejects_missing_or_cross_domain_source_related_ids(
    product_cases, monkeypatch, related_id
):
    case = product_cases.primitive_input("trend", "1d")
    original = adapters.step_trend_band

    def corrupt_related(state, raw_bar, *, profile):
        result = original(state, raw_bar, profile=profile)
        if result.marker is not None and result.marker.marker_type == "CLEAR":
            return replace(
                result,
                marker=replace(result.marker, related_marker_ids=(related_id,)),
            )
        return result

    monkeypatch.setattr(adapters, "step_trend_band", corrupt_related)
    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        replay_strategy(case.identity, case.bars)


def test_trend_rejects_a_related_source_marker_from_another_owner_domain(
    product_cases, monkeypatch
):
    case = product_cases.primitive_input("trend", "1d")
    first = case.bars[:40]
    foreign_build_id = next(
        action.source_marker_id
        for _, _, _, actions in replace(case, bars=first)
        .run_original_primitive()
        .main_values
        for action in actions
        if action.kind is ActionKind.BUILD
    )
    assert isinstance(foreign_build_id, str)
    second_segment = build_segment_id("rb", "RB2801", datetime(2026, 8, 1, tzinfo=UTC))
    second = tuple(
        replace(
            bar,
            bar=replace(
                bar.bar,
                physical_contract="RB2801",
                segment_id=second_segment,
                source_identity=f"owned:foreign-owner:{index}",
            ),
        )
        for index, bar in enumerate(first)
    )
    original = adapters.step_trend_band

    def cross_owner_related(state, raw_bar, *, profile):
        result = original(state, raw_bar, profile=profile)
        if (
            raw_bar.segment_id == second_segment
            and result.marker is not None
            and result.marker.marker_type == "CLEAR"
        ):
            return replace(
                result,
                marker=replace(result.marker, related_marker_ids=(foreign_build_id,)),
            )
        return result

    monkeypatch.setattr(adapters, "step_trend_band", cross_owner_related)
    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        replay_strategy(case.identity, first + second)


def test_same_contract_second_owner_segment_resets_state_and_keeps_complete_prefix(
    product_cases,
):
    case = _same_bar_oscillation_case(product_cases)
    first = case.bars[:10]
    second_id = build_segment_id("rb", "RB2710", datetime(2026, 7, 1, tzinfo=UTC))
    # A later owner segment may replay the same contract lifecycle prefix, so its
    # prefix timestamps can repeat or move backwards relative to the prior group.
    second = tuple(
        replace(bar, bar=replace(bar.bar, segment_id=second_id)) for bar in first
    )

    replay = replay_strategy(case.identity, first + second)

    assert tuple(frame.bar.bar.segment_id for frame in replay.frames) == (
        *(bar.bar.segment_id for bar in first),
        *(bar.bar.segment_id for bar in second),
    )
    assert replay.frames[9].actions[0].kind is ActionKind.BUILD
    assert replay.frames[19].actions[0].kind is ActionKind.BUILD
    assert replay.frames[19].actions[0].related_build_id is None


def test_adapter_rejects_out_of_order_bars_inside_one_segment(product_cases):
    case = product_cases.primitive_input("trend", "1d")
    with pytest.raises(ValueError, match="INPUT_ORDER"):
        replay_strategy(case.identity, (case.bars[1], case.bars[0]))


def test_adapter_rejects_formula_or_input_identity_substitution(product_cases):
    case = product_cases.primitive_input("trend", "1d")
    for identity, bars in (
        (replace(case.identity, formula_versions=("substituted",)), case.bars),
        (case.identity, (replace(case.bars[0], frequency="60m"),)),
        (
            case.identity,
            (
                replace(
                    case.bars[0],
                    bar=replace(case.bars[0].bar, product="cu"),
                ),
            ),
        ),
    ):
        with pytest.raises(ValueError, match="IDENTITY"):
            replay_strategy(identity, bars)
