"""Deterministic subprocess fixture for the backtest runner seam."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def _read_mode(run_root: Path) -> str:
    payload = json.loads((run_root / "strategy_params.json").read_text("utf-8"))
    return str(payload.get("fake_mode", "success"))


def _validate_safe_json_config(run_root: Path) -> None:
    record = json.loads((run_root / "run.json").read_text("utf-8"))
    config = record["effective_config"]
    assert set(config) == {"base", "mod"}
    assert config["base"]["accounts"] == {"FUTURE": "1000000"}
    assert config["base"]["margin_multiplier"] == "1"
    assert config["base"]["auto_update_bundle"] is False
    assert config["base"]["rqdatac_uri"] == "disabled"
    assert config["mod"]["sys_transaction_cost"] == {
        "enabled": True,
        "futures_commission_multiplier": "1",
    }
    assert config["mod"]["incremental"] == {"enabled": False}
    assert config["mod"]["sys_simulation"]["signal"] is False
    assert config["mod"]["ams"] == {"enabled": False}


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
    parser.add_argument("--launch-fd", type=int)
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

    if args.launch_fd is None or os.read(args.launch_fd, 3) != b"GO\n":
        return 2
    run_root = args.run_root
    assert run_root is not None
    _validate_safe_json_config(run_root)
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
    if mode == "descendant_timeout":
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import signal,time;"
                    "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                    "time.sleep(5)"
                ),
            ],
            stdin=subprocess.DEVNULL,
        )
        (run_root / "fake-descendant.pid").write_text(str(child.pid), "utf-8")
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(5)
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
    if mode == "redaction_chunks":
        os.write(1, b'prefix {"api_key":"abc\\"def-sensitive-suffix"} tail\n')
        os.write(2, b"password=" + (b"x" * 100_000) + b" end\n")
    if mode == "redaction_exact_boundary":
        os.write(1, (b"q" * 4096) + b"!")
    if mode == "redaction_long_credentials":
        os.write(
            1,
            b"redis://long-user:" + (b"r" * 9000) + b"@127.0.0.1:6379/0 done\n",
        )
        os.write(
            2,
            b"Authorization: Bearer " + (b"b" * 9000) + b" done\n",
        )
    _write_result(run_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
