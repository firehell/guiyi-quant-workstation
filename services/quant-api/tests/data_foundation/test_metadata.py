from __future__ import annotations

from datetime import date, timedelta, time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.errors import InfrastructureError
from app.market_data.metadata import MetadataSnapshot, MetadataSynchronizer
from app.models import (
    Contract,
    Exchange,
    Instrument,
    MainContractMap,
    TradingCalendar,
    TradingSession,
)


def test_metadata_snapshot_excludes_contract_specs() -> None:
    snapshot = MetadataSnapshot((), (), (), (), (), (), {})

    assert snapshot.main_contract_starts == {}
    assert not hasattr(snapshot, "contract_specs")


_DAY = date(2026, 8, 10)
_BEFORE = date(2026, 8, 7)
_AFTER = date(2026, 8, 11)
_WEEK_END = date(2026, 8, 16)


class _Adapter:
    def __init__(self, snapshot: MetadataSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[tuple[str, ...], date, dict[str, date]]] = []

    def fetch_metadata(
        self,
        products: tuple[str, ...],
        through: date,
        starts: dict[str, date],
    ) -> MetadataSnapshot:
        self.calls.append((products, through, dict(starts)))
        return self.snapshot

    def fetch_current_day_metadata(
        self,
        products: tuple[str, ...],
        trading_day: date,
    ) -> MetadataSnapshot:
        self.calls.append((products, trading_day, {item: trading_day for item in products}))
        return self.snapshot


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add_all(
        (
            Exchange(code="DCE", name="preserved DCE"),
            Exchange(code="SHFE", name="SHFE"),
            Instrument(symbol="j", name="J", exchange_code="DCE", is_active=True),
            Instrument(symbol="jm", name="JM", exchange_code="DCE", is_active=True),
            Instrument(symbol="ag", name="AG", exchange_code="SHFE", is_active=True),
            Contract(
                contract_code="J2605",
                instrument_symbol="j",
                exchange_code="DCE",
            ),
            Contract(
                contract_code="JM2605",
                instrument_symbol="jm",
                exchange_code="DCE",
            ),
            TradingCalendar(
                exchange_code="DCE",
                trade_date=_BEFORE,
                is_trading_day=True,
                has_night_session=True,
            ),
            TradingCalendar(
                exchange_code="DCE",
                trade_date=_DAY,
                is_trading_day=False,
                has_night_session=False,
            ),
            TradingCalendar(
                exchange_code="DCE",
                trade_date=_AFTER,
                is_trading_day=True,
                has_night_session=False,
            ),
            TradingCalendar(
                exchange_code="SHFE",
                trade_date=_DAY,
                is_trading_day=False,
                has_night_session=False,
            ),
            _session_row("j", _BEFORE, _BEFORE, "before"),
            _session_row("j", _DAY, _DAY, "replace"),
            _session_row("j", _DAY, None, "open-ended"),
            _session_row("j", _AFTER, _AFTER, "after"),
            _session_row("jm", _DAY, _DAY, "replace"),
            _session_row("ag", _DAY, _DAY, "unrelated"),
            MainContractMap(symbol="j", trade_date=_BEFORE, contract_code="J2509"),
            MainContractMap(symbol="j", trade_date=_DAY, contract_code="J2601"),
            MainContractMap(symbol="j", trade_date=_AFTER, contract_code="J2605"),
            MainContractMap(symbol="jm", trade_date=_DAY, contract_code="JM2601"),
            MainContractMap(symbol="ag", trade_date=_DAY, contract_code="AG2601"),
        )
    )
    session.commit()
    return session


def _session_row(
    symbol: str,
    effective_from: date,
    effective_to: date | None,
    name: str,
) -> TradingSession:
    return TradingSession(
        exchange_code="DCE" if symbol in {"j", "jm"} else "SHFE",
        instrument_symbol=symbol,
        session_name=name,
        start_time=time(9),
        end_time=time(15),
        effective_from=effective_from,
        effective_to=effective_to,
        is_active=True,
    )


