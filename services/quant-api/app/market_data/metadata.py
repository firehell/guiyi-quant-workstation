"""RQData 元数据同步（数据核心 V2 八表事实写入）。

``MetadataSynchronizer`` 将 adapter 拉取的交易所、品种、合约、交易日历、
交易时段与主力映射写入 Catalog 所绑定的 SQLAlchemy session。

设计要点：
- 交易时段（``TradingSession``）按品种全量替换，避免历史时段模板覆盖旧日；
- 主力映射按 ``main_contract_starts`` 窗口先删后插，保证刷新区间与 RQData 一致；
- 单事务 commit，异常 rollback，不向 Parquet 写入任何内容。

``synchronize_current_day`` 是 Runtime canary 使用的受限入口：它只替换指定品种
单一交易日的按日 TradingSession 与 rank-1 MainContractMap，并补齐当天至 ISO 周日
的最小 Calendar 上下文；绝不触碰历史 Session/Map、Dataset 或 Parquet。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta, time
from typing import Any, Protocol

from sqlalchemy import delete, select

from app.market_data.catalog import MarketCatalog
from app.market_data.product_retirement import assert_products_not_retired
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

    def fetch_current_day_metadata(
        self,
        products: tuple[str, ...],
        trading_day: date,
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
        assert_products_not_retired(normalized)
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

    def synchronize_current_day(
        self,
        products: tuple[str, ...],
        trading_day: date,
    ) -> date:
        """受限同步指定品种的当天事实与本周 Calendar 上下文。

        此入口特意不复用 ``synchronize``：后者会按品种删除全部 TradingSession，
        不适用于 Runtime 启用前补齐当天 metadata 的最小权限范围。Calendar 只允许
        写入当天至 ISO 周日，以证明周频窗口完整；Session 与 rank-1 Map 仍只写当天。
        事实须完整且与既有 Instrument/Exchange 身份一致，否则整个事务回滚。
        """
        normalized = _normalized_products(products)
        if type(trading_day) is not date:
            raise ValueError("CURRENT_DAY_TRADING_DAY_INVALID")
        assert_products_not_retired(normalized)
        snapshot = self.adapter.fetch_current_day_metadata(normalized, trading_day)
        session = self.catalog.session
        try:
            exchanges = _existing_product_exchanges(session, normalized)
            calendars = _current_week_calendars(
                snapshot, trading_day, set(exchanges.values())
            )
            sessions = _current_day_sessions(snapshot, normalized, exchanges, trading_day)
            main_contracts = _current_day_main_contracts(
                session, snapshot, normalized, trading_day
            )

            for values in calendars:
                _upsert(
                    session,
                    TradingCalendar,
                    {
                        "exchange_code": values["exchange_code"],
                        "trade_date": values["trade_date"],
                    },
                    values,
                )
            session.execute(
                delete(TradingSession).where(
                    TradingSession.instrument_symbol.in_(normalized),
                    TradingSession.effective_from == trading_day,
                    TradingSession.effective_to == trading_day,
                )
            )
            for values in sessions:
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
            session.execute(
                delete(MainContractMap).where(
                    MainContractMap.symbol.in_(normalized),
                    MainContractMap.trade_date == trading_day,
                )
            )
            self.catalog.upsert_main_contracts(main_contracts)
            session.commit()
        except Exception:
            session.rollback()
            raise
        return trading_day


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


def _normalized_products(products: tuple[str, ...]) -> tuple[str, ...]:
    """规范化受限同步的显式品种清单，拒绝空值或非字符串输入。"""
    if not products or any(not isinstance(item, str) or not item.strip() for item in products):
        raise ValueError("CURRENT_DAY_PRODUCTS_INVALID")
    return tuple(dict.fromkeys(item.strip().lower() for item in products))


def _existing_product_exchanges(
    session,
    products: tuple[str, ...],
) -> dict[str, str]:
    """受限写入只接受已在 Catalog 中确立身份的 Instrument/Exchange。"""
    rows = tuple(
        session.scalars(select(Instrument).where(Instrument.symbol.in_(products)))
    )
    exchanges = {row.symbol: row.exchange_code for row in rows}
    if set(exchanges) != set(products) or any(not value for value in exchanges.values()):
        raise ValueError("CURRENT_DAY_INSTRUMENT_IDENTITY_INVALID")
    return exchanges


def _current_week_calendars(
    snapshot: MetadataSnapshot,
    trading_day: date,
    expected_exchanges: set[str],
) -> tuple[dict[str, Any], ...]:
    """提取并验证当天至 ISO 周日的完整、受限 Calendar 上下文。"""
    week_end = trading_day + timedelta(days=7 - trading_day.isoweekday())
    expected_days = tuple(
        trading_day + timedelta(days=offset)
        for offset in range((week_end - trading_day).days + 1)
    )
    expected_keys = {
        (exchange, day) for exchange in expected_exchanges for day in expected_days
    }
    values_by_key: dict[tuple[str, date], dict[str, Any]] = {}
    for raw in snapshot.calendars:
        day = raw.get("trade_date")
        if type(day) is not date or day < trading_day or day > week_end:
            continue
        exchange = raw.get("exchange_code")
        if not isinstance(exchange, str) or exchange not in expected_exchanges:
            raise ValueError("CURRENT_DAY_CALENDAR_INVALID")
        key = (exchange, day)
        if key in values_by_key:
            raise ValueError("CURRENT_DAY_CALENDAR_INVALID")
        if (
            not isinstance(raw.get("is_trading_day"), bool)
            or not isinstance(raw.get("has_night_session"), bool)
            or (day == trading_day and raw["is_trading_day"] is not True)
        ):
            raise ValueError("CURRENT_DAY_CALENDAR_INVALID")
        values_by_key[key] = dict(raw)
    if set(values_by_key) != expected_keys:
        raise ValueError("CURRENT_DAY_CALENDAR_INVALID")
    return tuple(values_by_key[key] for key in sorted(values_by_key))


def _current_day_sessions(
    snapshot: MetadataSnapshot,
    products: tuple[str, ...],
    exchanges: Mapping[str, str],
    trading_day: date,
) -> tuple[dict[str, Any], ...]:
    """提取当前日按日 session；半开或跨日 provider 行都 fail-closed。"""
    values: list[dict[str, Any]] = []
    seen: set[tuple[object, ...]] = set()
    covered: set[str] = set()
    expected = set(products)
    for raw in snapshot.sessions:
        symbol = raw.get("instrument_symbol")
        effective_from = raw.get("effective_from")
        effective_to = raw.get("effective_to")
        touches_day = effective_from == trading_day or effective_to == trading_day
        if symbol not in expected:
            if touches_day:
                raise ValueError("CURRENT_DAY_TRADING_SESSION_INVALID")
            continue
        if not touches_day:
            continue
        if effective_from != trading_day or effective_to != trading_day:
            raise ValueError("CURRENT_DAY_TRADING_SESSION_INVALID")
        if (
            raw.get("exchange_code") != exchanges[symbol]
            or not isinstance(raw.get("session_name"), str)
            or not raw["session_name"].strip()
            or not isinstance(raw.get("start_time"), time)
            or not isinstance(raw.get("end_time"), time)
            or not isinstance(raw.get("crosses_midnight"), bool)
            or not isinstance(raw.get("is_active"), bool)
        ):
            raise ValueError("CURRENT_DAY_TRADING_SESSION_INVALID")
        identity = (
            raw["exchange_code"],
            symbol,
            raw["session_name"],
            raw["start_time"],
            raw["end_time"],
            effective_from,
        )
        if identity in seen:
            raise ValueError("CURRENT_DAY_TRADING_SESSION_INVALID")
        seen.add(identity)
        covered.add(symbol)
        values.append(dict(raw))
    if covered != expected:
        raise ValueError("CURRENT_DAY_TRADING_SESSION_INVALID")
    return tuple(values)


def _current_day_main_contracts(
    session,
    snapshot: MetadataSnapshot,
    products: tuple[str, ...],
    trading_day: date,
) -> tuple[tuple[str, date, str], ...]:
    """提取当天唯一 rank-1 映射，并拒绝缺失、重复或非当天 window。"""
    expected = set(products)
    if set(snapshot.main_contract_starts) != expected or any(
        snapshot.main_contract_starts.get(symbol) != trading_day for symbol in products
    ):
        raise ValueError("CURRENT_DAY_MAIN_CONTRACT_MAP_INVALID")
    values: dict[str, tuple[str, date, str]] = {}
    for row in snapshot.main_contracts:
        try:
            raw_symbol, row_day, raw_contract = row
        except (TypeError, ValueError) as exc:
            raise ValueError("CURRENT_DAY_MAIN_CONTRACT_MAP_INVALID") from exc
        if row_day != trading_day:
            continue
        if not isinstance(raw_symbol, str) or not isinstance(raw_contract, str):
            raise ValueError("CURRENT_DAY_MAIN_CONTRACT_MAP_INVALID")
        symbol = raw_symbol.strip().lower()
        contract = raw_contract.strip().upper()
        if symbol not in expected or not contract or symbol in values:
            raise ValueError("CURRENT_DAY_MAIN_CONTRACT_MAP_INVALID")
        values[symbol] = (symbol, trading_day, contract)
    if set(values) != expected:
        raise ValueError("CURRENT_DAY_MAIN_CONTRACT_MAP_INVALID")
    existing_contracts = {
        (row.instrument_symbol, row.contract_code.upper())
        for row in session.scalars(
            select(Contract).where(Contract.instrument_symbol.in_(products))
        )
    }
    if any(
        (symbol, contract) not in existing_contracts
        for symbol, _, contract in values.values()
    ):
        raise ValueError("CURRENT_DAY_MAIN_CONTRACT_MAP_INVALID")
    return tuple(values[symbol] for symbol in products)
