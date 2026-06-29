from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backtest.runner import BacktestTaskRunner
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.backtest import BacktestReportModel, BacktestTask, BacktestTradeModel
from app.models.data_center import MarketDataFile
from app.models.data_center import Contract, Exchange, FuturesTradingParameter, Instrument, MainContractMap, TradingCalendar


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_jm_v1b_files(session, tmp_path: Path, *, bars_by_period: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Path]:
    paths = {}
    for period in ("1d", "15m", "5m"):
        path = tmp_path / f"jm_MAIN_{period}_v1b.parquet"
        rows = (bars_by_period or {}).get(period)
        if rows is None:
            path.write_text("registered test placeholder", encoding="utf-8")
        else:
            pd.DataFrame(rows).to_parquet(path, index=False)
        paths[period] = path
        session.add(
            MarketDataFile(
                provider="rqdata",
                data_type="bars",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                period=period,
                start_time=datetime(2023, 1, 1, tzinfo=UTC),
                end_time=datetime(2025, 12, 31, 15, 0, tzinfo=UTC),
                file_path=str(path),
                row_count=1000,
                data_version="v1b_jm_20230101_20251231",
                data_role="primary",
                quality_status="passed",
            )
        )
    session.commit()
    return paths


def _seed_jm_daily_contract_reference(session, *, with_params: bool = True) -> None:
    session.add(Exchange(code="DCE", name="DCE", country="CN", timezone="Asia/Shanghai", is_active=True))
    session.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE", is_active=True))
    session.add(
        Contract(
            contract_code="JM2309",
            instrument_symbol="jm",
            exchange_code="DCE",
            name="焦煤2309",
            contract_month="2309",
            contract_multiplier=60,
            maturity_date=date(2023, 9, 15),
            provider="rqdata",
        )
    )
    session.add_all(
        [
            TradingCalendar(exchange_code="DCE", trade_date=day, is_trading_day=True, provider="rqdata")
            for day in [
                date(2023, 6, 28),
                date(2023, 6, 29),
                date(2023, 6, 30),
                date(2023, 8, 31),
            ]
        ]
    )
    session.add_all(
        [
            MainContractMap(
                instrument_symbol="jm",
                trade_date=day,
                rank=1,
                contract_code="JM2309",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="test-daily",
            )
            for day in [date(2023, 6, 28), date(2023, 6, 29), date(2023, 6, 30)]
        ]
    )
    if with_params:
        session.add_all(
            [
                FuturesTradingParameter(
                    contract_code="JM2309",
                    instrument_symbol="jm",
                    exchange_code="DCE",
                    trade_date=day,
                    long_margin_ratio=Decimal("0.12"),
                    short_margin_ratio=Decimal("0.13"),
                    open_commission=Decimal("0.0001"),
                    close_commission=Decimal("0.00011"),
                    close_today_commission=Decimal("0.0002"),
                    commission_type="by_money",
                    price_tick=Decimal("0.5"),
                    contract_multiplier=60,
                    provider="rqdata",
                    data_version="test-daily",
                )
                for day in [date(2023, 6, 28), date(2023, 6, 29), date(2023, 6, 30)]
            ]
        )
    session.commit()


def _seed_jm_contract_reference(session, *, with_params: bool = True) -> None:
    session.add(Exchange(code="DCE", name="DCE", country="CN", timezone="Asia/Shanghai", is_active=True))
    session.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE", is_active=True))
    session.add(
        Contract(
            contract_code="JM2405",
            instrument_symbol="jm",
            exchange_code="DCE",
            name="焦煤2405",
            contract_month="2405",
            contract_multiplier=60,
            maturity_date=date(2024, 5, 15),
            provider="rqdata",
        )
    )
    session.add_all(
        [
            TradingCalendar(exchange_code="DCE", trade_date=date(2024, 4, 29), is_trading_day=True, provider="rqdata"),
            TradingCalendar(exchange_code="DCE", trade_date=date(2024, 4, 30), is_trading_day=True, provider="rqdata"),
            TradingCalendar(exchange_code="DCE", trade_date=date(2024, 5, 1), is_trading_day=False, provider="rqdata"),
        ]
    )
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=date(2024, 1, 2),
            rank=1,
            contract_code="JM2405",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="test-v1",
        )
    )
    if with_params:
        session.add(
            FuturesTradingParameter(
                contract_code="JM2405",
                instrument_symbol="jm",
                exchange_code="DCE",
                trade_date=date(2024, 1, 2),
                long_margin_ratio=Decimal("0.12"),
                short_margin_ratio=Decimal("0.13"),
                open_commission=Decimal("0.0001"),
                close_commission=Decimal("0.00011"),
                close_today_commission=Decimal("0.0002"),
                commission_type="by_money",
                price_tick=Decimal("0.5"),
                contract_multiplier=60,
                provider="rqdata",
                data_version="test-v1",
            )
        )
    session.commit()


