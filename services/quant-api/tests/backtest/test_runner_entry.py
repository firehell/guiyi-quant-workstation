from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import fcntl
import json
import os
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import pytest

from app.backtest import runner_entry
from app.backtest.result_projection import ResultProjectionError, project_result


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
            "run_type": "b",
            "start_date": "2026-01-05",
            "end_date": "2026-01-06",
            "frequency": "1d",
            "accounts": {"FUTURE": "1000000"},
            "margin_multiplier": "1",
            "data_bundle_path": str(run_root.parent.parent / "bundle"),
            "auto_update_bundle": False,
            "rqdatac_uri": "disabled",
        },
        "mod": {
            "sys_simulation": {
                "enabled": True,
                "matching_type": "current_bar",
                "slippage_model": "PriceRatioSlippage",
                "slippage": "0",
                "signal": False,
            },
            "sys_transaction_cost": {
                "enabled": True,
                "futures_commission_multiplier": "1",
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
            "incremental": {"enabled": False},
        },
    }


def _run_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs" / "run-001"
    root.mkdir(parents=True)
    (root / "report").mkdir()
    (root / "strategy.py").write_text("def init(context): pass\n", "utf-8")
    (root / "strategy_params.json").write_text(json.dumps({"quantity": 1}), "utf-8")
    (root / "run.json").write_text(
        json.dumps(
            {
                "run_id": root.name,
                "started_at": "2026-08-23T01:02:03+00:00",
                "effective_config": _effective_config(root),
            }
        ),
        "utf-8",
    )
    (root.parent.parent / "bundle").mkdir()
    (root / "stdout.log").write_text("", "utf-8")
    (root / "stderr.log").write_text("", "utf-8")
    return root


def _run_entry(root: Path, *, raw_root: Path | None = None) -> int:
    lock_path = root.parent / "active.lock"
    lock_path.write_text(
        json.dumps(
            {
                "run_id": root.name,
                "pid": os.getpid(),
                "started_at": "2026-08-23T01:02:03+00:00",
            }
        ),
        "utf-8",
    )
    lock_descriptor = os.open(lock_path, os.O_RDONLY)
    fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"GO\n")
    isolated = root.parent.parent / f"runner-home-{root.name}"
    isolated.mkdir(exist_ok=True)
    previous = Path.cwd()
    try:
        os.chdir(isolated)
        return runner_entry.main(
            [
                "--run-root",
                str(raw_root if raw_root is not None else root),
                "--launch-fd",
                str(read_fd),
            ]
        )
    finally:
        os.chdir(previous)
        os.close(write_fd)
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)
        lock_path.unlink(missing_ok=True)


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
        observed["strategy_source"] = Path(strategy_file_path).read_text("utf-8")
        observed["config"] = config
        assert type(config["base"]["accounts"]["FUTURE"]) is float
        assert type(config["base"]["margin_multiplier"]) is float
        assert type(config["mod"]["sys_simulation"]["slippage"]) is float
        assert (
            type(config["mod"]["sys_transaction_cost"]["futures_commission_multiplier"])
            is float
        )
        params_path = os.environ["GUIYI_BACKTEST_STRATEGY_PARAMS_FILE"]
        observed["params"] = json.loads(Path(params_path).read_text("utf-8"))
        return _raw_result()

    rqalpha.run_file = run_file  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rqalpha", rqalpha)
    real_replace = runner_entry.os.replace
    replacements: list[tuple[Path | str, Path | str]] = []

    def observe_replace(source: Path | str, target: Path | str, **kwargs: Any) -> None:
        replacements.append((source, target))
        real_replace(source, target, **kwargs)

    monkeypatch.setattr(runner_entry.os, "replace", observe_replace)

    exit_code = _run_entry(root)

    assert exit_code == 0
    assert observed == {
        "strategy_source": "def init(context): pass\n\n__config__ = {}\n",
        "config": {
            **_effective_config(root),
            "base": {
                **_effective_config(root)["base"],
                "accounts": {"FUTURE": 1000000.0},
                "margin_multiplier": 1.0,
            },
            "mod": {
                **_effective_config(root)["mod"],
                "sys_simulation": {
                    **_effective_config(root)["mod"]["sys_simulation"],
                    "slippage": 0.0,
                },
                "sys_transaction_cost": {
                    "enabled": True,
                    "futures_commission_multiplier": 1.0,
                },
            },
        },
        "params": {"quantity": 1},
    }
    assert Path(replacements[-1][1]).name == "result.json"
    assert json.loads((root / "result.json").read_text("utf-8"))["trade_count"] == "2"
    assert not list(root.glob(".result.json.*.tmp"))


