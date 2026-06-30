from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))


def test_signal_candidates_reconstruct_final_long_signal() -> None:
    from export_su_bing_report_10_review_package import build_signal_candidate_rows, compute_indicator_frame

    start = datetime(2024, 1, 1, 15)
    closes = [100.0] * 28 + [80.0, 112.0]
    rows = []
    for index, close in enumerate(closes):
        rows.append(
            {
                "symbol": "jm",
                "contract": "jm.MAIN",
                "source_symbol": "jm2405",
                "datetime": start + timedelta(days=index),
                "trading_day": (start + timedelta(days=index)).date(),
                "open": close,
                "high": close + 5,
                "low": close - 5,
                "close": close,
                "volume": 1200.0 if index == len(closes) - 1 else 1000.0,
                "open_interest": 10000.0,
            }
        )
    indicator_frame = compute_indicator_frame(pd.DataFrame(rows))

    candidates = build_signal_candidate_rows(indicator_frame, entry_signal_times={start + timedelta(days=29): "long"})

    assert candidates[-1]["direction_candidate"] == "long"
    assert candidates[-1]["final_signal"] == "long"
    assert candidates[-1]["reject_reason"] == ""
    assert candidates[-1]["macd_cross_type"] == "golden_cross"
    assert candidates[-1]["macd_near_zero_25"] is True
    assert candidates[-1]["volume_expanded"] is True


def test_trade_review_rows_compute_holding_context_and_cross_contract_status() -> None:
    from export_su_bing_report_10_review_package import build_trade_review_rows, compute_indicator_frame

    start = datetime(2024, 1, 1, 15)
    frame = pd.DataFrame(
        [
            {
                "symbol": "jm",
                "contract": "jm.MAIN",
                "source_symbol": "jm2405",
                "datetime": start + timedelta(days=index),
                "trading_day": (start + timedelta(days=index)).date(),
                "open": 100.0 + index,
                "high": 110.0 if index == 2 else 105.0 + index,
                "low": 95.0 if index == 2 else 98.0 + index,
                "close": 101.0 + index,
                "volume": 1000.0 + index,
                "open_interest": 10000.0,
            }
            for index in range(5)
        ]
    )
    indicator_frame = compute_indicator_frame(frame)
    trade = {
        "trade_no": "SB-JM-D-X",
        "sequence": 1,
        "direction": "long",
        "entry_signal_time": (start + timedelta(days=0)).isoformat(),
        "open_time": (start + timedelta(days=1)).isoformat(),
        "open_price": 100.0,
        "exit_signal_time": (start + timedelta(days=2)).isoformat(),
        "close_time": (start + timedelta(days=3)).isoformat(),
        "close_price": 105.0,
        "entry_contract": "JM2405",
        "exit_contract": "JM2409",
        "gross_pnl": 300.0,
        "net_pnl": 220.0,
        "commission": 20.0,
        "slippage": 60.0,
        "margin_required": 12000.0,
        "holding_bars": 0,
        "entry_reason": "entry",
        "exit_reason": "exit",
        "contract_multiplier": 60,
        "volume": 1,
        "raw_payload": {"ema21": 99.0, "current_dif": 1.0, "current_dea": 0.0, "previous_dif": -1.0, "previous_dea": 0.0},
    }

    rows = build_trade_review_rows([trade], indicator_frame)

    assert rows[0]["trade_id"] == "SB-JM-D-X"
    assert rows[0]["is_cross_contract"] is True
    assert rows[0]["holding_bars_persisted_value"] == 0
    assert rows[0]["holding_bars_current_value"] == 2
    assert rows[0]["holding_bars_expected_value"] == 2
    assert rows[0]["holding_trading_days"] == 2
    assert rows[0]["max_favorable_excursion"] == 600.0
    assert rows[0]["max_adverse_excursion"] == -300.0
    assert rows[0]["mfe_r"] == ""
    assert rows[0]["mae_r"] == ""
    assert rows[0]["pnl_trust_status"] == "cross_contract_needs_review"


