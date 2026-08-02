from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.backtest.actual_dominant_roll import (
    apply_actual_dominant_roll_accounting,
    bar_open_time,
)
from app.backtest.runner import BacktestTaskRunner
from app.backtest.service import BacktestService
from app.backtest.contract_resolver import (
    ContractResolutionError,
    TradingParameterMissingError,
    resolve_jm_contract,
)
from app.backtest.equity_curve_generator import generate_equity_curve
from app.data_core.bar_schema import CANONICAL_BAR_SCHEMA_VERSION, CanonicalBar
from app.data_core.contracts import BarFrequency, BarQuery, BarsResult, DatasetKey
from app.db.base import Base
from app.models.data_center import (
    Contract,
    Exchange,
    FuturesTradingParameter,
    Instrument,
    MainContractMap,
    TradingCalendar,
)
from app.models.backtest import BacktestReportModel


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_contract_day(
    session: Session,
    *,
    trading_day: date,
    contract: str,
    multiplier: int,
    tick: str,
    open_fee: str,
    close_fee: str,
    close_today_fee: str | None = None,
) -> None:
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=trading_day,
            rank=1,
            contract_code=contract,
            rule="volume_open_interest",
            provider="rqdata",
            data_version="test-v1",
            raw_payload={
                "known_at": datetime.combine(
                    trading_day, datetime.min.time(), tzinfo=UTC
                ).isoformat()
            },
        )
    )
    session.add(
        FuturesTradingParameter(
            contract_code=contract,
            instrument_symbol="jm",
            exchange_code="DCE",
            trade_date=trading_day,
            long_margin_ratio=Decimal("0.12"),
            short_margin_ratio=Decimal("0.12"),
            open_commission=Decimal(open_fee),
            close_commission=Decimal(close_fee),
            close_today_commission=Decimal(close_today_fee or close_fee),
            commission_type="by_money",
            price_tick=Decimal(tick),
            contract_multiplier=multiplier,
            provider="rqdata",
            data_version="test-v1",
        )
    )


def _seed_reference_data(session: Session) -> None:
    session.add(Exchange(code="DCE", name="DCE", country="CN", timezone="Asia/Shanghai", is_active=True))
    session.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE", is_active=True))
    session.add_all(
        [
            Contract(
                contract_code="JM2405",
                instrument_symbol="jm",
                exchange_code="DCE",
                name="焦煤2405",
                contract_month="2024-05",
                contract_multiplier=10,
                maturity_date=date(2024, 5, 15),
                provider="rqdata",
            ),
            Contract(
                contract_code="JM2409",
                instrument_symbol="jm",
                exchange_code="DCE",
                name="焦煤2409",
                contract_month="2024-09",
                contract_multiplier=20,
                maturity_date=date(2024, 9, 15),
                provider="rqdata",
            ),
        ]
    )
    session.add_all(
        [
            TradingCalendar(exchange_code="DCE", trade_date=date(2024, 4, 30), is_trading_day=True, provider="rqdata"),
            TradingCalendar(exchange_code="DCE", trade_date=date(2024, 8, 30), is_trading_day=True, provider="rqdata"),
        ]
    )
    _seed_contract_day(
        session,
        trading_day=date(2024, 4, 29),
        contract="JM2405",
        multiplier=10,
        tick="0.5",
        open_fee="0.001",
        close_fee="0.002",
        close_today_fee="0.005",
    )
    _seed_contract_day(
        session,
        trading_day=date(2024, 5, 6),
        contract="JM2409",
        multiplier=20,
        tick="1",
        open_fee="0.003",
        close_fee="0.004",
        close_today_fee="0.006",
    )
    session.commit()


def _bars() -> list[dict[str, object]]:
    return [
        {
            "datetime": datetime(2024, 4, 29, 9, 15, tzinfo=UTC),
            "trading_day": date(2024, 4, 29),
            "contract": "JM2405",
            "interval": "15m",
            "open": Decimal("90"),
            "close": Decimal("95"),
        },
        {
            "datetime": datetime(2024, 4, 29, 15, 0, tzinfo=UTC),
            "trading_day": date(2024, 4, 29),
            "contract": "JM2405",
            "interval": "15m",
            "open": Decimal("95"),
            "close": Decimal("100"),
        },
        {
            "datetime": datetime(2024, 5, 6, 9, 15, tzinfo=UTC),
            "trading_day": date(2024, 5, 6),
            "contract": "JM2409",
            "interval": "15m",
            "open": Decimal("110"),
            "close": Decimal("115"),
        },
        {
            "datetime": datetime(2024, 5, 6, 9, 30, tzinfo=UTC),
            "trading_day": date(2024, 5, 6),
            "contract": "JM2409",
            "interval": "15m",
            "open": Decimal("115"),
            "close": Decimal("120"),
        },
    ]


