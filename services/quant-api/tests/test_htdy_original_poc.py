from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[3]
HTDY_CORE_PATH = REPO_ROOT / "experiments" / "htdy_indicator" / "htdy_original_core.py"


def load_htdy_core():
    spec = importlib.util.spec_from_file_location("htdy_original_core_for_tests", HTDY_CORE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_htdy_original_poc_outputs_complete_observation_fields() -> None:
    htdy = load_htdy_core()

    result = htdy.compute_synthetic(96)

    assert result.metadata["status"] == "observation_only"
    assert result.metadata["repainting_risk"] == "known"
    assert result.metadata["capital_branch"] == "futures_capital_0"
    assert result.metadata["from_open"] == 1.0
    assert result.metadata["backtest_capable"] is False
    assert result.metadata["live_capable"] is False
    assert result.metadata["alert_capable"] is False
    assert result.metadata["trading_capable"] is False
    assert result.metadata["output_fields"] == [
        "ZK1",
        "ZD1",
        "ZD2",
        "黄K",
        "白K",
        "买多信号",
        "卖空信号",
        "VAR23",
        "回调买",
        "XG",
        "DDX",
        "V2",
        "V5",
        "V10",
        "V20",
        "DY",
        "DY2",
        "XG2",
        "XG2_DRAWTEXT",
    ]
    assert set(result.fields) == set(htdy.NUMERIC_FIELDS) | set(htdy.BOOLEAN_FIELDS)
    assert all(len(values) == 96 for values in result.fields.values())
    assert np.isfinite(result.fields["ddx"]).any()
    assert np.isfinite(result.fields["v20"]).any()


def test_htdy_original_poc_uses_full_formula_yellow_white_rules() -> None:
    htdy = load_htdy_core()

    result = htdy.compute_synthetic(96)
    row = result.to_rows(original_names=True)[40]

    assert "黄K" in row
    assert "白K" in row
    assert "买多信号" in row
    assert "卖空信号" in row
    assert isinstance(row["黄K"], bool)
    assert isinstance(row["白K"], bool)


def test_htdy_new_third_consecutive_only_fires_once() -> None:
    htdy = load_htdy_core()

    flags = [False, True, True, True, True, False, True, True, True]

    result = htdy.new_third_consecutive(flags)

    assert result.tolist() == [False, False, False, True, False, False, False, False, True]


def test_htdy_xma_repaints_historical_channel_when_future_tail_changes() -> None:
    htdy = load_htdy_core()
    bars = htdy.synthetic_bars(96)
    changed_bars = {key: list(value) for key, value in bars.items()}
    changed_bars["high"][60] = changed_bars["high"][60] + 80.0

    original = htdy.compute_htdy_original(
        bars["datetime"],
        bars["open"],
        bars["high"],
        bars["low"],
        bars["close"],
        bars["volume"],
    )
    changed = htdy.compute_htdy_original(
        changed_bars["datetime"],
        changed_bars["open"],
        changed_bars["high"],
        changed_bars["low"],
        changed_bars["close"],
        changed_bars["volume"],
    )

    assert original.fields["zk1"][40] != changed.fields["zk1"][40]


def test_htdy_risk_catalog_keeps_xg_and_xg2_observation_only() -> None:
    htdy = load_htdy_core()

    catalog = htdy.indicator_risk_catalog()

    assert catalog["XMA"]["classification"] == "forbidden_for_backtest_signal"
    assert catalog["XMA"]["future_looking"] is True
    assert catalog["ZK1_ZD1_ZD2"]["depends_on"] == ["XMA"]
    assert catalog["VAR23"]["classification"] == "forbidden_for_backtest_signal"
    assert catalog["XG"]["classification"] == "observation_only"
    assert catalog["XG2"]["classification"] == "observation_only"
    assert catalog["DDX_V2_V5_V10_V20"]["classification"] == "candidate_after_rewrite"