def test_trade_review_rows_use_persisted_holding_bars_when_available() -> None:
    from export_su_bing_report_10_review_package import build_trade_review_rows, compute_indicator_frame

    start = datetime(2024, 1, 1, 15)
    frame = pd.DataFrame(
        [
            {
                "symbol": "jm",
                "contract": "jm.MAIN",
                "source_symbol": "jm2405",
                "datetime": start + timedelta(days=index),
                "trading_day": (start + timedelta(days=index)).date(),
                "open": 100.0 + index,
                "high": 105.0 + index,
                "low": 98.0 + index,
                "close": 101.0 + index,
                "volume": 1000.0 + index,
                "open_interest": 10000.0,
            }
            for index in range(5)
        ]
    )
    indicator_frame = compute_indicator_frame(frame)
    trade = {
        "trade_no": "SB-JM-D-Y",
        "sequence": 1,
        "direction": "long",
        "entry_signal_time": (start + timedelta(days=0)).isoformat(),
        "open_time": (start + timedelta(days=1)).isoformat(),
        "open_price": 100.0,
        "exit_signal_time": (start + timedelta(days=2)).isoformat(),
        "close_time": (start + timedelta(days=3)).isoformat(),
        "close_price": 105.0,
        "entry_contract": "JM2405",
        "exit_contract": "JM2405",
        "gross_pnl": 300.0,
        "net_pnl": 220.0,
        "commission": 20.0,
        "slippage": 60.0,
        "margin_required": 12000.0,
        "holding_bars": 2,
        "entry_reason": "entry",
        "exit_reason": "exit",
        "contract_multiplier": 60,
        "volume": 1,
        "raw_payload": {"ema21": 99.0, "current_dif": 1.0, "current_dea": 0.0, "previous_dif": -1.0, "previous_dea": 0.0},
    }

    rows = build_trade_review_rows([trade], indicator_frame)

    assert rows[0]["holding_bars_persisted_value"] == 2
    assert rows[0]["holding_bars_current_value"] == 2
    assert rows[0]["holding_bars_expected_value"] == 2
    assert rows[0]["holding_trading_days"] == 2
    assert rows[0]["issue_reason"] == ""


def test_trusted_exclusion_summary_excludes_cross_contract_and_untrusted_pnl() -> None:
    from export_su_bing_report_10_review_package import build_trusted_exclusion_summary

    trade_rows = [
        {
            "trade_id": "SB-JM-D-1",
            "entry_contract": "JM2401",
            "exit_contract": "JM2401",
            "is_cross_contract": False,
            "net_pnl": "12550.461",
            "pnl_trust_status": "traceable_same_contract",
        },
        {
            "trade_id": "SB-JM-D-2",
            "entry_contract": "JM2405",
            "exit_contract": "JM2405",
            "is_cross_contract": False,
            "net_pnl": "-4823.208",
            "pnl_trust_status": "traceable_same_contract",
        },
        {
            "trade_id": "SB-JM-D-3",
            "entry_contract": "JM2405",
            "exit_contract": "JM2409",
            "is_cross_contract": True,
            "net_pnl": "4060.38",
            "pnl_trust_status": "cross_contract_needs_review",
        },
        {
            "trade_id": "SB-JM-D-4",
            "entry_contract": "JM2409",
            "exit_contract": "JM2409",
            "is_cross_contract": False,
            "net_pnl": "7449.663",
            "pnl_trust_status": "traceable_same_contract",
        },
        {
            "trade_id": "SB-JM-D-5",
            "entry_contract": "JM2505",
            "exit_contract": "JM2505",
            "is_cross_contract": False,
            "net_pnl": "-1933.308",
            "pnl_trust_status": "traceable_same_contract",
        },
        {
            "trade_id": "SB-JM-D-6",
            "entry_contract": "JM2505",
            "exit_contract": "JM2505",
            "is_cross_contract": False,
            "net_pnl": "-1842.909",
            "pnl_trust_status": "traceable_same_contract",
        },
        {
            "trade_id": "SB-JM-D-7",
            "entry_contract": "JM2601",
            "exit_contract": "JM2601",
            "is_cross_contract": False,
            "net_pnl": "-6104.463",
            "pnl_trust_status": "traceable_same_contract",
        },
    ]

    summary = build_trusted_exclusion_summary(
        trade_rows,
        report_id=10,
        strategy_code="su_bing_jm_daily_ema21_macd_volume",
        strategy_version="v0.2.0-daily",
    )

    assert summary["metric_scope"] == "trade_level_only"
    assert summary["raw_trade_count"] == 7
    assert summary["trusted_trade_count"] == 6
    assert summary["excluded_trade_count"] == 1
    assert summary["cross_contract_trades"] == 1
    assert summary["excluded_trade_ids"] == "SB-JM-D-3"
    assert summary["raw_net_pnl"] == 9356.616
    assert summary["trusted_net_pnl"] == 5296.236
    assert summary["raw_win_rate"] == 0.4285714286
    assert summary["trusted_win_rate"] == 0.3333333333
    assert summary["raw_profit_loss_ratio"] == 2.1817815805
    assert summary["trusted_profit_loss_ratio"] == 2.7203857918
    assert summary["raw_max_consecutive_losses"] == 3
    assert summary["trusted_max_consecutive_losses"] == 3
    assert summary["trusted_max_drawdown"] == 0.0857869818
    assert summary["conclusion"] == "P0 partially closed: report 10 has trade-level trusted metrics after excluding cross-contract PnL."


