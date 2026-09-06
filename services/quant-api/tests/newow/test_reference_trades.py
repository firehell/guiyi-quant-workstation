"""Pure BUILD/CLEAR reference projection over owned product facts."""

from copy import copy
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from guiyi_quant.newow.product_contracts import StrategyHint, TradeEligibility
from guiyi_quant.newow.reference_trades import ReferenceTradeProjector


def _forged_actions(replay, actions):
    """Bypass upstream validation to exercise the projector's trust boundary."""
    forged = copy(replay)
    object.__setattr__(forged, "actions", tuple(actions))
    return forged


def test_closed_trade_covers_the_reference_contract_and_uses_action_prices(
    product_cases,
):
    case = product_cases.closed(entry="100", exit="110")

    result = ReferenceTradeProjector().project(
        case.replay, case.boundaries, case.as_of
    )

    assert result.as_of == case.as_of
    assert result.bar_level_hints == ()
    assert result.unassigned_hints == ()
    assert result.diagnostics == ()
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.reference_trade_id
    assert trade.product == "rb"
    assert trade.strategy_code == "trend"
    assert trade.frequency == "1d"
    assert trade.physical_contract == "RB2605"
    assert trade.segment_id == case.entry.segment_id
    assert trade.formula_versions == ("newow_trend_band_page_v2",)
    assert trade.reference_model_version == "newow_marker_reference_zero_cost_v1"
    assert trade.futures_adaptation_version == "newow_futures_segment_interrupt_v1"
    assert trade.entry_signal_id == case.entry.signal_id
    assert trade.entry_bar_end == case.entry.bar_end
    assert trade.entry_reference_price == Decimal("100")
    assert trade.exit_signal_id == case.exit.signal_id
    assert trade.exit_bar_end == case.exit.bar_end
    assert trade.exit_reference_price == Decimal("110")
    assert trade.status == "CLOSED"
    assert trade.holding_bars == 1
    assert trade.reference_return_pct == Decimal("10")
    assert trade.mark_bar_end is None
    assert trade.mark_reference_price is None
    assert trade.mark_change_pct is None
    assert trade.interrupted_at is None
    assert trade.interruption_reason is None
    assert trade.statistics_membership is None
    assert trade.hint_ids == ()


def test_open_trade_has_no_manufactured_exit_or_realized_return(product_cases):
    case = product_cases.open()

    trade = ReferenceTradeProjector().project(
        case.replay, case.boundaries, case.as_of
    ).trades[0]

    assert trade.status == "OPEN"
    assert trade.exit_signal_id is None
    assert trade.exit_bar_end is None
    assert trade.exit_reference_price is None
    assert trade.reference_return_pct is None
    assert trade.holding_bars == 1


def test_holding_bars_counts_effective_frequency_intervals_not_calendar_days(
    product_cases,
):
    case = product_cases.closed()
    exit_end = datetime(2026, 1, 30, 7, tzinfo=UTC)
    exit_bar = replace(
        case.bars[1],
        bar=replace(
            case.bars[1].bar,
            trading_day=date(2026, 1, 30),
            bar_end=exit_end,
            source_identity="owned:sparse-daily-exit",
        ),
    )
    clear = product_cases.action(
        case.identity,
        exit_bar,
        "CLEAR",
        "110",
        related_build_id=case.entry.signal_id,
    )
    replay = product_cases.replay(
        case.identity,
        (case.bars[0], exit_bar),
        (case.entry, clear),
        ("BUILD", "CLEAR"),
    )

    trade = ReferenceTradeProjector().project(
        replay, (), datetime(2026, 2, 1, tzinfo=UTC)
    ).trades[0]

    assert trade.holding_bars == 1