def test_runner_entry_neutralizes_strategy_config_before_rqalpha_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _run_root(tmp_path)
    (root / "strategy.py").write_text(
        "__config__ = {\n"
        "  'base': {'run_type': 'r', 'auto_update_bundle': True, "
        "'rqdatac_uri': 'attacker'},\n"
        "  'mod': {'ams': {'enabled': True}, 'incremental': {'enabled': True}, "
        "'sys_simulation': {'signal': True}, "
        "'sys_analyser': {'output_file': '/tmp/attacker.pkl'}}\n"
        "}\n"
        "def init(context): pass\n",
        "utf-8",
    )
    (root / "result.pkl").write_bytes(b"pickle")
    (root / "equity.png").write_bytes(b"png")
    (root / "report" / "summary.csv").write_text("x", "utf-8")
    observed: dict[str, Any] = {}
    rqalpha = ModuleType("rqalpha")

    def run_file(strategy_file_path: str, config: dict[str, Any]) -> dict[str, Any]:
        scope: dict[str, Any] = {}
        source = Path(strategy_file_path).read_text("utf-8")
        exec(compile(source, strategy_file_path, "exec"), scope)
        observed["strategy_config"] = scope.get("__config__")
        observed["config"] = config
        return _raw_result()

    rqalpha.run_file = run_file  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rqalpha", rqalpha)

    assert _run_entry(root) == 0
    assert observed["strategy_config"] == {}
    assert observed["config"]["base"]["run_type"] == "b"
    assert observed["config"]["base"]["auto_update_bundle"] is False
    assert observed["config"]["base"]["rqdatac_uri"] == "disabled"
    assert observed["config"]["mod"]["ams"]["enabled"] is False
    assert observed["config"]["mod"]["incremental"]["enabled"] is False
    assert observed["config"]["mod"]["sys_simulation"]["signal"] is False
    assert observed["config"]["mod"]["sys_analyser"]["output_file"] == str(
        root / "result.pkl"
    )


def test_runner_entry_rejects_launch_pipe_eof_before_engine_import(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _run_root(tmp_path)
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    exit_code = runner_entry.main(
        ["--run-root", str(root), "--launch-fd", str(read_fd)]
    )

    assert exit_code == 2
    with pytest.raises(OSError):
        os.fstat(read_fd)
    assert capsys.readouterr().err.strip() == "RUNNER_LAUNCH_NOT_AUTHORIZED"
    assert "rqalpha" not in sys.modules


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
            lambda config: config["mod"]["incremental"].__setitem__("enabled", True),
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

    exit_code = _run_entry(root)

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

    exit_code = _run_entry(root)

    assert exit_code == 3
    assert capsys.readouterr().err.strip() == "RUNNER_RESULT_INVALID"
    assert not (root / "result.json").exists()


def test_runner_entry_rejects_nonpositive_or_nonfinite_native_engine_numbers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _run_root(tmp_path)
    record = json.loads((root / "run.json").read_text("utf-8"))
    record["effective_config"]["base"]["margin_multiplier"] = "-1"
    (root / "run.json").write_text(json.dumps(record), "utf-8")
    rqalpha = ModuleType("rqalpha")
    rqalpha.run_file = lambda *_args, **_kwargs: _raw_result()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rqalpha", rqalpha)

    exit_code = _run_entry(root)

    assert exit_code == 2
    assert capsys.readouterr().err.strip() == "RUNNER_CONFIG_INVALID"
    assert not (root / "result.json").exists()


@pytest.mark.parametrize(
    "field_path",
    (
        ("base", "accounts", "FUTURE"),
        ("base", "margin_multiplier"),
        ("mod", "sys_transaction_cost", "futures_commission_multiplier"),
        ("mod", "sys_simulation", "slippage"),
    ),
)
def test_runner_entry_rejects_decimal_values_that_underflow_native_engine_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    field_path: tuple[str, ...],
) -> None:
    root = _run_root(tmp_path)
    record = json.loads((root / "run.json").read_text("utf-8"))
    target = record["effective_config"]
    for field in field_path[:-1]:
        target = target[field]
    target[field_path[-1]] = "1e-10000"
    (root / "run.json").write_text(json.dumps(record), "utf-8")
    rqalpha = ModuleType("rqalpha")
    rqalpha.run_file = lambda *_args, **_kwargs: _raw_result()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rqalpha", rqalpha)

    exit_code = _run_entry(root)

    assert exit_code == 2
    assert capsys.readouterr().err.strip() == "RUNNER_CONFIG_INVALID"
    assert not (root / "result.json").exists()


