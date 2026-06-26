#!/usr/bin/env python3
"""Safe backend E2E demo for the vn.py + RQData V1 path."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import importlib
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = Path(__file__).with_name("sample_config.json")
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("output")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
QUANT_CORE_ROOT = PROJECT_ROOT / "packages" / "quant-core"

for path in (API_ROOT, QUANT_CORE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


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
    parser.add_argument(
        "--check-env",
        action="store_true",
        help="Check local imports and write an environment report without requiring RQData credentials.",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Run sample-data mode through task creation, fake adapter, result converter, and standard JSON output.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for generated demo JSON. Defaults to experiments/vnpy_rqdata_demo/output/.",
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


def load_vnpy_demo_objects(config: dict[str, Any] | None = None) -> tuple[str, Any]:
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

    data = _require_mapping(config, "data") if config is not None else _default_demo_data()
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


def print_vnpy_check(version: str, bar: Any) -> None:
    print(f"vn.py is available: {version}")
    print(
        "Constructed demo BarData: "
        f"vt_symbol={bar.vt_symbol}, interval={bar.interval.value}, "
        f"datetime={bar.datetime.isoformat()}, close={bar.close_price}"
    )
    print("No external account, live gateway, Studio, or real backtest was used.")


@dataclass(frozen=True)
class SampleBar:
    source: str
    data_role: str
    symbol: str
    contract: str
    exchange: str
    vt_symbol: str
    datetime: str
    trading_day: str
    interval: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float
    open_interest: float
    data_version: str


class SampleDataProvider:
    mode = "sample_bars"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def load_bars(self) -> list[dict[str, Any]]:
        data = _require_mapping(self.config, "data")
        start = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)
        closes = [3500.0, 3512.0, 3526.0, 3518.0, 3545.0]
        rows: list[dict[str, Any]] = []
        previous = closes[0]
        for index, close in enumerate(closes):
            moment = start + timedelta(minutes=60 * index)
            high = max(previous, close) + 8
            low = min(previous, close) - 6
            rows.append(
                asdict(
                    SampleBar(
                        source=str(data["source"]),
                        data_role=str(data["data_role"]),
                        symbol=str(data["symbol"]),
                        contract=str(data["contract"]),
                        exchange=str(data["exchange"]),
                        vt_symbol=str(data["vt_symbol"]),
                        datetime=moment.isoformat(),
                        trading_day=date(2024, 1, 2).isoformat(),
                        interval=str(data["interval"]),
                        open=previous,
                        high=high,
                        low=low,
                        close=close,
                        volume=100 + index * 10,
                        turnover=close * (100 + index * 10),
                        open_interest=1000 + index,
                        data_version=str(data["data_version"]),
                    )
                )
            )
            previous = close
        return rows


class FakeVnpyAdapter:
    mode = "fake_vnpy_adapter"

    def __init__(self, bars: list[dict[str, Any]]) -> None:
        self.bars = bars

    def run(self, request: Any) -> dict[str, Any]:
        first = self.bars[0]
        last = self.bars[-1]
        return {
            "statistics": {
                "initial_capital": request.capital,
                "final_equity": request.capital + 860.0,
                "total_return": 0.0086,
                "annual_return": 0.12,
                "max_drawdown": 0.012,
                "win_rate": 1.0,
                "profit_loss_ratio": 2.3,
                "trade_count": 1,
                "max_consecutive_losses": 0,
                "total_commission": 18.0,
                "total_slippage": 10.0,
            },
            "trades": [
                {
                    "trade_id": "DEMO-T-001",
                    "symbol": request.symbol,
                    "vt_symbol": f"{request.symbol}.{request.exchange}",
                    "direction": "long",
                    "open_time": first["datetime"],
                    "open_price": first["open"],
                    "close_time": last["datetime"],
                    "close_price": last["close"],
                    "volume": 1,
                    "net_pnl": 860.0,
                    "reason": "sample_fake_adapter_only",
                }
            ],
            "orders": [],
            "daily_results": [],
            "equity_curve": [
                {"datetime": row["datetime"], "equity": request.capital + index * 215.0}
                for index, row in enumerate(self.bars)
            ],
            "drawdown_curve": [{"datetime": row["datetime"], "drawdown": 0.0} for row in self.bars],
            "warnings": [
                "sample data only; not a formal backtest conclusion",
                "回测结果不等于实盘结果",
            ],
            "metadata": {
                "adapter_mode": self.mode,
                "bar_count": len(self.bars),
                "live_trading_used": False,
            },
        }


def run_sample(config: dict[str, Any], output_dir: Path) -> Path:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.backtest.runner import BacktestTaskRunner
    from app.backtest.service import BacktestService
    from app.db.base import Base
    from app.schemas.backtest import BacktestTaskConfig

    provider = SampleDataProvider(config)
    bars = provider.load_bars()
    data = _require_mapping(config, "data")
    strategy = _require_mapping(config, "strategy")
    backtest = _require_mapping(config, "backtest")
    safety = _require_mapping(config, "safety")

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with SessionLocal() as session:
        task_config = BacktestTaskConfig(
            symbol=str(data["contract"]),
            exchange=str(data["exchange"]),
            interval=str(data["interval"]),
            start=datetime.fromisoformat(str(backtest["start"])),
            end=datetime.fromisoformat(str(backtest["end"])),
            strategy_class_path=str(strategy["class_path"]),
            strategy_parameters=dict(strategy.get("params") or {}),
            rate=float(backtest["rate"]),
            slippage=float(backtest["slippage"]),
            size=int(backtest["size"]),
            pricetick=float(backtest["pricetick"]),
            capital=float(backtest["initial_capital"]),
            data_source=str(data["source"]),
            data_role=str(data["data_role"]),
            data_version=str(data["data_version"]),
            research_only=bool(safety.get("research_only", True)),
            quality_status=str(data["quality_status"]),
        )
        task = BacktestService(session).create_task(task_config)
        session.commit()
        runner_result = BacktestTaskRunner(session, adapter=FakeVnpyAdapter(bars)).run(task.id)
        session.refresh(task)

        payload = {
            "mode": "sample",
            "experiment_name": config["experiment_name"],
            "disclaimer": "研究验证 demo，不是正式回测结论；回测结果不等于实盘结果。",
            "rqdata_account_required": False,
            "live_trading_used": False,
            "data_provider": {
                "mode": provider.mode,
                "bar_count": len(bars),
                "data_role": data["data_role"],
                "quality_status": data["quality_status"],
            },
            "adapter": {"mode": FakeVnpyAdapter.mode, "uses_real_gateway": False},
            "task": {
                "id": task.id,
                "task_no": task.task_no,
                "status": task.status,
                "engine_type": task.engine_type,
                "data_role": task.data_role,
                "research_only": task.research_only,
            },
            "standard_result": runner_result["result"],
            "output_note": "Generated under experiments/vnpy_rqdata_demo/output/ and ignored by git.",
        }

    return write_json(output_dir / "sample_standard_result.json", payload)


def run_check_env(output_dir: Path) -> Path:
    checks = {
        "mode": "check-env",
        "checked_at": datetime.now(UTC).isoformat(),
        "rqdata_account_required": False,
        "live_trading_used": False,
        "ctp_used": False,
        "tqsdk_live_used": False,
        "imports": {},
    }
    for module_name in ("app.backtest.service", "app.backtest.runner", "app.vnpy_integration.result_converter", "vnpy"):
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            checks["imports"][module_name] = {"available": False, "error": str(exc).splitlines()[0]}
        else:
            checks["imports"][module_name] = {
                "available": True,
                "version": getattr(module, "__version__", None),
            }
    checks["vnpy_available"] = bool(checks["imports"]["vnpy"]["available"])
    checks["message"] = "Environment check completed without reading credentials or touching live gateways."
    return write_json(output_dir / "environment_check.json", checks)


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    ensure_output_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def ensure_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    gitignore = output_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n!.gitignore\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.check_env:
        path = run_check_env(args.output_dir)
        print(f"Environment check written: {path}")
        return 0

    try:
        config = load_config(args.config)
        validate_config(config)
    except DemoConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    print(f"Loaded experiment config: {config['experiment_name']}", flush=True)
    print("Config validation passed.", flush=True)

    if args.sample:
        path = run_sample(config, args.output_dir)
        print(f"Sample standard JSON written: {path}")
        return 0

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

    print_vnpy_check(version, bar)
    print("Backtest execution is intentionally not implemented in this scaffold yet.")
    return 0


def _require_mapping(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key)
    if not isinstance(value, dict):
        raise DemoConfigError(f"{key} must be a JSON object.")
    return value


def _default_demo_data() -> dict[str, str]:
    return {
        "contract": "rb2405",
        "exchange": "SHFE",
    }


if __name__ == "__main__":
    raise SystemExit(main())