def test_pairing_closes_then_rebuilds_on_the_same_bar(product_cases):
    case = product_cases.same_bar_rebuild()

    result = ReferenceTradeProjector().project(
        case.replay, case.boundaries, case.as_of
    )

    assert [trade.status for trade in result.trades] == ["CLOSED", "OPEN"]
    assert result.trades[0].exit_signal_id != result.trades[1].entry_signal_id
    assert result.trades[0].exit_bar_end == result.trades[1].entry_bar_end
    assert result.trades[0].reference_trade_id != result.trades[1].reference_trade_id


def test_same_action_id_and_content_is_idempotent_but_changed_content_fails(
    product_cases,
):
    case = product_cases.closed()
    projector = ReferenceTradeProjector()
    duplicated = _forged_actions(
        case.replay, (case.entry, case.entry, case.exit, case.exit)
    )

    assert projector.project(duplicated, (), case.as_of) == projector.project(
        case.replay, (), case.as_of
    )

    conflicting_entry = replace(case.entry, reference_price=Decimal("101"))
    conflict = _forged_actions(case.replay, (case.entry, conflicting_entry, case.exit))
    with pytest.raises(ValueError, match="ID_CONTENT_CONFLICT"):
        projector.project(conflict, (), case.as_of)


def test_warmup_build_witnesses_do_not_fabricate_a_trade(product_cases):
    case = product_cases.warmup_only_build()
    second_witness = replace(case.entry, sequence=1)
    frames = (
        replace(case.replay.frames[0], actions=(case.entry, second_witness)),
        case.replay.frames[1],
    )
    replay = replace(
        case.replay,
        frames=frames,
        actions=(case.entry, second_witness, case.exit),
    )

    result = ReferenceTradeProjector().project(replay, (), case.as_of)

    assert result.trades == ()
    assert result.diagnostics == ("NO_ELIGIBLE_ENTRY",)


def test_no_eligible_entry_requires_the_exact_same_segment_warmup_witness(
    product_cases,
):
    case = product_cases.warmup_only_build()
    damaged = replace(case.exit, related_build_id="missing-warmup-build")
    replay = product_cases.replay(
        case.identity,
        case.bars,
        (case.entry, damaged),
        ("BUILD", "CLEAR"),
    )

    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        ReferenceTradeProjector().project(replay, (), case.as_of)


def test_repeated_eligible_build_is_not_treated_as_adding_to_a_trade(product_cases):
    case = product_cases.closed()
    repeated_build = product_cases.action(
        case.identity, case.bars[1], "BUILD", "110"
    )
    replay = product_cases.replay(
        case.identity,
        case.bars,
        (case.entry, repeated_build),
        ("BUILD", "BUILD"),
    )

    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        ReferenceTradeProjector().project(replay, (), case.as_of)


@pytest.mark.parametrize("relation", [None, "damaged-related-id"])
def test_clear_without_the_current_explicit_build_reference_fails_closed(
    product_cases, relation
):
    case = product_cases.closed()
    clear = replace(case.exit, related_build_id=relation)
    replay = product_cases.replay(
        case.identity,
        case.bars,
        (case.entry, clear),
        ("BUILD", "CLEAR"),
    )

    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        ReferenceTradeProjector().project(replay, (), case.as_of)


def test_cross_strategy_frequency_contract_or_segment_reference_fails_closed(
    product_cases,
):
    case = product_cases.closed()
    foreign_cases = (
        product_cases.closed(strategy="main_rise"),
        product_cases.closed(frequency="60m"),
    )
    for foreign in foreign_cases:
        clear = replace(case.exit, related_build_id=foreign.entry.signal_id)
        replay = product_cases.replay(
            case.identity,
            case.bars,
            (case.entry, clear),
            ("BUILD", "CLEAR"),
        )
        with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
            ReferenceTradeProjector().project(replay, (), case.as_of)

    other_segment_entry = replace(
        case.entry, segment_id=f"{case.entry.segment_id}:other"
    )
    for foreign_id in (
        other_segment_entry.signal_id,
        replace(case.entry, physical_contract="RB2610").signal_id,
    ):
        clear = replace(case.exit, related_build_id=foreign_id)
        replay = product_cases.replay(
            case.identity,
            case.bars,
            (case.entry, clear),
            ("BUILD", "CLEAR"),
        )
        with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
            ReferenceTradeProjector().project(replay, (), case.as_of)


