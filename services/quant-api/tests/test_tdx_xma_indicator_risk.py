from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[3]
XMA_CORE_PATH = REPO_ROOT / "experiments" / "rqalpha_tdx_xma_bands" / "xma_core.py"


def load_xma_core():
    spec = importlib.util.spec_from_file_location("tdx_xma_core_for_tests", XMA_CORE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_xma_risk_catalog_marks_xma_and_derived_signals_as_future_looking() -> None:
    xma_core = load_xma_core()

    catalog = xma_core.indicator_risk_catalog()

    assert catalog["XMA"]["classification"] == "forbidden_for_backtest_signal"
    assert catalog["XMA"]["future_looking"] is True
    assert catalog["XMA"]["repainting"] is True
    assert catalog["ZK1_ZD1_ZD2"]["depends_on"] == ["XMA"]
    assert catalog["VAR23"]["future_looking"] is True
    assert catalog["XG"]["classification"] == "observation_only"
    assert catalog["XG2"]["currbarscount_semantics"] == "poc_current_bar_as_chart_last_bar"
    assert catalog["DDX"]["classification"] == "candidate_after_rewrite"


def test_xma_uses_future_bars_at_current_index() -> None:
    xma_core = load_xma_core()
    sample = np.array([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0], dtype=float)

    result = xma_core.xma(sample, 5)

    assert result[3] == 30.0
    assert result[3] == float(np.mean([10.0, 20.0, 30.0, 40.0, 50.0]))


def test_xma_repaints_historical_value_when_future_tail_changes() -> None:
    xma_core = load_xma_core()
    original = np.array([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0], dtype=float)
    changed_future = np.array([10.0, 20.0, 30.0, 40.0, 500.0, 600.0, 700.0], dtype=float)

    original_result = xma_core.xma(original, 5)
    changed_result = xma_core.xma(changed_future, 5)

    assert original_result[3] != changed_result[3]


def test_backward_looking_helpers_are_not_marked_as_future_looking() -> None:
    xma_core = load_xma_core()

    catalog = xma_core.indicator_risk_catalog()

    for name in ("REF", "MA", "EMA"):
        assert catalog[name]["future_looking"] is False
        assert catalog[name]["repainting"] is False
        assert catalog[name]["classification"] == "candidate_after_rewrite"
