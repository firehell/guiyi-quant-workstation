"""Rollover interruption and explanatory-hint ownership over owned facts."""

from copy import copy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.newow.product_contracts import (
    OwnerBoundary,
    ProductBar,
    StrategyHint,
)
from guiyi_quant.newow.product_identity import build_segment_id
from guiyi_quant.newow.reference_trades import ReferenceTradeProjector


def _boundary(case, *, effective_at=None):
    effective_at = effective_at or datetime(2026, 1, 7, tzinfo=UTC)
    return OwnerBoundary(
        product=case.identity.product,
        old_contract=case.entry.physical_contract,
        new_contract="RB2610",
        old_segment_id=case.entry.segment_id,
        new_segment_id=build_segment_id("rb", "RB2610", effective_at),
        effective_trading_day=effective_at.date(),
        effective_at=effective_at,
        source_identity="owned:authoritative-owner-boundary",
    )


def _bar_like(
    base,
    *,
    bar_end,
    close,
    segment_id=None,
    frequency=None,
    source_identity="owned:task-7",
):
    value = Decimal(close)
    return ProductBar(
        bar=replace(
            base.bar,
            segment_id=segment_id or base.bar.segment_id,
            trading_day=bar_end.date(),
            bar_end=bar_end,
            open=value,
            high=value,
            low=value,
            close=value,
            source_identity=source_identity,
        ),
        frequency=frequency or base.frequency,
    )


def _replay_with_hints(replay, hints):
    hints = tuple(hints)
    frames = tuple(
        replace(
            frame,
            hints=tuple(
                hint
                for hint in hints
                if (
                    hint.physical_contract,
                    hint.segment_id,
                    hint.bar_end,
                )
                == (
                    frame.bar.bar.physical_contract,
                    frame.bar.bar.segment_id,
                    frame.bar.bar.bar_end,
                )
            ),
        )
        for frame in replay.frames
    )
    ordered_hints = tuple(hint for frame in frames for hint in frame.hints)
    return replace(replay, frames=frames, hints=ordered_hints)


def _hint(case, bar, kind, *, sequence, known_at=None):
    return StrategyHint(
        identity=case.identity,
        physical_contract=bar.bar.physical_contract,
        segment_id=bar.bar.segment_id,
        bar_end=bar.bar.bar_end,
        trading_day=bar.bar.trading_day,
        kind=kind,
        known_at=known_at or bar.bar.bar_end,
        anchor_price=bar.bar.close,
        sequence=sequence,
        source_marker_id=f"owned:{kind}:{bar.bar.bar_end.isoformat()}",
    )


def test_interruption_retains_negative_decimal_mark_without_fabricating_exit(
    product_cases,
):
    case = product_cases.interrupted(mark="90")

    trade = ReferenceTradeProjector().project(
        case.replay, case.boundaries, case.as_of
    ).trades[0]

    assert trade.status == "ROLLOVER_INTERRUPTED"
    assert trade.mark_bar_end == case.bars[-1].bar.bar_end
    assert trade.mark_reference_price == Decimal("90")
    assert trade.mark_change_pct == Decimal("-10")
    assert trade.exit_signal_id is None
    assert trade.exit_bar_end is None
    assert trade.exit_trading_day is None
    assert trade.exit_reference_price is None
    assert trade.reference_return_pct is None
    assert trade.interrupted_at == case.boundaries[0].effective_at
    assert trade.interruption_reason == "OWNER_BOUNDARY"


def test_future_boundary_and_pre_boundary_prefix_leave_the_trade_open(product_cases):
    case = product_cases.interrupted()
    before_boundary = case.boundaries[0].effective_at - timedelta(seconds=1)

    future_boundary_trade = ReferenceTradeProjector().project(
        case.replay, case.boundaries, before_boundary
    ).trades[0]
    prefix_replay = product_cases.replay(
        case.identity,
        case.bars[:1],
        (case.entry,),
        ("BUILD",),
    )
    prefix_trade = ReferenceTradeProjector().project(
        prefix_replay, case.boundaries, case.entry.bar_end
    ).trades[0]

    assert future_boundary_trade.status == "OPEN"
    assert prefix_trade.status == "OPEN"
    assert future_boundary_trade.interrupted_at is None
    assert prefix_trade.interrupted_at is None