def _result(*, trades: list[dict[str, object]] | None = None, orders=None) -> dict[str, object]:
    return {
        "summary": {"initial_capital": Decimal("1000")},
        "trades": trades
        if trades is not None
        else [
            {
                "trade_id": "strategy-1",
                "sequence": 1,
                "direction": "long",
                "entry_datetime": datetime(2024, 4, 29, 9, 15, tzinfo=UTC),
                "exit_datetime": datetime(2024, 5, 6, 9, 30, tzinfo=UTC),
                "entry_price": Decimal("90"),
                "exit_price": Decimal("120"),
                "volume": 2,
                "entry_reason": "strategy_entry",
                "exit_reason": "strategy_exit",
            }
        ],
        "orders": list(orders or []),
    }


def _canonical_roll_result(query: BarQuery) -> BarsResult:
    bars = tuple(
        CanonicalBar(
            provider="rqdata",
            dataset_kind=query.dataset_kind,
            symbol="jm",
            contract_or_series=str(row["contract"]),
            frequency=query.frequency,
            bar_end=row["datetime"],
            trading_day=row["trading_day"],
            open=row["open"],
            high=max(row["open"], row["close"]),
            low=min(row["open"], row["close"]),
            close=row["close"],
            volume=Decimal("1"),
            turnover=Decimal("1"),
            open_interest=Decimal("1"),
            adjustment="none",
            schema_version=CANONICAL_BAR_SCHEMA_VERSION,
        )
        for row in _bars()
    )
    sources = tuple(
        DatasetKey(
            provider="rqdata",
            dataset_kind=query.dataset_kind,
            symbol="jm",
            contract_or_series=contract,
            frequency=BarFrequency.M1,
            adjustment="none",
            schema_version=CANONICAL_BAR_SCHEMA_VERSION,
        )
        for contract in ("JM2405", "JM2409")
    )
    return BarsResult(
        bars=bars,
        source_datasets=sources,
        manifest_digests=("a" * 64, "b" * 64),
        source_data_versions=("roll-v1",),
        requested_window=(query.start, query.end),
        data_type=query.dataset_kind,
        derived_frequency=BarFrequency.M15,
    )


class _RollingMarketData:
    def get_bars(self, query: BarQuery) -> BarsResult:
        return _canonical_roll_result(query)


class _RollingAdapter:
    def run(self, request):
        return {
            "statistics": {"capital": request.capital},
            "prepared": {
                "vt_symbol": "jm.DCE",
                "interval": request.interval,
                "start": request.start.isoformat(),
                "end": request.end.isoformat(),
                "capital": request.capital,
                "size": request.size,
                "pricetick": request.pricetick,
            },
            "strategy_trades": _result()["trades"],
            "orders": [],
        }


class _MustNotRunAdapter:
    def run(self, request):
        pytest.fail("vn.py adapter ran before mapping known_at validation")


def test_roll_splits_open_exposure_and_charges_both_contract_legs_with_decimal() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)

        result = apply_actual_dominant_roll_accounting(
            session,
            _result(),
            bars=_bars(),
            slippage_ticks=Decimal("1"),
        )

    assert len(result["trades"]) == 2
    old_segment, new_segment = result["trades"]
    assert old_segment["entry_contract"] == old_segment["exit_contract"] == "JM2405"
    assert old_segment["exit_price"] == Decimal("100")
    assert old_segment["exit_reason"] == "contract_roll_boundary"
    assert new_segment["entry_contract"] == new_segment["exit_contract"] == "JM2409"
    assert new_segment["entry_price"] == Decimal("110")
    assert new_segment["entry_datetime"] == "2024-05-06T09:00:00+00:00"
    assert new_segment["entry_reason"] == "contract_roll_reopen"
    assert result["roll_events"] == [
        {
            "old_contract": "JM2405",
            "new_contract": "JM2409",
            "direction": "long",
            "volume": 2,
            "close_price": Decimal("100"),
            "open_price": Decimal("110"),
            "close_commission": Decimal("10.000"),
            "open_commission": Decimal("13.200"),
            "close_slippage": Decimal("10.0"),
            "open_slippage": Decimal("40"),
        }
    ]
    assert sum((trade["commission"] for trade in result["trades"]), Decimal("0")) == Decimal("53.800")
    assert sum((trade["slippage"] for trade in result["trades"]), Decimal("0")) == Decimal("100.0")
    assert sum((trade["net_pnl"] for trade in result["trades"]), Decimal("0")) == Decimal("446.200")
    equity = generate_equity_curve(result["trades"], initial_capital=Decimal("1000"))
    assert Decimal(str(equity[-1]["equity"])) == Decimal("1446.2")