def test_trusted_exclusion_summary_excludes_untrusted_status_even_without_contract_change() -> None:
    from export_su_bing_report_10_review_package import build_trusted_exclusion_summary

    rows = [
        {
            "trade_id": "A",
            "entry_contract": "JM2405",
            "exit_contract": "JM2405",
            "is_cross_contract": False,
            "net_pnl": "100",
            "pnl_trust_status": "traceable_same_contract",
        },
        {
            "trade_id": "B",
            "entry_contract": "JM2405",
            "exit_contract": "JM2405",
            "is_cross_contract": False,
            "net_pnl": "200",
            "pnl_trust_status": "untrusted_cross_contract_pnl",
        },
    ]

    summary = build_trusted_exclusion_summary(rows, report_id=10, strategy_code="s", strategy_version="v")

    assert summary["trusted_trade_count"] == 1
    assert summary["excluded_trade_count"] == 1
    assert summary["excluded_trade_ids"] == "B"
    assert summary["trusted_net_pnl"] == 100.0


def test_skill_alignment_template_does_not_invent_skill_rules() -> None:
    from export_su_bing_report_10_review_package import build_skill_alignment_template

    content = build_skill_alignment_template()

    assert "su_bing_skill_rule" in content
    assert "| 趋势方向 |" in content
    assert "待填写" in content
    assert "课程原文" not in content


def test_score2of4_distribution_groups_scores_conditions_and_trusted_metrics() -> None:
    from export_su_bing_daily_score2of4_package import build_score_distribution_summary, build_score_distribution_markdown

    trades = [
        {
            "trade_id": "S2-1",
            "net_pnl": 1000,
            "entry_score": 2,
            "satisfied_conditions": ["long_trend_ok", "volume_expanded"],
            "is_cross_contract": False,
            "pnl_trust_status": "traceable_same_contract",
        },
        {
            "trade_id": "S2-2",
            "net_pnl": -300,
            "entry_score": 3,
            "satisfied_conditions": ["short_trend_ok", "macd_near_zero", "short_macd_cross"],
            "is_cross_contract": False,
            "pnl_trust_status": "traceable_same_contract",
        },
        {
            "trade_id": "S2-3",
            "net_pnl": 500,
            "entry_score": 4,
            "satisfied_conditions": ["long_trend_ok", "macd_near_zero", "long_macd_cross", "volume_expanded"],
            "is_cross_contract": True,
            "pnl_trust_status": "cross_contract_needs_review",
        },
    ]
    candidates = [
        {"entry_score": 2, "satisfied_conditions": ["long_trend_ok", "volume_expanded"]},
        {"entry_score": 2, "satisfied_conditions": ["macd_near_zero", "volume_expanded"]},
        {"entry_score": 3, "satisfied_conditions": ["short_trend_ok", "macd_near_zero", "short_macd_cross"]},
        {"entry_score": 4, "satisfied_conditions": ["long_trend_ok", "macd_near_zero", "long_macd_cross", "volume_expanded"]},
    ]

    summary = build_score_distribution_summary(trades, candidates)
    content = build_score_distribution_markdown(summary)

    assert summary["candidate_score_counts"][2] == 2
    assert summary["trade_score_stats"][2]["trade_count"] == 1
    assert summary["trade_score_stats"][2]["trusted_net_pnl"] == 1000.0
    assert summary["trade_score_stats"][4]["trusted_trade_count"] == 0
    assert summary["condition_combo_counts"]["long_trend_ok+volume_expanded"] == 1
    assert "| score=2 | 2 | 1 | 1000.0 |" in content
    assert "long_trend_ok+volume_expanded" in content


def test_score2of4_scene_tag_summary_excludes_cross_contract_from_trusted_pnl() -> None:
    from export_su_bing_daily_score2of4_package import build_scene_tag_summary

    trades = [
        {
            "trade_id": "S2-1",
            "net_pnl": 1000,
            "scene_tags": ["standard_trend", "trend_continuation"],
            "is_cross_contract": False,
            "pnl_trust_status": "traceable_same_contract",
        },
        {
            "trade_id": "S2-2",
            "net_pnl": 5000,
            "scene_tags": ["standard_trend"],
            "is_cross_contract": True,
            "pnl_trust_status": "cross_contract_needs_review",
        },
        {
            "trade_id": "S2-3",
            "net_pnl": -300,
            "scene_tags": ["weak_two_condition"],
            "is_cross_contract": False,
            "pnl_trust_status": "traceable_same_contract",
        },
    ]

    summary = build_scene_tag_summary(trades)

    assert summary["standard_trend"]["trade_count"] == 2
    assert summary["standard_trend"]["trusted_trade_count"] == 1
    assert summary["standard_trend"]["net_pnl"] == 6000.0
    assert summary["standard_trend"]["trusted_net_pnl"] == 1000.0
    assert summary["weak_two_condition"]["max_loss"] == -300.0
