from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
import json
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.data_sources import DataRole, LegacyDataProvider, LocalParquetProvider, MarketDataQuery
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.backtest import BacktestReportModel, BacktestTask, BacktestTradeModel
from app.models.data_center import MarketDataFile
from app.vnpy_integration import GuiyiBacktestRequest, VnpyBacktestRunner, convert_vnpy_result

REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"
STRATEGY_DIR = QUANT_CORE_ROOT / "guiyi_quant" / "strategies" / "su_bing_ema21"

if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))


@dataclass(frozen=True)
class RawTrade:
    trade_id: str
    datetime: datetime
    price: Decimal
    volume: int


@dataclass(frozen=True)
class RawResult:
    statistics: dict[str, Any]
    trades: list[RawTrade]
    orders: list[dict[str, Any]]
    equity_curve: list[dict[str, Any]]
    drawdown_curve: list[dict[str, Any]]


class DemoStrategy:
    pass


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _write_bar_file(path: Path, *, provider: str, close: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        [
            {
                "symbol": "rb",
                "contract": "rb2405",
                "exchange": "SHFE",
                "datetime": datetime(2024, 1, 2, 9, 0),
                "trading_day": date(2024, 1, 2),
                "open": 3500.0,
                "high": 3510.0,
                "low": 3490.0,
                "close": close,
                "volume": 1,
                "open_interest": 10,
                "turnover": 3500.0,
                "period": "1m",
                "provider": provider,
                "data_version": "acceptance",
            }
        ]
    )
    frame.to_parquet(path, index=False)


def _market_file(path: Path, *, provider: str, data_role: str, quality_status: str = "passed") -> MarketDataFile:
    return MarketDataFile(
        provider=provider,
        data_type="bars",
        instrument_symbol="rb",
        contract_code="rb2405",
        period="1m",
        start_time=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
        file_path=str(path),
        row_count=1,
        quality_status=quality_status,
        data_version=f"{provider}-{data_role}",
        data_role=data_role,
    )


def _query() -> MarketDataQuery:
    return MarketDataQuery(
        symbol="rb",
        contract="rb2405",
        period="1m",
        start=datetime(2024, 1, 2, 8, 59, tzinfo=UTC),
        end=datetime(2024, 1, 2, 9, 1, tzinfo=UTC),
    )


def test_v1_data_role_isolation_keeps_primary_and_legacy_apart(tmp_path) -> None:
    SessionLocal = _session_factory()
    primary_path = tmp_path / "canonical" / "bars" / "primary.parquet"
    legacy_path = tmp_path / "canonical" / "bars" / "legacy.parquet"
    _write_bar_file(primary_path, provider="rqdata", close=3505.0)
    _write_bar_file(legacy_path, provider="trader_future_data", close=9999.0)

    with SessionLocal() as session:
        session.add_all(
            [
                _market_file(primary_path, provider="rqdata", data_role="primary"),
                _market_file(legacy_path, provider="trader_future_data", data_role="legacy_reference"),
            ]
        )
        session.commit()

        primary_rows = LocalParquetProvider(session).get_bars(_query())
        legacy_rows = LegacyDataProvider.legacy_reference(session, explicit=True).get_bars(_query())

    assert [row["close"] for row in primary_rows] == [3505.0]
    assert primary_rows[0]["data_role"] == DataRole.PRIMARY.value
    assert primary_rows[0]["research_only"] is False
    assert [row["close"] for row in legacy_rows] == [9999.0]
    assert legacy_rows[0]["data_role"] == DataRole.LEGACY_REFERENCE.value
    assert legacy_rows[0]["research_only"] is True


def test_v1_vnpy_adapter_prepares_request_without_live_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.vnpy_integration.backtest_runner as runner_module

    monkeypatch.setattr(runner_module, "require_vnpy", lambda: object())

    request = GuiyiBacktestRequest(
        symbol="rb2405",
        exchange="SHFE",
        interval="1m",
        start=datetime(2024, 1, 2, 9, 0),
        end=datetime(2024, 1, 2, 15, 0),
        rate=0.0001,
        slippage=1,
        size=10,
        pricetick=1,
        capital=100000,
        strategy_class_path="tests.test_v1_refactor_acceptance:DemoStrategy",
        strategy_parameters={"ema_period": 21},
        prepared_only=True,
    )

    result = VnpyBacktestRunner().run(request)

    assert result["status"] == "prepared"
    assert result["executed"] is False
    assert result["prepared"]["vt_symbol"] == "rb2405.SHFE"
    assert result["prepared"]["strategy_parameters"] == {"ema_period": 21}
    assert "gateway" not in json.dumps(result).lower()


