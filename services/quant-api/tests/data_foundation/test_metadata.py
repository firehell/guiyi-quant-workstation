from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.metadata import MetadataSnapshot, MetadataSynchronizer
from app.models import Contract, ContractSpec, Exchange, Instrument, MainContractMap, TradingCalendar, TradingSession


class FakeAdapter:
    def __init__(self, snapshot: MetadataSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = []

    def fetch_metadata(self, products, through, starts):
        self.calls.append((products, through, starts))
        return self.snapshot


class SequenceAdapter:
    def __init__(self, snapshots) -> None:
        self.snapshots = iter(snapshots)

    def fetch_metadata(self, products, through, starts):
        return next(self.snapshots)


def test_metadata_synchronizer_upserts_all_current_facts(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    snapshot = MetadataSnapshot(
        exchanges=({"code": "DCE", "name": "DCE"},),
        instruments=(
            {"symbol": "jm", "name": "焦煤", "exchange_code": "DCE", "is_active": True},
        ),
        contracts=(
            {"contract_code": "JM2509", "instrument_symbol": "jm", "exchange_code": "DCE"},
        ),
        calendars=(
            {"exchange_code": "DCE", "trade_date": date(2025, 1, 2), "is_trading_day": True},
        ),
        sessions=(
            {
                "exchange_code": "DCE",
                "instrument_symbol": "jm",
                "session_name": "day",
                "start_time": time(9),
                "end_time": time(15),
                "effective_from": date(2025, 1, 1),
                "effective_to": None,
                "crosses_midnight": False,
            },
        ),
        main_contracts=(("jm", date(2025, 1, 2), "JM2509"),),
        contract_specs=(
            {
                "contract_code": "JM2509",
                "symbol": "jm",
                "exchange_code": "DCE",
                "trade_date": date(2025, 1, 2),
                "price_tick": Decimal("0.5"),
                "contract_multiplier": Decimal("60"),
            },
        ),
        main_contract_starts={"jm": date(2025, 1, 2)},
    )
    adapter = FakeAdapter(snapshot)
    with Session(engine) as session:
        synchronizer = MetadataSynchronizer(adapter, MarketCatalog(session, tmp_path))

        assert synchronizer.synchronize(("jm",), date(2025, 1, 2)) == date(2025, 1, 2)
        assert synchronizer.synchronize(("jm",), date(2025, 1, 2)) == date(2025, 1, 2)

        assert len(list(session.scalars(select(Exchange)))) == 1
        assert len(list(session.scalars(select(Instrument)))) == 1
        assert len(list(session.scalars(select(Contract)))) == 1
        assert len(list(session.scalars(select(TradingCalendar)))) == 1
        assert len(list(session.scalars(select(TradingSession)))) == 1
        assert len(list(session.scalars(select(MainContractMap)))) == 1
        assert len(list(session.scalars(select(ContractSpec)))) == 1


def test_metadata_synchronizer_reconciles_removed_facts_in_refresh_window(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    common = {
        "exchanges": ({"code": "DCE", "name": "DCE"},),
        "instruments": (
            {"symbol": "jm", "name": "焦煤", "exchange_code": "DCE", "is_active": True},
        ),
        "contracts": (
            {"contract_code": "JM2509", "instrument_symbol": "jm", "exchange_code": "DCE"},
        ),
        "calendars": (
            {"exchange_code": "DCE", "trade_date": date(2025, 1, 2), "is_trading_day": True},
        ),
        "sessions": (),
        "main_contract_starts": {"jm": date(2025, 1, 2)},
    }
    first = SimpleNamespace(
        **common,
        main_contracts=(("jm", date(2025, 1, 2), "JM2509"),),
        contract_specs=(
            {
                "contract_code": "JM2509",
                "symbol": "jm",
                "exchange_code": "DCE",
                "trade_date": date(2025, 1, 2),
                "price_tick": Decimal("0.5"),
                "contract_multiplier": Decimal("60"),
            },
        ),
    )
    second = SimpleNamespace(**common, main_contracts=(), contract_specs=())
    adapter = SequenceAdapter((first, second))

    with Session(engine) as session:
        synchronizer = MetadataSynchronizer(adapter, MarketCatalog(session, tmp_path))
        synchronizer.synchronize(
            ("jm",),
            date(2025, 1, 2),
            {"jm": date(2025, 1, 2)},
        )
        synchronizer.synchronize(
            ("jm",),
            date(2025, 1, 2),
            {"jm": date(2025, 1, 2)},
        )

        assert list(session.scalars(select(MainContractMap))) == []
        assert list(session.scalars(select(ContractSpec))) == []