def test_projection_validates_segment_local_input_order_without_global_sorting(
    product_cases,
):
    case = product_cases.closed()
    reversed_replay = _forged_actions(case.replay, tuple(reversed(case.replay.actions)))
    with pytest.raises(ValueError, match="INPUT_ORDER"):
        ReferenceTradeProjector().project(reversed_replay, (), case.as_of)

    daily = product_cases.closed()
    hourly = product_cases.closed(frequency="60m")
    second_bar = replace(
        daily.bars[0],
        bar=replace(
            daily.bars[0].bar,
            segment_id=f"{daily.entry.segment_id}:second-owner",
            bar_end=hourly.entry.bar_end,
            trading_day=hourly.entry.trading_day,
            source_identity="owned:second-owner-prefix",
        ),
    )
    second_entry = product_cases.action(
        daily.identity, second_bar, "BUILD", "100"
    )
    second_frame = replace(
        daily.replay.frames[0], bar=second_bar, actions=(second_entry,)
    )
    reset = replace(
        daily.replay,
        frames=(daily.replay.frames[0], second_frame),
        actions=(daily.entry, second_entry),
    )
    result = ReferenceTradeProjector().project(reset, (), daily.as_of)
    assert [trade.status for trade in result.trades] == ["OPEN", "OPEN"]


def test_actions_after_as_of_do_not_change_the_earlier_projection(product_cases):
    case = product_cases.closed()
    as_of = case.entry.bar_end

    trade = ReferenceTradeProjector().project(case.replay, (), as_of).trades[0]

    assert trade.status == "OPEN"
    assert trade.exit_signal_id is None
    assert trade.holding_bars == 0


@pytest.mark.parametrize("strategy", ["trend", "oscillation", "main_rise"])
@pytest.mark.parametrize("frequency", ["1w", "1d", "60m"])
def test_all_nine_strategy_frequency_identities_stay_isolated(
    product_cases, strategy, frequency
):
    case = product_cases.closed(strategy=strategy, frequency=frequency)

    trade = ReferenceTradeProjector().project(case.replay, (), case.as_of).trades[0]

    assert (trade.strategy_code, trade.frequency, trade.formula_versions) == (
        strategy,
        frequency,
        case.identity.formula_versions,
    )
    assert trade.entry_signal_id == case.entry.signal_id


def test_non_finite_prices_and_a_naked_hint_are_rejected_at_the_boundary(
    product_cases,
):
    case = product_cases.closed()
    invalid_entry = copy(case.entry)
    object.__setattr__(invalid_entry, "reference_price", Decimal("NaN"))
    replay = _forged_actions(case.replay, (invalid_entry, case.exit))
    with pytest.raises(ValueError, match="INVALID_PRICE"):
        ReferenceTradeProjector().project(replay, (), case.as_of)

    hint = StrategyHint(
        identity=case.identity,
        physical_contract=case.entry.physical_contract,
        segment_id=case.entry.segment_id,
        bar_end=case.entry.bar_end,
        trading_day=case.entry.trading_day,
        kind="D1",
        known_at=case.entry.bar_end,
    )
    with pytest.raises(ValueError, match="INVALID_REPLAY"):
        ReferenceTradeProjector().project(hint, (), case.as_of)


def test_no_eligible_entry_value_cannot_be_used_on_a_build(product_cases):
    case = product_cases.closed()
    invalid = replace(
        case.entry, trade_eligibility=TradeEligibility.NO_ELIGIBLE_ENTRY
    )
    replay = _forged_actions(case.replay, (invalid,))

    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        ReferenceTradeProjector().project(replay, (), case.as_of)