@pytest.mark.parametrize(
    ("interval", "bar_end", "expected"),
    [
        (
            "15m",
            datetime(2024, 5, 6, 9, 15, tzinfo=UTC),
            datetime(2024, 5, 6, 9, 0, tzinfo=UTC),
        ),
        (
            "60m",
            datetime(2024, 5, 6, 10, 0, tzinfo=UTC),
            datetime(2024, 5, 6, 9, 0, tzinfo=UTC),
        ),
    ],
)
def test_roll_reopen_time_is_bar_open_for_intraday_frequency(
    interval: str, bar_end: datetime, expected: datetime
) -> None:
    assert bar_open_time({"datetime": bar_end, "interval": interval}) == expected


def test_mapping_requires_explicit_known_at_no_later_than_first_bar_open() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        mapping = session.query(MainContractMap).filter_by(
            trade_date=date(2024, 5, 6)
        ).one()
        mapping.raw_payload = {}
        mapping.created_at = datetime(2024, 5, 6, 8, 0, tzinfo=UTC)
        session.flush()

        with pytest.raises(ContractResolutionError, match="known_at"):
            apply_actual_dominant_roll_accounting(
                session,
                _result(),
                bars=_bars(),
                slippage_ticks=Decimal("1"),
            )

        mapping.raw_payload = {"known_at": "2024-05-06T09:01:00+00:00"}
        session.flush()
        with pytest.raises(ContractResolutionError, match="known_at"):
            apply_actual_dominant_roll_accounting(
                session,
                _result(),
                bars=_bars(),
                slippage_ticks=Decimal("1"),
            )


def test_runner_blocks_unknown_mapping_before_vnpy_execution() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        mapping = session.query(MainContractMap).filter_by(
            trade_date=date(2024, 5, 6)
        ).one()
        mapping.raw_payload = {}
        session.commit()
        service = BacktestService(session, market_data=_RollingMarketData())
        task = service.create_formal_task(
            {
                "dataset_kind": "actual_dominant",
                "instrument_symbol": "jm",
                "exchange": "DCE",
                "interval": "15m",
                "start": datetime(2024, 4, 29, 9, 0, tzinfo=UTC),
                "end": datetime(2024, 5, 6, 10, 0, tzinfo=UTC),
                "strategy_class_path": "tests.test_actual_dominant_roll_accounting:FakeStrategy",
                "strategy_code": "roll_test",
                "strategy_version": "v1",
                "strategy_parameters": {
                    "indicator_versions": ["ema21"],
                    "formal_policy_ids": ["ema_sma_window_v1"],
                    "confirmed_only": True,
                    "research_status": "formal_candidate",
                },
            }
        )
        session.commit()

        outcome = BacktestTaskRunner(
            session,
            adapter=_MustNotRunAdapter(),
            service=service,
        ).run(task.id)

        assert outcome["status"] == "failed"
        assert outcome["error_type"] == "MainContractMappingKnowledgeError"
        assert session.query(BacktestReportModel).count() == 0