def test_related_clear_before_the_effective_boundary_remains_closed(product_cases):
    case = product_cases.closed(entry="100", exit="80")

    trade = ReferenceTradeProjector().project(
        case.replay, (_boundary(case),), case.as_of
    ).trades[0]

    assert trade.status == "CLOSED"
    assert trade.exit_signal_id == case.exit.signal_id
    assert trade.reference_return_pct == Decimal("-20")
    assert trade.interrupted_at is None
    assert trade.mark_change_pct is None


def test_related_clear_after_the_effective_boundary_cannot_close_the_trade(
    product_cases,
):
    case = product_cases.closed(entry="100", exit="90")
    mark_bar = case.bars[-1]
    late_clear_bar = _bar_like(
        mark_bar,
        bar_end=datetime(2026, 1, 8, 7, tzinfo=UTC),
        close="120",
        source_identity="owned:late-old-owner-clear",
    )
    late_clear = product_cases.action(
        case.identity,
        late_clear_bar,
        "CLEAR",
        "120",
        related_build_id=case.entry.signal_id,
    )
    replay = product_cases.replay(
        case.identity,
        (case.bars[0], mark_bar, late_clear_bar),
        (case.entry, late_clear),
        ("BUILD", "HOLD", "CLEAR"),
    )

    trade = ReferenceTradeProjector().project(
        replay, (_boundary(case),), case.as_of
    ).trades[0]

    assert trade.status == "ROLLOVER_INTERRUPTED"
    assert trade.exit_signal_id is None
    assert trade.reference_return_pct is None
    assert trade.mark_bar_end == mark_bar.bar.bar_end
    assert trade.mark_reference_price == Decimal("90")


def test_clear_after_boundary_still_requires_the_exact_open_build_reference(
    product_cases,
):
    case = product_cases.closed(entry="100", exit="90")
    late_clear_bar = _bar_like(
        case.bars[-1],
        bar_end=datetime(2026, 1, 8, 7, tzinfo=UTC),
        close="120",
        source_identity="owned:damaged-late-clear",
    )
    damaged_clear = product_cases.action(
        case.identity,
        late_clear_bar,
        "CLEAR",
        "120",
        related_build_id="damaged-related-build",
    )
    replay = product_cases.replay(
        case.identity,
        (*case.bars, late_clear_bar),
        (case.entry, damaged_clear),
        ("BUILD", "HOLD", "CLEAR"),
    )

    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        ReferenceTradeProjector().project(replay, (_boundary(case),), case.as_of)


def test_weekly_interruption_uses_the_earlier_completed_owner_mark(product_cases):
    case = product_cases.closed(frequency="1w", entry="100", exit="90")
    replay = product_cases.replay(
        case.identity,
        case.bars,
        (case.entry,),
        ("BUILD", "HOLD"),
    )
    boundary = _boundary(case, effective_at=datetime(2026, 1, 12, tzinfo=UTC))

    as_of = boundary.effective_at + timedelta(days=1)
    trade = ReferenceTradeProjector().project(replay, (boundary,), as_of).trades[0]

    assert trade.status == "ROLLOVER_INTERRUPTED"
    assert trade.mark_bar_end == case.bars[-1].bar.bar_end
    assert trade.mark_bar_end < boundary.effective_at
    assert trade.mark_reference_price == Decimal("90")
    assert trade.mark_change_pct == Decimal("-10")


def test_missing_eligible_mark_keeps_the_interrupted_trade_with_reason(product_cases):
    case = product_cases.open()
    boundary = _boundary(
        case, effective_at=case.entry.bar_end - timedelta(seconds=1)
    )

    trade = ReferenceTradeProjector().project(
        replay=case.replay, boundaries=(boundary,), as_of=case.as_of
    ).trades[0]

    assert trade.status == "ROLLOVER_INTERRUPTED"
    assert trade.reference_trade_id
    assert trade.mark_bar_end is None
    assert trade.mark_reference_price is None
    assert trade.mark_change_pct is None
    assert trade.interruption_reason == "OWNER_BOUNDARY_MARK_UNAVAILABLE"


