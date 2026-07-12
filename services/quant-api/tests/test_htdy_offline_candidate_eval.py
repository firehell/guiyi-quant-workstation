from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
OFFLINE_MODULE_PATH = REPO_ROOT / "experiments" / "htdy_indicator" / "offline_candidate_eval.py"


def load_offline_module():
    spec = importlib.util.spec_from_file_location("htdy_offline_candidate_eval_for_tests", OFFLINE_MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_htdy_offline_candidate_eval_keeps_version_and_capability_boundary() -> None:
    offline = load_offline_module()
    htdy = offline._load_module("htdy_strict_core_for_offline_test", REPO_ROOT / "experiments" / "htdy_indicator" / "htdy_strict_core.py")
    synthetic = htdy.synthetic_bars(120)
    bars = offline.OfflineBars(
        source_path=Path("/tmp/synthetic_jm_15m.parquet"),
        bars=synthetic,
        input_sha256=offline.stable_sha256(offline._serializable_bars(synthetic)),
        file_sha256="synthetic",
        lineage={
            "provider": "rqdata",
            "source": "rqdata",
            "data_role": "primary",
            "quality_status": "passed",
            "data_version": "rqdata_jm_standard_15m_20230103_20260710_v2",
            "symbol": "jm",
            "contract": "jm.MAIN",
            "period": "15m",
        },
    )

    payload = offline.evaluate_offline_candidate(bars)

    assert payload["status"] == "offline_backtest_candidate_eval"
    assert payload["strategy_code"] == "huotian_dayou_strict"
    assert payload["strategy_version"] == "v0.1.0-offline"
    assert len(payload["strategy_version"]) <= 32
    assert payload["candidate_policy"] == "strict_v1_15m_offline_v0"
    assert payload["fill_policy"] == "signal_on_close_fill_next_bar_open"
    assert payload["execution_scope"] == "offline_comparison_only"
    assert payload["event_interpretation"]["mode"] == "candidate_events_only"
    assert payload["event_interpretation"]["pnl_calculated"] is False
    assert payload["event_interpretation"]["trusted_backtest_report_created"] is False
    assert payload["capabilities"] == {
        "future_looking": False,
        "closed_bar_only": True,
        "backtest_candidate": True,
        "backtest_capable": False,
        "live_capable": False,
        "alert_capable": False,
        "trading_capable": False,
    }
    assert "BacktestReport" in payload["forbidden_integrations"]
    assert "signal_events" in payload["forbidden_integrations"]


def test_htdy_offline_candidate_events_use_next_bar_open_policy() -> None:
    offline = load_offline_module()
    htdy = offline._load_module("htdy_strict_core_for_event_test", REPO_ROOT / "experiments" / "htdy_indicator" / "htdy_strict_core.py")
    synthetic = htdy.synthetic_bars(120)
    bars = offline.OfflineBars(
        source_path=Path("/tmp/synthetic_jm_15m.parquet"),
        bars=synthetic,
        input_sha256=offline.stable_sha256(offline._serializable_bars(synthetic)),
        file_sha256="synthetic",
        lineage={
            "provider": "rqdata",
            "source": "rqdata",
            "data_role": "primary",
            "quality_status": "passed",
            "data_version": "rqdata_jm_standard_15m_20230103_20260710_v2",
            "symbol": "jm",
            "contract": "jm.MAIN",
            "period": "15m",
        },
    )

    payload = offline.evaluate_offline_candidate(bars)

    assert payload["events"]
    assert payload["event_counts"]["any_candidate_event"] == len(payload["events"])
    for event in payload["events"]:
        assert event["signal_confirmed_on"] == "current_bar_close"
        assert event["proposed_fill_policy"] == "signal_on_close_fill_next_bar_open"
        if event["index"] < payload["data"]["row_count"] - 1:
            assert event["proposed_fill_datetime"] is not None
            assert event["proposed_fill_open"] is not None
        assert set(event["event_type"].split("_candidate")) or event["event_type"] == "conflict_candidate"
        assert event["event_type"] in {"long_entry_candidate", "short_or_exit_candidate", "conflict_candidate"}


def test_htdy_offline_candidate_rejects_non_primary_passed_lineage(tmp_path: Path) -> None:
    offline = load_offline_module()
    htdy = offline._load_module("htdy_strict_core_for_lineage_test", REPO_ROOT / "experiments" / "htdy_indicator" / "htdy_strict_core.py")
    synthetic = htdy.synthetic_bars(80)
    table = pa.Table.from_pylist(
        [
            {
                **{column: synthetic[column][index] for column in offline.INPUT_COLUMNS},
                "provider": "rqdata",
                "source": "rqdata",
                "data_role": "candidate",
                "quality_status": "passed",
                "data_version": "rqdata_jm_standard_15m_20230103_20260710_v2",
                "symbol": "jm",
                "contract": "jm.MAIN",
                "period": "15m",
            }
            for index in range(80)
        ]
    )
    source = tmp_path / "wrong_lineage.parquet"
    pq.write_table(table, source)
    manifest = offline.load_manifest()

    with pytest.raises(ValueError, match="source lineage mismatch for data_role"):
        offline.read_offline_bars(source, manifest)


def test_htdy_offline_candidate_handles_short_window_without_events() -> None:
    offline = load_offline_module()
    htdy = offline._load_module("htdy_strict_core_for_short_test", REPO_ROOT / "experiments" / "htdy_indicator" / "htdy_strict_core.py")
    synthetic = htdy.synthetic_bars(10)
    bars = offline.OfflineBars(
        source_path=Path("/tmp/synthetic_short.parquet"),
        bars=synthetic,
        input_sha256=offline.stable_sha256(offline._serializable_bars(synthetic)),
        file_sha256="synthetic",
        lineage={
            "provider": "rqdata",
            "source": "rqdata",
            "data_role": "primary",
            "quality_status": "passed",
            "data_version": "rqdata_jm_standard_15m_20230103_20260710_v2",
            "symbol": "jm",
            "contract": "jm.MAIN",
            "period": "15m",
        },
    )

    payload = offline.evaluate_offline_candidate(bars)

    assert payload["data"]["row_count"] == 10
    assert payload["event_counts"] == {
        "long_entry_candidate": 0,
        "short_or_exit_candidate": 0,
        "conflict_candidate": 0,
        "any_candidate_event": 0,
    }
    assert payload["strict_summary"]["numeric"]["zk1"]["first_finite_index"] is None


def test_htdy_offline_candidate_writes_markdown_report(tmp_path: Path) -> None:
    offline = load_offline_module()
    payload = {
        "status": "offline_backtest_candidate_eval",
        "strategy_code": "huotian_dayou_strict",
        "strategy_version": "v0.1.0-offline",
        "indicator_version": "huotian_dayou_strict_v1",
        "candidate_policy": "strict_v1_15m_offline_v0",
        "execution_scope": "offline_comparison_only",
        "fill_policy": "signal_on_close_fill_next_bar_open",
        "data": {
            "lineage": {"provider": "rqdata", "data_role": "primary", "quality_status": "passed"},
            "start_datetime": "2026-01-01T00:00:00",
            "end_datetime": "2026-01-02T00:00:00",
            "row_count": 10,
            "input_sha256": "abc",
        },
        "event_counts": {
            "long_entry_candidate": 1,
            "short_or_exit_candidate": 2,
            "any_candidate_event": 3,
        },
    }
    report_path = tmp_path / "report.md"

    offline.write_markdown_report(payload, report_path)

    text = report_path.read_text(encoding="utf-8")
    assert "offline_backtest_candidate_eval" in text
    assert "v0.1.0-offline" in text
    assert "Candidate events only" in text
