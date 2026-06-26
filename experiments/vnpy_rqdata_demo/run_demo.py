#!/usr/bin/env python3
"""Safe experiment entrypoint for a future vn.py + local Parquet demo."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = Path(__file__).with_name("sample_config.json")


class DemoConfigError(ValueError):
    """Raised when the demo config is missing required local fields."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the experimental vn.py + local standard Parquet backtest "
            "scaffold without installing dependencies or touching formal services."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Path to the local demo config JSON. Defaults to sample_config.json.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load and validate the config, then skip the vn.py availability check.",
    )
    return parser.parse_args(argv)


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise DemoConfigError(f"Config file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DemoConfigError(f"Invalid JSON config: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DemoConfigError("Config root must be a JSON object.")
    return payload


def validate_config(config: dict[str, Any]) -> None:
    required = {
        "experiment_name",
        "engine_type",
        "data",
        "strategy",
        "backtest",
    }
    missing = sorted(required.difference(config))
    if missing:
        raise DemoConfigError(f"Config missing required keys: {', '.join(missing)}")

    if config["engine_type"] != "vnpy":
        raise DemoConfigError("engine_type must be 'vnpy' for this experiment.")

    data = _require_mapping(config, "data")
    if data.get("source") not in {"local_parquet", "rqdata_standard_parquet"}:
        raise DemoConfigError("data.source must be local_parquet or rqdata_standard_parquet.")
    if data.get("data_role") != "primary":
        raise DemoConfigError("data.data_role must be primary for the default demo path.")
    if not data.get("parquet_path"):
        raise DemoConfigError("data.parquet_path is required and must be a local path.")

    strategy = _require_mapping(config, "strategy")
    if not strategy.get("class_path"):
        raise DemoConfigError("strategy.class_path is required.")

    backtest = _require_mapping(config, "backtest")
    for key in ("start", "end", "initial_capital", "rate", "slippage", "size", "pricetick"):
        if key not in backtest:
            raise DemoConfigError(f"backtest.{key} is required.")


def load_vnpy_demo_objects(config: dict[str, Any]) -> tuple[str, Any]:
    try:
        import vnpy
        from vnpy.trader.constant import Exchange, Interval
        from vnpy.trader.object import BarData
    except ImportError as exc:
        raise RuntimeError(
            "vn.py is not installed in this Python environment. "
            "This experiment will not install it automatically. "
            "Install and pin vn.py only in a separate dependency decision task."
        ) from exc

    data = _require_mapping(config, "data")
    exchange_code = str(data["exchange"])
    try:
        exchange = Exchange[exchange_code]
    except KeyError as exc:
        raise DemoConfigError(f"Unsupported demo exchange for vn.py enum: {exchange_code}") from exc

    bar = BarData(
        gateway_name="demo",
        symbol=str(data["contract"]),
        exchange=exchange,
        datetime=datetime(2024, 1, 2, 9, 0),
        interval=Interval.MINUTE,
        volume=1,
        turnover=3500,
        open_interest=10,
        open_price=3500,
        high_price=3510,
        low_price=3490,
        close_price=3505,
    )
    return vnpy.__version__, bar


def print_vnpy_unavailable(exc: RuntimeError) -> None:
    print(f"vn.py unavailable: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(args.config)
        validate_config(config)
    except DemoConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    print(f"Loaded experiment config: {config['experiment_name']}", flush=True)
    print("Config validation passed.", flush=True)

    if args.dry_run:
        print("Dry run complete. Skipped vn.py availability check.")
        return 0

    try:
        version, bar = load_vnpy_demo_objects(config)
    except RuntimeError as exc:
        print_vnpy_unavailable(exc)
        return 3
    except DemoConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    print(f"vn.py is available: {version}")
    print(
        "Constructed demo BarData: "
        f"vt_symbol={bar.vt_symbol}, interval={bar.interval.value}, "
        f"datetime={bar.datetime.isoformat()}, close={bar.close_price}"
    )
    print("Backtest execution is intentionally not implemented in this scaffold yet.")
    return 0


def _require_mapping(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key)
    if not isinstance(value, dict):
        raise DemoConfigError(f"{key} must be a JSON object.")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