def test_mark_excludes_later_old_contract_bars_and_another_segment(product_cases):
    case = product_cases.interrupted(mark="90")
    later = _bar_like(
        case.bars[-1],
        bar_end=datetime(2026, 1, 8, 7, tzinfo=UTC),
        close="200",
        source_identity="owned:later-non-rank1",
    )
    foreign_segment = _bar_like(
        case.bars[-1],
        bar_end=datetime(2026, 1, 6, 8, tzinfo=UTC),
        close="300",
        segment_id=f"{case.entry.segment_id}:foreign",
        source_identity="owned:foreign-segment",
    )
    replay = product_cases.replay(
        case.identity,
        (*case.bars, later, foreign_segment),
        (case.entry,),
        ("BUILD", "HOLD", "HOLD", "HOLD"),
    )

    trade = ReferenceTradeProjector().project(
        replay, case.boundaries, case.as_of
    ).trades[0]

    assert trade.mark_bar_end == case.bars[-1].bar.bar_end
    assert trade.mark_reference_price == Decimal("90")
    assert trade.holding_bars == 1


def test_mark_excludes_a_forged_cross_frequency_frame(product_cases):
    case = product_cases.interrupted(mark="90")
    foreign_bar = _bar_like(
        case.bars[-1],
        bar_end=datetime(2026, 1, 6, 8, tzinfo=UTC),
        close="300",
        frequency="60m",
        source_identity="owned:foreign-frequency",
    )
    foreign_frame = replace(case.replay.frames[-1], bar=foreign_bar, actions=())
    forged = copy(case.replay)
    object.__setattr__(forged, "frames", (*case.replay.frames, foreign_frame))

    trade = ReferenceTradeProjector().project(
        forged, case.boundaries, case.as_of
    ).trades[0]

    assert trade.mark_bar_end == case.bars[-1].bar.bar_end
    assert trade.mark_reference_price == Decimal("90")


def test_open_trade_has_positive_current_reference_float_without_an_exit(
    product_cases,
):
    case = product_cases.open()

    trade = ReferenceTradeProjector().project(case.replay, (), case.as_of).trades[0]

    assert trade.status == "OPEN"
    assert trade.mark_bar_end == case.bars[-1].bar.bar_end
    assert trade.mark_reference_price == Decimal("110")
    assert trade.mark_change_pct == Decimal("10")
    assert trade.exit_signal_id is None
    assert trade.reference_return_pct is None


def test_open_trade_preserves_negative_current_reference_float(product_cases):
    case = product_cases.open()
    mark_bar = _bar_like(
        case.bars[-1],
        bar_end=case.bars[-1].bar.bar_end,
        close="90",
        source_identity="owned:negative-open-mark",
    )
    replay = product_cases.replay(
        case.identity,
        (case.bars[0], mark_bar),
        (case.entry,),
        ("BUILD", "HOLD"),
    )

    trade = ReferenceTradeProjector().project(replay, (), case.as_of).trades[0]

    assert trade.status == "OPEN"
    assert trade.mark_bar_end == mark_bar.bar.bar_end
    assert trade.mark_reference_price == Decimal("90")
    assert trade.mark_change_pct == Decimal("-10")
    assert trade.exit_signal_id is None
    assert trade.reference_return_pct is None


def test_open_trade_without_a_later_eligible_mark_is_explicitly_unavailable(
    product_cases,
):
    case = product_cases.open()
    replay = product_cases.replay(
        case.identity,
        case.bars[:1],
        (case.entry,),
        ("BUILD",),
    )

    result = ReferenceTradeProjector().project(replay, (), case.as_of)
    trade = result.trades[0]

    assert trade.status == "OPEN"
    assert trade.mark_bar_end is None
    assert trade.mark_reference_price is None
    assert trade.mark_change_pct is None
    assert trade.exit_signal_id is None
    assert trade.reference_return_pct is None
    assert result.diagnostics == ("OPEN_MARK_UNAVAILABLE",)


