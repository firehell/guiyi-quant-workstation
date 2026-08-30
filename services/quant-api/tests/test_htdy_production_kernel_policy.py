from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_PATH = REPO_ROOT / "tests/fixtures/htdy_original_realtime_v1_golden.json"


def _bars(length: int, *, body: tuple[float, float] = (9.9, 10.1)) -> dict[str, list[float | str]]:
    return {
        "datetime": [f"2026-07-26T{index:02d}:00:00" for index in range(length)],
        "open": [body[0]] * length,
        "high": [10.0] * length,
        "low": [10.0] * length,
        "close": [body[1]] * length,
        "volume": [1000.0 + index for index in range(length)],
    }


def _compute(bars: dict[str, list[float | str]]):
    from guiyi_quant.indicators import compute_htdy_original

    return compute_htdy_original(
        bars["datetime"],
        bars["open"],
        bars["high"],
        bars["low"],
        bars["close"],
        bars["volume"],
    )


def test_xma25_uses_symmetric_clipped_single_and_double_dependency_windows() -> None:
    from guiyi_quant.indicators import xma

    values = np.zeros(80, dtype=float)
    values[42] = 100.0  # i + 12, where i = 30
    assert xma(values, 25)[30] == pytest.approx(100.0 / 25.0)
    values[42] = 0.0
    baseline = xma(xma(values, 25), 25)
    values[54] = 100.0  # i + 24, where i = 30
    at_horizon = xma(xma(values, 25), 25)
    values[54] = 0.0
    values[55] = 100.0  # i + 25
    past_horizon = xma(xma(values, 25), 25)

    assert at_horizon[30] == pytest.approx(100.0 / 625.0)
    assert past_horizon[30] == baseline[30] == 0.0


def test_xma6_normalizes_to_the_symmetric_seven_bar_window_and_ignores_nonfinite_values() -> None:
    from guiyi_quant.indicators import normalize_period, xma

    values = [0.0, 1.0, 2.0, math.nan, 4.0, 5.0, 6.0]

    assert normalize_period(6) == 7
    assert xma(values, 6)[3] == pytest.approx(3.0)
    assert math.isnan(xma([math.nan], 6)[0])


def test_htdy_original_is_aligned_for_empty_short_nan_and_rejects_bad_input_shapes() -> None:
    from guiyi_quant.indicators import compute_htdy_original

    empty = compute_htdy_original([], [], [], [], [], [])
    assert all(len(getattr(empty, name)) == 0 for name in ("zk1", "zd1", "zd2", "yellow_candle", "buy_observation"))

    short = compute_htdy_original(["t0"], [1.0], [math.nan], [0.0], [1.0], [1.0])
    assert len(short.zk1) == len(short.zd1) == len(short.buy_observation) == 1
    assert math.isnan(short.zk1[0])
    assert short.buy_observation.tolist() == [False]

    with pytest.raises(ValueError, match="input lengths must match"):
        compute_htdy_original(["t0"], [1.0], [2.0], [0.0], [1.0], [])
    with pytest.raises(ValueError, match="period must be positive"):
        compute_htdy_original(["t0"], [1.0], [2.0], [0.0], [1.0], [1.0], channel_period=0)
    with pytest.raises(ValueError, match="channel_period must be exactly 25"):
        compute_htdy_original(["t0"], [1.0], [2.0], [0.0], [1.0], [1.0], channel_period=24)


@pytest.mark.parametrize(
    ("datetimes", "open_values", "high_values", "error"),
    [
        ("2026-07-26T00:00:00", [1.0], [2.0], "datetimes must be one-dimensional"),
        (np.array([["2026-07-26T00:00:00"]], dtype=object), [1.0], [2.0], "datetimes must be one-dimensional"),
        ([["t0"], ["t1", "t2"]], [1.0, 1.0], [2.0, 2.0], "datetimes must be one-dimensional"),
        (["t0", "t1"], 1.0, [2.0, 2.0], "open must be a one-dimensional numeric sequence"),
        (["t0", "t1"], [1.0, 1.0], np.array([[2.0], [2.0]]), "high must be a one-dimensional numeric sequence"),
        (["t0", "t1"], [[1.0], [1.0, 2.0]], [2.0, 2.0], "open must be a one-dimensional numeric sequence"),
        (["t0", "t1"], np.array([1.0, object()], dtype=object), [2.0, 2.0], "open must be a one-dimensional numeric sequence"),
    ],
)
def test_htdy_original_fail_closes_non_one_dimensional_or_non_numeric_inputs(
    datetimes, open_values, high_values, error: str
) -> None:
    from guiyi_quant.indicators import compute_htdy_original

    with pytest.raises(ValueError, match=error):
        compute_htdy_original(datetimes, open_values, high_values, [0.0, 0.0], [1.0, 1.0], [1.0, 1.0])


