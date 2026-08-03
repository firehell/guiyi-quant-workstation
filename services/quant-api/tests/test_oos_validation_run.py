from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import oos_validation_run as oos  # noqa: E402


def _trade(*, net_pnl: float, commission: float = 10.0, slippage: float = 5.0) -> dict:
    return {
        "trade_id": f"T-{net_pnl}",
        "direction": "long",
        "entry_signal_time": "2024-01-02T09:00:00+00:00",
        "entry_time": "2024-01-02T09:15:00+00:00",
        "exit_time": "2024-01-02T10:00:00+00:00",
        "entry_price": 100.0,
        "exit_price": 101.0 if net_pnl >= 0 else 99.0,
        "volume": 1,
        "contract_multiplier": 60,
        "price_tick": 0.5,
        "commission": commission,
        "slippage": slippage,
        "net_pnl": net_pnl,
        "contract": "JM2405",
    }


def test_select_windows_filters_by_id() -> None:
    windows = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    selected = oos._select_windows(windows, ["a", "c"])
    assert [window["id"] for window in selected] == ["a", "c"]


def test_summarize_maps_report_metrics_fields() -> None:
    trades = [_trade(net_pnl=100.0), _trade(net_pnl=-40.0)]
    metrics = {
        "total_return": -0.05,
        "max_drawdown_pct": 0.12,
        "max_drawdown_amount": 12000.0,
        "max_consecutive_losses": 1,
        "win_rate": 0.5,
        "profit_loss_ratio": 2.5,
        "expectancy": 30.0,
        "total_commission": 20.0,
        "total_slippage": 10.0,
        "total_net_pnl": -5000.0,
        "initial_capital": 100000.0,
        "final_equity": 95000.0,
        "rollover_exit_count": 0,
        "delivery_risk_exit_count": 0,
    }
    summary = oos._summarize(metrics, trades)

    assert summary["trade_count"] == 2
    assert summary["total_return"] == -0.05
    assert summary["max_drawdown"] == 0.12
    assert summary["total_fee"] == 20.0
    assert summary["total_slippage"] == 10.0


def test_run_window_rejects_invalid_range_without_running_engine() -> None:
    result = oos._run_window(
        MagicMock(),
        MagicMock(),
        MagicMock(),
        {"id": "invalid", "start": "2026-07-10T15:00:00", "end": "2026-07-10T15:00:00"},
    )
    assert result == {"window_id": "invalid", "status": "failed", "error": "invalid window: start >= end"}


def test_render_markdown_reports_current_readonly_contract() -> None:
    rendered = oos._render_markdown(
        {"baseline_report_id": 14, "readonly": True, "persist_to_db": False, "windows": []}
    )
    assert "baseline_report_id: 14" in rendered
    assert "readonly: True" in rendered
    assert "persist_to_db: False" in rendered


