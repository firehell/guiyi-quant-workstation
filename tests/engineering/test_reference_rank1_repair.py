"""One-time rank-1 repair must keep source, scope and existing facts exact."""

from __future__ import annotations

from datetime import date, time
from hashlib import sha256
import json
from pathlib import Path
import runpy

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.models import (
    Contract, Exchange, Instrument, MainContractMap, TradingCalendar, TradingSession,
)


MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts/reference_rank1_repair.py"),
)
DAY = date(2026, 9, 24)


def test_source_is_pinned_and_rejects_changed_bytes(tmp_path: Path) -> None:
    source = {
        "schema_version": 1, "status": "source_captured",
        "trading_day": DAY.isoformat(),
        "runtime_commit": MODULE["SOURCE_COMMIT"],
        "production_writes": 0, "provider_call_count": 64,
        "source_dominants": {
            "RB": [{"date": "2026-09-24 00:00:00", "dominant": "RB2701"}],
        },
    }
    path = tmp_path / "source.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    digest = sha256(path.read_bytes()).hexdigest()
    read_source = MODULE["_read_source"]
    read_source.__globals__["SOURCE_SHA256"] = digest
    assert read_source(path, digest)["trading_day"] == DAY.isoformat()
    path.write_text(json.dumps({**source, "trading_day": "2026-09-25"}), encoding="utf-8")
    with pytest.raises(MODULE["RepairBlocked"], match="SOURCE_IDENTITY_INVALID"):
        read_source(path, digest)


def test_source_requires_exact_product_day_and_single_contract() -> None:
    contracts = MODULE["_contracts"]
    source = {"source_dominants": {
        "RB": [{"date": "2026-09-24 00:00:00", "dominant": "RB2701"}],
    }}
    assert contracts(source, ("rb",)) == {"rb": "RB2701"}
    with pytest.raises(MODULE["RepairBlocked"], match="SOURCE_SCOPE_INVALID"):
        contracts(source, ("rb", "cu"))
    source["source_dominants"]["RB"].append(
        {"date": "2026-09-24 00:00:00", "dominant": "RB2705"}
    )
    with pytest.raises(MODULE["RepairBlocked"], match="SOURCE_DOMINANT_INVALID"):
        contracts(source, ("rb",))


def test_plan_is_insert_only_then_equal_and_conflict_blocks() -> None:
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _database_identity(dbapi_connection, _record) -> None:
        dbapi_connection.create_function("current_database", 0, lambda: "guiyi_quant")

    Base.metadata.create_all(engine, tables=[
        Exchange.__table__, Instrument.__table__, Contract.__table__,
        TradingCalendar.__table__, TradingSession.__table__, MainContractMap.__table__,
    ])
    symbols = tuple(f"p{index:02d}" for index in range(60))
    contracts = {symbol: f"P{index:02d}2701" for index, symbol in enumerate(symbols)}
    with Session(engine) as session:
        session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        session.execute(text(
            "INSERT INTO alembic_version (version_num) VALUES ('20260919_0047')"
        ))
        session.add(Exchange(code="SHFE", name="Shanghai"))
        session.add(TradingCalendar(
            exchange_code="SHFE", trade_date=DAY, is_trading_day=True,
            has_night_session=True, provider="rqdata",
        ))
        for symbol, code in contracts.items():
            session.add(Instrument(symbol=symbol, name=symbol, exchange_code="SHFE"))
            session.add(TradingSession(
                exchange_code="SHFE", instrument_symbol=symbol, session_name="day",
                start_time=time(9), end_time=time(15), effective_from=DAY,
                effective_to=DAY, provider="rqdata",
            ))
            session.add(Contract(
                contract_code=code, instrument_symbol=symbol, exchange_code="SHFE",
                listed_date=date(2026, 1, 1), expired_date=date(2027, 1, 1),
            ))
        session.flush()
        plan = MODULE["_plan"](
            session, contracts, source_sha="a" * 64, code_sha="b" * 40,
            universe_sha="c" * 64, database="guiyi_quant",
        )
        assert plan["counts"] == {"total": 60, "insert": 60, "equal": 0}
        MarketCatalog(session, Path("/tmp")).upsert_main_contracts(
            (symbol, DAY, code) for symbol, code in contracts.items()
        )
        equal = MODULE["_plan"](
            session, contracts, source_sha="a" * 64, code_sha="b" * 40,
            universe_sha="c" * 64, database="guiyi_quant",
        )
        assert equal["counts"] == {"total": 60, "insert": 0, "equal": 60}
        assert equal["plan_sha256"] != plan["plan_sha256"]
        row = session.query(MainContractMap).filter_by(symbol="p00").one()
        row.contract_code = "P002705"
        session.flush()
        with pytest.raises(MODULE["RepairBlocked"], match="RANK1_CONFLICT"):
            MODULE["_plan"](
                session, contracts, source_sha="a" * 64, code_sha="b" * 40,
                universe_sha="c" * 64, database="guiyi_quant",
            )