def test_normalized_payload_canonicalizes_datetime_values_and_rejects_unsupported_values() -> None:
    from guiyi_quant.indicators import compute_htdy_original

    values = [
        "unchanged-time-string",
        datetime(2026, 7, 26, 12, 34, 56),
        date(2026, 7, 27),
        np.datetime64("2026-07-28T12:34:56"),
        datetime(2026, 7, 29, 12, 34, 56, tzinfo=timezone.utc),
    ]
    result = compute_htdy_original(values, [1.0] * 5, [2.0] * 5, [0.0] * 5, [1.0] * 5, [1.0] * 5)
    payload = result.normalized_payload()

    assert [bar["datetime"] for bar in payload["bars"]] == [
        "unchanged-time-string",
        "2026-07-26T12:34:56",
        "2026-07-27",
        "2026-07-28T12:34:56",
        "2026-07-29T12:34:56+00:00",
    ]
    json.dumps(payload)

    unsupported = compute_htdy_original([object()], [1.0], [2.0], [0.0], [1.0], [1.0])
    with pytest.raises(ValueError, match="datetime.*JSON-serializable"):
        unsupported.normalized_payload()


def test_buy_sell_and_conflict_only_fire_on_the_new_third_consecutive_candle() -> None:
    bars = _bars(5)
    result = _compute(bars)

    assert result.yellow_candle.tolist() == [True] * 5
    assert result.white_candle.tolist() == [True] * 5
    assert result.buy_observation.tolist() == [False, False, True, False, False]
    assert result.sell_observation.tolist() == [False, False, True, False, False]
    assert result.observation_conflict.tolist() == [False, False, True, False, False]


def test_future_tail_can_make_an_old_buy_observation_appear_or_disappear() -> None:
    # The production regression this catches: treat XMA as trailing or use the old off-by-one window.
    appear = _bars(54)
    for index in (28, 29):
        appear["open"][index], appear["close"][index] = 9.9, 10.1
    appear["open"][27], appear["close"][27] = 10.1, 10.2
    appear["open"][30], appear["close"][30] = 10.1, 10.2
    before_appear = _compute(appear)
    appear["datetime"].append("2026-07-28T06:00:00")
    for key in ("open", "high", "low", "close", "volume"):
        appear[key].append(100.0 if key in {"high", "low"} else 10.0)
    after_appear = _compute(appear)

    assert bool(before_appear.buy_observation[30]) is False
    assert bool(after_appear.buy_observation[30]) is True
    append_changed = _changed_observation_indexes(before_appear, after_appear, original_length=54)
    assert append_changed == {"buy": [30, 33], "sell": []}
    assert _all_inside_repaint_zone(append_changed, original_length=54)

    disappear = _bars(55)
    disappear["open"][27] = disappear["close"][27] = 10.0
    before_disappear = _compute(disappear)
    disappear["high"][54] = 100.0
    disappear["low"][54] = 100.0
    after_disappear = _compute(disappear)

    assert bool(before_disappear.sell_observation[30]) is True
    assert bool(after_disappear.sell_observation[30]) is False
    revision_changed = _changed_observation_indexes(before_disappear, after_disappear, original_length=55)
    assert revision_changed == {"buy": [], "sell": [30]}
    assert _all_inside_repaint_zone(revision_changed, original_length=55)


def test_exact_24_bar_future_horizon_and_27_bar_repaint_scan_zone_cover_signal_changes() -> None:
    bars = _bars(54)
    bars["open"][27], bars["close"][27] = 10.1, 10.2
    bars["open"][30], bars["close"][30] = 10.1, 10.2
    baseline = _compute(bars)
    bars["datetime"].append("2026-07-28T06:00:00")
    for key in ("open", "high", "low", "close", "volume"):
        bars[key].append(100.0 if key in {"high", "low"} else 10.0)
    changed = _compute(bars)

    numeric_changed = [
        index
        for index, (left, right) in enumerate(zip(baseline.zk1, changed.zk1[: len(baseline.zk1)], strict=True))
        if not np.isclose(left, right, equal_nan=True)
    ]
    signal_changed = [
        index
        for index, (left, right) in enumerate(
            zip(baseline.buy_observation, changed.buy_observation[: len(baseline.buy_observation)], strict=True)
        )
        if left != right
    ]

    assert numeric_changed == list(range(30, 54))
    assert signal_changed == [30, 33]
    assert all(index >= len(baseline.zk1) - 27 for index in numeric_changed + signal_changed)
    assert changed.metadata["future_dependency_horizon_bars"] == 24
    assert changed.metadata["configured_repaint_scan_zone_bars"] == 27


