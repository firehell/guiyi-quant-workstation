"""Standalone entrypoint executed by the configured RQAlpha interpreter."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
import importlib.metadata
import importlib
import json
import os
from pathlib import Path
import platform
import secrets
import stat
import sys
from typing import Any, NoReturn

_projection = importlib.import_module(
    f"{__package__}.result_projection" if __package__ else "result_projection"
)
ResultProjectionError = _projection.ResultProjectionError
project_result = _projection.project_result


_PARAMS_ENV = "GUIYI_BACKTEST_STRATEGY_PARAMS_FILE"
_BASE_KEYS = {
    "start_date",
    "end_date",
    "frequency",
    "accounts",
    "data_bundle_path",
    "auto_update_bundle",
    "rqdatac_uri",
}
_SIMULATION_KEYS = {
    "enabled",
    "matching_type",
    "margin_multiplier",
    "commission_multiplier",
    "slippage_model",
    "slippage",
    "signal",
}
_ANALYSER_KEYS = {
    "enabled",
    "record",
    "output_file",
    "report_save_path",
    "plot",
    "plot_save_file",
}


class RunnerConfigError(ValueError):
    pass


def _invalid() -> NoReturn:
    raise RunnerConfigError


def _mapping(value: object, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        _invalid()
    return value


def _decimal_string(value: object, *, positive: bool) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        _invalid()
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        _invalid()
    if not parsed.is_finite() or (parsed <= 0 if positive else parsed < 0):
        _invalid()


def _regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _load_json(path: Path) -> object:
    if not _regular_file(path):
        _invalid()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _invalid()


def _run_root(raw: str) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        _invalid()
    try:
        resolved = candidate.resolve(strict=True)
        mode = candidate.lstat().st_mode
    except OSError:
        _invalid()
    if resolved != candidate or not stat.S_ISDIR(mode):
        _invalid()
    return candidate


def _validate_config(config: object, run_root: Path) -> dict[str, Any]:
    top = _mapping(config, {"base", "mod", "incremental"})
    base = _mapping(top["base"], _BASE_KEYS)
    modules = _mapping(
        top["mod"], {"sys_simulation", "sys_analyser", "sys_progress", "ams"}
    )
    simulation = _mapping(modules["sys_simulation"], _SIMULATION_KEYS)
    analyser = _mapping(modules["sys_analyser"], _ANALYSER_KEYS)
    progress = _mapping(modules["sys_progress"], {"enabled", "show"})
    ams = _mapping(modules["ams"], {"enabled"})
    incremental = _mapping(top["incremental"], {"enabled"})
    accounts = _mapping(base["accounts"], {"future"})

    try:
        start = date.fromisoformat(base["start_date"])
        end = date.fromisoformat(base["end_date"])
    except (TypeError, ValueError):
        _invalid()
    if start > end or base["frequency"] not in {"1d", "1m"}:
        _invalid()
    _decimal_string(accounts["future"], positive=True)
    _decimal_string(simulation["margin_multiplier"], positive=True)
    _decimal_string(simulation["commission_multiplier"], positive=False)
    _decimal_string(simulation["slippage"], positive=False)
    if simulation["matching_type"] not in {"current_bar", "next_bar"}:
        _invalid()
    if base["frequency"] == "1d" and simulation["matching_type"] != "current_bar":
        _invalid()
    if simulation["slippage_model"] not in {
        "PriceRatioSlippage",
        "TickSizeSlippage",
    }:
        _invalid()

    bundle_path = Path(base["data_bundle_path"])
    if not bundle_path.is_absolute():
        _invalid()
    try:
        bundle_path = bundle_path.resolve(strict=True)
    except OSError:
        _invalid()
    if (
        not bundle_path.is_dir()
        or run_root.is_relative_to(bundle_path)
        or bundle_path.is_relative_to(run_root)
    ):
        _invalid()

    forced_values = (
        base["auto_update_bundle"] is False,
        base["rqdatac_uri"] == "disabled",
        simulation["enabled"] is True,
        simulation["signal"] is False,
        analyser["enabled"] is True,
        analyser["record"] is True,
        analyser["plot"] is True,
        progress["enabled"] is True,
        progress["show"] is False,
        ams["enabled"] is False,
        incremental["enabled"] is False,
        analyser["output_file"] == str(run_root / "result.pkl"),
        analyser["report_save_path"] == str(run_root / "report"),
        analyser["plot_save_file"] == str(run_root / "equity.png"),
    )
    if not all(forced_values):
        _invalid()
    return dict(top)


def _version(module: object, distribution: str) -> str:
    value = getattr(module, "__version__", None)
    if isinstance(value, str) and value:
        return value
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _probe() -> int:
    try:
        import rqalpha
        import rqsdk

        payload = {
            "available": True,
            "rqalpha_version": _version(rqalpha, "rqalpha"),
            "rqsdk_version": _version(rqsdk, "rqsdk"),
            "python_version": platform.python_version(),
        }
        print(json.dumps(payload, sort_keys=True))
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "available": False,
                    "rqalpha_version": "unknown",
                    "rqsdk_version": "unknown",
                    "python_version": platform.python_version(),
                },
                sort_keys=True,
            )
        )
        return 1


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, mode="w", encoding="utf-8") as handle:
            descriptor = None
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _execute(raw_root: str) -> int:
    try:
        root = _run_root(raw_root)
        strategy_path = root / "strategy.py"
        params_path = root / "strategy_params.json"
        run_path = root / "run.json"
        report_path = root / "report"
        if (
            not _regular_file(strategy_path)
            or not report_path.is_dir()
            or report_path.is_symlink()
        ):
            _invalid()
        params = _load_json(params_path)
        record = _load_json(run_path)
        if not isinstance(params, Mapping) or not all(
            isinstance(key, str) for key in params
        ):
            _invalid()
        if not isinstance(record, Mapping) or "effective_config" not in record:
            _invalid()
        config = _validate_config(record["effective_config"], root)
    except RunnerConfigError:
        print("RUNNER_CONFIG_INVALID", file=sys.stderr)
        return 2

    os.environ[_PARAMS_ENV] = str(params_path)
    try:
        import rqalpha

        raw_result = rqalpha.run_file(str(strategy_path), config)
        projected = project_result(raw_result, root)
    except ResultProjectionError:
        print("RUNNER_RESULT_INVALID", file=sys.stderr)
        return 3
    except Exception:
        print("RUNNER_EXECUTION_FAILED", file=sys.stderr)
        return 3

    try:
        _write_json_atomic(root / "result.json", projected)
    except (OSError, TypeError, ValueError):
        print("RUNNER_EXECUTION_FAILED", file=sys.stderr)
        return 3
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="guiyi-backtest-runner")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--probe", action="store_true")
    group.add_argument("--run-root")
    args = parser.parse_args(argv)
    if args.probe:
        return _probe()
    return _execute(args.run_root)


if __name__ == "__main__":  # pragma: no cover - subprocess entrypoint
    raise SystemExit(main())