def test_runner_entry_returns_safe_config_error_for_wrong_path_type(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _run_root(tmp_path)
    record = json.loads((root / "run.json").read_text("utf-8"))
    record["effective_config"]["base"]["data_bundle_path"] = {"secret": "x"}
    (root / "run.json").write_text(json.dumps(record), "utf-8")

    exit_code = _run_entry(root)

    assert exit_code == 2
    assert capsys.readouterr().err.strip() == "RUNNER_CONFIG_INVALID"
    assert not (root / "result.json").exists()


def test_runner_entry_rejects_relative_or_symlinked_run_root(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _run_root(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)

    for unsafe in (Path("relative-run"), alias):
        assert _run_entry(root, raw_root=unsafe) == 2
        assert capsys.readouterr().err.strip() == "RUNNER_CONFIG_INVALID"


def test_runner_entry_uses_opened_json_instead_of_a_replaced_directory_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _run_root(tmp_path)
    outside = tmp_path / "outside-run.json"
    unsafe_config = _effective_config(root)
    unsafe_config["base"]["auto_update_bundle"] = True
    outside.write_text(json.dumps({"effective_config": unsafe_config}), "utf-8")
    real_read_text = Path.read_text
    swapped = False

    def swap_on_path_read(path: Path, *args: Any, **kwargs: Any) -> str:
        nonlocal swapped
        if path == root / "run.json" and not swapped:
            swapped = True
            path.unlink()
            path.symlink_to(outside)
        return real_read_text(path, *args, **kwargs)

    rqalpha = ModuleType("rqalpha")
    rqalpha.run_file = lambda *_args, **_kwargs: _raw_result()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rqalpha", rqalpha)
    monkeypatch.setattr(Path, "read_text", swap_on_path_read)

    exit_code = _run_entry(root)

    assert exit_code == 0
    assert swapped is False


def test_runner_entry_rejects_oversized_json_before_parsing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _run_root(tmp_path)
    with (root / "run.json").open("a", encoding="utf-8") as handle:
        handle.write(" " * 1_100_000)

    exit_code = _run_entry(root)

    assert exit_code == 2
    assert capsys.readouterr().err.strip() == "RUNNER_CONFIG_INVALID"


def test_runner_entry_binds_strategy_identity_and_rejects_mid_run_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _run_root(tmp_path)
    original_source = (root / "strategy.py").read_text("utf-8")
    attacker = tmp_path / "attacker.py"
    attacker.write_text("raise RuntimeError('attacker ran')\n", "utf-8")
    observed_source: list[str] = []
    rqalpha = ModuleType("rqalpha")

    def replace_then_read(
        strategy_file_path: str, _config: dict[str, Any]
    ) -> dict[str, Any]:
        (root / "strategy.py").unlink()
        (root / "strategy.py").symlink_to(attacker)
        observed_source.append(Path(strategy_file_path).read_text("utf-8"))
        return _raw_result()

    rqalpha.run_file = replace_then_read  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rqalpha", rqalpha)

    exit_code = _run_entry(root)

    assert exit_code == 2
    assert capsys.readouterr().err.strip() == "RUNNER_CONFIG_INVALID"
    assert observed_source == [original_source + "\n__config__ = {}\n"]
    assert not (root / "result.json").exists()


@pytest.mark.parametrize(
    ("portfolio", "trades"),
    [
        ([{"date": "2026-01-05-extra", "unit_net_value": "1"}], []),
        ([{"date": "2026-01-05", "unit_net_value": "1"}], {"trade": 1}),
        ([{"date": "2026-01-05"}], []),
    ],
)
def test_project_result_rejects_malformed_equity_and_trade_shapes(
    tmp_path: Path,
    portfolio: object,
    trades: object,
) -> None:
    root = _run_root(tmp_path)
    raw = _raw_result()
    raw["sys_analyser"]["portfolio"] = portfolio
    raw["sys_analyser"]["trades"] = trades

    with pytest.raises(ResultProjectionError, match="^RUNNER_RESULT_INVALID$"):
        project_result(raw, root)
