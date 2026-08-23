"""Standalone entrypoint executed by the configured RQAlpha interpreter."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
import importlib.metadata
import importlib
import json
import math
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
    "margin_multiplier",
    "data_bundle_path",
    "auto_update_bundle",
    "rqdatac_uri",
}
_SIMULATION_KEYS = {
    "enabled",
    "matching_type",
    "slippage_model",
    "slippage",
    "signal",
}
_TRANSACTION_COST_KEYS = {"enabled", "futures_commission_multiplier"}
_ANALYSER_KEYS = {
    "enabled",
    "record",
    "output_file",
    "report_save_path",
    "plot",
    "plot_save_file",
}
_MAX_JSON_BYTES = 1_048_576
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_READ_FILE_FLAGS = (
    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
)


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


def _native_number(value: object) -> float:
    if not isinstance(value, str):
        _invalid()
    try:
        native = float(Decimal(value))
    except (InvalidOperation, OverflowError, ValueError):
        _invalid()
    if not math.isfinite(native):
        _invalid()
    return native


def _identity(descriptor: int) -> tuple[int, int]:
    metadata = os.fstat(descriptor)
    return metadata.st_dev, metadata.st_ino


def _open_run_root(path: Path) -> int:
    try:
        descriptor = os.open(path, _DIRECTORY_FLAGS)
    except OSError:
        _invalid()
    try:
        metadata = os.fstat(descriptor)
        path_metadata = path.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or (
            metadata.st_dev,
            metadata.st_ino,
        ) != (path_metadata.st_dev, path_metadata.st_ino):
            _invalid()
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_regular_at(root_descriptor: int, name: str) -> int:
    try:
        descriptor = os.open(name, _READ_FILE_FLAGS, dir_fd=root_descriptor)
    except OSError:
        _invalid()
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            _invalid()
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _load_json_descriptor(descriptor: int) -> object:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65_536, _MAX_JSON_BYTES + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_JSON_BYTES:
                _invalid()
            chunks.append(chunk)
        os.lseek(descriptor, 0, os.SEEK_SET)
        return json.loads(b"".join(chunks).decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _invalid()


def _entry_matches(
    root_descriptor: int,
    name: str,
    expected_identity: tuple[int, int],
) -> bool:
    try:
        descriptor = _open_regular_at(root_descriptor, name)
    except RunnerConfigError:
        return False
    try:
        return _identity(descriptor) == expected_identity
    finally:
        os.close(descriptor)


def _descriptor_path(descriptor: int) -> str:
    path = Path("/dev/fd") / str(descriptor)
    try:
        metadata = path.stat()
    except OSError:
        _invalid()
    if metadata.st_ino != os.fstat(descriptor).st_ino:
        _invalid()
    return str(path)


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
    top = _mapping(config, {"base", "mod"})
    base = _mapping(top["base"], _BASE_KEYS)
    modules = _mapping(
        top["mod"],
        {
            "sys_simulation",
            "sys_transaction_cost",
            "sys_analyser",
            "sys_progress",
            "ams",
            "incremental",
        },
    )
    simulation = _mapping(modules["sys_simulation"], _SIMULATION_KEYS)
    transaction_cost = _mapping(modules["sys_transaction_cost"], _TRANSACTION_COST_KEYS)
    analyser = _mapping(modules["sys_analyser"], _ANALYSER_KEYS)
    progress = _mapping(modules["sys_progress"], {"enabled", "show"})
    ams = _mapping(modules["ams"], {"enabled"})
    incremental = _mapping(modules["incremental"], {"enabled"})
    accounts = _mapping(base["accounts"], {"FUTURE"})

    try:
        start = date.fromisoformat(base["start_date"])
        end = date.fromisoformat(base["end_date"])
    except (TypeError, ValueError):
        _invalid()
    if start > end or base["frequency"] not in {"1d", "1m"}:
        _invalid()
    _decimal_string(accounts["FUTURE"], positive=True)
    _decimal_string(base["margin_multiplier"], positive=True)
    _decimal_string(transaction_cost["futures_commission_multiplier"], positive=False)
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

    if not isinstance(base["data_bundle_path"], str):
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
        transaction_cost["enabled"] is True,
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
    return {
        "base": {
            **dict(base),
            "accounts": {"FUTURE": _native_number(accounts["FUTURE"])},
            "margin_multiplier": _native_number(base["margin_multiplier"]),
        },
        "mod": {
            **dict(modules),
            "sys_simulation": {
                **dict(simulation),
                "slippage": _native_number(simulation["slippage"]),
            },
            "sys_transaction_cost": {
                **dict(transaction_cost),
                "futures_commission_multiplier": _native_number(
                    transaction_cost["futures_commission_multiplier"]
                ),
            },
        },
    }


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


def _write_json_atomic(
    root_descriptor: int,
    payload: Mapping[str, Any],
) -> None:
    temporary = f".result.json.{secrets.token_hex(8)}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=root_descriptor,
        )
        with os.fdopen(descriptor, mode="w", encoding="utf-8") as handle:
            descriptor = None
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temporary,
            "result.json",
            src_dir_fd=root_descriptor,
            dst_dir_fd=root_descriptor,
        )
        os.fsync(root_descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=root_descriptor)
        except FileNotFoundError:
            pass


def _execute(raw_root: str) -> int:
    root_descriptor: int | None = None
    strategy_descriptor: int | None = None
    params_descriptor: int | None = None
    run_descriptor: int | None = None
    try:
        root = _run_root(raw_root)
        root_descriptor = _open_run_root(root)
        strategy_descriptor = _open_regular_at(root_descriptor, "strategy.py")
        params_descriptor = _open_regular_at(root_descriptor, "strategy_params.json")
        run_descriptor = _open_regular_at(root_descriptor, "run.json")
        try:
            report_descriptor = os.open(
                "report", _DIRECTORY_FLAGS, dir_fd=root_descriptor
            )
        except OSError:
            _invalid()
        else:
            os.close(report_descriptor)
        strategy_identity = _identity(strategy_descriptor)
        params_identity = _identity(params_descriptor)
        run_identity = _identity(run_descriptor)
        params = _load_json_descriptor(params_descriptor)
        record = _load_json_descriptor(run_descriptor)
        if not isinstance(params, Mapping) or not all(
            isinstance(key, str) for key in params
        ):
            _invalid()
        if not isinstance(record, Mapping) or "effective_config" not in record:
            _invalid()
        config = _validate_config(record["effective_config"], root)
        strategy_path = _descriptor_path(strategy_descriptor)
        params_path = _descriptor_path(params_descriptor)
    except RunnerConfigError:
        print("RUNNER_CONFIG_INVALID", file=sys.stderr)
        for descriptor in (
            run_descriptor,
            params_descriptor,
            strategy_descriptor,
            root_descriptor,
        ):
            if descriptor is not None:
                os.close(descriptor)
        return 2

    os.environ[_PARAMS_ENV] = params_path
    try:
        import rqalpha

        raw_result = rqalpha.run_file(strategy_path, config)
        if not (
            _entry_matches(root_descriptor, "strategy.py", strategy_identity)
            and _entry_matches(root_descriptor, "strategy_params.json", params_identity)
            and _entry_matches(root_descriptor, "run.json", run_identity)
        ):
            _invalid()
        projected = project_result(raw_result, root)
        if not _entry_matches(root_descriptor, "strategy.py", strategy_identity):
            _invalid()
    except RunnerConfigError:
        print("RUNNER_CONFIG_INVALID", file=sys.stderr)
        return_code = 2
    except ResultProjectionError:
        print("RUNNER_RESULT_INVALID", file=sys.stderr)
        return_code = 3
    except Exception:
        print("RUNNER_EXECUTION_FAILED", file=sys.stderr)
        return_code = 3
    else:
        try:
            _write_json_atomic(root_descriptor, projected)
        except (OSError, TypeError, ValueError):
            print("RUNNER_EXECUTION_FAILED", file=sys.stderr)
            return_code = 3
        else:
            return_code = 0
    finally:
        for descriptor in (
            run_descriptor,
            params_descriptor,
            strategy_descriptor,
            root_descriptor,
        ):
            if descriptor is not None:
                os.close(descriptor)
    return return_code


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