def _snapshot(
    *,
    include_jm_map: bool = True,
    j_contract: str = "J2605",
) -> MetadataSnapshot:
    main_contracts = [("j", _DAY, j_contract)]
    if include_jm_map:
        main_contracts.append(("jm", _DAY, "JM2605"))
    return MetadataSnapshot(
        exchanges=({"code": "DCE", "name": "provider must not overwrite"},),
        instruments=(
            {
                "symbol": "j",
                "name": "provider must not overwrite",
                "exchange_code": "DCE",
                "is_active": True,
            },
        ),
        contracts=(),
        calendars=tuple(
            {
                "exchange_code": "DCE",
                "trade_date": _DAY + timedelta(days=offset),
                "is_trading_day": offset in {0, 1},
                "has_night_session": offset in {0, 1},
                "provider": "rqdata",
            }
            for offset in range((_WEEK_END - _DAY).days + 1)
        ),
        sessions=(
            _session_values("j", "day"),
            _session_values("jm", "night"),
            {
                **_session_values("j", "future"),
                "effective_from": _AFTER,
                "effective_to": _AFTER,
            },
            {
                **_session_values("jm", "future"),
                "effective_from": _AFTER,
                "effective_to": _AFTER,
            },
        ),
        main_contracts=tuple(
            main_contracts + [("j", _AFTER, "J2609"), ("jm", _AFTER, "JM2609")]
        ),
        main_contract_starts={"j": _DAY, "jm": _DAY},
    )


def _session_values(symbol: str, name: str) -> dict[str, object]:
    return {
        "exchange_code": "DCE",
        "instrument_symbol": symbol,
        "session_name": name,
        "start_time": time(9),
        "end_time": time(15),
        "effective_from": _DAY,
        "effective_to": _DAY,
        "crosses_midnight": False,
        "is_active": True,
        "provider": "rqdata",
    }


def _metadata_state(session: Session) -> dict[str, list[tuple[object, ...]]]:
    return {
        "calendar": [
            (row.exchange_code, row.trade_date, row.is_trading_day, row.has_night_session)
            for row in session.scalars(
                select(TradingCalendar).order_by(
                    TradingCalendar.exchange_code, TradingCalendar.trade_date
                )
            )
        ],
        "sessions": [
            (
                row.instrument_symbol,
                row.session_name,
                row.effective_from,
                row.effective_to,
            )
            for row in session.scalars(
                select(TradingSession).order_by(
                    TradingSession.instrument_symbol,
                    TradingSession.effective_from,
                    TradingSession.session_name,
                )
            )
        ],
        "maps": [
            (row.symbol, row.trade_date, row.contract_code)
            for row in session.scalars(
                select(MainContractMap).order_by(
                    MainContractMap.symbol, MainContractMap.trade_date
                )
            )
        ],
    }


def test_current_day_sync_replaces_day_facts_and_bounded_week_calendar_context() -> None:
    session = _session()
    adapter = _Adapter(_snapshot())
    synchronizer = MetadataSynchronizer(adapter, MarketCatalog(session, Path(".")))

    assert synchronizer.synchronize_current_day((" J ", "jm"), _DAY) == _DAY
    assert adapter.calls == [(("j", "jm"), _DAY, {"j": _DAY, "jm": _DAY})]

    state = _metadata_state(session)
    assert state["calendar"] == [
        ("DCE", _BEFORE, True, True),
        ("DCE", _DAY, True, True),
        ("DCE", _AFTER, True, True),
        ("DCE", date(2026, 8, 12), False, False),
        ("DCE", date(2026, 8, 13), False, False),
        ("DCE", date(2026, 8, 14), False, False),
        ("DCE", date(2026, 8, 15), False, False),
        ("DCE", _WEEK_END, False, False),
        ("SHFE", _DAY, False, False),
    ]
    assert state["sessions"] == [
        ("ag", "unrelated", _DAY, _DAY),
        ("j", "before", _BEFORE, _BEFORE),
        ("j", "day", _DAY, _DAY),
        ("j", "open-ended", _DAY, None),
        ("j", "future", _AFTER, _AFTER),
        ("jm", "night", _DAY, _DAY),
        ("jm", "future", _AFTER, _AFTER),
    ]
    assert state["maps"] == [
        ("ag", _DAY, "AG2601"),
        ("j", _BEFORE, "J2509"),
        ("j", _DAY, "J2605"),
        ("j", _AFTER, "J2605"),
        ("jm", _DAY, "JM2605"),
    ]
    assert session.get(Exchange, 1).name == "preserved DCE"
    session.close()


def test_current_day_sync_replaces_next_trading_day_sessions_only() -> None:
    """盘后同步必须准备下一交易日 Session，但不得提前发布下一日 rank1。"""
    session = _session()
    synchronizer = MetadataSynchronizer(
        _Adapter(_snapshot()), MarketCatalog(session, Path("."))
    )

    synchronizer.synchronize_current_day(("j", "jm"), _DAY)

    state = _metadata_state(session)
    assert ("j", "future", _AFTER, _AFTER) in state["sessions"]
    assert ("jm", "future", _AFTER, _AFTER) in state["sessions"]
    assert ("j", "after", _AFTER, _AFTER) not in state["sessions"]
    assert ("j", _AFTER, "J2605") in state["maps"]
    assert ("jm", _AFTER, "JM2609") not in state["maps"]
    session.close()


