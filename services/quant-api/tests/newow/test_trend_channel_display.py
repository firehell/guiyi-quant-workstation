from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from guiyi_quant.newow.product_contracts import ProductBar
from guiyi_quant.newow.trend_channel_display import (
    TREND_CHANNEL_PERIOD,
    build_trend_channel_layer,
)

from tests.newow.test_oscillation_channel import golden_bars


def _bars() -> tuple[ProductBar, ...]:
    return tuple(ProductBar(bar, "1d") for bar in golden_bars())


def test_partial_segment_and_isolated_first_bar_are_ready_page_values() -> None:
    bars = _bars()

    partial = build_trend_channel_layer(bars[:4], bars[:4])
    isolated = build_trend_channel_layer(bars[:1], bars[:1])

    assert TREND_CHANNEL_PERIOD == 10
    assert [(point.upper, point.lower) for point in partial.points] == [
        (Decimal("14.78"), Decimal("14.26")),
        (Decimal("14.78"), Decimal("14.07")),
        (Decimal("14.78"), Decimal("14.01")),
        (Decimal("14.78"), Decimal("13.9")),
    ]
    assert isolated.points[0].availability.status == "ready"
    assert isolated.points[0].upper == bars[0].bar.high
    assert isolated.points[0].lower == bars[0].bar.low


def test_owner_change_restarts_without_borrowing_previous_extrema() -> None:
    bars = _bars()[:12]
    changed = tuple(
        replace(
            item,
            bar=replace(
                item.bar,
                physical_contract="RB0001",
                segment_id="rb:RB0001:research-2",
                source_identity="canonical:rb:RB0001:1d",
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("9"),
                close=Decimal("10"),
            ),
        )
        for item in bars[10:]
    )
    replay = (*bars[:10], *changed)

    layer = build_trend_channel_layer(replay, replay)

    assert layer.points[9].upper == Decimal("15.4")
    assert layer.points[10].upper == Decimal("11")
    assert layer.points[10].lower == Decimal("9")
    assert layer.points[10].physical_contract == "RB0001"
    assert layer.points[10].segment_id == "rb:RB0001:research-2"


def test_calculation_segment_change_restarts_channel_without_changing_owner() -> None:
    bars = _bars()[:11]
    restarted = replace(
        bars[10],
        calculation_segment_id="rb:RB9999:research|price-gap:2025-09-11T00:00:00+00:00",
        bar=replace(
            bars[10].bar,
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("99"),
            close=Decimal("100"),
        ),
    )

    layer = build_trend_channel_layer((*bars[:10], restarted), (*bars[:10], restarted))

    assert layer.points[9].upper == Decimal("15.4")
    assert layer.points[10].upper == Decimal("100")
    assert layer.points[10].lower == Decimal("99")
    assert layer.points[10].calculation_segment_id == restarted.calculation_segment_id


def test_visible_pagination_uses_full_prefix_and_is_prefix_invariant() -> None:
    bars = _bars()
    full = build_trend_channel_layer(bars, bars)
    page = build_trend_channel_layer(bars, bars[20:])
    shorter_prefix = build_trend_channel_layer(bars[:25], bars[20:25])

    assert page.points == full.points[20:]
    assert shorter_prefix.points == full.points[20:25]


def test_missing_replay_bar_is_explicitly_unavailable_without_values() -> None:
    bars = _bars()

    layer = build_trend_channel_layer(bars[:1], bars[:2])

    point = layer.points[1]
    assert point.upper is None
    assert point.lower is None
    assert point.availability.status == "unavailable"
    assert point.availability.reason_code == "NEWOW_TREND_CHANNEL_BAR_MISSING"


def test_same_time_owner_conflict_is_unavailable_and_preserves_visible_owner() -> None:
    bars = _bars()
    conflicting = replace(
        bars[0],
        bar=replace(
            bars[0].bar,
            physical_contract="RB0001",
            segment_id="rb:RB0001:research-2",
            source_identity="canonical:rb:RB0001:1d",
        ),
    )

    layer = build_trend_channel_layer(bars[:1], (conflicting,))

    point = layer.points[0]
    assert point.upper is None
    assert point.lower is None
    assert point.physical_contract == "RB0001"
    assert point.segment_id == "rb:RB0001:research-2"
    assert point.source_identity == "canonical:rb:RB0001:1d"
    assert point.availability.status == "unavailable"
    assert point.availability.reason_code == "NEWOW_TREND_CHANNEL_OWNER_CONFLICT"


def test_duplicate_replay_fact_does_not_pollute_later_channel_values() -> None:
    bars = _bars()[:12]
    duplicate = replace(
        bars[0],
        bar=replace(bars[0].bar, high=Decimal("24.78")),
    )

    layer = build_trend_channel_layer((bars[0], duplicate, *bars[1:]), bars)

    assert layer.points[0].availability.reason_code == "NEWOW_TREND_CHANNEL_OWNER_CONFLICT"
    assert all(
        point.availability.reason_code == "NEWOW_TREND_CHANNEL_WARMUP_INSUFFICIENT"
        for point in layer.points[1:10]
    )
    assert layer.points[10].availability.status == "ready"
    assert layer.points[10].upper == Decimal("15.4")
    assert layer.points[10].upper != duplicate.bar.high


def test_each_bar_keeps_its_own_source_identity_without_treating_it_as_run_owner() -> None:
    bars = _bars()[:3]
    drifted = replace(
        bars[1],
        bar=replace(bars[1].bar, source_identity="canonical:rb:RB9999:1d"),
    )

    layer = build_trend_channel_layer(
        (bars[0], drifted, bars[2]),
        (bars[0], drifted, bars[2]),
    )

    assert all(point.availability.status == "ready" for point in layer.points)
    assert [point.source_identity for point in layer.points] == [
        bars[0].bar.source_identity,
        drifted.bar.source_identity,
        bars[2].bar.source_identity,
    ]


def test_out_of_order_owner_run_is_unavailable_instead_of_borrowing_future_values() -> None:
    bars = _bars()[:3]

    layer = build_trend_channel_layer(
        (bars[1], bars[0], bars[2]),
        (bars[1], bars[0], bars[2]),
    )

    assert all(point.upper is None and point.lower is None for point in layer.points)
    assert all(
        point.availability.reason_code == "NEWOW_TREND_CHANNEL_ORDER_CONFLICT"
        for point in layer.points
    )


def test_out_of_order_run_stays_fail_closed_when_the_lower_time_is_duplicated() -> None:
    bars = _bars()[:4]
    duplicate = replace(
        bars[1],
        bar=replace(bars[1].bar, high=Decimal("24.78")),
    )

    layer = build_trend_channel_layer(
        (bars[2], bars[1], duplicate, bars[3]),
        (bars[2], bars[1], bars[3]),
    )

    assert all(point.availability.status == "unavailable" for point in layer.points)
    assert layer.points[0].availability.reason_code == "NEWOW_TREND_CHANNEL_ORDER_CONFLICT"
    assert layer.points[-1].availability.reason_code == "NEWOW_TREND_CHANNEL_ORDER_CONFLICT"