def test_production_metadata_and_source_hash_are_repeatable_and_bound_to_module_bytes() -> None:
    from guiyi_quant.indicators import compute_htdy_original, htdy_original_source_sha256
    import guiyi_quant.indicators.htdy_original as module

    result = compute_htdy_original([], [], [], [], [], [])
    expected = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()

    assert htdy_original_source_sha256() == expected
    assert result.metadata["source_sha256"] == expected
    assert result.metadata["indicator_code"] == "huotian_dayou_original_v0"
    assert result.metadata["indicator_version"] == "original-v0"
    assert result.metadata["status"] == "observation_only"
    assert result.metadata["alert_capable"] is True
    assert result.metadata["future_looking"] is True
    assert result.metadata["repainting_accepted"] is True
    assert result.metadata["historical_backtest_allowed"] is False
    assert result.metadata["xma6_oracle_status"] == "externally_unresolved"


def test_source_hash_is_sensitive_to_the_module_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import guiyi_quant.indicators.htdy_original as module

    original = module.htdy_original_source_sha256()
    altered = tmp_path / "htdy_original.py"
    altered.write_bytes(Path(module.__file__).read_bytes() + b"\n# hash sensitivity fixture\n")
    monkeypatch.setattr(module, "__file__", str(altered))

    assert module.htdy_original_source_sha256() != original


def test_realtime_repainting_policy_accepts_only_the_frozen_exact_identity_and_hashes_canonically() -> None:
    from guiyi_quant.indicators import (
        RealtimeRepaintingObservationPolicy,
        realtime_observation_policy_sha256,
        require_realtime_repainting_observation_policy,
    )

    policy = require_realtime_repainting_observation_policy(RealtimeRepaintingObservationPolicy())
    raw = policy.to_dict()
    canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert realtime_observation_policy_sha256() == hashlib.sha256(canonical).hexdigest()
    changed_canonical = json.dumps(
        {**raw, "detection_mode": "latest"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert hashlib.sha256(changed_canonical).hexdigest() != realtime_observation_policy_sha256()

    for field, value in {
        "product": "rb",
        "contract_mode": "continuous",
        "main_contract_rank": 2,
        "period": "5m",
        "source_mode": "live_confirmed",
        "strategy_version": "v2.0",
        "detection_mode": "latest",
        "auto_order": True,
    }.items():
        with pytest.raises(ValueError, match="REALTIME_REPAINTING_OBSERVATION_POLICY_INVALID"):
            require_realtime_repainting_observation_policy({**raw, field: value})
    with pytest.raises(ValueError, match="REALTIME_REPAINTING_OBSERVATION_POLICY_INVALID"):
        require_realtime_repainting_observation_policy({**raw, "unexpected": "field"})


def test_registry_remains_observation_only_and_formal_policy_still_rejects_original() -> None:
    from guiyi_quant.indicators import FORMAL_BACKTEST_CONSUMER, get_indicator, require_formal_policy

    definition = get_indicator("huo_tian_da_you")
    assert definition.indicator_version == "original-v0"
    assert definition.calculation_source == "guiyi_quant.indicators.htdy_original.compute_htdy_original"
    assert definition.input_fields == ("open", "high", "low", "close", "volume")
    assert definition.status == "observation_only"
    assert (definition.backtest_capable, definition.live_capable, definition.alert_capable) == (False, False, True)

    with pytest.raises(ValueError, match="FORMAL_POLICY_CONSUMER_BLOCKED"):
        require_formal_policy("huotian_dayou_original_v0", consumer=FORMAL_BACKTEST_CONSUMER)


def test_tracked_golden_fixture_matches_normalized_production_payload_and_hash() -> None:
    fixture = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    bars = fixture["bars"]
    result = _compute({key: [row[key] for row in bars] for key in ("datetime", "open", "high", "low", "close", "volume")})
    payload = result.normalized_payload()

    numeric_outputs = (payload["outputs"]["zk1"], payload["outputs"]["zd1"], payload["outputs"]["zd2"])
    assert any(value is None for values in numeric_outputs for value in values)
    assert any(
        isinstance(value, float) and value != round(value, 6)
        for values in numeric_outputs
        for value in values
        if value is not None
    )
    for field in ("yellow_candle", "white_candle", "buy_observation", "sell_observation", "observation_conflict"):
        states = payload["outputs"][field]
        assert True in states, f"golden fixture must exercise a true {field} state"
        assert False in states, f"golden fixture must exercise a false {field} state"
    assert payload["bars"] == fixture["bars"]
    assert payload["outputs"] == fixture["expected"]["outputs"]
    assert payload["metadata"] == fixture["expected"]["metadata"]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == fixture["payload_sha256"]


def _changed_observation_indexes(before, after, *, original_length: int) -> dict[str, list[int]]:
    return {
        field: [
            index
            for index, (left, right) in enumerate(
                zip(getattr(before, f"{field}_observation"), getattr(after, f"{field}_observation")[:original_length], strict=True)
            )
            if left != right
        ]
        for field in ("buy", "sell")
    }


def _all_inside_repaint_zone(changed: dict[str, list[int]], *, original_length: int) -> bool:
    return all(index >= original_length - 27 for indexes in changed.values() for index in indexes)