def _seed_exchange_and_instrument(session) -> None:
    session.add(Exchange(code="DCE", name="DCE", country="CN", timezone="Asia/Shanghai", is_active=True))
    session.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE", is_active=True))


def _seed_contract(session, contract_code: str, contract_month: str, maturity_date: date) -> None:
    session.add(
        Contract(
            contract_code=contract_code,
            instrument_symbol="jm",
            exchange_code="DCE",
            name=f"焦煤{contract_month}",
            contract_month=contract_month,
            contract_multiplier=60,
            maturity_date=maturity_date,
            provider="rqdata",
        )
    )


def _seed_calendar(session, days: list[date]) -> None:
    session.add_all([TradingCalendar(exchange_code="DCE", trade_date=day, is_trading_day=True, provider="rqdata") for day in days])


def _seed_main_map(session, mapping: dict[date, str]) -> None:
    session.add_all(
        [
            MainContractMap(
                instrument_symbol="jm",
                trade_date=day,
                rank=1,
                contract_code=contract_code,
                rule="volume_open_interest",
                provider="rqdata",
                data_version="test-v1",
            )
            for day, contract_code in mapping.items()
        ]
    )


def _seed_trading_params(session, mapping: dict[date, str]) -> None:
    session.add_all(
        [
            FuturesTradingParameter(
                contract_code=contract_code,
                instrument_symbol="jm",
                exchange_code="DCE",
                trade_date=day,
                long_margin_ratio=Decimal("0.12"),
                short_margin_ratio=Decimal("0.13"),
                open_commission=Decimal("0.0001"),
                close_commission=Decimal("0.00011"),
                close_today_commission=Decimal("0.0002"),
                commission_type="by_money",
                price_tick=Decimal("0.5"),
                contract_multiplier=60,
                provider="rqdata",
                data_version="test-v1",
            )
            for day, contract_code in mapping.items()
        ]
    )


def _seed_jm2405_delivery_reference(session, *, mapping: dict[date, str] | None = None) -> None:
    mapping = mapping or {date(2024, 4, 29): "JM2405", date(2024, 4, 30): "JM2405"}
    _seed_exchange_and_instrument(session)
    _seed_contract(session, "JM2405", "2405", date(2024, 5, 15))
    _seed_calendar(session, [date(2024, 4, 29), date(2024, 4, 30)])
    _seed_main_map(session, mapping)
    _seed_trading_params(session, mapping)
    session.commit()


def _seed_jm_rollover_reference(session) -> None:
    mapping = {
        date(2024, 4, 19): "JM2405",
        date(2024, 4, 20): "JM2409",
    }
    _seed_exchange_and_instrument(session)
    _seed_contract(session, "JM2405", "2405", date(2024, 5, 15))
    _seed_contract(session, "JM2409", "2409", date(2024, 9, 15))
    _seed_calendar(session, [date(2024, 4, 19), date(2024, 4, 20), date(2024, 4, 30), date(2024, 8, 30)])
    _seed_main_map(session, mapping)
    _seed_trading_params(session, mapping)
    session.commit()