def test_current_day_sync_reports_missing_next_trading_sessions_as_not_ready() -> None:
    """下一交易日 Session 尚未发布是可重试时点，不是未知 ValueError。"""
    session = _session()
    before = _metadata_state(session)
    snapshot = _snapshot()
    snapshot = MetadataSnapshot(
        exchanges=snapshot.exchanges,
        instruments=snapshot.instruments,
        contracts=snapshot.contracts,
        calendars=snapshot.calendars,
        sessions=tuple(
            row for row in snapshot.sessions if row["effective_from"] == _DAY
        ),
        main_contracts=snapshot.main_contracts,
        main_contract_starts=snapshot.main_contract_starts,
    )
    synchronizer = MetadataSynchronizer(
        _Adapter(snapshot), MarketCatalog(session, Path("."))
    )

    with pytest.raises(InfrastructureError) as captured:
        synchronizer.synchronize_current_day(("j", "jm"), _DAY)

    assert captured.value.code == "NEXT_TRADING_SESSION_NOT_READY"
    assert _metadata_state(session) == before
    session.close()


def test_current_day_sync_keeps_missing_current_sessions_fail_closed() -> None:
    session = _session()
    before = _metadata_state(session)
    snapshot = _snapshot()
    snapshot = MetadataSnapshot(
        exchanges=snapshot.exchanges,
        instruments=snapshot.instruments,
        contracts=snapshot.contracts,
        calendars=snapshot.calendars,
        sessions=tuple(
            row for row in snapshot.sessions if row["effective_from"] == _AFTER
        ),
        main_contracts=snapshot.main_contracts,
        main_contract_starts=snapshot.main_contract_starts,
    )
    synchronizer = MetadataSynchronizer(
        _Adapter(snapshot), MarketCatalog(session, Path("."))
    )

    with pytest.raises(ValueError, match="CURRENT_DAY_TRADING_SESSION_INVALID"):
        synchronizer.synchronize_current_day(("j", "jm"), _DAY)

    assert _metadata_state(session) == before
    session.close()


def test_current_day_sync_invalid_provider_fact_rolls_back_all_metadata() -> None:
    session = _session()
    before = _metadata_state(session)
    adapter = _Adapter(_snapshot(include_jm_map=False))
    synchronizer = MetadataSynchronizer(adapter, MarketCatalog(session, Path(".")))

    with pytest.raises(ValueError, match="CURRENT_DAY_MAIN_CONTRACT_MAP_INVALID"):
        synchronizer.synchronize_current_day(("j", "jm"), _DAY)

    assert _metadata_state(session) == before
    session.close()


def test_current_day_sync_checks_rank1_before_missing_next_session() -> None:
    session = _session()
    before = _metadata_state(session)
    snapshot = _snapshot(include_jm_map=False)
    snapshot = MetadataSnapshot(
        exchanges=snapshot.exchanges,
        instruments=snapshot.instruments,
        contracts=snapshot.contracts,
        calendars=snapshot.calendars,
        sessions=tuple(
            row for row in snapshot.sessions if row["effective_from"] == _DAY
        ),
        main_contracts=snapshot.main_contracts,
        main_contract_starts=snapshot.main_contract_starts,
    )
    synchronizer = MetadataSynchronizer(
        _Adapter(snapshot), MarketCatalog(session, Path("."))
    )

    with pytest.raises(ValueError, match="CURRENT_DAY_MAIN_CONTRACT_MAP_INVALID"):
        synchronizer.synchronize_current_day(("j", "jm"), _DAY)

    assert _metadata_state(session) == before
    session.close()


def test_current_day_sync_rejects_unknown_rank1_contract_without_any_write() -> None:
    session = _session()
    before = _metadata_state(session)
    adapter = _Adapter(_snapshot(j_contract="J9999"))
    synchronizer = MetadataSynchronizer(adapter, MarketCatalog(session, Path(".")))

    with pytest.raises(ValueError, match="CURRENT_DAY_MAIN_CONTRACT_MAP_INVALID"):
        synchronizer.synchronize_current_day(("j", "jm"), _DAY)

    assert _metadata_state(session) == before
    session.close()


def test_current_day_sync_rejects_rank1_contract_owned_by_another_product() -> None:
    session = _session()
    before = _metadata_state(session)
    adapter = _Adapter(_snapshot(j_contract="JM2605"))
    synchronizer = MetadataSynchronizer(adapter, MarketCatalog(session, Path(".")))

    with pytest.raises(ValueError, match="CURRENT_DAY_MAIN_CONTRACT_MAP_INVALID"):
        synchronizer.synchronize_current_day(("j", "jm"), _DAY)

    assert _metadata_state(session) == before
    session.close()