def test_v1_result_converter_outputs_standard_json_metrics() -> None:
    raw = RawResult(
        statistics={
            "initial_capital": Decimal("100000"),
            "final_equity": Decimal("103500"),
            "total_return": Decimal("0.035"),
            "annual_return": Decimal("0.12"),
            "max_drawdown": Decimal("0.02"),
            "win_rate": Decimal("0.5"),
            "profit_loss_ratio": Decimal("1.8"),
            "trade_count": 2,
            "max_consecutive_losses": 1,
            "total_commission": Decimal("12.5"),
            "total_slippage": Decimal("6.0"),
        },
        trades=[RawTrade("T1", datetime(2024, 1, 2, 9, 0), Decimal("3500.5"), 1)],
        orders=[{"order_id": "O1", "price": Decimal("3500.0")}],
        equity_curve=[{"datetime": datetime(2024, 1, 2, 9, 0), "equity": Decimal("100000")}],
        drawdown_curve=[{"datetime": datetime(2024, 1, 2, 9, 0), "drawdown": Decimal("0")}],
    )

    result = convert_vnpy_result(raw)

    assert result["engine"] == "vnpy_cta_backtesting"
    assert result["summary"]["initial_capital"] == 100000.0
    assert result["summary"]["final_equity"] == 103500.0
    assert result["summary"]["max_consecutive_losses"] == 1
    assert result["summary"]["total_commission"] == 12.5
    assert result["trades"][0]["datetime"] == "2024-01-02T09:00:00"
    assert result["orders"][0]["price"] == 3500.0
    assert result["metadata"]["research_only"] is True


def test_v1_su_bing_strategy_config_is_valid_and_conservative() -> None:
    from guiyi_quant.strategies.su_bing_ema21 import STRATEGY_CLASS_PATH
    from guiyi_quant.strategies.su_bing_ema21.config_schema import validate_params

    with (STRATEGY_DIR / "default_params.json").open(encoding="utf-8") as file:
        params = validate_params(json.load(file))

    assert STRATEGY_CLASS_PATH == "guiyi_quant.strategies.su_bing_ema21.vnpy_strategy.SuBingEma21VnpyStrategy"
    assert params.ema_period == 21
    assert params.macd_fast < params.macd_slow
    assert params.stop_atr_multiple > 0
    assert params.allow_long or params.allow_short


def test_v1_backtest_api_report_endpoints_are_serializable() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        task = BacktestTask(task_no="BTV1-ACCEPT-001", engine_type="vnpy", status="success", data_source="local_parquet", data_role="primary")
        session.add(task)
        session.flush()
        report = BacktestReportModel(
            task_id=task.id,
            task_no=task.task_no,
            report_no="RPT-V1-ACCEPT-001",
            template_name="vnpy",
            engine_type="vnpy",
            symbol="rb2405",
            contract="rb2405",
            period="1m",
            data_role="primary",
            research_only=False,
            status="success",
            summary={"initial_capital": 100000.0, "total_return": 0.01, "max_drawdown": 0.0},
            warnings=[],
            equity_curve=[{"datetime": "2024-01-02T09:00:00", "equity": 100000.0}],
            drawdown_curve=[{"datetime": "2024-01-02T09:00:00", "drawdown": 0.0}],
        )
        session.add(report)
        session.flush()
        session.add(
            BacktestTradeModel(
                report_id=report.id,
                trade_no="T-V1-1",
                symbol="rb2405",
                contract="rb2405",
                direction="long",
                open_time=datetime(2024, 1, 2, 9, 0, tzinfo=UTC),
                open_price=3500,
                close_time=datetime(2024, 1, 2, 10, 0, tzinfo=UTC),
                close_price=3520,
                volume=1,
                turnover=35000,
                commission=3,
                slippage=1,
                gross_pnl=200,
                net_pnl=196,
                return_pct=0.00196,
                holding_bars=12,
                entry_reason="entry",
                exit_reason="exit",
            )
        )
        session.commit()
        report_id = report.id

    def override_get_db():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        detail = client.get(f"/api/backtests/reports/{report_id}")
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["engine_type"] == "vnpy"
        assert payload["data_role"] == "primary"
        assert "回测结果不等于实盘结果" in payload["disclaimer"]

        trades = client.get(f"/api/backtests/reports/{report_id}/trades")
        assert trades.status_code == 200
        assert trades.json()[0]["trade_no"] == "T-V1-1"

        equity = client.get(f"/api/backtests/reports/{report_id}/equity-curve")
        assert equity.status_code == 200
        assert equity.json()[0]["equity"] == 100000.0
    finally:
        app.dependency_overrides.clear()
