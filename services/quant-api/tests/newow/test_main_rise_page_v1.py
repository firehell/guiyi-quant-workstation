from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from guiyi_quant.newow.main_rise import (
    MAIN_RISE_PAGE_V1,
    MainRiseAction,
    MainRiseBuyKind,
    calculate_main_rise_series,
    main_rise_formula_gate,
    restore_main_rise_state,
    step_main_rise,
)
from guiyi_quant.newow.models import NewowDailyBar, NewowMarkerType


_GOLDEN_HLC = (
    (14.78, 14.26, 14.5),
    (14.7, 14.07, 14.22),
    (14.48, 14.01, 14.14),
    (14.27, 13.9, 14.23),
    (14.54, 14.19, 14.54),
    (15.4, 14.25, 15.4),
    (15.38, 14.59, 14.69),
    (14.8, 14.33, 14.5),
    (14.69, 14.32, 14.68),
    (14.75, 14.2, 14.54),
    (14.58, 14.16, 14.23),
    (14.65, 13.96, 14.32),
    (14.38, 14.16, 14.33),
    (14.41, 13.92, 14),
    (14.23, 13.95, 14.16),
    (14.11, 13.7, 13.86),
    (13.87, 13.21, 13.56),
    (14.03, 13.53, 13.99),
    (14.14, 13.86, 13.98),
    (15.33, 14.07, 14.83),
    (14.88, 14.52, 14.85),
    (14.96, 14.61, 14.89),
    (15.02, 14.16, 14.54),
    (15.02, 14.35, 14.83),
    (14.53, 13.6, 13.96),
    (14.12, 13.22, 13.31),
    (13.58, 13.28, 13.5),
    (13.62, 13.31, 13.37),
    (13.58, 12.94, 12.97),
    (13.37, 13, 13.13),
    (13.38, 12.99, 13.32),
    (13.73, 13.24, 13.55),
    (14.22, 13.48, 14.17),
    (14.42, 13.96, 14.17),
    (14.48, 13.99, 14.36),
    (14.5, 14.21, 14.32),
    (14.86, 14.12, 14.68),
    (14.49, 14.04, 14.3),
    (14.48, 14.08, 14.1),
    (14.38, 13.8, 14.25),
    (14.38, 13.91, 14),
    (14.07, 13.76, 13.8),
    (14.91, 13.8, 14.66),
    (15.21, 14.53, 15.07),
    (15.86, 15.02, 15.65),
    (15.79, 15.36, 15.63),
    (15.88, 15.33, 15.7),
    (16.1, 15.34, 15.87),
    (16.46, 15.61, 15.61),
    (16.37, 15.34, 15.82),
    (15.94, 15.11, 15.28),
    (15.58, 15.14, 15.44),
    (15.63, 14.71, 14.79),
    (15.06, 14.46, 14.66),
    (15.03, 14.62, 14.79),
    (14.92, 14.5, 14.62),
    (14.81, 14.38, 14.4),
    (14.96, 14.39, 14.79),
    (15.38, 14.73, 15.26),
    (15.64, 15.11, 15.35),
    (15.57, 14.98, 15.28),
    (15.48, 15.11, 15.15),
    (15.17, 14.84, 14.98),
    (15.25, 14.88, 15.14),
    (15.2, 14.53, 14.67),
    (14.79, 14.24, 14.26),
    (14.38, 14.1, 14.29),
    (14.41, 14.04, 14.08),
    (14.21, 13.92, 14.13),
    (14.51, 13.92, 14.28),
    (14.3, 13.73, 14.21),
    (14.94, 14.08, 14.8),
    (15.51, 14.74, 15.18),
    (15.61, 15.14, 15.47),
    (15.93, 15.35, 15.73),
    (15.92, 15.58, 15.72),
    (16.32, 15.56, 16.23),
    (16.95, 16.23, 16.74),
    (17.2, 16.4, 16.73),
    (17.1, 16.43, 16.6),
)


def _bar(index: int, values, *, contract: str = "RB9999") -> NewowDailyBar:
    high, low, close = values
    day = date(2025, 9, 1) + timedelta(days=index)
    return NewowDailyBar(
        product="rb",
        physical_contract=contract,
        segment_id=f"rb:{contract}:research",
        trading_day=day,
        bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        open=Decimal(str(close)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=1,
        open_interest=None,
        source_identity="browser:601233.SH",
        observation_eligible=True,
        completed=True,
    )


def _bars() -> tuple[NewowDailyBar, ...]:
    return tuple(_bar(index, values) for index, values in enumerate(_GOLDEN_HLC))


def test_formula_gate_rejects_partial_or_mixed_compositions() -> None:
    assert main_rise_formula_gate(MAIN_RISE_PAGE_V1) is True
    assert (
        main_rise_formula_gate(
            replace(MAIN_RISE_PAGE_V1, escape_formula="newow_escape_d123_v1")
        )
        is False
    )


def test_601233_browser_prefix_matches_band_reduce_d123_d456_and_magic11() -> None:
    results = calculate_main_rise_series(_bars())

    assert [
        (i, step.band_signal.action)
        for i, step in enumerate(results)
        if step.band_signal
    ] == [(35, MainRiseAction.CLEAR), (50, MainRiseAction.BUILD)]
    assert [
        (i, step.reduce_signal.j_value)
        for i, step in enumerate(results)
        if step.reduce_signal
    ] == [(21, 89.7114), (35, 103.214), (45, 99.3967), (60, 87.2665), (74, 105.6207)]
    assert [
        (i, marker.marker_type)
        for i, step in enumerate(results)
        for marker in step.escape_markers
    ] == [(78, NewowMarkerType.ESCAPE_D2)]
    assert [
        (i, marker.kind)
        for i, step in enumerate(results)
        for marker in step.buy_markers
    ] == [(4, MainRiseBuyKind.D4)]
    assert [
        (i, step.magic11.marker.label.value)
        for i, step in enumerate(results)
        if step.magic11.marker
    ] == [
        (9, "4低"),
        (12, "7高"),
        (20, "4高"),
        (23, "7低"),
        (27, "11变"),
        (32, "4高"),
        (35, "7低"),
        (39, "11变"),
        (52, "4低"),
        (55, "7高"),
        (59, "11变"),
    ]


def test_composite_is_prefix_incremental_serializable_and_rollover_safe() -> None:
    bars = _bars()
    full = calculate_main_rise_series(bars)
    assert calculate_main_rise_series(bars[:50]) == full[:50]
    restored = restore_main_rise_state(asdict(full[49].state))
    resumed = []
    for bar in bars[50:]:
        step = step_main_rise(restored, bar)
        resumed.append(step)
        restored = step.state
    assert tuple(resumed) == full[50:]

    rollover = _bar(80, (20.0, 18.0, 19.0), contract="RB0001")
    reset = step_main_rise(full[-1].state, rollover)
    assert reset.state.history_count == 1
    assert reset.band_signal is None
    assert reset.reduce_signal is None
    assert reset.escape_markers == ()
    assert reset.buy_markers == ()


def test_restore_main_rise_rejects_malformed_payload_immediately() -> None:
    valid = calculate_main_rise_series(_bars()[:50])[-1].state

    malformed = restore_main_rise_state(
        {**asdict(valid), "history_count": valid.history_count + 1}
    )
    unknown = restore_main_rise_state({**asdict(valid), "unexpected": True})

    assert malformed == restore_main_rise_state({})
    assert unknown == restore_main_rise_state({})