def test_high_precision_roll_equity_and_metrics_remain_decimal() -> None:
    from app.backtest.report_metrics import compute_report_metrics

    trades = [
        {
            "trade_id": "precision-1",
            "sequence": 1,
            "exit_datetime": "2024-01-02T10:00:00+00:00",
            "net_pnl": Decimal("0.000000000000000001"),
            "gross_pnl": Decimal("0.000000000000000003"),
            "commission": Decimal("0.000000000000000001"),
            "slippage": Decimal("0.000000000000000001"),
        }
    ]
    initial = Decimal("1000.000000000000000001")
    equity = generate_equity_curve(trades, initial_capital=initial)
    metrics = compute_report_metrics(
        summary={"initial_capital": initial},
        trades=trades,
        equity_curve=equity,
        drawdown_curve=[],
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 2, tzinfo=UTC),
        default_initial_capital=initial,
    )

    assert equity[-1]["equity"] == Decimal("1000.000000000000000002")
    assert metrics["initial_capital"] == initial
    assert metrics["total_net_pnl"] == Decimal("0.000000000000000001")
    assert metrics["final_equity"] == Decimal("1000.000000000000000002")


def test_part_filled_old_contract_order_cancels_only_remainder_and_preserves_fill() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        result = apply_actual_dominant_roll_accounting(
            session,
            _result(
                trades=[
                    {
                        "trade_id": "filled-part",
                        "entry_order_no": "pending-1",
                        "direction": "long",
                        "entry_datetime": datetime(2024, 5, 6, 9, 15, tzinfo=UTC),
                        "exit_datetime": datetime(2024, 5, 6, 9, 30, tzinfo=UTC),
                        "entry_price": Decimal("110"),
                        "exit_price": Decimal("120"),
                        "volume": 1,
                    }
                ],
                orders=[
                    {
                        "order_id": "pending-1",
                        "symbol": "JM2405",
                        "status": "part_traded",
                        "volume": 2,
                        "traded": 1,
                        "datetime": datetime(2024, 4, 29, 15, 0, tzinfo=UTC),
                    }
                ],
            ),
            bars=_bars(),
            slippage_ticks=Decimal("1"),
        )

    assert len(result["trades"]) == 1
    assert result["trades"][0]["trade_id"] == "filled-part"
    assert result["trades"][0]["volume"] == 1
    assert result["roll_events"] == []
    assert result["orders"][0]["status"] == "cancelled"
    assert result["orders"][0]["cancel_reason"] == "contract_roll_boundary"
    assert result["orders"][0]["cancelled_volume"] == 1
    assert result["orders"][0]["traded"] == 1


def test_roll_fails_closed_on_mapping_mismatch_or_missing_contract_parameters() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        mismatched = _bars()
        mismatched[2] = {**mismatched[2], "contract": "JM2405"}
        with pytest.raises(ContractResolutionError, match="rank=1 mapping"):
            apply_actual_dominant_roll_accounting(
                session,
                _result(),
                bars=mismatched,
                slippage_ticks=Decimal("1"),
            )

        parameter = session.query(FuturesTradingParameter).filter_by(
            contract_code="JM2409"
        ).one()
        session.delete(parameter)
        session.flush()
        with pytest.raises(TradingParameterMissingError):
            apply_actual_dominant_roll_accounting(
                session,
                _result(),
                bars=_bars(),
                slippage_ticks=Decimal("1"),
            )


def test_contract_day_parameters_preserve_exact_decimal_values() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        parameter = session.query(FuturesTradingParameter).filter_by(
            contract_code="JM2405"
        ).one()
        parameter.open_commission = Decimal("0.001000000000000001")
        session.flush()

        resolved = resolve_jm_contract(session, trading_day=date(2024, 4, 29))

    assert resolved.commission_rule.open_fee == Decimal("0.001000000000000001")

def test_runner_failure_creates_no_report_when_roll_parameters_are_missing() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        parameter = session.query(FuturesTradingParameter).filter_by(
            contract_code="JM2409"
        ).one()
        session.delete(parameter)
        session.commit()
        service = BacktestService(session, market_data=_RollingMarketData())
        task = service.create_formal_task(
            {
                "dataset_kind": "actual_dominant",
                "instrument_symbol": "jm",
                "contract_or_series": None,
                "exchange": "DCE",
                "interval": "15m",
                "start": datetime(2024, 4, 29, 9, 0, tzinfo=UTC),
                "end": datetime(2024, 5, 6, 10, 0, tzinfo=UTC),
                "strategy_class_path": "tests.test_actual_dominant_roll_accounting:FakeStrategy",
                "strategy_code": "roll_test",
                "strategy_version": "v1",
                "strategy_parameters": {
                    "indicator_versions": ["ema21"],
                    "formal_policy_ids": ["ema_sma_window_v1"],
                    "confirmed_only": True,
                    "research_status": "formal_candidate",
                },
                "slippage": 1,
            }
        )
        session.commit()

        result = BacktestTaskRunner(
            session,
            adapter=_RollingAdapter(),
            service=service,
        ).run(task.id)

        assert result["status"] == "failed"
        assert result["error_type"] == "TradingParameterMissingError"
        assert session.query(BacktestReportModel).count() == 0


