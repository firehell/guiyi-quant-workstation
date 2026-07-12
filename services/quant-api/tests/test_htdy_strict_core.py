from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
HTDY_STRICT_CORE_PATH = REPO_ROOT / "experiments" / "htdy_indicator" / "htdy_strict_core.py"


def load_htdy_strict():
    spec = importlib.util.spec_from_file_location("htdy_strict_core_for_tests", HTDY_STRICT_CORE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_htdy_strict_outputs_only_research_candidate_fields() -> None:
    htdy = load_htdy_strict()

    result = htdy.compute_synthetic(96)

    assert result.metadata["indicator_version"] == "huotian_dayou_strict_v1"
    assert result.metadata["source_version"] == "huotian_dayou_original_v0"
    assert result.metadata["xma_replacement_policy"] == "double_trailing_ema"
    assert result.metadata["status"] == "strict_research_candidate"
    assert result.metadata["closed_bar_only"] is True
    assert result.metadata["backtest_capable"] is False
    assert result.metadata["live_capable"] is False
    assert result.metadata["alert_capable"] is False
    assert result.metadata["trading_capable"] is False
    assert set(result.fields) == set(htdy.NUMERIC_FIELDS) | set(htdy.BOOLEAN_FIELDS)
    assert "xg2" not in result.fields
    assert "ddx" not in result.fields
    assert all(len(values) == 96 for values in result.fields.values())
    assert np.isfinite(result.fields["zk1"]).any()
    assert np.isfinite(result.fields["zd1"]).any()
    assert np.isfinite(result.fields["var23"]).any()


def test_htdy_strict_warmup_uses_nan_not_future_fill() -> None:
    htdy = load_htdy_strict()

    result = htdy.compute_synthetic(96)

    assert np.isnan(result.fields["zk1"][:48]).all()
    assert np.isfinite(result.fields["zk1"][48])
    assert np.isnan(result.fields["zd2"][:72]).all()
    assert np.isfinite(result.fields["zd2"][72])
    assert np.isnan(result.fields["var23"][:11]).all()
    assert np.isfinite(result.fields["var23"][11])
    assert not result.fields["yellow_candle"][:48].any()
    assert not result.fields["white_candle"][:48].any()


def test_htdy_strict_future_tail_does_not_repaint_history() -> None:
    htdy = load_htdy_strict()
    bars = htdy.synthetic_bars(120)
    changed_bars = {key: list(value) for key, value in bars.items()}
    changed_bars["high"][95] = changed_bars["high"][95] + 80.0
    changed_bars["low"][95] = changed_bars["low"][95] - 50.0
    changed_bars["close"][95] = changed_bars["close"][95] + 25.0

    original = htdy.compute_htdy_strict(
        bars["datetime"],
        bars["open"],
        bars["high"],
        bars["low"],
        bars["close"],
        bars["volume"],
    )
    changed = htdy.compute_htdy_strict(
        changed_bars["datetime"],
        changed_bars["open"],
        changed_bars["high"],
        changed_bars["low"],
        changed_bars["close"],
        changed_bars["volume"],
    )

    for name in htdy.NUMERIC_FIELDS:
        np.testing.assert_allclose(original.fields[name][:90], changed.fields[name][:90], equal_nan=True)
    for name in htdy.BOOLEAN_FIELDS:
        np.testing.assert_array_equal(original.fields[name][:90], changed.fields[name][:90])


def test_htdy_strict_append_consistency_matches_batch_calculation() -> None:
    htdy = load_htdy_strict()
    bars = htdy.synthetic_bars(96)
    batch = htdy.compute_htdy_strict(
        bars["datetime"],
        bars["open"],
        bars["high"],
        bars["low"],
        bars["close"],
        bars["volume"],
    )

    for end in range(1, 97):
        prefix = htdy.compute_htdy_strict(
            bars["datetime"][:end],
            bars["open"][:end],
            bars["high"][:end],
            bars["low"][:end],
            bars["close"][:end],
            bars["volume"][:end],
        )
        for name in htdy.NUMERIC_FIELDS:
            actual = prefix.fields[name][-1]
            expected = batch.fields[name][end - 1]
            if np.isnan(expected):
                assert np.isnan(actual), f"{name} at prefix {end}"
            else:
                assert actual == pytest.approx(expected), f"{name} at prefix {end}"
        for name in htdy.BOOLEAN_FIELDS:
            assert bool(prefix.fields[name][-1]) is bool(batch.fields[name][end - 1]), f"{name} at prefix {end}"


def test_htdy_strict_empty_short_and_invalid_inputs_have_explicit_behavior() -> None:
    htdy = load_htdy_strict()

    empty = htdy.compute_htdy_strict([], [], [], [], [], [])
    assert len(empty.datetimes) == 0
    assert all(len(values) == 0 for values in empty.fields.values())

    short = htdy.compute_synthetic(10)
    assert all(np.isnan(short.fields[name]).all() for name in htdy.NUMERIC_FIELDS)
    assert all(not short.fields[name].any() for name in htdy.BOOLEAN_FIELDS)

    bars = htdy.synthetic_bars(20)
    with pytest.raises(ValueError, match="channel_period must be positive"):
        htdy.compute_htdy_strict(
            bars["datetime"],
            bars["open"],
            bars["high"],
            bars["low"],
            bars["close"],
            bars["volume"],
            channel_period=0,
        )
    with pytest.raises(ValueError, match="input lengths must match"):
        htdy.compute_htdy_strict(bars["datetime"], bars["open"][:-1], bars["high"], bars["low"], bars["close"], bars["volume"])


def test_htdy_strict_risk_catalog_excludes_xg2_from_strict_v1() -> None:
    htdy = load_htdy_strict()

    catalog = htdy.strict_risk_catalog()

    assert catalog["DOUBLE_TRAILING_EMA"]["future_looking"] is False
    assert catalog["ZK1_ZD1_ZD2"]["classification"] == "strict_research_candidate"
    assert catalog["VAR23"]["future_looking"] is False
    assert catalog["XG_OBSERVATION"]["classification"] == "observation_candidate"
    assert catalog["XG2"]["classification"] == "excluded_from_strict_v1"
