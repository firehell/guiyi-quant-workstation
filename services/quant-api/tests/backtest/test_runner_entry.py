from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import pytest

from app.backtest import runner_entry
from app.backtest.result_projection import project_result


class _Portfolio:
    columns = ("unit_net_value",)

    def iterrows(self):
        yield datetime(2026, 1, 5), {"unit_net_value": Decimal("1.000")}
        yield date(2026, 1, 6), {"unit_net_value": Decimal("1.1250")}


def _raw_result() -> dict[str, Any]:
    return {
        "sys_analyser": {
            "summary": {
                "total_returns": Decimal("0.1250"),
                "annualized_returns": 0.25,
                "max_drawdown": Decimal("0.050"),
                "sharpe": 1.5,
                "sortino": Decimal("2.0"),
                "volatility": 0.2,
                "total_value": Decimal("1125000.00"),
                "cash": 100000,
                "benchmark_total_returns": Decimal("999"),
            },
            "portfolio": _Portfolio(),
            "trades": [{"price": Decimal("3500")}, {"price": Decimal("3510")}],
        }
    }


def _effective_config(run_root: Path) -> dict[str, Any]:
    return {
        "base": {
            "start_date": "2026-01-05",
            "end_date": "2026-01-06",
            "frequency": "1d",
            "accounts": {"future": "1000000"},
            "data_bundle_path": str(run_root.parent.parent / "bundle"),
            "auto_update_bundle": False,
            "rqdatac_uri": "disabled",
        },
        "mod": {
            "sys_simulation": {
                "enabled": True,
                "matching_type": "current_bar",
                "margin_multiplier": "1",
                "commission_multiplier": "1",
                "slippage_model": "PriceRatioSlippage",
                "slippage": "0",
                "signal": False,
            },
            "sys_analyser": {
                "enabled": True,
                "record": True,
                "output_file": str(run_root / "result.pkl"),
                "report_save_path": str(run_root / "report"),
                "plot": True,
                "plot_save_file": str(run_root / "equity.png"),
            },
            "sys_progress": {"enabled": True, "show": False},
            "ams": {"enabled": False},
        },
        "incremental": {"enabled": False},
    }


def _run_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs" / "run-001"
    root.mkdir(parents=True)
    (root / "report").mkdir()
    (root / "strategy.py").write_text("def init(context): pass\n", "utf-8")
    (root / "strategy_params.json").write_text(json.dumps({"quantity": 1}), "utf-8")
    (root / "run.json").write_text(
        json.dumps({"effective_config": _effective_config(root)}), "utf-8"
    )
    (root.parent.parent / "bundle").mkdir()
    (root / "stdout.log").write_text("", "utf-8")
    (root / "stderr.log").write_text("", "utf-8")
    return root


def test_project_result_uses_fixed_summary_equity_and_decimal_strings(
    tmp_path: Path,
) -> None:
    root = _run_root(tmp_path)
    (root / "result.pkl").write_bytes(b"not a pickle and must never be read")
    (root / "equity.png").write_bytes(b"png")
    (root / "report" / "summary.csv").write_text("x", "utf-8")

    projected = project_result(_raw_result(), root)

    assert projected == {
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
        "trade_count": "2",
        "artifacts": {
            "report_zip": True,
            "result_pickle": True,
            "equity_png": True,
            "stdout_log": True,
            "stderr_log": True,
            "run_json": True,
        },
    }


def test_runner_entry_calls_run_file_and_atomically_writes_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _run_root(tmp_path)
    (root / "result.pkl").write_bytes(b"malformed pickle")
    (root / "equity.png").write_bytes(b"png")
    (root / "report" / "summary.csv").write_text("x", "utf-8")
    observed: dict[str, Any] = {}
    rqalpha = ModuleType("rqalpha")

    def run_file(strategy_file_path: str, config: dict[str, Any]) -> dict[str, Any]:
        observed["strategy_file_path"] = strategy_file_path
        observed["config"] = config
        observed["params_env"] = os.environ.get("GUIYI_BACKTEST_STRATEGY_PARAMS_FILE")
        return _raw_result()

    rqalpha.run_file = run_file  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rqalpha", rqalpha)
    real_replace = runner_entry.os.replace
    replacements: list[tuple[Path | str, Path | str]] = []

    def observe_replace(source: Path | str, target: Path | str) -> None:
        replacements.append((source, target))
        real_replace(source, target)

    monkeypatch.setattr(runner_entry.os, "replace", observe_replace)

    exit_code = runner_entry.main(["--run-root", str(root)])

    assert exit_code == 0
    assert observed == {
        "strategy_file_path": str(root / "strategy.py"),
        "config": _effective_config(root),
        "params_env": str(root / "strategy_params.json"),
    }
    assert replacements[-1][1] == root / "result.json"
    assert json.loads((root / "result.json").read_text("utf-8"))["trade_count"] == "2"
    assert not list(root.glob(".result.json.*.tmp"))


def test_runner_entry_probe_emits_version_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rqalpha = ModuleType("rqalpha")
    rqalpha.__version__ = "2.1.0"  # type: ignore[attr-defined]
    rqsdk = ModuleType("rqsdk")
    rqsdk.__version__ = "1.4.0"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rqalpha", rqalpha)
    monkeypatch.setitem(sys.modules, "rqsdk", rqsdk)

    exit_code = runner_entry.main(["--probe"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rqalpha_version"] == "2.1.0"
    assert payload["rqsdk_version"] == "1.4.0"
    assert isinstance(payload["python_version"], str)
    assert payload["python_version"]


@pytest.mark.parametrize(
    ("mutator", "expected_stderr"),
    [
        (
            lambda config: config["base"].__setitem__("auto_update_bundle", True),
            "RUNNER_CONFIG_INVALID",
        ),
        (
            lambda config: config["mod"]["ams"].__setitem__("enabled", True),
            "RUNNER_CONFIG_INVALID",
        ),
        (
            lambda config: config["incremental"].__setitem__("enabled", True),
            "RUNNER_CONFIG_INVALID",
        ),
    ],
)
def test_runner_entry_fails_closed_when_forced_config_is_weakened(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mutator: Any,
    expected_stderr: str,
) -> None:
    root = _run_root(tmp_path)
    record = json.loads((root / "run.json").read_text("utf-8"))
    mutator(record["effective_config"])
    (root / "run.json").write_text(json.dumps(record), "utf-8")

    exit_code = runner_entry.main(["--run-root", str(root)])

    assert exit_code == 2
    assert capsys.readouterr().err.strip() == expected_stderr
    assert not (root / "result.json").exists()


def test_runner_entry_rejects_incomplete_rqalpha_result_without_partial_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _run_root(tmp_path)
    rqalpha = ModuleType("rqalpha")
    rqalpha.run_file = lambda *_args, **_kwargs: {"sys_analyser": {}}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rqalpha", rqalpha)

    exit_code = runner_entry.main(["--run-root", str(root)])

    assert exit_code == 3
    assert capsys.readouterr().err.strip() == "RUNNER_RESULT_INVALID"
    assert not (root / "result.json").exists()


def test_runner_entry_rejects_relative_or_symlinked_run_root(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _run_root(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)

    for unsafe in (Path("relative-run"), alias):
        assert runner_entry.main(["--run-root", str(unsafe)]) == 2
        assert capsys.readouterr().err.strip() == "RUNNER_CONFIG_INVALID"
