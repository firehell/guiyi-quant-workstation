from __future__ import annotations

import json
from pathlib import Path
import sys
import time

import pytest

from app.backtest import runner as runner_module
from app.backtest.artifact_store import ArtifactStore
from app.backtest.config import BacktestSettings
from app.backtest.contracts import BacktestRunRequest
from app.backtest.registry import StrategyRegistry
from app.backtest.runner import SubprocessRunner
from app.backtest.service import BacktestService


def test_fake_subprocess_end_to_end_publishes_complete_research_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    runs = tmp_path / "runs"
    runs.mkdir()
    strategies = tmp_path / "strategies"
    strategies.mkdir()
    (strategies / "example.py").write_text("def init(context): pass\n", "utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "strategies": [
                    {
                        "id": "example",
                        "name": "Example",
                        "description": "Fixture strategy",
                        "enabled": True,
                        "entry_file": "example.py",
                        "supported_frequencies": ["1d"],
                        "defaults": {
                            "future_cash": "1000000",
                            "matching_type": "current_bar",
                            "margin_multiplier": "1",
                            "futures_commission_multiplier": "1",
                            "slippage_model": "PriceRatioSlippage",
                            "slippage": "0",
                        },
                        "parameters": [],
                    }
                ],
            }
        ),
        "utf-8",
    )
    fake_runner = tmp_path / "fake_runner.py"
    fake_runner.write_text(
        """
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument("--probe", action="store_true")
group.add_argument("--run-root", type=Path)
parser.add_argument("--launch-fd", type=int)
args = parser.parse_args()
if args.probe:
    print(json.dumps({"rqalpha_version": "fake-rqalpha-e2e", "rqsdk_version": "fake-rqsdk-e2e", "python_version": "fake-python-e2e"}))
    raise SystemExit(0)
root = args.run_root
assert args.launch_fd is not None
assert os.read(args.launch_fd, 3) == b"GO\\n"
record = json.loads((root / "run.json").read_text("utf-8"))
assert record["effective_config"]["base"]["run_type"] == "b"
assert record["effective_config"]["base"]["auto_update_bundle"] is False
(root / "result.pkl").write_bytes(b"fake-pickle")
(root / "equity.png").write_bytes(b"fake-png")
(root / "report" / "summary.csv").write_text("metric,value\\n", "utf-8")
(root / "result.json").write_text(json.dumps({
    "summary": {
        "total_returns": "0.125", "annualized_returns": "0.25",
        "max_drawdown": "0.05", "sharpe": "1.5", "sortino": "2",
        "volatility": "0.2", "total_value": "1125000", "cash": "100000"
    },
    "equity": [{"date": "2026-01-05", "unit_net_value": "1.125"}],
    "trade_count": "1",
    "artifacts": {
        "report_zip": True, "result_pickle": True, "equity_png": True,
        "stdout_log": True, "stderr_log": True, "run_json": True
    }
}), "utf-8")
print("fake e2e complete")
""",
        "utf-8",
    )
    settings = BacktestSettings(
        python_executable=Path(sys.executable).resolve(),
        bundle_path=bundle.resolve(),
        runs_root=runs.resolve(),
        timeout_seconds=2,
        cors_origins=("http://127.0.0.1:5173",),
    )
    monkeypatch.setattr(runner_module, "_RUNNER_ENTRY_PATH", fake_runner)
    service = BacktestService(
        registry=StrategyRegistry.load(registry_path, strategies),
        store=ArtifactStore(settings),
        runner=SubprocessRunner(settings),
        repository_commit="cc8b4dd1fc2e684ef1d067a4d6798287cc87c5b4",
    )

    started = service.start_run(
        BacktestRunRequest.model_validate(
            {
                "strategy_id": "example",
                "start_date": "2026-01-05",
                "end_date": "2026-01-06",
                "frequency": "1d",
            }
        )
    )
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        detail = service.get_run(started["run_id"])
        if detail["status"] != "running":
            break
        time.sleep(0.01)

    assert detail["status"] == "succeeded"
    assert detail["result"]["summary"]["total_returns"] == "0.125"
    assert detail["stdout_tail"] == "fake e2e complete"
    assert service.store.read_lock() is None
    with service.open_artifact(started["run_id"], "result_pickle") as artifact:
        assert artifact.read() == b"fake-pickle"
    with service.open_artifact(started["run_id"], "report_zip") as artifact:
        assert artifact.read(2) == b"PK"
