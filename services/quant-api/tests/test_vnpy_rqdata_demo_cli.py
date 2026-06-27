from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEMO_SCRIPT = PROJECT_ROOT / "experiments" / "vnpy_rqdata_demo" / "run_demo.py"


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
