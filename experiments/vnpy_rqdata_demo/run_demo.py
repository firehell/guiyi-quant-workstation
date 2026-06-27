#!/usr/bin/env python3
"""Safe backend E2E demo for the vn.py + RQData V1 path."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import importlib
import json
import sys
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pandas as pd
from sqlalchemy import func, select


DEFAULT_CONFIG = Path(__file__).with_name("sample_config.json")
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("output")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
QUANT_CORE_ROOT = PROJECT_ROOT / "packages" / "quant-core"
DEFAULT_JM_AGGREGATE_RESULT = PROJECT_ROOT / "experiments" / "rqdata_sample_acceptance" / "output" / "rqdata_jm_aggregate_result.json"

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
        "--fixture-backtest",
        action="store_true",
        help="Run the standard Parquet fixture through the real vn.py BacktestingEngine adapter.",
    )
    parser.add_argument(
        "--backend-e2e",
        action="store_true",
        help="Run fixture -> task -> real runner -> persistence -> FastAPI query end to end.",
    )
    parser.add_argument(
        "--jm-smoke-backtest",
        action="store_true",
        help="Run the P0-004 real JM 5m/15m standard parquet through VnpyBacktestRunner.",
    )
    parser.add_argument(
        "--jm-backend-e2e",
        action="store_true",
        help="Persist the real JM 5m/15m vn.py smoke results through BacktestTaskRunner and report tables.",
    )
    parser.add_argument(
        "--jm-daily-direction-backtest",
        action="store_true",
        help="Run P0-009 JM 5m/15m Su Bing EMA21 backtests with confirmed 1d direction filtering.",
    )
    parser.add_argument(
        "--use-app-db",
        action="store_true",
        help="Use the configured app database for --backend-e2e instead of an isolated temporary SQLite database.",
    )
    parser.add_argument(
        "--jm-aggregate-result",
        type=Path,
        default=DEFAULT_JM_AGGREGATE_RESULT,
        help="Path to rqdata_jm_aggregate_result.json. Defaults to the P0-004 ignored output.",
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


def run_fixture_backtest(config: dict[str, Any], output_dir: Path) -> Path:
    from app.vnpy_integration import GuiyiBacktestRequest, VnpyBacktestRunner, convert_vnpy_result
    from generate_standard_fixture import write_fixture

    data = _require_mapping(config, "data")
    strategy = _require_mapping(config, "strategy")
    backtest = _require_mapping(config, "backtest")
    fixture_path = PROJECT_ROOT / str(data["parquet_path"])
    write_fixture(fixture_path)

    request = GuiyiBacktestRequest(
        symbol=str(data["contract"]),
        exchange=str(data["exchange"]),
        interval=str(data["interval"]),
        start=datetime.fromisoformat(str(backtest["start"])),
        end=datetime.fromisoformat(str(backtest["end"])),
        rate=float(backtest["rate"]),
        slippage=float(backtest["slippage"]),
        size=int(backtest["size"]),
        pricetick=float(backtest["pricetick"]),
        capital=float(backtest["initial_capital"]),
        strategy_class_path=str(strategy["class_path"]),
        strategy_parameters=dict(strategy.get("params") or {}),
        bar_data_path=fixture_path,
    )
    raw_result = VnpyBacktestRunner().run(request)
    standard_result = convert_vnpy_result(raw_result)

    payload = {
        "mode": "fixture-backtest",
        "experiment_name": config["experiment_name"],
        "disclaimer": "合成研究样本，不是正式回测结论；回测结果不等于实盘结果。",
        "rqdata_account_required": False,
        "live_trading_used": False,
        "data_provider": {
            "mode": "standard_parquet_fixture",
            "path": str(fixture_path),
            "data_role": data["data_role"],
            "quality_status": data["quality_status"],
        },
        "adapter": {
            "mode": "real_vnpy_backtesting_engine",
            "load_data_called": raw_result["metadata"]["load_data_called"],
            "uses_real_gateway": False,
        },
        "raw_metadata": raw_result["metadata"],
        "standard_result": standard_result,
        "output_note": "Generated under experiments/vnpy_rqdata_demo/output/ and ignored by git.",
    }
    return write_json(output_dir / "real_fixture_standard_result.json", payload)


def run_backend_e2e(config: dict[str, Any], output_dir: Path, *, use_app_db: bool = False) -> Path:
    from fastapi.testclient import TestClient

    from app.backtest.runner import BacktestTaskRunner
    from app.backtest.service import BacktestService
    from app.db.session import get_db
    from app.main import app
    from app.schemas.backtest import BacktestTaskConfig
    from generate_standard_fixture import write_fixture

    data = _require_mapping(config, "data")
    backtest = _require_mapping(config, "backtest")
    safety = _require_mapping(config, "safety")
    fixture_path = PROJECT_ROOT / str(data["parquet_path"])
    write_fixture(fixture_path)

    with _demo_session_factory(use_app_db=use_app_db) as SessionLocal:
        with SessionLocal() as session:
            task_config = BacktestTaskConfig(
                symbol=str(data["contract"]),
                exchange=str(data["exchange"]),
                interval=str(data["interval"]),
                start=datetime.fromisoformat(str(backtest["start"])),
                end=datetime.fromisoformat(str(backtest["end"])),
                strategy_class_path="tests.test_vnpy_integration:FixtureRoundTripStrategy",
                strategy_code="fixture_round_trip",
                strategy_version="backend-e2e",
                strategy_parameters={},
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
                bar_data_path=str(fixture_path),
            )
            task = BacktestService(session).create_task(task_config)
            session.commit()
            runner_result = BacktestTaskRunner(session).run(task.id)
            session.refresh(task)
            report_id = int(task.result_payload["report_id"])
            task_payload = {
                "id": task.id,
                "task_no": task.task_no,
                "status": task.status,
                "engine_type": task.engine_type,
                "data_role": task.data_role,
                "research_only": task.research_only,
            }

        def override_get_db():
            with SessionLocal() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        try:
            client = TestClient(app)
            report_response = client.get(f"/api/backtests/reports/{report_id}")
            trades_response = client.get(f"/api/backtests/reports/{report_id}/trades")
            equity_response = client.get(f"/api/backtests/reports/{report_id}/equity-curve")
            drawdown_response = client.get(f"/api/backtests/reports/{report_id}/drawdown-curve")
        finally:
            app.dependency_overrides.clear()

    report_response.raise_for_status()
    trades_response.raise_for_status()
    equity_response.raise_for_status()
    drawdown_response.raise_for_status()

    report_payload = report_response.json()
    trades_payload = trades_response.json()
    equity_payload = equity_response.json()
    drawdown_payload = drawdown_response.json()
    api_paths = {
        "report_path": f"/api/backtests/reports/{report_id}",
        "trades_path": f"/api/backtests/reports/{report_id}/trades",
        "equity_curve_path": f"/api/backtests/reports/{report_id}/equity-curve",
        "drawdown_curve_path": f"/api/backtests/reports/{report_id}/drawdown-curve",
    }
    payload = {
        "mode": "backend-e2e",
        "experiment_name": config["experiment_name"],
        "disclaimer": "研究验证 demo，不是正式回测结论；回测结果不等于实盘结果。",
        "rqdata_account_required": False,
        "live_trading_used": False,
        "database_mode": "app_db" if use_app_db else "isolated_sqlite",
        "data_provider": {
            "mode": "standard_parquet_fixture",
            "path": str(fixture_path),
            "data_role": data["data_role"],
            "quality_status": data["quality_status"],
        },
        "task": task_payload,
        "runner": {
            "status": runner_result["status"],
            "result_engine": runner_result["result"]["engine"],
        },
        "report_id": report_id,
        "report_no": report_payload["report_no"],
        "api": {
            **api_paths,
            "report_status": report_response.status_code,
            "trades_status": trades_response.status_code,
            "equity_curve_status": equity_response.status_code,
            "drawdown_curve_status": drawdown_response.status_code,
        },
        "counts": {
            "trades": len(trades_payload),
            "orders": len(report_payload.get("orders") or []),
            "equity_curve": len(equity_payload),
            "drawdown_curve": len(drawdown_payload),
        },
        "samples": {
            "report_summary": report_payload.get("summary") or {},
            "first_trade": trades_payload[0] if trades_payload else None,
            "first_equity_point": equity_payload[0] if equity_payload else None,
            "first_drawdown_point": drawdown_payload[0] if drawdown_payload else None,
        },
        "output_note": "Generated under experiments/vnpy_rqdata_demo/output/ and ignored by git.",
    }
    return write_json(output_dir / "backend_e2e_result.json", payload)


def run_jm_smoke_backtest(aggregate_result_path: Path, output_dir: Path) -> Path:
    from app.vnpy_integration import GuiyiBacktestRequest, VnpyBacktestRunner, convert_vnpy_result

    aggregate_payload = _load_jm_aggregate_result(aggregate_result_path)
    symbol_mapping = _require_mapping(aggregate_payload, "symbol_mapping")
    aggregates = _require_mapping(aggregate_payload, "aggregates")
    runner = VnpyBacktestRunner()
    periods: dict[str, Any] = {}

    for period in ("5m", "15m"):
        summary = _require_mapping(aggregates, period)
        parquet_path = Path(str(summary["path"]))
        frame = pd.read_parquet(parquet_path)
        quality_statuses = sorted(str(value) for value in frame["quality_status"].dropna().unique())
        data_roles = sorted(str(value) for value in frame["data_role"].dropna().unique())
        sources = sorted(str(value) for value in frame["source"].dropna().unique())
        if quality_statuses != ["passed"]:
            raise DemoConfigError(f"{period} JM smoke requires quality_status=passed, got {quality_statuses}")
        if data_roles != ["primary"]:
            raise DemoConfigError(f"{period} JM smoke requires data_role=primary, got {data_roles}")
        if sources != ["rqdata"]:
            raise DemoConfigError(f"{period} JM smoke requires source=rqdata, got {sources}")

        request = GuiyiBacktestRequest(
            symbol=str(symbol_mapping["contract"]),
            exchange=str(symbol_mapping["exchange"]),
            interval=period,
            start=datetime.fromisoformat(str(summary["start_datetime"])),
            end=datetime.fromisoformat(str(summary["end_datetime"])),
            rate=0.0001,
            slippage=0.5,
            size=1,
            pricetick=0.5,
            capital=100000,
            strategy_class_path="app.vnpy_integration.smoke_strategy:VnpySmokeRoundTripStrategy",
            strategy_parameters={"entry_bar": 2, "exit_bar": 6, "volume": 1},
            bar_data_path=parquet_path,
        )
        raw_result = runner.run(request)
        standard_result = convert_vnpy_result(raw_result)
        trades = standard_result["trades"]
        equity_curve = standard_result["equity_curve"]
        drawdown_curve = standard_result["drawdown_curve"]
        periods[period] = {
            "path": str(parquet_path),
            "row_count": int(summary["row_count"]),
            "start_datetime": summary["start_datetime"],
            "end_datetime": summary["end_datetime"],
            "executed": bool(raw_result["executed"]),
            "status": raw_result["status"],
            "statistics": standard_result["summary"],
            "counts": {
                "trades": len(trades),
                "orders": len(standard_result["orders"]),
                "daily_results": len(standard_result["daily_results"]),
                "equity_curve": len(equity_curve),
                "drawdown_curve": len(drawdown_curve),
            },
            "samples": {
                "first_trade": trades[0] if trades else None,
                "first_equity_point": equity_curve[0] if equity_curve else None,
                "last_equity_point": equity_curve[-1] if equity_curve else None,
                "first_drawdown_point": drawdown_curve[0] if drawdown_curve else None,
            },
            "raw_metadata": raw_result["metadata"],
            "standard_result_converter": standard_result["metadata"],
        }

    payload = {
        "mode": "jm-real-vnpy-smoke-backtest",
        "disclaimer": "真实 RQData 焦煤 standard parquet 的 vn.py 链路 smoke，不是正式策略收益结论；回测结果不等于实盘结果。",
        "rqdata_network_used": False,
        "live_trading_used": False,
        "ctp_used": False,
        "tqsdk_used": False,
        "veighna_studio_used": False,
        "aggregate_result_path": str(aggregate_result_path),
        "symbol_mapping": symbol_mapping,
        "strategy": {
            "class_path": "app.vnpy_integration.smoke_strategy:VnpySmokeRoundTripStrategy",
            "note": "Minimal fixed round-trip strategy for adapter/result_converter smoke only.",
            "daily_direction_filter": "not_supported_in_smoke; record for P0-009",
        },
        "periods": periods,
        "output_note": "Generated under experiments/vnpy_rqdata_demo/output/ and ignored by git.",
    }
    return write_json(output_dir / "jm_real_smoke_backtest_result.json", payload)


def run_jm_backend_e2e(aggregate_result_path: Path, output_dir: Path, *, use_app_db: bool = False) -> Path:
    from app.backtest.runner import BacktestTaskRunner
    from app.backtest.service import BacktestService
    from app.models.backtest import (
        BacktestDrawdownCurvePointModel,
        BacktestEquityCurvePointModel,
        BacktestOrderModel,
        BacktestReportModel,
        BacktestTask,
        BacktestTradeModel,
    )
    from app.schemas.backtest import BacktestTaskConfig

    aggregate_payload = _load_jm_aggregate_result(aggregate_result_path)
    symbol_mapping = _require_mapping(aggregate_payload, "symbol_mapping")
    aggregates = _require_mapping(aggregate_payload, "aggregates")
    periods: dict[str, Any] = {}
    report_ids: dict[str, int] = {}

    with _demo_session_factory(use_app_db=use_app_db) as SessionLocal:
        with SessionLocal() as session:
            for period in ("5m", "15m"):
                summary = _require_mapping(aggregates, period)
                parquet_path = Path(str(summary["path"]))
                _validate_jm_period_parquet(parquet_path, period)
                config = BacktestTaskConfig(
                    symbol=str(symbol_mapping["contract"]),
                    exchange=str(symbol_mapping["exchange"]),
                    interval=period,
                    start=datetime.fromisoformat(str(summary["start_datetime"])),
                    end=datetime.fromisoformat(str(summary["end_datetime"])),
                    strategy_class_path="app.vnpy_integration.smoke_strategy:VnpySmokeRoundTripStrategy",
                    strategy_code="vnpy_smoke_round_trip",
                    strategy_version="p0-006",
                    strategy_parameters={"entry_bar": 2, "exit_bar": 6, "volume": 1},
                    rate=0.0001,
                    slippage=0.5,
                    size=1,
                    pricetick=0.5,
                    capital=100000,
                    data_source="rqdata",
                    data_role="primary",
                    data_version=f"rqdata_jm_standard_{period}_20250102_20251231_v1",
                    research_only=True,
                    quality_status="passed",
                    bar_data_path=str(parquet_path),
                )
                task = BacktestService(session).create_task(config)
                session.commit()
                runner_result = BacktestTaskRunner(session).run(task.id)
                session.refresh(task)
                if runner_result["status"] != "success":
                    raise DemoConfigError(f"JM {period} backend E2E failed: {runner_result}")

                report_id = int(task.result_payload["report_id"])
                report = session.get(BacktestReportModel, report_id)
                if report is None:
                    raise DemoConfigError(f"JM {period} backend E2E did not create report_id={report_id}")

                counts = {
                    "trades": _count_by_report(session, BacktestTradeModel, report_id),
                    "orders": _count_by_report(session, BacktestOrderModel, report_id),
                    "equity_curve": _count_by_report(session, BacktestEquityCurvePointModel, report_id),
                    "drawdown_curve": _count_by_report(session, BacktestDrawdownCurvePointModel, report_id),
                }
                if counts["trades"] <= 0 or counts["orders"] <= 0 or counts["equity_curve"] <= 0 or counts["drawdown_curve"] <= 0:
                    raise DemoConfigError(f"JM {period} backend E2E report detail counts are incomplete: {counts}")

                persisted_task = session.get(BacktestTask, task.id)
                assert persisted_task is not None
                periods[period] = {
                    "task_id": task.id,
                    "task_no": task.task_no,
                    "task_status": task.status,
                    "report_id": report_id,
                    "report_no": report.report_no,
                    "report_status": report.status,
                    "engine_type": report.engine_type,
                    "data_source": report.data_source,
                    "data_role": report.data_role,
                    "quality_status": report.quality_status,
                    "strategy_code": report.strategy_code,
                    "strategy_version": report.strategy_version,
                    "symbol": report.symbol,
                    "contract": report.contract,
                    "period": report.period,
                    "summary_metadata": (report.summary or {}).get("report_metadata") or {},
                    "counts": counts,
                    "request_bar_data_path": persisted_task.request_payload.get("bar_data_path"),
                    "vnpy_setting_bar_data_path": persisted_task.vnpy_setting_json.get("bar_data_path"),
                    "source_path_redacted": True,
                }
                report_ids[period] = report_id

            session.commit()

    payload = {
        "mode": "jm-real-backend-e2e",
        "database_mode": "app_db" if use_app_db else "isolated_sqlite",
        "disclaimer": "真实 RQData 焦煤 standard parquet 的 PostgreSQL 入库 smoke，不是正式策略收益结论；回测结果不等于实盘结果。",
        "rqdata_network_used": False,
        "live_trading_used": False,
        "ctp_used": False,
        "tqsdk_used": False,
        "veighna_studio_used": False,
        "aggregate_result_path": "<local_path_redacted>",
        "report_ids": report_ids,
        "symbol_mapping": {
            "symbol": symbol_mapping.get("symbol"),
            "contract": symbol_mapping.get("contract"),
            "exchange": symbol_mapping.get("exchange"),
            "project_vt_symbol": symbol_mapping.get("project_vt_symbol"),
            "source_contracts": symbol_mapping.get("source_contracts"),
        },
        "periods": periods,
        "output_note": "Generated under experiments/vnpy_rqdata_demo/output/ and ignored by git.",
    }
    return write_json(output_dir / "jm_backend_e2e_result.json", payload)


def run_jm_daily_direction_backtest(aggregate_result_path: Path, output_dir: Path) -> Path:
    from app.vnpy_integration import GuiyiBacktestRequest, VnpyBacktestRunner, convert_vnpy_result

    aggregate_payload = _load_jm_aggregate_result(aggregate_result_path)
    symbol_mapping = _require_mapping(aggregate_payload, "symbol_mapping")
    aggregates = _require_mapping(aggregate_payload, "aggregates")
    daily_summary = _require_mapping(aggregates, "1d")
    daily_path = Path(str(daily_summary["path"]))
    _validate_jm_period_parquet(daily_path, "1d")

    runner = VnpyBacktestRunner()
    periods: dict[str, Any] = {}
    for period in ("5m", "15m"):
        summary = _require_mapping(aggregates, period)
        parquet_path = Path(str(summary["path"]))
        _validate_jm_period_parquet(parquet_path, period)
        strategy_parameters = _p0_009_strategy_parameters(period)
        request = GuiyiBacktestRequest(
            symbol=str(symbol_mapping["contract"]),
            exchange=str(symbol_mapping["exchange"]),
            interval=period,
            start=datetime.fromisoformat(str(summary["start_datetime"])),
            end=datetime.fromisoformat(str(summary["end_datetime"])),
            rate=0.0001,
            slippage=0.5,
            size=1,
            pricetick=0.5,
            capital=100000,
            strategy_class_path="guiyi_quant.strategies.su_bing_ema21.vnpy_strategy.SuBingEma21VnpyStrategy",
            strategy_parameters=strategy_parameters,
            bar_data_path=parquet_path,
            auxiliary_bar_data_paths={"1d": daily_path},
        )
        raw_result = runner.run(request)
        standard_result = convert_vnpy_result(raw_result)
        periods[period] = {
            "path": str(parquet_path),
            "row_count": int(summary["row_count"]),
            "start_datetime": summary["start_datetime"],
            "end_datetime": summary["end_datetime"],
            "executed": bool(raw_result["executed"]),
            "status": raw_result["status"],
            "strategy_code": "su_bing_ema21",
            "strategy_version": "p0-009",
            "entry_timeframe": period,
            "daily_direction": strategy_parameters["daily_direction"],
            "statistics": standard_result["summary"],
            "counts": {
                "trades": len(standard_result["trades"]),
                "orders": len(standard_result["orders"]),
                "daily_results": len(standard_result["daily_results"]),
                "equity_curve": len(standard_result["equity_curve"]),
                "drawdown_curve": len(standard_result["drawdown_curve"]),
            },
            "raw_metadata": raw_result["metadata"],
            "standard_result_converter": standard_result["metadata"],
        }

    payload = {
        "mode": "jm-daily-direction-backtest",
        "disclaimer": "P0-009 真实 RQData 焦煤 standard parquet 多周期链路验收，不做参数优化，不追求收益；回测结果不等于实盘结果。",
        "rqdata_network_used": False,
        "live_trading_used": False,
        "ctp_used": False,
        "tqsdk_used": False,
        "veighna_studio_used": False,
        "aggregate_result_path": str(aggregate_result_path),
        "symbol_mapping": symbol_mapping,
        "daily_data": {
            "path": str(daily_path),
            "row_count": int(daily_summary["row_count"]),
            "start_datetime": daily_summary["start_datetime"],
            "end_datetime": daily_summary["end_datetime"],
        },
        "daily_confirmation": "Only completed 1d bars with trading_day earlier than the current 5m/15m trading_day can filter entry signals.",
        "periods": periods,
        "output_note": "Generated under experiments/vnpy_rqdata_demo/output/ and ignored by git.",
    }
    return write_json(output_dir / "jm_daily_direction_backtest_result.json", payload)


def _p0_009_strategy_parameters(entry_timeframe: str) -> dict[str, Any]:
    return {
        "entry_timeframe": entry_timeframe,
        "ema_period": 21,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "volume_window": 20,
        "volume_multiplier": 1.2,
        "atr_period": 14,
        "stop_atr_multiple": 2.0,
        "take_profit_r_multiple": 2.5,
        "max_ema_deviation_atr": 1.5,
        "allow_long": True,
        "allow_short": True,
        "daily_direction": {
            "enabled": True,
            "interval": "1d",
            "ema_period": 21,
            "rule": "close_above_ema21_allows_long_close_below_ema21_allows_short",
            "effective_policy": "confirmed_daily_bar_effective_next_trading_day",
        },
    }


@contextmanager
def _demo_session_factory(*, use_app_db: bool):
    if use_app_db:
        from app.db.session import SessionLocal

        yield SessionLocal
        return

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base

    with TemporaryDirectory(prefix="guiyi-backtest-e2e-") as tmp_dir:
        database_path = Path(tmp_dir) / "backend_e2e.sqlite"
        engine = create_engine(
            f"sqlite+pysqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        yield SessionLocal


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


def _load_jm_aggregate_result(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise DemoConfigError(f"JM aggregate result JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("mode") != "jm-standard-aggregation":
        raise DemoConfigError(f"Unexpected JM aggregate result mode in {path}: {payload.get('mode')}")
    return payload


def _validate_jm_period_parquet(path: Path, period: str) -> None:
    if not path.exists():
        raise DemoConfigError(f"JM {period} standard parquet not found")
    frame = pd.read_parquet(path)
    if frame.empty:
        raise DemoConfigError(f"JM {period} standard parquet is empty")
    quality_statuses = sorted(str(value) for value in frame["quality_status"].dropna().unique())
    data_roles = sorted(str(value) for value in frame["data_role"].dropna().unique())
    sources = sorted(str(value) for value in frame["source"].dropna().unique())
    if quality_statuses != ["passed"]:
        raise DemoConfigError(f"{period} JM backend E2E requires quality_status=passed, got {quality_statuses}")
    if data_roles != ["primary"]:
        raise DemoConfigError(f"{period} JM backend E2E requires data_role=primary, got {data_roles}")
    if sources != ["rqdata"]:
        raise DemoConfigError(f"{period} JM backend E2E requires source=rqdata, got {sources}")


def _count_by_report(session: Any, model: type[Any], report_id: int) -> int:
    return int(session.scalar(select(func.count()).select_from(model).where(model.report_id == report_id)) or 0)


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

    if args.fixture_backtest:
        path = run_fixture_backtest(config, args.output_dir)
        print(f"Fixture backtest standard JSON written: {path}")
        return 0

    if args.backend_e2e:
        path = run_backend_e2e(config, args.output_dir, use_app_db=args.use_app_db)
        print(f"Backend E2E JSON written: {path}")
        return 0

    if args.jm_smoke_backtest:
        try:
            path = run_jm_smoke_backtest(args.jm_aggregate_result, args.output_dir)
        except DemoConfigError as exc:
            print(f"JM smoke config error: {exc}", file=sys.stderr)
            return 2
        print(f"JM real vn.py smoke JSON written: {path}")
        return 0

    if args.jm_backend_e2e:
        try:
            path = run_jm_backend_e2e(args.jm_aggregate_result, args.output_dir, use_app_db=args.use_app_db)
        except DemoConfigError as exc:
            print(f"JM backend E2E config error: {exc}", file=sys.stderr)
            return 2
        payload = json.loads(path.read_text(encoding="utf-8"))
        print(f"JM backend E2E JSON written: {path}")
        print(f"5m report_id={payload['report_ids']['5m']}")
        print(f"15m report_id={payload['report_ids']['15m']}")
        return 0

    if args.jm_daily_direction_backtest:
        try:
            path = run_jm_daily_direction_backtest(args.jm_aggregate_result, args.output_dir)
        except DemoConfigError as exc:
            print(f"JM daily-direction config error: {exc}", file=sys.stderr)
            return 2
        payload = json.loads(path.read_text(encoding="utf-8"))
        print(f"JM daily-direction backtest JSON written: {path}")
        print(f"5m status={payload['periods']['5m']['status']} trades={payload['periods']['5m']['counts']['trades']}")
        print(f"15m status={payload['periods']['15m']['status']} trades={payload['periods']['15m']['counts']['trades']}")
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