def test_ordered_hints_attach_only_inside_one_trade_and_do_not_change_authority(
    product_cases,
):
    case = product_cases.closed(entry="100", exit="110")
    clear = replace(case.exit, sequence=2)
    replay = product_cases.replay(
        case.identity,
        case.bars,
        (case.entry, clear),
        ("BUILD", "CLEAR"),
    )
    after_build = _hint(case, case.bars[0], "D1", sequence=1)
    before_clear = _hint(case, case.bars[1], "J", sequence=1)
    after_clear = _hint(case, case.bars[1], "D2", sequence=3)
    ambiguous = _hint(case, case.bars[1], "D3", sequence=None)
    future_known = _hint(
        case,
        case.bars[0],
        "D4",
        sequence=1,
        known_at=case.as_of + timedelta(days=1),
    )
    with_hints = _replay_with_hints(
        replay, (after_build, before_clear, after_clear, ambiguous, future_known)
    )
    projector = ReferenceTradeProjector()

    result = projector.project(with_hints, (), case.as_of)
    trade = result.trades[0]
    baseline = projector.project(replay, (), case.as_of).trades[0]

    assert trade.hint_ids == (after_build.hint_id, before_clear.hint_id)
    assert result.unassigned_hints == (after_clear,)
    assert result.bar_level_hints == (ambiguous,)
    assert replace(trade, hint_ids=()) == baseline


def test_adapter_shaped_unsequenced_hint_on_an_interior_bar_attaches(product_cases):
    case = product_cases.closed(entry="100", exit="110")
    interior_bar = case.bars[-1]
    clear_bar = _bar_like(
        interior_bar,
        bar_end=datetime(2026, 1, 7, 7, tzinfo=UTC),
        close="110",
        source_identity="owned:clear-after-interior-hint",
    )
    clear = product_cases.action(
        case.identity,
        clear_bar,
        "CLEAR",
        "110",
        related_build_id=case.entry.signal_id,
    )
    replay = product_cases.replay(
        case.identity,
        (case.bars[0], interior_bar, clear_bar),
        (case.entry, clear),
        ("BUILD", "HOLD", "CLEAR"),
    )
    interior = _hint(case, interior_bar, "J", sequence=None)

    result = ReferenceTradeProjector().project(
        _replay_with_hints(replay, (interior,)), (), case.as_of
    )

    assert result.trades[0].hint_ids == (interior.hint_id,)
    assert result.bar_level_hints == ()
    assert result.unassigned_hints == ()


def test_adapter_shaped_unsequenced_hint_on_a_flat_bar_stays_visible(
    product_cases,
):
    case = product_cases.closed()
    flat_bar = _bar_like(
        case.bars[-1],
        bar_end=datetime(2026, 1, 7, 7, tzinfo=UTC),
        close="110",
        source_identity="owned:flat-hint",
    )
    replay = product_cases.replay(
        case.identity,
        (*case.bars, flat_bar),
        case.replay.actions,
        ("BUILD", "CLEAR", "FLAT"),
    )
    flat = _hint(case, flat_bar, "D1", sequence=None)

    result = ReferenceTradeProjector().project(
        _replay_with_hints(replay, (flat,)), (), case.as_of
    )

    assert result.trades[0].hint_ids == ()
    assert result.bar_level_hints == ()
    assert result.unassigned_hints == (flat,)


@pytest.mark.parametrize("kind", ["control_mirror", "zhaoyaojing"])
def test_repainting_mirror_hint_names_are_rejected_at_projection_boundary(
    product_cases, kind
):
    case = product_cases.open()
    mirror = _hint(case, case.bars[-1], kind, sequence=None)
    replay = _replay_with_hints(case.replay, (mirror,))

    with pytest.raises(ValueError, match="RETROSPECTIVE_HINT"):
        ReferenceTradeProjector().project(replay, (), case.as_of)
