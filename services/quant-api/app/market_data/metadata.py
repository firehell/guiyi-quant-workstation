"""RQData 元数据同步（数据核心 V2 八表事实写入）。

``MetadataSynchronizer`` 将 adapter 拉取的交易所、品种、合约、交易日历、
交易时段与主力映射写入 Catalog 所绑定的 SQLAlchemy session。

设计要点：
- 交易时段（``TradingSession``）按品种全量替换，避免历史时段模板覆盖旧日；
- 主力映射按 ``main_contract_starts`` 窗口先删后插，保证刷新区间与 RQData 一致；
- 单事务 commit，异常 rollback，不向 Parquet 写入任何内容。
"""

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
    """一次元数据拉取的不可变快照，供 synchronizer 按表 upsert。"""

    exchanges: tuple[Mapping[str, Any], ...]
    instruments: tuple[Mapping[str, Any], ...]
    contracts: tuple[Mapping[str, Any], ...]
    calendars: tuple[Mapping[str, Any], ...]
    sessions: tuple[Mapping[str, Any], ...]
    main_contracts: tuple[tuple[str, date, str], ...]
    main_contract_starts: Mapping[str, date]


class MetadataAdapter(Protocol):
    """外部元数据来源协议（通常为 RQData 适配器实现）。"""

    def fetch_metadata(
        self,
        products: tuple[str, ...],
        through: date,
        starts: Mapping[str, date],
    ) -> MetadataSnapshot: ...


class MetadataSynchronizer:
    """将 RQData 固定元数据面同步为当前数据库事实（八表中的 reference 表）。"""

    def __init__(self, adapter: MetadataAdapter, catalog: MarketCatalog) -> None:
        self.adapter = adapter
        self.catalog = catalog

    def synchronize(
        self,
        products: tuple[str, ...],
        through: date,
        starts: Mapping[str, date] | None = None,
    ) -> date:
        """拉取并写入元数据，成功返回 ``through`` 日期。

        ``starts`` 未提供时各品种默认从 ``through`` 当天开始刷新主力映射；
        ``main_contract_starts`` 与删除窗口不一致时 fail-closed（``ValueError``）。
        """
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
            # 历史时段是「按生效日」的事实；先删后插，避免旧版当前时段模板误盖历史日
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
    """按 identity 字段查找行，存在则更新全部列，否则插入新行。"""
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
