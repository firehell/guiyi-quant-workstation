from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from sqlalchemy import delete, select

from app.market_data.catalog import MarketCatalog
from app.models import (
    Contract,
    Exchange,
    Instrument,
    MainContractMap,
    TradingCalendar,
    TradingSession,
)


@dataclass(frozen=True, slots=True)
class MetadataSnapshot:
    exchanges: tuple[Mapping[str, Any], ...]
    instruments: tuple[Mapping[str, Any], ...]
    contracts: tuple[Mapping[str, Any], ...]
    calendars: tuple[Mapping[str, Any], ...]
    sessions: tuple[Mapping[str, Any], ...]
    main_contracts: tuple[tuple[str, date, str], ...]
    main_contract_starts: Mapping[str, date]


class MetadataAdapter(Protocol):
    def fetch_metadata(
        self,
        products: tuple[str, ...],
        through: date,
        starts: Mapping[str, date],
    ) -> MetadataSnapshot: ...


class MetadataSynchronizer:
    """Synchronize the fixed RQData metadata surface as current facts."""

    def __init__(self, adapter: MetadataAdapter, catalog: MarketCatalog) -> None:
        self.adapter = adapter
        self.catalog = catalog

    def synchronize(
        self,
        products: tuple[str, ...],
        through: date,
        starts: Mapping[str, date] | None = None,
    ) -> date:
        normalized = tuple(dict.fromkeys(item.strip().lower() for item in products))
        floors = dict(starts or {symbol: through for symbol in normalized})
        snapshot = self.adapter.fetch_metadata(normalized, through, floors)
        session = self.catalog.session
        try:
            for values in snapshot.exchanges:
                _upsert(session, Exchange, {"code": values["code"]}, values)
            session.flush()
            for values in snapshot.instruments:
                _upsert(session, Instrument, {"symbol": values["symbol"]}, values)
            session.flush()
            for values in snapshot.contracts:
                _upsert(
                    session,
                    Contract,
                    {"contract_code": values["contract_code"]},
                    values,
                )
            for values in snapshot.calendars:
                _upsert(
                    session,
                    TradingCalendar,
                    {
                        "exchange_code": values["exchange_code"],
                        "trade_date": values["trade_date"],
                    },
                    values,
                )
            # Historical periods are date-scoped facts. Replace prior templates
            # so a former current-hours approximation cannot cover an older day.
            session.execute(
                delete(TradingSession).where(
                    TradingSession.instrument_symbol.in_(normalized)
                )
            )
            for values in snapshot.sessions:
                _upsert(
                    session,
                    TradingSession,
                    {
                        "exchange_code": values["exchange_code"],
                        "instrument_symbol": values["instrument_symbol"],
                        "session_name": values["session_name"],
                        "start_time": values["start_time"],
                        "end_time": values["end_time"],
                        "effective_from": values["effective_from"],
                    },
                    values,
                )
            for symbol in normalized:
                refresh_start = snapshot.main_contract_starts.get(symbol)
                if refresh_start is None or refresh_start > through:
                    raise ValueError("MAIN_CONTRACT_REFRESH_WINDOW_INVALID")
                session.execute(
                    delete(MainContractMap).where(
                        MainContractMap.symbol == symbol,
                        MainContractMap.trade_date >= refresh_start,
                        MainContractMap.trade_date <= through,
                    )
                )
            self.catalog.upsert_main_contracts(snapshot.main_contracts)
            session.commit()
        except Exception:
            session.rollback()
            raise
        return through


def _upsert(session, model, identity: Mapping[str, object], values: Mapping[str, Any]) -> None:
    row = session.scalar(
        select(model).where(
            *(getattr(model, field) == value for field, value in identity.items())
        )
    )
    payload = dict(values)
    if row is None:
        session.add(model(**payload))
        return
    for field, value in payload.items():
        setattr(row, field, value)
