from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import (
    Contract,
    DataDownloadTask,
    DataQualityReport,
    FeeMarginRule,
    FuturesBasis,
    FuturesContinuousContractMap,
    FuturesContractUniverse,
    FuturesExFactor,
    FuturesTradingParameter,
    FuturesWarehouseStock,
    Instrument,
    MainContractMap,
    MarketDataFile,
)
from app.services.rqdata_ingest.db import as_date
from app.services.rqdata_ingest.client import RqDataClient
from app.services.rqdata_ingest.ingestors import (
    CatalogIngestor,
    ContinuousContractIngestor,
    ContractUniverseIngestor,
    DailyBaselineIngestor,
    DominantDailyBaselineIngestor,
    ExFactorIngestor,
    MainMappingIngestor,
    MarketSampleIngestor,
    ResearchEnhancerIngestor,
    TradingParameterIngestor,
)
from app.services.rqdata_ingest.recovery import backfill_ex_factors_from_raw


class FakeRqDataClient:
    def all_future_instruments(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "order_book_id": "RB2405",
                    "underlying_symbol": "RB",
                    "symbol": "螺纹钢2405",
                    "exchange": "SHFE",
                    "listed_date": "2024-01-01",
                    "de_listed_date": "2024-05-15",
                    "contract_multiplier": 10,
                    "trading_code": "rb2405",
                    "maturity_date": "2024-05-15",
                    "product": "rb",
                    "trading_hours": "09:00-10:15,10:30-11:30,13:30-15:00",
                }
            ]
        )

    def trading_dates(self, start_date: date, end_date: date) -> list[date]:
        return [date(2024, 1, 2), date(2024, 1, 3)]

    def trading_periods(self, products: list[str]) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "product": "rb",
                    "exchange": "SHFE",
                    "session_name": "day",
                    "start_time": "09:00:00",
                    "end_time": "15:00:00",
                }
            ]
        )

    def dominant_contracts(self, product: str, start_date: date, end_date: date, rank: int) -> pd.DataFrame:
        contract = "RB2405" if rank == 1 else "RB2410"
        return pd.DataFrame(
            [
                {"date": date(2024, 1, 2), "contract": contract},
                {"date": date(2024, 1, 3), "contract": contract},
            ]
        )

    def continuous_contracts(self, product: str, start_date: date, end_date: date) -> pd.DataFrame:
        return pd.DataFrame([{"date": date(2024, 1, 2), "near_month": "RB2405", "next_month": "RB2410"}])

    def listed_contracts(self, product: str, trade_date: date) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"date": trade_date, "contract": "RB2405"},
                {"date": trade_date, "contract": "RB2410"},
            ]
        )

    def continuous_contract_by_type(self, product: str, start_date: date, end_date: date, continuous_type: str) -> pd.DataFrame:
        contract = "RB2405" if continuous_type == "front_month" else "RB2410"
        return pd.DataFrame(
            [
                {"date": date(2024, 1, 2), "contract": contract},
                {"date": date(2024, 1, 3), "contract": contract},
            ]
        )

    def ex_factor(self, product: str, start_date: date, end_date: date) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "date": date(2024, 1, 2),
                    "contract": "RB2405",
                    "prev_close_spread": 1.0,
                    "open_spread": 1.1,
                    "prev_close_ratio": 0.99,
                    "open_ratio": 1.01,
                }
            ]
        )

    def trading_parameters(self, contract: str, start_date: date, end_date: date) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "date": date(2024, 1, 2),
                    "contract": contract,
                    "product": "rb",
                    "exchange": "SHFE",
                    "long_margin_ratio": 0.09,
                    "short_margin_ratio": 0.1,
                    "open_commission": 0.0001,
                    "close_commission": 0.0001,
                    "close_today_commission": 0.0002,
                    "commission_type": "by_money",
                    "price_tick": 1.0,
                    "contract_multiplier": 10,
                    "min_order_quantity": 1,
                    "max_order_quantity": 500,
                }
            ]
        )

    def contract_multiplier(self, contract: str) -> int:
        return 10

    def price_tick(self, contract: str) -> float:
        return 1.0

    def exchange_daily(self, contract: str, start_date: date, end_date: date) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "date": date(2024, 1, 2),
                    "order_book_id": contract,
                    "open": 3900,
                    "high": 3920,
                    "low": 3880,
                    "close": 3910,
                    "settlement": 3905,
                    "prev_settlement": 3890,
                    "limit_up": 4200,
                    "limit_down": 3600,
                    "volume": 10000,
                    "open_interest": 120000,
                    "turnover": 390000000,
                }
            ]
        )

    def dominant_daily_price(self, product: str, start_date: date, end_date: date) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "datetime": pd.Timestamp("2024-01-02"),
                    "dominant_id": "RB2405",
                    "open": 3900,
                    "high": 3920,
                    "low": 3880,
                    "close": 3910,
                    "settlement": 3905,
                    "prev_settlement": 3890,
                    "limit_up": 4200,
                    "limit_down": 3600,
                    "volume": 10000,
                    "open_interest": 120000,
                }
            ]
        )

    def warehouse_stocks(self, product: str, start_date: date, end_date: date) -> pd.DataFrame:
        return pd.DataFrame([{"date": date(2024, 1, 2), "product": product, "warehouse": "上海", "quantity": 1000}])

    def roll_yield(self, product: str, start_date: date, end_date: date) -> pd.DataFrame:
        return pd.DataFrame([{"date": date(2024, 1, 2), "product": product, "near_contract": "RB2405", "far_contract": "RB2410", "roll_yield": 0.01}])

    def basis(self, contract: str, start_date: date, end_date: date) -> pd.DataFrame:
        return pd.DataFrame([{"date": date(2024, 1, 2), "contract": contract, "spot_price": 4000, "futures_price": 3910, "basis": 90}])


