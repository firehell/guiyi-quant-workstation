from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"

if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))


def _bar_end(index: int) -> str:
    return f"2026-01-{index + 1:02d}T00:00:00Z"


def _constant_bars(
    count: int,
    close: float = 10.0,
    *,
    start: int = 0,
) -> list[dict[str, object]]:
    return [
        {
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "bar_end": _bar_end(start + index),
        }
        for index in range(count)
    ]


def _run_streamed(bars: list[dict[str, object]]):
    from guiyi_quant.indicators import (
        initial_range_detector_lux_state,
        step_range_detector_lux,
    )

    state = initial_range_detector_lux_state(
        source_identity="test:actual_dominant:jm:1d",
        minimum_range_length=3,
        range_atr_length=3,
    )
    points = []
    for bar in bars:
        state, point = step_range_detector_lux(state, **bar)
        points.append(point)
    return state, tuple(points)


def _json_value(value: object) -> object:
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _canonical_hash_value(value: object) -> object:
    if isinstance(value, list):
        return [_canonical_hash_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical_hash_value(item) for key, item in value.items()}
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def test_range_detector_requires_valid_parameters_and_source_identity() -> None:
    from guiyi_quant.indicators import initial_range_detector_lux_state

    with pytest.raises(ValueError, match="source_identity"):
        initial_range_detector_lux_state(source_identity="")
    with pytest.raises(ValueError, match="minimum_range_length"):
        initial_range_detector_lux_state(
            source_identity="test:actual_dominant:jm:1d",
            minimum_range_length=1,
        )
    with pytest.raises(ValueError, match="range_width_atr_multiplier"):
        initial_range_detector_lux_state(
            source_identity="test:actual_dominant:jm:1d",
            range_width_atr_multiplier=0,
        )


def test_range_detector_confirms_after_atr_and_close_window_warmup() -> None:
    _, points = _run_streamed(_constant_bars(5))

    assert [point.ready for point in points[:3]] == [False, False, False]
    confirmed = points[3]
    assert confirmed.ready is True
    assert confirmed.valid is True
    assert confirmed.transition is not None
    assert confirmed.transition.kind == "confirmed"
    assert confirmed.snapshot is not None
    assert confirmed.snapshot.visual_start_at == _bar_end(0)
    assert confirmed.snapshot.confirmed_at == _bar_end(3)
    assert confirmed.snapshot.detection_right_at == _bar_end(3)
    assert points[4].snapshot is not None
    assert points[4].snapshot.detection_right_at == _bar_end(4)


def test_range_detector_confirmation_id_is_deterministic() -> None:
    _, points = _run_streamed(_constant_bars(4))

    snapshot = points[-1].snapshot
    assert snapshot is not None
    expected = hashlib.sha256(
        b"range_detector_lux_v1|test:actual_dominant:jm:1d|2026-01-04T00:00:00Z"
    ).hexdigest()
    assert snapshot.range_id == expected
    assert snapshot.revision == 1
    assert snapshot.current_upper == 12.0
    assert snapshot.current_lower == 8.0


@pytest.mark.parametrize(
    ("close", "high", "low"),
    [(12.0, 13.0, 11.0), (8.0, 9.0, 7.0)],
)
def test_exact_range_boundaries_remain_intact(
    close: float,
    high: float,
    low: float,
) -> None:
    _, points = _run_streamed(
        [*_constant_bars(4), {"high": high, "low": low, "close": close, "bar_end": _bar_end(4)}]
    )

    assert points[-1].snapshot is not None
    assert points[-1].snapshot.state == "intact"
    assert points[-1].snapshot.broken_at is None
    assert points[-1].transition is None


@pytest.mark.parametrize(
    ("close", "high", "low", "expected_state"),
    [(13.0, 14.0, 12.0, "broken_up"), (7.0, 8.0, 6.0, "broken_down")],
)
def test_range_breaks_once_and_does_not_automatically_recover(
    close: float,
    high: float,
    low: float,
    expected_state: str,
) -> None:
    bars = [
        *_constant_bars(4),
        {"high": high, "low": low, "close": close, "bar_end": _bar_end(4)},
        {"high": 11.0, "low": 9.0, "close": 10.0, "bar_end": _bar_end(5)},
    ]
    _, points = _run_streamed(bars)

    assert points[4].transition is not None
    assert points[4].transition.kind == expected_state
    assert points[4].snapshot is not None
    assert points[4].snapshot.state == expected_state
    assert points[5].snapshot is not None
    assert points[5].snapshot.state == expected_state
    assert points[5].transition is None


