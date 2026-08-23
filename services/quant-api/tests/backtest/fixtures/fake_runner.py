"""Deterministic subprocess fixture for the backtest runner seam."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time


def _read_mode(run_root: Path) -> str:
    payload = json.loads((run_root / "strategy_params.json").read_text("utf-8"))
    return str(payload.get("fake_mode", "success"))


def _write_result(run_root: Path) -> None:
    payload = {
        "summary": {
            "total_returns": "0.125",
            "annualized_returns": "0.25",
            "max_drawdown": "0.05",
            "sharpe": "1.5",
            "sortino": "2",
            "volatility": "0.2",
            "total_value": "1125000",
            "cash": "100000",
        },
        "equity": [
            {"date": "2026-01-05", "unit_net_value": "1"},
            {"date": "2026-01-06", "unit_net_value": "1.125"},
        ],
        "trade_count": "1",
        "artifacts": {
            "report_zip": False,
            "result_pickle": False,
            "equity_png": False,
            "stdout_log": True,
            "stderr_log": True,
            "run_json": True,
        },
    }
    (run_root / "result.json").write_text(
        json.dumps(payload, sort_keys=True), encoding="utf-8"
    )


def _write_malformed_result(run_root: Path) -> None:
    payload = {
        "summary": {
            name: "0"
            for name in (
                "total_returns",
                "annualized_returns",
                "max_drawdown",
                "sharpe",
                "sortino",
                "volatility",
                "total_value",
                "cash",
            )
        },
        "equity": [{"date": "not-a-date", "unit_net_value": "not-a-number"}],
        "trade_count": "-1",
        "artifacts": {},
    }
    (run_root / "result.json").write_text(json.dumps(payload), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--probe", action="store_true")
    group.add_argument("--run-root", type=Path)
    args = parser.parse_args()
    if args.probe:
        print(
            json.dumps(
                {
                    "rqalpha_version": "fake-rqalpha-1",
                    "rqsdk_version": "fake-rqsdk-1",
                    "python_version": "fake-python-1",
                }
            )
        )
        return 0

    run_root = args.run_root
    assert run_root is not None
    mode = _read_mode(run_root)
    if mode == "failure":
        print("fake strategy failure", file=sys.stderr)
        return 7
    if mode == "incomplete":
        return 0
    if mode == "malformed":
        _write_malformed_result(run_root)
        return 0
    if mode == "timeout":
        time.sleep(30)
        return 0
    if mode == "ignore_terminate":
        signal.signal(signal.SIGTERM, lambda *_args: None)
        time.sleep(30)
        return 0
    if mode == "redaction":
        print('token="stdout-secret" password=stdout-password')
        print('{"api_key":"child-json-secret"}')
        print(
            "redis://redis-user:redis-password@127.0.0.1:6379/0",
            file=sys.stderr,
        )
        print(
            json.dumps(
                {
                    "DATABASE_URL": os.environ.get("DATABASE_URL"),
                    "REDIS_URL": os.environ.get("REDIS_URL"),
                    "PUSHPLUS_TOKEN": os.environ.get("PUSHPLUS_TOKEN"),
                    "RQDATA_USERNAME": os.environ.get("RQDATA_USERNAME"),
                },
                sort_keys=True,
            )
        )
        print(
            json.dumps(
                {
                    "SENSITIVE_ENV_PRESENT": any(
                        os.environ.get(name)
                        for name in (
                            "DATABASE_URL",
                            "REDIS_URL",
                            "PUSHPLUS_TOKEN",
                            "RQDATA_USERNAME",
                        )
                    )
                }
            )
        )
    _write_result(run_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