def test_rqdata_client_listed_contracts_normalizes_list_result() -> None:
    class FakeFuturesApi:
        @staticmethod
        def get_contracts(product: str, date: date) -> list[str]:
            assert product == "RB"
            return ["RB2405", "RB2410"]

    class FakeRqdatacModule:
        futures = FakeFuturesApi()

    client = object.__new__(RqDataClient)
    client.rqdatac = FakeRqdatacModule()

    frame = client.listed_contracts("rb", date(2024, 1, 2))

    assert list(frame.columns) == ["contract", "date"]
    assert frame.to_dict("records") == [
        {"contract": "RB2405", "date": date(2024, 1, 2)},
        {"contract": "RB2410", "date": date(2024, 1, 2)},
    ]


def _session(tmp_path: Path):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def test_catalog_ingest_writes_contracts_calendar_sessions_and_raw_file(tmp_path) -> None:
    with _session(tmp_path) as session:
        ingestor = CatalogIngestor(session=session, client=FakeRqDataClient(), project_root=tmp_path)
        result = ingestor.run(start_date=date(2024, 1, 1), end_date=date(2024, 1, 31))
        session.commit()

        assert result.rows == 4
        assert session.scalar(select(Instrument).where(Instrument.symbol == "rb")) is not None
        contract = session.scalar(select(Contract).where(Contract.contract_code == "RB2405"))
        assert contract is not None
        assert contract.contract_multiplier == 10
        assert contract.product == "rb"
        assert session.scalar(select(func.count()).select_from(MarketDataFile)) == 1
        assert (tmp_path / "data/raw/rqdata/catalog/futures_contracts.parquet").exists()


def test_as_date_handles_invalid_placeholders() -> None:
    assert as_date("0000-00-00") is None
    assert as_date("0000/00/00") is None
    assert as_date("") is None
    assert as_date("nat") is None
    assert as_date("2024-05-15") == date(2024, 5, 15)


