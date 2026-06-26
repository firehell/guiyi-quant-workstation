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