def test_main_plan_only_does_not_run_backtests(tmp_path: Path) -> None:
    config_path = tmp_path / "frozen.json"
    config_path.write_text(
        json.dumps(
            {
                "baseline_report_id": 14,
                "frozen_strategy": {"strategy_code": "jm_v1b_daily_direction_fast_entry"},
                "windows": [{"id": "oos_fixed", "start": "2026-01-01T00:00:00", "end": "2026-07-10T15:00:00"}],
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "plan_only"

    exit_code = oos.main(["--config", str(config_path), "--format", "json", "--output-dir", str(output_dir)])

    assert exit_code == 0
    payload = json.loads((output_dir / "oos_validation.json").read_text(encoding="utf-8"))
    assert payload["persist_to_db"] is False
    assert payload["readonly"] is True
    assert payload["windows"][0]["status"] == "plan_only"


def test_main_run_is_disabled_before_profile_file_builder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "frozen.json"
    config_path.write_text(
        json.dumps(
            {
                "windows": [
                    {
                        "id": "oos_fixed",
                        "start": "2026-01-01T00:00:00",
                        "end": "2026-07-10T15:00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    exit_code = oos.main(["--config", str(config_path), "--run"])

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out)["error"] == (
        "BACKTEST_LEGACY_OOS_EXECUTION_DISABLED"
    )


def test_main_run_no_longer_writes_legacy_review_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "frozen.json"
    config_path.write_text(
        json.dumps(
            {
                "baseline_report_id": 14,
                "frozen_strategy": {"strategy_code": "jm_v1b_daily_direction_fast_entry"},
                "frozen_data_policy": {"quality_status": "passed"},
                "frozen_costs": {"rate": 0.0001, "slippage": 1.0, "size": 60, "pricetick": 0.5, "capital": 100000.0},
                "windows": [{"id": "oos_fixed", "label": "OOS", "start": "2026-01-01T00:00:00", "end": "2026-07-10T15:00:00"}],
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "run"

    fake_config = MagicMock()
    fake_config.model_copy.return_value = fake_config
    fake_config.request_payload = {}
    fake_config.symbol = "jm.MAIN"
    fake_config.exchange = "DCE"
    fake_config.interval = "15m"
    fake_config.start = datetime(2026, 1, 1, tzinfo=UTC)
    fake_config.end = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
    fake_config.rate = 0.0001
    fake_config.slippage = 1.0
    fake_config.size = 60
    fake_config.pricetick = 0.5
    fake_config.capital = 100000.0
    fake_config.strategy_class_path = "fake.strategy.Path"
    fake_config.strategy_parameters = {}
    fake_config.bar_data_path = "/Volumes/secret/path.parquet"
    fake_config.auxiliary_bar_data_paths = {}
    fake_config.execution_timing = "next_bar_open"
    fake_config.data_version = "v1b_jm_test"
    fake_config.quality_status = "passed"
    fake_config.strategy_code = "jm_v1b_daily_direction_fast_entry"

    fake_session = MagicMock()
    fake_session.__enter__.return_value = fake_session
    fake_session.__exit__.return_value = False
    fake_report = MagicMock()
    fake_report.id = 14
    fake_report.task_no = "BTV-TEST"
    fake_report.strategy_code = "jm_v1b_daily_direction_fast_entry"
    fake_report.strategy_version = "v1b.0"
    fake_report.period = "15m"
    fake_report.data_source = "local_parquet"
    fake_report.data_role = "primary"
    fake_report.data_version = "baseline-v1"
    fake_report.quality_status = {"status": "passed"}
    fake_report.summary = {"start": "2023-01-03", "end": "2025-12-31", "lineage_summary": {"mapped_trades": 1}}
    fake_report.order_rows = []
    fake_report.trade_count = 1
    fake_report.total_return = -0.1
    fake_report.max_drawdown_pct = 0.2
    fake_report.max_drawdown_amount = 20000.0
    fake_report.win_rate = 0.4
    fake_report.profit_loss_ratio = 1.2
    fake_report.max_consecutive_losses = 2
    fake_report.total_commission = 10.0
    fake_report.total_slippage = 5.0
    fake_report.initial_capital = 100000.0
    fake_report.final_equity = 90000.0
    fake_session.get.return_value = fake_report

    window_result = {
        "window_id": "oos_fixed",
        "status": "success",
        "summary": {
            "trade_count": 1,
            "total_return_pct": -5.0,
            "max_drawdown_pct": 0.1,
            "win_rate": 0.0,
            "profit_factor": None,
            "total_commission": 10.0,
            "total_slippage": 5.0,
        },
        "data_version": "v1b_jm_test",
        "quality_status": "passed",
    }

    monkeypatch.setattr(oos, "_run_window", lambda session, runner, config, window: window_result)

    exit_code = oos.main(["--config", str(config_path), "--run", "--format", "json", "--output-dir", str(output_dir)])

    assert exit_code == 2
    assert not (output_dir / "oos_validation.json").exists()