def test_catalog_ingest_tolerates_invalid_maturity_date(tmp_path) -> None:
    class ClientWithInvalidDate(FakeRqDataClient):
        def all_future_instruments(self) -> pd.DataFrame:
            frame = super().all_future_instruments()
            invalid = frame.iloc[0].to_dict()
            invalid.update(
                {
                    "order_book_id": "RB9999",
                    "symbol": "螺纹钢9999",
                    "maturity_date": "0000-00-00",
                    "start_delivery_date": "0000-00-00",
                    "end_delivery_date": "0000-00-00",
                }
            )
            return pd.DataFrame([frame.iloc[0].to_dict(), invalid])

    with _session(tmp_path) as session:
        CatalogIngestor(session=session, client=ClientWithInvalidDate(), project_root=tmp_path).run(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        session.commit()

        contract = session.scalar(select(Contract).where(Contract.contract_code == "RB9999"))
        assert contract is not None
        assert contract.maturity_date is None
        assert contract.start_delivery_date is None
        assert contract.end_delivery_date is None


def test_catalog_ingest_does_not_pollute_instrument_name_with_synthetic_contract(tmp_path) -> None:
    class ClientWithSynthetic(FakeRqDataClient):
        def all_future_instruments(self) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "order_book_id": "RB2405",
                        "underlying_symbol": "RB",
                        "symbol": "螺纹钢2405",
                        "exchange": "SHFE",
                        "listed_date": "2024-01-01",
                        "de_listed_date": "2024-05-15",
                        "contract_multiplier": 10,
                    },
                    {
                        "order_book_id": "RB8888",
                        "underlying_symbol": "RB",
                        "symbol": "螺纹钢8888",
                        "exchange": "SHFE",
                        "listed_date": "0000-00-00",
                        "de_listed_date": "0000-00-00",
                        "contract_multiplier": 10,
                    },
                    {
                        "order_book_id": "RB9999",
                        "underlying_symbol": "RB",
                        "symbol": "螺纹钢指数连续",
                        "exchange": "SHFE",
                        "listed_date": "0000-00-00",
                        "de_listed_date": "0000-00-00",
                        "contract_multiplier": 10,
                    },
                ]
            )

    with _session(tmp_path) as session:
        CatalogIngestor(session=session, client=ClientWithSynthetic(), project_root=tmp_path).run(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        session.commit()

        instrument = session.scalar(select(Instrument).where(Instrument.symbol == "rb"))
        assert instrument is not None
        assert instrument.name == "螺纹钢"
        assert session.scalar(select(Contract).where(Contract.contract_code == "RB8888")) is not None


def test_catalog_ingest_does_not_downgrade_chinese_name_with_ascii_contract(tmp_path) -> None:
    class ClientWithMixedSymbols(FakeRqDataClient):
        def all_future_instruments(self) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "order_book_id": "RB2610",
                        "underlying_symbol": "RB",
                        "symbol": "rb2610",
                        "exchange": "SHFE",
                        "listed_date": "2025-10-16",
                        "de_listed_date": "2026-10-15",
                        "contract_multiplier": 10,
                    },
                    {
                        "order_book_id": "RB0909",
                        "underlying_symbol": "RB",
                        "symbol": "螺纹钢0909",
                        "exchange": "SHFE",
                        "listed_date": "2009-09-01",
                        "de_listed_date": "2009-09-15",
                        "contract_multiplier": 10,
                    },
                ]
            )

    with _session(tmp_path) as session:
        CatalogIngestor(session=session, client=ClientWithMixedSymbols(), project_root=tmp_path).run(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        session.commit()

        instrument = session.scalar(select(Instrument).where(Instrument.symbol == "rb"))
        assert instrument is not None
        assert instrument.name == "螺纹钢"


def test_mapping_and_ex_factor_ingest_upsert_structured_tables(tmp_path) -> None:
    with _session(tmp_path) as session:
        CatalogIngestor(session=session, client=FakeRqDataClient(), project_root=tmp_path).run(date(2024, 1, 1), date(2024, 1, 31))
        MainMappingIngestor(session=session, client=FakeRqDataClient(), project_root=tmp_path).run(
            products=["rb"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            ranks=[1, 2],
        )
        ExFactorIngestor(session=session, client=FakeRqDataClient(), project_root=tmp_path).run(
            products=["rb"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        session.commit()

        assert session.scalar(select(func.count()).select_from(MainContractMap)) == 4
        rank_two = session.scalar(select(MainContractMap).where(MainContractMap.rank == 2))
        assert rank_two is not None
        assert rank_two.contract_code == "RB2410"
        factor = session.scalar(select(FuturesExFactor))
        assert factor is not None
        assert float(factor.prev_close_ratio) == 0.99


def test_trading_params_syncs_fee_margin_rules_and_quality(tmp_path) -> None:
    with _session(tmp_path) as session:
        CatalogIngestor(session=session, client=FakeRqDataClient(), project_root=tmp_path).run(date(2024, 1, 1), date(2024, 1, 31))
        TradingParameterIngestor(session=session, client=FakeRqDataClient(), project_root=tmp_path).run(
            contracts=["RB2405"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        session.commit()

        params = session.scalar(select(FuturesTradingParameter))
        assert params is not None
        assert params.contract_code == "RB2405"
        fee_rule = session.scalar(select(FeeMarginRule).where(FeeMarginRule.contract_code == "RB2405"))
        assert fee_rule is not None
        assert float(fee_rule.margin_rate) == 0.1
        assert session.scalar(select(DataDownloadTask).where(DataDownloadTask.data_type == "trading_parameters")).status == "success"


def test_trading_params_uses_tick_size_fallback_when_parameters_omit_price_tick(tmp_path) -> None:
    class ClientWithoutPriceTickInParams(FakeRqDataClient):
        def trading_parameters(self, contract: str, start_date: date, end_date: date) -> pd.DataFrame:
            frame = super().trading_parameters(contract, start_date, end_date)
            return frame.drop(columns=["price_tick"])

        def price_tick(self, contract: str) -> float:
            assert contract == "RB2405"
            return 0.5

    with _session(tmp_path) as session:
        client = ClientWithoutPriceTickInParams()
        CatalogIngestor(session=session, client=client, project_root=tmp_path).run(date(2024, 1, 1), date(2024, 1, 31))
        TradingParameterIngestor(session=session, client=client, project_root=tmp_path).run(
            contracts=["RB2405"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        session.commit()

        params = session.scalar(select(FuturesTradingParameter))
        assert params is not None
        assert float(params.price_tick) == 0.5
        fee_rule = session.scalar(select(FeeMarginRule).where(FeeMarginRule.contract_code == "RB2405"))
        assert fee_rule is not None
        assert float(fee_rule.price_tick) == 0.5


def test_daily_and_research_enhancers_write_parquet_indexes_and_tables(tmp_path) -> None:
    with _session(tmp_path) as session:
        CatalogIngestor(session=session, client=FakeRqDataClient(), project_root=tmp_path).run(date(2024, 1, 1), date(2024, 1, 31))
        DailyBaselineIngestor(session=session, client=FakeRqDataClient(), project_root=tmp_path).run(
            contracts=["RB2405"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        ResearchEnhancerIngestor(session=session, client=FakeRqDataClient(), project_root=tmp_path).run(
            products=["rb"],
            contracts=["RB2405"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            include_basis=True,
        )
        session.commit()

        daily_file = session.scalar(select(MarketDataFile).where(MarketDataFile.data_type == "daily_baseline"))
        assert daily_file is not None
        assert Path(daily_file.file_path).exists()
        quality = session.scalar(select(DataQualityReport).where(DataQualityReport.data_type == "daily_baseline"))
        assert quality is not None
        assert quality.status == "passed"
        assert session.scalar(select(FuturesWarehouseStock)).quantity == 1000
        assert session.scalar(select(FuturesBasis)).basis == 90


def test_contract_universe_and_continuous_contracts_upsert_structured_tables(tmp_path) -> None:
    with _session(tmp_path) as session:
        CatalogIngestor(session=session, client=FakeRqDataClient(), project_root=tmp_path).run(date(2024, 1, 1), date(2024, 1, 31))
        ContractUniverseIngestor(session=session, client=FakeRqDataClient(), project_root=tmp_path).run(
            products=["RB"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 3),
        )
        ContinuousContractIngestor(session=session, client=FakeRqDataClient(), project_root=tmp_path).run(
            products=["RB"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            continuous_types=["front_month", "next_month"],
        )
        session.commit()

        universe = session.scalars(select(FuturesContractUniverse).order_by(FuturesContractUniverse.trade_date, FuturesContractUniverse.sort_order)).all()
        assert [(row.instrument_symbol, row.trade_date, row.contract_code, row.sort_order) for row in universe] == [
            ("rb", date(2024, 1, 2), "RB2405", 0),
            ("rb", date(2024, 1, 2), "RB2410", 1),
            ("rb", date(2024, 1, 3), "RB2405", 0),
            ("rb", date(2024, 1, 3), "RB2410", 1),
        ]
        continuous = session.scalars(select(FuturesContinuousContractMap).order_by(FuturesContinuousContractMap.continuous_type, FuturesContinuousContractMap.trade_date)).all()
        assert [(row.instrument_symbol, row.continuous_type, row.contract_code) for row in continuous] == [
            ("rb", "front_month", "RB2405"),
            ("rb", "front_month", "RB2405"),
            ("rb", "next_month", "RB2410"),
            ("rb", "next_month", "RB2410"),
        ]
        assert session.scalar(select(MarketDataFile).where(MarketDataFile.data_type == "contract_universe")) is not None
        assert session.scalar(select(MarketDataFile).where(MarketDataFile.data_type == "continuous_contracts")) is not None


def test_dominant_daily_baseline_writes_only_parquet_and_file_index(tmp_path) -> None:
    with _session(tmp_path) as session:
        result = DominantDailyBaselineIngestor(session=session, client=FakeRqDataClient(), project_root=tmp_path).run(
            products=["RB"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        session.commit()

        assert result.rows == 1
        market_file = session.scalar(select(MarketDataFile).where(MarketDataFile.data_type == "dominant_daily_baseline"))
        assert market_file is not None
        frame = pd.read_parquet(market_file.file_path)
        assert {"date", "datetime", "dominant_id", "limit_up", "limit_down"}.issubset(frame.columns)
        assert session.scalar(select(DataQualityReport).where(DataQualityReport.data_type == "dominant_daily_baseline")).status == "passed"


def test_research_enhancer_skips_basis_by_default(tmp_path) -> None:
    with _session(tmp_path) as session:
        ResearchEnhancerIngestor(session=session, client=FakeRqDataClient(), project_root=tmp_path).run(
            products=["rb"],
            contracts=["RB2405"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        session.commit()

        assert session.scalar(select(FuturesWarehouseStock)) is not None
        assert session.scalar(select(FuturesBasis)) is None
        assert session.scalar(select(MarketDataFile).where(MarketDataFile.data_type == "basis")) is None


def test_frame_preserves_unnamed_datetime_index_as_index_column() -> None:
    raw = pd.DataFrame(
        [{"close_commission_today": 0.0002, "min_margin_ratio": 0.08}],
        index=pd.DatetimeIndex([pd.Timestamp("2024-01-02")]),
    )

    frame = RqDataClient._frame(raw)

    assert "index" in frame.columns
    assert frame.loc[0, "index"] == pd.Timestamp("2024-01-02")


def test_real_rqdata_field_shapes_upsert_structured_tables(tmp_path) -> None:
    class RealShapeClient(FakeRqDataClient):
        def ex_factor(self, product: str, start_date: date, end_date: date) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "ex_date": pd.Timestamp("2024-01-02"),
                        "ex_factor": 2.5,
                        "ex_end_date": pd.Timestamp("2024-03-01"),
                        "ex_cum_factor": 7.5,
                    }
                ]
            )

        def trading_parameters(self, contract: str, start_date: date, end_date: date) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "long_margin_ratio": 0.09,
                        "short_margin_ratio": 0.10,
                        "open_commission": 0.0001,
                        "close_commission": 0.00011,
                        "close_commission_today": 0.00022,
                        "min_margin_ratio": 0.08,
                        "non_member_limit": 600,
                        "client_limit": 500,
                    }
                ],
                index=pd.DatetimeIndex([pd.Timestamp("2024-01-02")]),
            ).reset_index()

        def exchange_daily(self, contract: str, start_date: date, end_date: date) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "open": 3900,
                        "close": 3910,
                        "high": 3920,
                        "low": 3880,
                        "total_turnover": 390000000,
                        "volume": 10000,
                        "settlement": 3905,
                        "prev_settlement": 3890,
                        "open_interest": 120000,
                    }
                ],
                index=pd.DatetimeIndex([pd.Timestamp("2024-01-02")]),
            ).reset_index()

        def warehouse_stocks(self, product: str, start_date: date, end_date: date) -> pd.DataFrame:
            return pd.DataFrame(
                [{"on_warrant": 1000, "exchange": "SHFE", "warrant_units": "ton"}],
                index=pd.DatetimeIndex([pd.Timestamp("2024-01-02")]),
            ).reset_index()

    with _session(tmp_path) as session:
        client = RealShapeClient()
        CatalogIngestor(session=session, client=client, project_root=tmp_path).run(date(2024, 1, 1), date(2024, 1, 31))
        ExFactorIngestor(session=session, client=client, project_root=tmp_path).run(["rb"], date(2024, 1, 1), date(2024, 1, 31))
        TradingParameterIngestor(session=session, client=client, project_root=tmp_path).run(["RB2405"], date(2024, 1, 1), date(2024, 1, 31))
        DailyBaselineIngestor(session=session, client=client, project_root=tmp_path).run(["RB2405"], date(2024, 1, 1), date(2024, 1, 31))
        ResearchEnhancerIngestor(session=session, client=client, project_root=tmp_path).run(["rb"], [], date(2024, 1, 1), date(2024, 1, 31))
        session.commit()

        factor = session.scalar(select(FuturesExFactor))
        assert factor is not None
        assert float(factor.prev_close_spread) == 2.5
        assert float(factor.prev_close_ratio) == 7.5
        params = session.scalar(select(FuturesTradingParameter))
        assert params is not None
        assert float(params.close_today_commission) == 0.00022
        assert params.max_order_quantity == 500
        fee_rule = session.scalar(select(FeeMarginRule).where(FeeMarginRule.contract_code == "RB2405"))
        assert fee_rule is not None
        assert float(fee_rule.close_today_fee) == 0.00022
        assert session.scalar(select(FuturesWarehouseStock)).trade_date == date(2024, 1, 2)
        daily_file = session.scalar(select(MarketDataFile).where(MarketDataFile.data_type == "daily_baseline"))
        daily = pd.read_parquet(daily_file.file_path)
        assert "date" in daily.columns
        assert "total_turnover" in daily.columns


def test_market_file_index_keeps_same_type_different_products_separate(tmp_path) -> None:
    class SampleClient(FakeRqDataClient):
        def main_price(self, product: str, start_date: date, end_date: date, frequency: str) -> pd.DataFrame:
            return pd.DataFrame(
                [{"datetime": pd.Timestamp("2024-01-02 09:01:00"), "close": 100, "volume": 1}],
            )

    with _session(tmp_path) as session:
        MarketSampleIngestor(session=session, client=SampleClient(), project_root=tmp_path).run(
            products=["rb", "hc"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            frequencies=["1m"],
        )
        session.commit()

        files = session.scalars(select(MarketDataFile).where(MarketDataFile.data_type == "market_sample")).all()
        assert len(files) == 2
        assert {item.instrument_symbol for item in files} == {"rb", "hc"}


def test_backfill_ex_factors_from_raw_uses_real_rqdata_fields(tmp_path) -> None:
    raw_dir = tmp_path / "data/raw/rqdata/futures_ex_factor/product=rb"
    raw_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "ex_date": pd.Timestamp("2024-01-02"),
                "ex_factor": 2.5,
                "ex_end_date": pd.Timestamp("2024-03-01"),
                "ex_cum_factor": 7.5,
                "product": "rb",
            }
        ]
    ).to_parquet(raw_dir / "rb_2005_2026.parquet")

    with _session(tmp_path) as session:
        rows, files = backfill_ex_factors_from_raw(session, tmp_path)
        session.commit()

        assert rows == 1
        assert files == 1
        factor = session.scalar(select(FuturesExFactor))
        assert factor is not None
        assert factor.instrument_symbol == "rb"
        assert factor.trade_date == date(2024, 1, 2)
        assert float(factor.prev_close_spread) == 2.5
        assert float(factor.prev_close_ratio) == 7.5
