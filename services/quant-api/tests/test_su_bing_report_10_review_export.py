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


def test_skill_alignment_template_does_not_invent_skill_rules() -> None:
    from export_su_bing_report_10_review_package import build_skill_alignment_template

    content = build_skill_alignment_template()

    assert "su_bing_skill_rule" in content
    assert "| 趋势方向 |" in content
    assert "待填写" in content
    assert "课程原文" not in content
