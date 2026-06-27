from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEMO_SCRIPT = PROJECT_ROOT / "experiments" / "vnpy_rqdata_demo" / "run_demo.py"


def _write_jm_period_parquet(path: Path, period: str, minute_step: int) -> dict[str, str | int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    start = datetime(2025, 1, 2, 9, minute_step)
    rows = []
    for index in range(10):
        moment = start + timedelta(minutes=minute_step * index)
        close = 1000.0 + index * 3
        rows.append(
            {
                "symbol": "jm",
                "contract": "jm.MAIN",
                "exchange": "DCE",
                "vt_symbol": "jm.MAIN.DCE",
                "datetime": moment,
                "trading_day": moment.date(),
                "interval": period,
                "period": period,
                "open": close - 1,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "volume": 100 + index,
                "turnover": close * (100 + index),
                "open_interest": 1000 + index,
                "source": "rqdata",
                "data_role": "primary",
                "quality_status": "passed",
            }
        )
    pd.DataFrame(rows).to_parquet(path, index=False)
    return {
        "path": str(path),
        "row_count": len(rows),
        "start_datetime": start.isoformat(),
        "end_datetime": rows[-1]["datetime"].isoformat(),
    }


def _write_jm_aggregate_result(tmp_path: Path) -> Path:
    aggregate_path = tmp_path / "rqdata_jm_aggregate_result.json"
    payload = {
        "mode": "jm-standard-aggregation",
        "symbol_mapping": {
            "symbol": "jm",
            "contract": "jm.MAIN",
            "exchange": "DCE",
            "project_vt_symbol": "jm.MAIN.DCE",
            "source_contracts": ["jm2505"],
        },
        "aggregates": {
            "5m": _write_jm_period_parquet(tmp_path / "jm_MAIN_5m.parquet", "5m", 5),
            "15m": _write_jm_period_parquet(tmp_path / "jm_MAIN_15m.parquet", "15m", 15),
        },
    }
    aggregate_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return aggregate_path


def test_demo_check_env_writes_environment_report(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(DEMO_SCRIPT), "--check-env", "--output-dir", str(tmp_path)],
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    output_path = tmp_path / "environment_check.json"
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "check-env"
    assert payload["rqdata_account_required"] is False
    assert payload["live_trading_used"] is False
    assert "vnpy_available" in payload


def test_demo_sample_writes_standard_json_without_real_accounts(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(DEMO_SCRIPT), "--sample", "--output-dir", str(tmp_path)],
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    output_path = tmp_path / "sample_standard_result.json"
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "sample"
    assert payload["task"]["engine_type"] == "vnpy"
    assert payload["task"]["data_role"] == "primary"
    assert payload["data_provider"]["mode"] == "sample_bars"
    assert payload["adapter"]["mode"] == "fake_vnpy_adapter"
    assert payload["standard_result"]["engine"] == "vnpy_cta_backtesting"
    assert payload["standard_result"]["trades"]
    assert payload["standard_result"]["equity_curve"]
    assert payload["live_trading_used"] is False
    assert "研究验证" in payload["disclaimer"]


def test_demo_backend_e2e_writes_report_query_payload_without_real_accounts(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(DEMO_SCRIPT), "--backend-e2e", "--output-dir", str(tmp_path)],
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    output_path = tmp_path / "backend_e2e_result.json"
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "backend-e2e"
    assert payload["database_mode"] == "isolated_sqlite"
    assert payload["rqdata_account_required"] is False
    assert payload["live_trading_used"] is False
    assert payload["report_id"] > 0
    assert payload["api"]["report_path"] == f"/api/backtests/reports/{payload['report_id']}"
    assert payload["api"]["trades_path"].endswith("/trades")
    assert payload["api"]["equity_curve_path"].endswith("/equity-curve")
    assert payload["api"]["drawdown_curve_path"].endswith("/drawdown-curve")
    assert payload["api"]["report_status"] == 200
    assert payload["api"]["trades_status"] == 200
    assert payload["api"]["equity_curve_status"] == 200
    assert payload["api"]["drawdown_curve_status"] == 200
    assert payload["counts"]["trades"] > 0
    assert payload["counts"]["equity_curve"] > 0
    assert payload["counts"]["drawdown_curve"] > 0
    assert "研究验证" in payload["disclaimer"]


def test_demo_jm_smoke_backtest_runs_5m_and_15m_without_external_accounts(tmp_path: Path) -> None:
    aggregate_result = _write_jm_aggregate_result(tmp_path)
    output_dir = tmp_path / "out"

    result = subprocess.run(
        [
            sys.executable,
            str(DEMO_SCRIPT),
            "--jm-smoke-backtest",
            "--jm-aggregate-result",
            str(aggregate_result),
            "--output-dir",
            str(output_dir),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    output_path = output_dir / "jm_real_smoke_backtest_result.json"
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "jm-real-vnpy-smoke-backtest"
    assert payload["rqdata_network_used"] is False
    assert payload["ctp_used"] is False
    assert payload["tqsdk_used"] is False
    assert set(payload["periods"]) == {"5m", "15m"}
    for period in ("5m", "15m"):
        summary = payload["periods"][period]
        assert summary["executed"] is True
        assert summary["raw_metadata"]["load_data_called"] is False
        assert summary["raw_metadata"]["vnpy_runtime_symbol"] == "jm_MAIN"
        assert summary["counts"]["trades"] >= 1
        assert summary["counts"]["equity_curve"] >= 1
        assert summary["counts"]["drawdown_curve"] >= 1