def test_runner_persists_one_recomputed_rolled_fact_set() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        service = BacktestService(session, market_data=_RollingMarketData())
        task = service.create_formal_task(
            {
                "dataset_kind": "actual_dominant",
                "instrument_symbol": "jm",
                "contract_or_series": None,
                "exchange": "DCE",
                "interval": "15m",
                "start": datetime(2024, 4, 29, 9, 0, tzinfo=UTC),
                "end": datetime(2024, 5, 6, 10, 0, tzinfo=UTC),
                "strategy_class_path": "tests.test_actual_dominant_roll_accounting:FakeStrategy",
                "strategy_code": "roll_test",
                "strategy_version": "v1",
                "strategy_parameters": {
                    "indicator_versions": ["ema21"],
                    "formal_policy_ids": ["ema_sma_window_v1"],
                    "confirmed_only": True,
                    "research_status": "formal_candidate",
                },
                "slippage": 1,
                "capital": 1000,
            }
        )
        session.commit()

        result = BacktestTaskRunner(
            session,
            adapter=_RollingAdapter(),
            service=service,
        ).run(task.id)

        assert result["status"] == "success", result
        report = session.query(BacktestReportModel).one()
        assert len(report.trades) == 2
        assert report.trades[0].exit_reason == "contract_roll_boundary"
        assert report.trades[1].entry_reason == "contract_roll_reopen"
        assert Decimal(str(report.final_equity)) == Decimal("1446.2")
        assert Decimal(str(result["result"]["summary"]["final_equity"])) == Decimal(
            "1446.2"
        )
        assert Decimal(str(result["result"]["summary"]["total_net_pnl"])) == Decimal(
            "446.2"
        )
        task_summary = task.result_payload["normalized_result"]["summary"]
        assert Decimal(str(task_summary["final_equity"])) == Decimal("1446.2")
        assert Decimal(str(report.summary["total_net_pnl"])) == sum(
            (Decimal(str(trade.net_pnl)) for trade in report.trades),
            Decimal("0"),
        )
        assert Decimal(str(result["result"]["equity_curve"][-1]["equity"])) == Decimal(
            "1446.2"
        )


def test_result_persistence_failure_after_report_flush_is_atomic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.backtest.service as service_module

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        service = BacktestService(session, market_data=_RollingMarketData())
        task = service.create_formal_task(
            {
                "dataset_kind": "actual_dominant",
                "instrument_symbol": "jm",
                "contract_or_series": None,
                "exchange": "DCE",
                "interval": "15m",
                "start": datetime(2024, 4, 29, 9, 0, tzinfo=UTC),
                "end": datetime(2024, 5, 6, 10, 0, tzinfo=UTC),
                "strategy_class_path": "tests.test_actual_dominant_roll_accounting:FakeStrategy",
                "strategy_code": "roll_test",
                "strategy_version": "v1",
                "strategy_parameters": {
                    "indicator_versions": ["ema21"],
                    "formal_policy_ids": ["ema_sma_window_v1"],
                    "confirmed_only": True,
                    "research_status": "formal_candidate",
                },
                "slippage": 1,
                "capital": 1000,
            }
        )
        session.commit()
        original_trade_model = service_module._trade_model
        calls = 0

        def fail_on_second_trade(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("injected second trade conversion failure")
            return original_trade_model(*args, **kwargs)

        monkeypatch.setattr(service_module, "_trade_model", fail_on_second_trade)

        outcome = BacktestTaskRunner(
            session,
            adapter=_RollingAdapter(),
            service=service,
        ).run(task.id)

        assert outcome["status"] == "failed"
        assert session.query(BacktestReportModel).count() == 0
        assert session.query(service_module.BacktestTradeModel).count() == 0
        assert session.query(service_module.BacktestOrderModel).count() == 0
        session.refresh(task)
        assert task.status == "failed"


class FakeStrategy:
    pass
