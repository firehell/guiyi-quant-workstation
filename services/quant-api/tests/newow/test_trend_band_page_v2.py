from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from guiyi_quant.newow.models import (
    NewowDailyBar,
    NewowMarkerType,
    TrendBandState,
    TrendTransition,
)
from guiyi_quant.newow.profile import (
    NEWOW_TREND_D1_PAGE_V2,
    NEWOW_TREND_D1_V1,
)
from guiyi_quant.newow.trend_band import initial_trend_band_state, step_trend_band


_STOCK_PAGE_GOLDEN = (
    (
        "2025-09-01",
        "14.49",
        "14.78",
        "14.26",
        "14.5",
        14.513333333333334,
        14.513333333333334,
        TrendBandState.BLUE,
    ),
    (
        "2025-09-02",
        "14.49",
        "14.7",
        "14.07",
        "14.22",
        14.421666666666667,
        14.421666666666667,
        TrendBandState.BLUE,
    ),
    (
        "2025-09-03",
        "14.28",
        "14.48",
        "14.01",
        "14.14",
        14.351111111111111,
        14.351111111111111,
        TrendBandState.BLUE,
    ),
    (
        "2025-09-04",
        "14.1",
        "14.27",
        "13.9",
        "14.23",
        14.296666666666667,
        14.296666666666667,
        TrendBandState.BLUE,
    ),
    (
        "2025-09-05",
        "14.23",
        "14.54",
        "14.19",
        "14.54",
        14.322,
        14.322,
        TrendBandState.YELLOW,
    ),
    (
        "2025-09-08",
        "14.53",
        "15.4",
        "14.25",
        "15.4",
        14.437777777777777,
        14.437777777777777,
        TrendBandState.YELLOW,
    ),
    (
        "2025-09-09",
        "15.25",
        "15.38",
        "14.59",
        "14.69",
        14.50190476190476,
        14.50190476190476,
        TrendBandState.YELLOW,
    ),
    (
        "2025-09-10",
        "14.7",
        "14.8",
        "14.33",
        "14.5",
        14.506190476190477,
        14.507083333333334,
        TrendBandState.BLUE,
    ),
    (
        "2025-09-11",
        "14.5",
        "14.69",
        "14.32",
        "14.68",
        14.53952380952381,
        14.513333333333334,
        TrendBandState.YELLOW,
    ),
    (
        "2025-09-12",
        "14.65",
        "14.75",
        "14.2",
        "14.54",
        14.58047619047619,
        14.511666666666667,
        TrendBandState.YELLOW,
    ),
    (
        "2025-09-15",
        "14.51",
        "14.58",
        "14.16",
        "14.23",
        14.607619047619048,
        14.492666666666668,
        TrendBandState.BLUE,
    ),
    (
        "2025-09-16",
        "14.22",
        "14.65",
        "13.96",
        "14.32",
        14.59142857142857,
        14.490666666666666,
        TrendBandState.BLUE,
    ),
)


def _bar(
    row: tuple[str, str, str, str, str, float, float, TrendBandState],
    *,
    contract: str = "RB2701",
    segment: str = "rb:RB2701:2025-09-01",
) -> NewowDailyBar:
    trading_day = date.fromisoformat(row[0])
    return NewowDailyBar(
        product="rb",
        physical_contract=contract,
        segment_id=segment,
        trading_day=trading_day,
        bar_end=datetime.combine(trading_day, datetime.min.time(), tzinfo=UTC),
        open=Decimal(row[1]),
        high=Decimal(row[2]),
        low=Decimal(row[3]),
        close=Decimal(row[4]),
        volume=100,
        open_interest=None,
        source_identity="browser:601233.SH:v3.2.63",
        observation_eligible=True,
        completed=True,
    )


def _run_page_golden():
    state = initial_trend_band_state()
    results = []
    for row in _STOCK_PAGE_GOLDEN:
        result = step_trend_band(state, _bar(row), profile=NEWOW_TREND_D1_PAGE_V2)
        results.append(result)
        state = result.state
    return tuple(results)