class FakeV1bSuccessfulAdapter:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def run(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        return {
            "status": "success",
            "statistics": {
                "capital": 100000,
                "end_balance": 100600,
                "total_return": 0.006,
                "max_drawdown": 120.0,
                "total_trade_count": 1,
            },
            "strategy_trades": [
                {
                    "daily_direction": "long",
                    "entry_interval": request.strategy_parameters["entry_interval"],
                    "entry_reason": "daily_long_ema21_pullback_macd_confirmed",
                    "exit_reason": "max_hold_bars_exit",
                    "hold_bars": 8,
                    "stop_loss_price": 980.0,
                    "entry_datetime": "2024-01-02T09:15:00",
                    "exit_datetime": "2024-01-02T11:15:00",
                    "entry_price": 1000.0,
                    "exit_price": 1010.0,
                    "direction": "long",
                    "volume": 1,
                }
            ],
            "orders": [{"orderid": "O-V1B-1", "symbol": request.symbol, "direction": "long", "price": 1000, "volume": 1}],
            "equity_curve": [{"date": "2024-01-02", "balance": 100000}, {"date": "2024-01-03", "balance": 100600}],
            "drawdown_curve": [{"date": "2024-01-02", "drawdown": 0, "ddpercent": 0}],
            "warnings": [],
        }


class FakeV1bTradeAdapter:
    def __init__(self, trade: dict[str, Any]) -> None:
        self.trade = trade
        self.requests: list[Any] = []

    def run(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        trade = dict(self.trade)
        trade.setdefault("daily_direction", "long")
        trade.setdefault("entry_interval", request.strategy_parameters["entry_interval"])
        trade.setdefault("entry_reason", "test_entry")
        trade.setdefault("exit_reason", "max_hold_bars_exit")
        trade.setdefault("hold_bars", 8)
        trade.setdefault("direction", "long")
        trade.setdefault("volume", 1)
        return {
            "status": "success",
            "statistics": {
                "capital": 100000,
                "end_balance": 100000,
                "total_return": 0,
                "max_drawdown": 0,
                "total_trade_count": 1,
            },
            "strategy_trades": [trade],
            "orders": [],
            "equity_curve": [{"date": "2024-01-02", "balance": 100000}],
            "drawdown_curve": [{"date": "2024-01-02", "drawdown": 0, "ddpercent": 0}],
            "warnings": [],
        }


class FakeDailySuccessfulAdapter:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def run(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        return {
            "status": "success",
            "statistics": {"capital": 100000, "end_balance": 100000, "total_return": 0, "max_drawdown": 0},
            "strategy_trades": [
                {
                    "trade_id": "SB-JM-D-1",
                    "strategy_code": "su_bing_jm_daily_ema21_macd_volume",
                    "strategy_version": "v0.2.0-daily",
                    "product": "JM",
                    "symbol": "jm.MAIN",
                    "exchange": "DCE",
                    "interval": "1d",
                    "direction": "long",
                    "signal_datetime": "2023-06-28T15:00:00",
                    "entry_signal_time": "2023-06-28T15:00:00",
                    "fill_datetime": "2023-06-29T09:00:00",
                    "entry_datetime": "2023-06-29T09:00:00",
                    "exit_signal_datetime": "2023-06-29T15:00:00",
                    "exit_fill_datetime": "2023-06-30T09:00:00",
                    "exit_datetime": "2023-06-30T09:00:00",
                    "entry_price": 1000.5,
                    "exit_price": 1011.0,
                    "entry_reason": "daily_close_above_ema21+macd_near_zero_golden_cross+volume_expansion",
                    "exit_reason": "long_close_below_ema21_exit_next_daily_open",
                    "volume": 1,
                    "ema21": 990.0,
                    "current_dif": 1.0,
                    "current_dea": 0.5,
                    "previous_dif": 0.4,
                    "previous_dea": 0.6,
                    "current_volume": 1200,
                    "previous_volume": 1000,
                }
            ],
            "orders": [{"orderid": "O-D-1", "symbol": request.symbol, "direction": "long", "price": 1000.5, "volume": 1}],
            "warnings": [],
        }


def _run_v1b_task_with_trade(session, trade: dict[str, Any]):
    from app.backtest.service import BacktestService
    from app.backtest.v1b_jm_tasks import build_jm_v1b_task_config

    spec = build_jm_v1b_task_config(session, "15m")  # type: ignore[arg-type]
    task = BacktestService(session).create_task(spec.config)
    session.commit()
    result = BacktestTaskRunner(session, adapter=FakeV1bTradeAdapter(trade)).run(task.id)
    session.refresh(task)
    report = session.get(BacktestReportModel, task.result_payload["report_id"]) if task.result_payload else None
    trades = []
    if report is not None:
        trades = session.scalars(select(BacktestTradeModel).where(BacktestTradeModel.report_id == report.id)).all()
    return result, task, report, trades


def test_build_jm_daily_ema21_macd_volume_task_config_uses_only_primary_passed_daily_data(tmp_path: Path) -> None:
    from app.backtest.v1b_jm_tasks import build_jm_daily_ema21_macd_volume_task_config

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        paths = _seed_jm_v1b_files(session, tmp_path)
        _seed_jm_daily_contract_reference(session)

        spec = build_jm_daily_ema21_macd_volume_task_config(session)

        assert spec.config.task_type == "v1b_jm_daily_ema21_macd_volume"
        assert spec.config.strategy_code == "su_bing_jm_daily_ema21_macd_volume"
        assert spec.config.strategy_version == "v0.2.0-daily"
        assert spec.config.interval == "1d"
        assert spec.config.start == datetime(2023, 6, 28, tzinfo=UTC)
        assert spec.config.end == datetime(2025, 12, 31, 15, 0, tzinfo=UTC)
        assert spec.config.bar_data_path == str(paths["1d"])
        assert spec.config.auxiliary_bar_data_paths == {}
        assert spec.config.data_role.value == "primary"
        assert spec.config.quality_status == "passed"
        assert spec.config.strategy_parameters["interval"] == "1d"
        assert spec.config.strategy_parameters["price_tick"] == 0.5
        assert spec.config.strategy_parameters["contract_multiplier"] == 60
        assert spec.config.strategy_parameters["commission_rate"] == pytest.approx(0.0001)
        assert spec.config.strategy_parameters["margin_rate"] == pytest.approx(0.13)
        context = spec.config.request_payload["strategy_review_context"]
        assert context["strategy_code"] == "su_bing_jm_daily_ema21_macd_volume"
        assert context["data_constraints"]["interval"] == "1d"
        assert context["data_constraints"]["data_role"] == "primary"
        assert context["data_constraints"]["quality_status"] == "passed"
        assert context["forbidden_sources"] == ["legacy_reference", "validation", "tqsdk_formal_backtest_data"]


def test_build_jm_daily_ema21_macd_volume_task_rejects_non_primary_or_missing_costs(tmp_path: Path) -> None:
    from app.backtest.v1b_jm_tasks import build_jm_daily_ema21_macd_volume_task_config

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_jm_v1b_files(session, tmp_path)
        daily_file = session.scalar(select(MarketDataFile).where(MarketDataFile.period == "1d"))
        assert daily_file is not None
        daily_file.data_role = "legacy_reference"
        _seed_jm_daily_contract_reference(session)

        with pytest.raises(ValueError, match="rqdata primary passed"):
            build_jm_daily_ema21_macd_volume_task_config(session)

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_jm_v1b_files(session, tmp_path)
        _seed_jm_daily_contract_reference(session, with_params=False)

        with pytest.raises(ValueError, match="trading parameters"):
            build_jm_daily_ema21_macd_volume_task_config(session)


def test_create_jm_daily_ema21_macd_volume_task_enters_backtest_queue(tmp_path: Path, monkeypatch) -> None:
    import app.api.backtests as api_module

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_jm_v1b_files(session, tmp_path)
        _seed_jm_daily_contract_reference(session)

    queued_ids: list[int] = []

    def fake_enqueue(task_id: int) -> str:
        queued_ids.append(task_id)
        return f"job-{task_id}"

    monkeypatch.setattr(api_module, "enqueue_backtest_task", fake_enqueue)

    def override_get_db():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        created = client.post("/api/backtests/v1b/jm/daily-ema21-macd-volume/tasks")
        legacy = client.post("/api/backtests/v1b/jm/15m/tasks")

        assert created.status_code == 200
        assert legacy.status_code == 200
        assert created.json()["status"] == "queued"
        assert created.json()["fixed_task"]["name"] == "JM V1-B daily EMA21 MACD volume"
        assert created.json()["fixed_task"]["interval"] == "1d"
        assert created.json()["fixed_task"]["strategy_code"] == "su_bing_jm_daily_ema21_macd_volume"
        assert created.json()["fixed_task"]["result_report_id_path"] == "result_payload.report_id"
        assert legacy.json()["fixed_task"]["entry_interval"] == "15m"
        assert queued_ids == [created.json()["id"], legacy.json()["id"]]

        with SessionLocal() as session:
            tasks = session.scalars(select(BacktestTask).order_by(BacktestTask.id)).all()
            assert [task.task_type for task in tasks] == ["v1b_jm_daily_ema21_macd_volume", "v1b_jm_15m_entry"]
            assert tasks[0].vnpy_setting_json["interval"] == "1d"
            assert tasks[0].vnpy_setting_json["auxiliary_bar_data_paths"] == {}
            assert "daily_ema21_macd_volume" in tasks[0].vnpy_strategy_class
            assert tasks[1].vnpy_setting_json["interval"] == "15m"
            assert tasks[1].vnpy_setting_json["auxiliary_bar_data_paths"].keys() == {"1d"}
    finally:
        app.dependency_overrides.clear()


def test_jm_daily_ema21_macd_volume_runner_persists_report_and_exportable_artifacts(tmp_path: Path) -> None:
    from app.backtest.service import BacktestService
    from app.backtest.v1b_jm_tasks import build_jm_daily_ema21_macd_volume_task_config

    SessionLocal = _session_factory()
    adapter = FakeDailySuccessfulAdapter()
    with SessionLocal() as session:
        _seed_jm_v1b_files(session, tmp_path)
        _seed_jm_daily_contract_reference(session)
        spec = build_jm_daily_ema21_macd_volume_task_config(session)
        task = BacktestService(session).create_task(spec.config)
        session.commit()

        result = BacktestTaskRunner(session, adapter=adapter).run(task.id)
        session.refresh(task)

        assert result["status"] == "success"
        assert adapter.requests[0].interval == "1d"
        assert adapter.requests[0].auxiliary_bar_data_paths == {}
        assert adapter.requests[0].strategy_parameters["live_trading_enabled"] is False
        assert adapter.requests[0].strategy_parameters["auto_order_enabled"] is False
        assert task.status == "success"
        assert task.result_payload["report_id"]
        report = session.get(BacktestReportModel, task.result_payload["report_id"])
        assert report is not None
        assert report.strategy_code == "su_bing_jm_daily_ema21_macd_volume"
        assert report.period == "1d"
        assert report.trade_count == 1
        assert report.total_commission == pytest.approx(12.6756)
        assert report.total_slippage == pytest.approx(60.0)
        assert report.max_margin_required == pytest.approx(7803.9)
        assert report.summary["real_contract_enrichment"]["enabled"] is True
        assert report.summary["strategy_review_context"]["strategy_code"] == "su_bing_jm_daily_ema21_macd_volume"
        assert report.summary["report_metadata"]["strategy_review_context"]["data_constraints"]["interval"] == "1d"
        assert task.result_payload["order_count"] == 1
        assert task.result_payload["derived_curve_source"] == "trades"

        trades = session.scalars(select(BacktestTradeModel).where(BacktestTradeModel.report_id == report.id)).all()
        assert len(trades) == 1
        assert trades[0].contract == "JM2309"
        assert trades[0].entry_contract == "JM2309"
        assert trades[0].exit_contract == "JM2309"
        assert trades[0].contract_multiplier == 60
        assert trades[0].price_tick == 0.5
        assert trades[0].commission == pytest.approx(12.6756)
        assert trades[0].slippage == pytest.approx(60.0)
        assert trades[0].margin_ratio == 0.13
        assert trades[0].margin_required == pytest.approx(7803.9)
        assert trades[0].parameter_source == "futures_trading_parameters"
        assert trades[0].raw_payload["entry_reason"].startswith("daily_close_above_ema21")


def test_create_jm_v1b_15m_and_5m_tasks_enter_backtest_queue(tmp_path: Path, monkeypatch) -> None:
    import app.api.backtests as api_module

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_jm_v1b_files(session, tmp_path)

    queued_ids: list[int] = []

    def fake_enqueue(task_id: int) -> str:
        queued_ids.append(task_id)
        return f"job-{task_id}"

    monkeypatch.setattr(api_module, "enqueue_backtest_task", fake_enqueue)

    def override_get_db():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        created_15m = client.post("/api/backtests/v1b/jm/15m/tasks")
        created_5m = client.post("/api/backtests/v1b/jm/5m/tasks")

        assert created_15m.status_code == 200
        assert created_5m.status_code == 200
        assert created_15m.json()["status"] == "queued"
        assert created_5m.json()["status"] == "queued"
        assert created_15m.json()["fixed_task"]["entry_interval"] == "15m"
        assert created_5m.json()["fixed_task"]["entry_interval"] == "5m"
        assert queued_ids == [created_15m.json()["id"], created_5m.json()["id"]]

        with SessionLocal() as session:
            tasks = session.scalars(select(BacktestTask).order_by(BacktestTask.id)).all()
            assert [task.task_type for task in tasks] == ["v1b_jm_15m_entry", "v1b_jm_5m_entry"]
            assert [task.vnpy_setting_json["interval"] for task in tasks] == ["15m", "5m"]
            assert all(task.vnpy_strategy_class and "jm_v1b_daily_direction_fast_entry" in task.vnpy_strategy_class for task in tasks)
            assert all(task.vnpy_setting_json["auxiliary_bar_data_paths"].keys() == {"1d"} for task in tasks)
            assert tasks[0].vnpy_setting_json["strategy_parameters"]["entry_interval"] == "15m"
            assert tasks[1].vnpy_setting_json["strategy_parameters"]["entry_interval"] == "5m"
            assert all(task.vnpy_setting_json["strategy_parameters"]["max_hold_bars_min"] == 5 for task in tasks)
            assert all(task.vnpy_setting_json["strategy_parameters"]["max_hold_bars_max"] == 8 for task in tasks)
            assert all(task.vnpy_setting_json["strategy_parameters"]["stop_loss_atr_multiple"] > 0 for task in tasks)
    finally:
        app.dependency_overrides.clear()


def test_build_su_bing_jm_v1b_short_hold_task_uses_new_strategy_and_enriched_primary_data(tmp_path: Path) -> None:
    from app.backtest.v1b_jm_tasks import build_su_bing_jm_v1b_short_hold_task_config

    SessionLocal = _session_factory()
    bars = [
        {
            "symbol": "jm",
            "contract": "jm.MAIN",
            "exchange": "DCE",
            "vt_symbol": "jm.MAIN.DCE",
            "datetime": datetime(2024, 1, 2, 9, 15, tzinfo=UTC),
            "trading_day": date(2024, 1, 2),
            "interval": "15m",
            "period": "15m",
            "open": 1000.0,
            "high": 1005.0,
            "low": 998.0,
            "close": 1002.0,
            "volume": 100.0,
            "turnover": 100200.0,
            "open_interest": 1000.0,
            "source": "rqdata",
            "provider": "rqdata",
            "source_symbol": "JM2405",
            "data_role": "primary",
            "quality_status": "passed",
        }
    ]
    with SessionLocal() as session:
        _seed_jm_v1b_files(session, tmp_path, bars_by_period={"15m": bars})
        _seed_jm_contract_reference(session)

        spec = build_su_bing_jm_v1b_short_hold_task_config(session, "15m")

        assert spec.config.strategy_code == "su_bing_jm_v1b_short_hold"
        assert spec.config.strategy_version == "v0.1.1-spec"
        assert spec.config.strategy_class_path.endswith("SuBingJmV1bShortHoldStrategy")
        assert spec.config.strategy_parameters["entry_interval"] == "15m"
        assert spec.config.strategy_parameters["submit_vnpy_orders"] is False
        assert spec.config.capital == 1_000_000.0
        assert spec.config.data_role.value == "primary"
        assert spec.config.quality_status == "passed"
        assert spec.config.start == datetime(2023, 6, 28)
        assert spec.config.end == datetime(2025, 12, 31, 15, 0)

        enriched = pd.read_parquet(spec.config.bar_data_path)
        assert len(enriched) == 1
        assert enriched.loc[0, "data_role"] == "primary"
        assert enriched.loc[0, "quality_status"] == "passed"
        assert enriched.loc[0, "actual_contract"] == "JM2405"
        assert enriched.loc[0, "price_tick"] == pytest.approx(0.5)
        assert enriched.loc[0, "contract_multiplier"] == 60
        assert enriched.loc[0, "margin_rate"] == pytest.approx(0.13)
        assert enriched.loc[0, "commission_rate"] == pytest.approx(0.0001)


@pytest.mark.parametrize("entry_interval", ["15m", "5m"])
def test_jm_v1b_fixed_task_runner_persists_real_contract_costs_and_totals(tmp_path: Path, entry_interval: str) -> None:
    from app.backtest.service import BacktestService
    from app.backtest.v1b_jm_tasks import build_jm_v1b_task_config

    SessionLocal = _session_factory()
    adapter = FakeV1bSuccessfulAdapter()
    with SessionLocal() as session:
        _seed_jm_v1b_files(session, tmp_path)
        _seed_jm_contract_reference(session)
        spec = build_jm_v1b_task_config(session, entry_interval)  # type: ignore[arg-type]
        task = BacktestService(session).create_task(spec.config)
        session.commit()

        result = BacktestTaskRunner(session, adapter=adapter).run(task.id)
        session.refresh(task)

        assert result["status"] == "success"
        assert adapter.requests[0].strategy_class_path.endswith("JmV1bDailyDirectionFastEntryStrategy")
        assert adapter.requests[0].strategy_parameters["entry_interval"] == entry_interval
        assert adapter.requests[0].auxiliary_bar_data_paths.keys() == {"1d"}
        assert task.status == "success"
        assert task.error_message is None
        assert task.traceback is None

        report = session.get(BacktestReportModel, task.result_payload["report_id"])
        assert report is not None
        assert report.strategy_code == "jm_v1b_daily_direction_fast_entry"
        assert report.period == entry_interval
        assert report.trade_count == 1
        assert report.total_commission == pytest.approx(18.12)
        assert report.total_slippage == pytest.approx(60.0)
        assert report.max_margin_required == pytest.approx(7800.0)
        assert report.max_margin_usage_pct == pytest.approx(0.078)
        assert report.summary["total_commission"] == pytest.approx(report.total_commission)
        assert report.summary["total_slippage"] == pytest.approx(report.total_slippage)

        trades = session.scalars(select(BacktestTradeModel).where(BacktestTradeModel.report_id == report.id)).all()

        assert len(trades) == 1
        assert report.consistency_hash
        assert task.result_payload["derived_curve_source"] == "trades"
        assert trades[0].entry_reason == "daily_long_ema21_pullback_macd_confirmed"
        assert trades[0].exit_reason == "max_hold_bars_exit"
        assert trades[0].holding_bars == 8
        assert trades[0].sequence == 1
        assert trades[0].exchange == "DCE"
        assert trades[0].research_contract == "jm.MAIN"
        assert trades[0].timeframe == entry_interval
        assert trades[0].contract == "JM2405"
        assert trades[0].entry_contract == "JM2405"
        assert trades[0].exit_contract == "JM2405"
        assert trades[0].contract_multiplier == 60
        assert trades[0].price_tick == 0.5
        assert trades[0].commission == pytest.approx(18.12)
        assert trades[0].slippage == pytest.approx(60.0)
        assert trades[0].margin_ratio == 0.13
        assert trades[0].margin_required == pytest.approx(7800.0)
        assert trades[0].parameter_source == "futures_trading_parameters"
        assert report.total_commission == pytest.approx(sum(trade.commission for trade in trades))
        assert report.total_slippage == pytest.approx(sum(trade.slippage for trade in trades))
        assert report.max_margin_required == pytest.approx(max(trade.margin_required or 0 for trade in trades))
        assert trades[0].raw_payload["daily_direction"] == "long"
        assert trades[0].raw_payload["entry_interval"] == entry_interval
        assert trades[0].raw_payload["stop_loss_price"] == 980.0
        assert trades[0].raw_payload["research_symbol"] == "jm.MAIN"


def test_jm_v1b_forces_jm2405_delivery_risk_exit_before_may_delivery_month(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    bars = [
        {"datetime": datetime(2024, 4, 29, 9, 0, tzinfo=UTC), "open": 1000.0},
        {"datetime": datetime(2024, 4, 30, 14, 30, tzinfo=UTC), "open": 1007.0},
        {"datetime": datetime(2024, 4, 30, 14, 45, tzinfo=UTC), "open": 1008.0},
        {"datetime": datetime(2024, 5, 6, 9, 0, tzinfo=UTC), "open": 1015.0},
    ]
    trade = {
        "entry_datetime": "2024-04-29T09:00:00",
        "exit_datetime": "2024-05-06T09:00:00",
        "entry_price": 1000.0,
        "exit_price": 1015.0,
    }
    with SessionLocal() as session:
        _seed_jm_v1b_files(session, tmp_path, bars_by_period={"15m": bars})
        _seed_jm2405_delivery_reference(session)

        result, task, report, trades = _run_v1b_task_with_trade(session, trade)

        assert result["status"] == "success"
        assert task.status == "success"
        assert report is not None
        assert report.delivery_risk_exit_count == 1
        assert report.rollover_exit_count == 0
        assert len(trades) == 1
        assert trades[0].exit_reason == "delivery_risk_exit"
        assert trades[0].delivery_risk_exit is True
        assert trades[0].rollover_forced_exit is False
        assert trades[0].close_time == datetime(2024, 4, 30, 14, 45)
        assert trades[0].close_price == pytest.approx(1008.0)
        assert trades[0].raw_payload["rollover_reason"] == "last_allowed_holding_date=2024-04-30"


def test_jm_v1b_blocks_new_entries_inside_jm2405_delivery_window(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    bars = [
        {"datetime": datetime(2024, 4, 30, 9, 0, tzinfo=UTC), "open": 1000.0},
        {"datetime": datetime(2024, 4, 30, 14, 45, tzinfo=UTC), "open": 1005.0},
    ]
    trade = {
        "entry_datetime": "2024-04-30T09:00:00",
        "exit_datetime": "2024-04-30T14:45:00",
        "entry_price": 1000.0,
        "exit_price": 1005.0,
    }
    with SessionLocal() as session:
        _seed_jm_v1b_files(session, tmp_path, bars_by_period={"15m": bars})
        _seed_jm2405_delivery_reference(session, mapping={date(2024, 4, 30): "JM2405"})

        result, task, report, trades = _run_v1b_task_with_trade(session, trade)

        assert result["status"] == "success"
        assert task.status == "success"
        assert report is not None
        assert report.trade_count == 0
        assert report.summary["blocked_delivery_window_entry_count"] == 1
        assert report.warnings[0]["code"] == "blocked_delivery_window_entry"
        assert trades == []


def test_jm_v1b_forces_exit_when_main_contract_switches(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    bars = [
        {"datetime": datetime(2024, 4, 19, 9, 0, tzinfo=UTC), "open": 1000.0},
        {"datetime": datetime(2024, 4, 19, 14, 45, tzinfo=UTC), "open": 1006.0},
        {"datetime": datetime(2024, 4, 20, 9, 0, tzinfo=UTC), "open": 1010.0},
    ]
    trade = {
        "entry_datetime": "2024-04-19T09:00:00",
        "exit_datetime": "2024-04-20T09:00:00",
        "entry_price": 1000.0,
        "exit_price": 1010.0,
    }
    with SessionLocal() as session:
        _seed_jm_v1b_files(session, tmp_path, bars_by_period={"15m": bars})
        _seed_jm_rollover_reference(session)

        result, task, report, trades = _run_v1b_task_with_trade(session, trade)

        assert result["status"] == "success"
        assert task.status == "success"
        assert report is not None
        assert report.rollover_exit_count == 1
        assert report.delivery_risk_exit_count == 0
        assert len(trades) == 1
        assert trades[0].exit_reason == "main_contract_roll_exit"
        assert trades[0].rollover_forced_exit is True
        assert trades[0].delivery_risk_exit is False
        assert trades[0].entry_contract == "JM2405"
        assert trades[0].exit_contract == "JM2405"
        assert trades[0].close_time == datetime(2024, 4, 19, 14, 45)
        assert trades[0].close_price == pytest.approx(1006.0)
        assert trades[0].rollover_reason == "main_contract_changed:JM2405->JM2409"
        assert trades[0].raw_payload["original_exit_reason"] == "max_hold_bars_exit"


def test_jm_v1b_runner_fails_clearly_when_trading_parameters_are_missing(tmp_path: Path) -> None:
    from app.backtest.service import BacktestService
    from app.backtest.v1b_jm_tasks import build_jm_v1b_task_config

    SessionLocal = _session_factory()
    adapter = FakeV1bSuccessfulAdapter()
    with SessionLocal() as session:
        _seed_jm_v1b_files(session, tmp_path)
        _seed_jm_contract_reference(session, with_params=False)
        spec = build_jm_v1b_task_config(session, "15m")
        task = BacktestService(session).create_task(spec.config)
        session.commit()

        result = BacktestTaskRunner(session, adapter=adapter).run(task.id)
        session.refresh(task)

        assert result["status"] == "failed"
        assert task.status == "failed"
        assert task.error_type == "TradingParameterMissingError"
        assert task.error_message is not None
        assert "trading parameters missing for contract=JM2405" in task.error_message
        assert task.traceback


def test_jm_v1b_fixed_task_rejects_missing_formal_data(tmp_path: Path, monkeypatch) -> None:
    import app.api.backtests as api_module

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_jm_v1b_files(session, tmp_path)
        missing = session.scalar(select(MarketDataFile).where(MarketDataFile.period == "15m"))
        assert missing is not None
        Path(missing.file_path).unlink()
        session.commit()

    monkeypatch.setattr(api_module, "enqueue_backtest_task", lambda task_id: f"job-{task_id}")

    def override_get_db():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post("/api/backtests/v1b/jm/15m/tasks")

        assert response.status_code == 422
        assert "registered but missing on disk" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