def test_invalid_input_resets_active_range_and_restarts_warmup() -> None:
    bars = [
        *_constant_bars(4),
        {"high": float("nan"), "low": 9.0, "close": 10.0, "bar_end": _bar_end(4)},
        *_constant_bars(3, close=20.0, start=5),
    ]
    _, points = _run_streamed(bars)

    assert points[4].valid is False
    assert points[4].reason == "input_invalid"
    assert points[4].transition is not None
    assert points[4].transition.kind == "invalid_reset"
    assert points[4].snapshot is None
    assert [point.ready for point in points[5:]] == [False, False, False]


def test_range_detector_rejects_non_monotonic_or_invalid_timestamps() -> None:
    from guiyi_quant.indicators import (
        initial_range_detector_lux_state,
        step_range_detector_lux,
    )

    state = initial_range_detector_lux_state(
        source_identity="test:actual_dominant:jm:1d",
        minimum_range_length=3,
        range_atr_length=3,
    )
    with pytest.raises(ValueError, match="ISO-8601"):
        step_range_detector_lux(
            state,
            high=11.0,
            low=9.0,
            close=10.0,
            bar_end="not-a-time",
        )
    with pytest.raises(ValueError, match="timezone"):
        step_range_detector_lux(
            state,
            high=11.0,
            low=9.0,
            close=10.0,
            bar_end="2026-01-02T00:00:00",
        )
    state, _ = step_range_detector_lux(
        state,
        high=11.0,
        low=9.0,
        close=10.0,
        bar_end="2026-01-02T08:00:00+08:00",
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        step_range_detector_lux(
            state,
            high=11.0,
            low=9.0,
            close=10.0,
            bar_end=_bar_end(1),
        )


def test_batch_matches_incremental_and_future_tail_does_not_rewrite_prefix() -> None:
    from guiyi_quant.indicators import range_detector_lux_series

    bars = [
        *_constant_bars(4),
        {"high": 13.0, "low": 11.0, "close": 12.0, "bar_end": _bar_end(4)},
        {"high": 14.0, "low": 12.0, "close": 13.0, "bar_end": _bar_end(5)},
    ]
    _, streamed = _run_streamed(bars)
    batch = range_detector_lux_series(
        [bar["high"] for bar in bars],
        [bar["low"] for bar in bars],
        [bar["close"] for bar in bars],
        bar_ends=[str(bar["bar_end"]) for bar in bars],
        source_identity="test:actual_dominant:jm:1d",
        minimum_range_length=3,
        range_atr_length=3,
    )
    tailed_bars = [
        *bars,
        {"high": 101.0, "low": 99.0, "close": 100.0, "bar_end": _bar_end(6)},
    ]
    tailed = range_detector_lux_series(
        [bar["high"] for bar in tailed_bars],
        [bar["low"] for bar in tailed_bars],
        [bar["close"] for bar in tailed_bars],
        bar_ends=[str(bar["bar_end"]) for bar in tailed_bars],
        source_identity="test:actual_dominant:jm:1d",
        minimum_range_length=3,
        range_atr_length=3,
    )

    assert batch.points == streamed
    assert tailed.points[: len(batch.points)] == batch.points


def test_overlap_revision_keeps_identity_and_new_confirmation_terminates_levels() -> None:
    from guiyi_quant.indicators import range_detector_lux_series

    closes = [10.0, 10.0, 10.0, 10.0, 5.0, 5.0, 5.0, 15.0, 15.0, 5.0, 10.0]
    highs = [close + 1 for close in closes]
    lows = [close - 1 for close in closes]
    series = range_detector_lux_series(
        highs,
        lows,
        closes,
        bar_ends=[_bar_end(index) for index in range(len(closes))],
        source_identity="test:actual_dominant:jm:1d",
        minimum_range_length=3,
        range_atr_length=3,
    )

    initial = series.points[3].snapshot
    revision = series.points[6].snapshot
    replacement = series.points[10].snapshot
    assert initial is not None
    assert revision is not None
    assert replacement is not None
    assert series.points[6].transition is not None
    assert series.points[6].transition.kind == "revised"
    assert revision.range_id == initial.range_id
    assert revision.revision == initial.revision + 1
    assert revision.current_upper >= initial.current_upper
    assert revision.current_lower <= initial.current_lower
    assert revision.confirmed_at == _bar_end(6)
    assert series.points[10].transition is not None
    assert series.points[10].transition.kind == "confirmed"
    assert replacement.range_id != initial.range_id
    assert next(
        item for item in series.ranges if item.range_id == revision.range_id and item.revision == revision.revision
    ).levels_active_until == replacement.levels_active_from


def test_every_ready_prefix_matches_the_full_run() -> None:
    from guiyi_quant.indicators import range_detector_lux_series

    closes = [10.0, 10.0, 10.0, 10.0, 5.0, 5.0, 5.0, 15.0, 15.0, 5.0, 10.0]
    highs = [close + 1 for close in closes]
    lows = [close - 1 for close in closes]
    bar_ends = [_bar_end(index) for index in range(len(closes))]
    full = range_detector_lux_series(
        highs,
        lows,
        closes,
        bar_ends=bar_ends,
        source_identity="test:actual_dominant:jm:1d",
        minimum_range_length=3,
        range_atr_length=3,
    )

    for end in range(1, len(closes) + 1):
        prefix = range_detector_lux_series(
            highs[:end],
            lows[:end],
            closes[:end],
            bar_ends=bar_ends[:end],
            source_identity="test:actual_dominant:jm:1d",
            minimum_range_length=3,
            range_atr_length=3,
        )
        assert prefix.points == full.points[:end]


def test_ranges_use_a_visual_type_with_future_derived_level_end() -> None:
    from guiyi_quant.indicators import range_detector_lux_series

    bars = [
        *_constant_bars(4),
        {"high": 21.0, "low": 19.0, "close": 20.0, "bar_end": _bar_end(4)},
        {"high": 21.0, "low": 19.0, "close": 20.0, "bar_end": _bar_end(5)},
        {"high": 21.0, "low": 19.0, "close": 20.0, "bar_end": _bar_end(6)},
        {"high": 21.0, "low": 19.0, "close": 20.0, "bar_end": _bar_end(7)},
    ]
    series = range_detector_lux_series(
        [bar["high"] for bar in bars],
        [bar["low"] for bar in bars],
        [bar["close"] for bar in bars],
        bar_ends=[str(bar["bar_end"]) for bar in bars],
        source_identity="test:actual_dominant:jm:1d",
        minimum_range_length=3,
        range_atr_length=3,
    )

    assert series.ranges
    assert type(series.ranges[0]).__name__ == "RangeDetectorVisualRange"
    assert series.ranges[0].levels_active_until is None or isinstance(
        series.ranges[0].levels_active_until, str
    )


def test_range_detector_golden_fixture_has_canonical_hash_and_exact_python_output() -> None:
    from guiyi_quant.indicators import range_detector_lux_series

    fixture = json.loads(
        (REPO_ROOT / "tests/fixtures/range_detector_lux_v1_golden.json").read_text(
            encoding="utf-8"
        )
    )
    payload = {
        key: value for key, value in fixture.items() if key != "payload_sha256"
    }
    canonical = json.dumps(
        _canonical_hash_value(payload), sort_keys=True, separators=(",", ":")
    )
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == fixture[
        "payload_sha256"
    ]

    bars = fixture["bars"]
    result = range_detector_lux_series(
        [bar["high"] for bar in bars],
        [bar["low"] for bar in bars],
        [bar["close"] for bar in bars],
        bar_ends=[bar["bar_end"] for bar in bars],
        trading_days=[bar.get("trading_day") for bar in bars],
        source_identity=fixture["source_identity"],
        **fixture["parameters"],
    )
    actual = {
        "points": [_json_value(asdict(point)) for point in result.points],
        "ranges": [_json_value(asdict(item)) for item in result.ranges],
    }
    assert actual == fixture["expected"]


def test_range_detector_rounding_golden_uses_canonical_decimal_half_even() -> None:
    from guiyi_quant.indicators import range_detector_lux_series

    fixture = json.loads(
        (
            REPO_ROOT
            / "tests/fixtures/range_detector_lux_v1_rounding_golden.json"
        ).read_text(encoding="utf-8")
    )
    payload = {
        key: value for key, value in fixture.items() if key != "payload_sha256"
    }
    canonical = json.dumps(
        _canonical_hash_value(payload), sort_keys=True, separators=(",", ":")
    )
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == fixture[
        "payload_sha256"
    ]

    for case in fixture["cases"]:
        bars = case["bars"]
        result = range_detector_lux_series(
            [bar["high"] for bar in bars],
            [bar["low"] for bar in bars],
            [bar["close"] for bar in bars],
            bar_ends=[bar["bar_end"] for bar in bars],
            source_identity=case["source_identity"],
            **case["parameters"],
        )
        expected = case["expected"]
        confirmed = result.points[expected["confirmation_index"]]
        assert confirmed.snapshot is not None, case["name"]
        assert confirmed.snapshot.current_upper == expected["current_upper"], case["name"]
        assert confirmed.snapshot.current_lower == expected["current_lower"], case["name"]
        assert confirmed.snapshot.current_mid == expected["current_mid"], case["name"]
        assert confirmed.transition is not None, case["name"]
        assert confirmed.transition.kind == expected["confirmation_transition"], case["name"]
        break_index = expected["break_index"]
        if break_index is not None:
            broken = result.points[break_index]
            assert broken.snapshot is not None, case["name"]
            assert broken.snapshot.state == expected["break_state"], case["name"]
            assert broken.transition is not None, case["name"]
            assert broken.transition.kind == expected["break_transition"], case["name"]