def test_page_v2_has_new_identity_without_rewriting_v1() -> None:
    assert NEWOW_TREND_D1_V1.profile_id == "newow_trend_d1_v1"
    assert NEWOW_TREND_D1_V1.trend_band_formula == "newow_trend_band_cleanroom_v1"
    assert NEWOW_TREND_D1_PAGE_V2.profile_id == "newow_trend_d1_page_v2"
    assert NEWOW_TREND_D1_PAGE_V2.trend_band_formula == "newow_trend_band_page_v2"
    assert NEWOW_TREND_D1_PAGE_V2.trend_weight_period == 7
    assert NEWOW_TREND_D1_PAGE_V2.trend_signal_period == 10


def test_page_v2_matches_frozen_stock_a_b_and_state_from_first_bar() -> None:
    results = _run_page_golden()

    assert [result.point.b_value for result in results] == pytest.approx(
        [row[5] for row in _STOCK_PAGE_GOLDEN]
    )
    assert [result.point.c_value for result in results] == pytest.approx(
        [row[6] for row in _STOCK_PAGE_GOLDEN]
    )
    assert [result.point.state for result in results] == [
        row[7] for row in _STOCK_PAGE_GOLDEN
    ]
    assert results[0].point.state is TrendBandState.BLUE
    assert results[0].point.state_before is None
    assert results[0].point.transition is None


def test_page_v2_emits_frozen_transitions_at_slow_band_price() -> None:
    results = _run_page_golden()
    emitted = tuple(
        (index, result.point.transition, result.marker)
        for index, result in enumerate(results)
        if result.marker is not None
    )

    assert [item[0] for item in emitted] == [4, 7, 8, 10]
    assert [item[1] for item in emitted] == [
        TrendTransition.BUILD,
        TrendTransition.CLEAR,
        TrendTransition.BUILD,
        TrendTransition.CLEAR,
    ]
    assert [item[2].marker_type for item in emitted] == [
        NewowMarkerType.BUILD,
        NewowMarkerType.CLEAR,
        NewowMarkerType.BUILD,
        NewowMarkerType.CLEAR,
    ]
    assert [float(item[2].price) for item in emitted] == pytest.approx(
        [14.322, 14.507083333333334, 14.513333333333334, 14.492666666666668]
    )
    assert emitted[1][2].trigger_facts["reference_basis"] == "trend_slow_band"
    assert emitted[1][2].trigger_facts["reference_change_pct"] == pytest.approx(
        1.292300889075093
    )
    assert emitted[3][2].trigger_facts["reference_change_pct"] == pytest.approx(
        -0.14239779513090453
    )
    assert all(
        marker.formula_version == "newow_trend_band_page_v2" for _, _, marker in emitted
    )


def test_page_v2_rollover_starts_partial_window_without_cross_segment_marker() -> None:
    prior = _run_page_golden()[-1].state
    first_new_segment = (
        "2026-01-05",
        "100",
        "101",
        "99",
        "100",
        100.0,
        100.0,
        TrendBandState.YELLOW,
    )

    result = step_trend_band(
        prior,
        _bar(first_new_segment, contract="RB2705", segment="rb:RB2705:2026-01-05"),
        profile=NEWOW_TREND_D1_PAGE_V2,
    )

    assert result.point.b_value == 100.0
    assert result.point.c_value == 100.0
    assert result.point.state is TrendBandState.YELLOW
    assert result.point.state_before is None
    assert result.point.transition is None
    assert result.marker is None
    assert result.state.physical_contract == "RB2705"
    assert result.state.segment_id == "rb:RB2705:2026-01-05"


def test_page_v2_equal_close_and_slow_band_is_yellow() -> None:
    row = (
        "2026-01-05",
        "100",
        "100",
        "100",
        "100",
        100.0,
        100.0,
        TrendBandState.YELLOW,
    )

    result = step_trend_band(
        initial_trend_band_state(),
        _bar(row),
        profile=NEWOW_TREND_D1_PAGE_V2,
    )

    assert result.point.state is TrendBandState.YELLOW
    assert result.marker is None
