"""RQData bars/metadata adapter and lazy provider client."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import os
import re
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.env import load_project_env
from app.market_data.coverage_source import (
    _calendar_context_start,
    _iso_week_end,
    _product_trading_days,
)
from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey, DatasetKind
from app.market_data.errors import InfrastructureError
from app.market_data.historical_data_manager import BarBatch
from app.market_data.metadata import MetadataSnapshot
from app.market_data.session_clock import SHANGHAI
from app.models import Contract, Instrument, MainContractMap, TradingCalendar


_SESSION = re.compile(r"(?P<start>\d{1,2}:\d{2})\s*[-~]\s*(?P<end>\d{1,2}:\d{2})")


class RQDataMarketAdapter:
    """固定 RQData 适配器：bars 拉取与 metadata snapshot（实现 BarSource / MetadataPort）。"""

    def __init__(self, *, session: Session, client: Any | None = None) -> None:
        self.session = session
        self._client = client

    @property
    def client(self) -> Any:
        """仅在 apply 路径首次需要行情时初始化 rqdatac，dry-run 不触网。"""
        if self._client is None:
            self._client = RQDataClient()
        return self._client

    def fetch(self, key: DatasetKey, expected: tuple[datetime, ...]) -> BarBatch:
        """按 expected bar_end 拉取并归一化为 CanonicalBar；配额错误转为 PROVIDER_QUOTA_EXHAUSTED。"""
        if not expected:
            raise InfrastructureError("PROVIDER_WINDOW_EMPTY")
        if key.frequency is BarFrequency.D1:
            return BarBatch(self._daily_bars(key, expected))
        if key.frequency is BarFrequency.W1:
            return BarBatch(self._weekly_bars(key, expected))
        return BarBatch(self._minute_bars(key, expected))

    def _minute_bars(
        self, key: DatasetKey, expected: tuple[datetime, ...]
    ) -> tuple[CanonicalBar, ...]:
        """1m 保持 get_price；期货日/周线另走交易所日行情。"""
        order_book_id = (
            f"{key.symbol.upper()}88"
            if key.kind is DatasetKind.CONTINUOUS
            else key.series_or_contract
        )
        try:
            rows = _records(
                self.client.price(
                    order_book_id,
                    min(expected).date(),
                    max(expected).date(),
                    key.frequency.value,
                )
            )
        except Exception as exc:  # noqa: BLE001 - normalize provider boundary
            if _is_rqdata_quota_error(exc):
                raise InfrastructureError("PROVIDER_QUOTA_EXHAUSTED") from exc
            raise
        bars = [
            _canonical_bar(row, bar_end, _row_date(row))
            for row in rows
            if (bar_end := _row_datetime(row)) in expected
        ]
        return tuple(sorted(bars, key=lambda item: item.bar_end))

    def _daily_bars(
        self, key: DatasetKey, expected: tuple[datetime, ...]
    ) -> tuple[CanonicalBar, ...]:
        """期货日线取交易所日行情；continuous 按交易日 rank1 合约拼接。"""
        expected_by_day = {
            value.astimezone(SHANGHAI).date(): value for value in expected
        }
        rows = self._exchange_daily_rows(key, tuple(expected_by_day))
        return tuple(
            _canonical_bar(row, expected_by_day[trading_day], trading_day)
            for trading_day, row in sorted(rows.items())
            if trading_day in expected_by_day
        )

    def _weekly_bars(
        self, key: DatasetKey, expected: tuple[datetime, ...]
    ) -> tuple[CanonicalBar, ...]:
        """期货周线仅由同一交易所日行情在完整 ISO 周内聚合。"""
        expected_by_week = {
            _iso_week(value.astimezone(SHANGHAI).date()): value for value in expected
        }
        mondays = tuple(
            _iso_monday(value.astimezone(SHANGHAI).date()) for value in expected
        )
        source_days = self._source_trading_days(
            key, min(mondays), max(mondays) + timedelta(days=6)
        )
        rows = self._exchange_daily_rows(key, source_days)
        required_by_week: dict[tuple[int, int], set[date]] = {}
        for trading_day in source_days:
            iso = _iso_week(trading_day)
            if iso in expected_by_week:
                required_by_week.setdefault(iso, set()).add(trading_day)
        grouped: dict[tuple[int, int], list[tuple[date, dict[str, Any]]]] = {}
        for trading_day, row in rows.items():
            iso = _iso_week(trading_day)
            if iso in expected_by_week:
                grouped.setdefault(iso, []).append((trading_day, row))
        return tuple(
            _aggregate_daily_rows(tuple(sorted(rows)), bar_end=expected_by_week[iso])
            for iso, rows in sorted(grouped.items())
            if {trading_day for trading_day, _ in rows} == required_by_week[iso]
        )

    def _exchange_daily_rows(
        self, key: DatasetKey, days: tuple[date, ...]
    ) -> dict[date, dict[str, Any]]:
        """按真实合约分组读取交易所日线；每个交易日只接受一行。"""
        contracts_by_day = self._contracts_by_day(key, days)
        requested: dict[str, list[date]] = {}
        for trading_day, contract in contracts_by_day.items():
            requested.setdefault(contract, []).append(trading_day)
        result: dict[date, dict[str, Any]] = {}
        for contract, contract_days in requested.items():
            try:
                rows = _records(
                    self.client.exchange_daily(
                        contract, min(contract_days), max(contract_days)
                    )
                )
            except Exception as exc:  # noqa: BLE001 - normalize provider boundary
                if _is_rqdata_quota_error(exc):
                    raise InfrastructureError("PROVIDER_QUOTA_EXHAUSTED") from exc
                raise
            allowed = set(contract_days)
            for row in rows:
                trading_day = _row_date(row)
                if trading_day not in allowed:
                    continue
                if trading_day in result:
                    raise InfrastructureError("RQDATA_EXCHANGE_DAILY_DUPLICATE")
                result[trading_day] = row
        return result

    def _contracts_by_day(
        self, key: DatasetKey, days: tuple[date, ...]
    ) -> dict[date, str]:
        """continuous 使用已同步的 rank1 映射，contract 保持物理身份。"""
        normalized = tuple(sorted(dict.fromkeys(days)))
        if key.kind is DatasetKind.CONTRACT:
            return {trading_day: key.series_or_contract for trading_day in normalized}
        mapped = {
            item.trade_date: item.contract_code
            for item in self.session.scalars(
                select(MainContractMap).where(
                    MainContractMap.symbol == key.symbol,
                    MainContractMap.trade_date.in_(normalized),
                )
            )
        }
        if any(day not in mapped for day in normalized):
            raise InfrastructureError("MAIN_CONTRACT_MAP_MISSING")
        return mapped

    def _source_trading_days(
        self, key: DatasetKey, start: date, end: date
    ) -> tuple[date, ...]:
        """周线聚合的交易日集合，真实合约仅纳入挂牌且未到期区间。"""
        exchange = self.session.scalar(
            select(Instrument.exchange_code).where(Instrument.symbol == key.symbol)
        )
        if exchange is None:
            raise InfrastructureError("INSTRUMENT_EXCHANGE_MISSING")
        statement = select(TradingCalendar.trade_date).where(
            TradingCalendar.exchange_code == exchange,
            TradingCalendar.trade_date >= start,
            TradingCalendar.trade_date <= end,
            TradingCalendar.is_trading_day.is_(True),
        )
        days = tuple(self.session.scalars(statement.order_by(TradingCalendar.trade_date)))
        if key.kind is DatasetKind.CONTRACT:
            contract = self.session.scalar(select(Contract).where(
                Contract.contract_code == key.series_or_contract,
                Contract.instrument_symbol == key.symbol,
            ))
            if (
                contract is None
                or contract.listed_date is None
                or contract.expired_date is None
            ):
                return ()
            return tuple(
                day
                for day in days
                if contract.listed_date <= day < contract.expired_date
            )
        return days

    def fetch_metadata(
        self,
        products: tuple[str, ...],
        through: date,
        starts: Mapping[str, date],
    ) -> MetadataSnapshot:
        """规划 metadata 拉取起点：兼顾映射缺口与近端刷新窗口，再调 RQData snapshot。"""
        requested_starts: dict[str, date] = {}
        for symbol in products:
            floor = starts[symbol]
            current = self.session.scalar(
                select(func.max(MainContractMap.trade_date)).where(
                    MainContractMap.symbol == symbol
                )
            )
            # 默认从最近映射日前 14 天刷新，映射缺口则前推到首个缺失日。
            refresh_start = (
                max(floor, current - timedelta(days=14)) if current else floor
            )
            exchange = self.session.scalar(
                select(Instrument.exchange_code).where(Instrument.symbol == symbol)
            )
            if exchange is not None:
                first_map_day = self.session.scalar(
                    select(func.min(MainContractMap.trade_date)).where(
                        MainContractMap.symbol == symbol,
                        MainContractMap.trade_date >= floor,
                        MainContractMap.trade_date <= through,
                    )
                )
                map_floor = first_map_day or floor
                # MetadataSynchronizer replaces all historical Session facts for a
                # product.  Its snapshot must therefore start at the first
                # provider-backed map day, not merely the recent map-refresh
                # window; otherwise a near-term refresh erases older sessions.
                refresh_start = map_floor
                calendar_days = _product_trading_days(
                    self.session,
                    symbol,
                    exchange,
                    map_floor,
                    through,
                )
                mapped_days = set(
                    self.session.scalars(
                        select(MainContractMap.trade_date).where(
                            MainContractMap.symbol == symbol,
                            MainContractMap.trade_date >= map_floor,
                            MainContractMap.trade_date <= through,
                        )
                    )
                )
                missing_map = next(
                    (day for day in calendar_days if day not in mapped_days), None
                )
                if missing_map is not None:
                    refresh_start = min(refresh_start, missing_map)
            requested_starts[symbol] = refresh_start
        return self.client.metadata_snapshot(products, through, requested_starts)

    def fetch_current_day_metadata(
        self,
        products: tuple[str, ...],
        trading_day: date,
    ) -> MetadataSnapshot:
        """只请求指定交易日的 Runtime metadata，不扩展历史 refresh window。"""
        return self.client.current_day_metadata_snapshot(products, trading_day)


class RQDataClient:
    """rqdatac 薄封装：凭证初始化与 price / metadata 高层调用。"""

    def __init__(self) -> None:
        load_project_env()
        try:
            import rqdatac  # type: ignore[import-not-found, import-untyped]
        except ImportError as exc:
            raise InfrastructureError("RQDATA_NOT_INSTALLED") from exc
        uri = os.getenv("RQDATAC2_CONF") or os.getenv("RQDATAC_CONF")
        license_key = os.getenv("RQDATA_LICENSE_KEY")
        username = os.getenv("RQDATA_USERNAME")
        password = os.getenv("RQDATA_PASSWORD")
        if uri:
            rqdatac.init(uri=uri)
        elif license_key:
            rqdatac.init("license", license_key)
        elif username and password:
            rqdatac.init(
                username,
                password,
                os.getenv("RQDATA_ADDR", "rqdatad-pro.ricequant.com:16011"),
            )
        else:
            raise InfrastructureError("RQDATA_CREDENTIALS_MISSING")
        self.api = rqdatac

    def price(self, order_book_id: str, start: date, end: date, frequency: str):
        """调用 get_price；adjust_type=none 保持与 canonical 未复权语义一致。"""
        return self.api.get_price(
            order_book_id,
            start_date=start,
            end_date=end,
            frequency=frequency,
            adjust_type="none",
        )

    def exchange_daily(self, order_book_id: str, start: date, end: date):
        """调用期货交易所日行情，保留 close 与 settlement 的独立事实。"""
        return self.api.futures.get_exchange_daily(
            order_book_id,
            start_date=start,
            end_date=end,
            market="cn",
        )

    def is_future_data_ready(self, trading_day: date) -> bool:
        """确认日线与分钟线均已由 RQData 标记为可用。"""
        categories = ("future_daybar", "future_minbar")
        frame = self.api.is_data_ready(
            categories=list(categories),
            expected_date=trading_day,
            market="cn",
        )
        if (
            not isinstance(frame, pd.DataFrame)
            or not isinstance(frame.index, pd.MultiIndex)
            or tuple(frame.index.names) != ("market", "category")
            or not frame.index.is_unique
            or "ready" not in frame.columns
        ):
            raise InfrastructureError("RQDATA_READY_RESPONSE_INVALID")
        required_keys = tuple(("cn", category) for category in categories)
        if any(key not in frame.index for key in required_keys):
            raise InfrastructureError("RQDATA_READY_RESPONSE_INVALID")
        required = frame.loc[list(required_keys), "ready"]
        if (
            tuple(required.index.tolist()) != required_keys
            or not pd.api.types.is_bool_dtype(required.dtype)
            or bool(required.isna().any())
        ):
            raise InfrastructureError("RQDATA_READY_RESPONSE_INVALID")
        return bool(required.all())

    def dominant_for_day(self, symbol: str, trading_day: date) -> str:
        """返回指定交易日唯一的 rank=1 主力合约；异常结果显式拒绝。"""
        frame = _frame(
            self.api.futures.get_dominant(
                symbol.upper(),
                start_date=trading_day,
                end_date=trading_day,
                rule=2,
                rank=1,
            )
        )
        values = tuple(
            _row_text(
                row,
                "dominant",
                "order_book_id",
                "contract",
                "dominant_contract",
                0,
                "0",
            ).strip().upper()
            for row in frame.to_dict("records")
        )
        normalized = tuple(value for value in values if value)
        if len(normalized) != 1:
            raise InfrastructureError("RQDATA_DOMINANT_INVALID")
        return normalized[0]

    def live_market_client(self) -> Any:
        """创建 RQData Live client；仅由显式的前台 live Runtime 使用。"""
        return self.api.LiveMarketDataClient()

    def metadata_snapshot(
        self,
        products: tuple[str, ...],
        through: date,
        starts: Mapping[str, date],
        *,
        current_day_only: bool = False,
    ) -> MetadataSnapshot:
        """组装 MetadataSnapshot：合约、日历、按日会话、主力 rank1 映射。"""
        frame = _frame(self.api.all_instruments(type="Future"))
        product_set = {item.upper() for item in products}
        if "underlying_symbol" not in frame.columns:
            raise InfrastructureError("RQDATA_INSTRUMENT_SCHEMA_INVALID")
        frame = frame[
            frame["underlying_symbol"].astype(str).str.upper().isin(product_set)
        ]
        exchanges: dict[str, dict[str, object]] = {}
        instruments: dict[str, dict[str, object]] = {}
        contracts: list[dict[str, object]] = []
        for row in frame.to_dict("records"):
            symbol = str(row["underlying_symbol"]).lower()
            exchange = str(row.get("exchange", row.get("exchange_code", ""))).upper()
            contract = str(row.get("order_book_id", "")).upper()
            if not exchange or not contract:
                continue
            listed = _optional_date(row.get("listed_date"))
            exchanges[exchange] = {"code": exchange, "name": exchange}
            instruments[symbol] = {
                "symbol": symbol,
                "name": str(row.get("underlying_symbol", symbol)),
                "exchange_code": exchange,
                "is_active": True,
            }
            contracts.append(
                {
                    "contract_code": contract,
                    "instrument_symbol": symbol,
                    "exchange_code": exchange,
                    "name": str(row.get("symbol", contract)),
                    "contract_multiplier": _optional_int(
                        row.get("contract_multiplier")
                    ),
                    "listed_date": listed,
                    "expired_date": _optional_date(row.get("de_listed_date")),
                    "maturity_date": _optional_date(row.get("maturity_date")),
                    "trading_hours": _optional_text(row.get("trading_hours")),
                    "provider": "rqdata",
                }
            )
        # Fetch one week past the bar watermark so a holiday-short ISO week can
        # still be proven complete without storing a second calendar watermark.
        # Calendar may start one natural month before the earliest effective_start
        # for previous-day / night-session / first ISO-week context only.
        # 日历向后多取一周：短假周仍可证明 ISO 周完整，无需第二套 calendar watermark。
        if current_day_only:
            calendar_start = min(starts.values())
            calendar_end = max(_iso_week_end(calendar_start), through)
        else:
            earliest = min(starts.values())
            calendar_start = _calendar_context_start(earliest)
            calendar_end = through + timedelta(days=7)
        trading_dates = tuple(
            pd.Timestamp(item).date()
            for item in self.api.get_trading_dates(
                start_date=calendar_start,
                end_date=calendar_end,
            )
        )
        main_contracts: list[tuple[str, date, str]] = []
        for symbol in products:
            values = _frame(
                self.api.futures.get_dominant(
                    symbol.upper(),
                    start_date=starts[symbol],
                    end_date=through,
                    rule=2,
                    rank=1,
                )
            )
            for row in values.to_dict("records"):
                day = _row_date(row)
                contract = _row_text(
                    row,
                    "dominant",
                    "order_book_id",
                    "contract",
                    "dominant_contract",
                    0,
                    "0",
                )
                main_contracts.append((symbol, day, contract.upper()))
        symbol_exchanges = {
            symbol: str(values["exchange_code"])
            for symbol, values in instruments.items()
        }
        # 按主力合约集合拉取按日 trading_periods，用于构建历史会话事实（非当前 trading_hours）。
        periods = _records(
            self.api.get_trading_periods(
                tuple(sorted({contract for _, _, contract in main_contracts})),
                start_date=calendar_start,
                end_date=through,
                frequency="1m",
            )
        )
        sessions = _historical_session_rows(
            periods,
            main_contracts,
            symbol_exchanges,
        )
        # 有夜盘或跨日的交易所，日历行标记 has_night_session。
        night_exchanges = {
            str(row["exchange_code"])
            for row in sessions
            if (isinstance(row["start_time"], time) and row["start_time"] >= time(18))
            or bool(row["crosses_midnight"])
        }
        trading_day_set = set(trading_dates)
        calendars = tuple(
            {
                "exchange_code": exchange,
                "trade_date": day,
                "is_trading_day": day in trading_day_set,
                "has_night_session": exchange in night_exchanges
                and day in trading_day_set,
                "provider": "rqdata",
            }
            for exchange in exchanges
            for day in _days(calendar_start, calendar_end)
        )
        return MetadataSnapshot(
            exchanges=tuple(exchanges.values()),
            instruments=tuple(instruments.values()),
            contracts=tuple(contracts),
            calendars=calendars,
            sessions=sessions,
            main_contracts=tuple(main_contracts),
            main_contract_starts=dict(starts),
        )

    def current_day_metadata_snapshot(
        self,
        products: tuple[str, ...],
        trading_day: date,
    ) -> MetadataSnapshot:
        """构造当天 rank1、当天/下一交易日 Session 与有界 Calendar 上下文。"""
        probe_end = trading_day + timedelta(days=14)
        probe_dates = tuple(
            pd.Timestamp(item).date()
            for item in self.api.get_trading_dates(
                start_date=trading_day,
                end_date=probe_end,
            )
        )
        next_trading_day = next(
            (day for day in probe_dates if day > trading_day),
            None,
        )
        if next_trading_day is None:
            raise InfrastructureError("RQDATA_NEXT_TRADING_DAY_MISSING")
        starts = {symbol: trading_day for symbol in products}
        return self.metadata_snapshot(
            products,
            next_trading_day,
            starts,
            current_day_only=True,
        )


def _records(value: Any) -> tuple[dict[str, Any], ...]:
    """将 RQData 返回统一为 record 元组。"""
    return tuple(_frame(value).to_dict("records"))


def _frame(value: Any) -> pd.DataFrame:
    """将 Series/DataFrame/其他结构规范为带 RangeIndex 的 DataFrame。"""
    if isinstance(value, pd.DataFrame):
        result = value.copy()
        if not isinstance(result.index, pd.RangeIndex):
            result = result.reset_index()
        return result
    if isinstance(value, pd.Series):
        return value.reset_index()
    return pd.DataFrame(value)


def _row_date(row: dict[str, Any]) -> date:
    """从 provider 行解析 trading_day。"""
    value = _row_value(row, "trading_date", "trade_date", "date", "index")
    parsed = pd.Timestamp(value)
    if pd.isna(parsed):
        raise InfrastructureError("RQDATA_TRADING_DAY_INVALID")
    return parsed.date()


def _row_datetime(row: dict[str, Any]) -> datetime:
    """从 provider 行解析 bar_end，统一转为 UTC。"""
    parsed = pd.Timestamp(_row_value(row, "datetime", "index"))
    if pd.isna(parsed):
        raise InfrastructureError("RQDATA_BAR_END_INVALID")
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize(SHANGHAI)
    return parsed.tz_convert(UTC).to_pydatetime()


def _iso_week(value: date) -> tuple[int, int]:
    """返回 ISO 年/周，避免把日线/周线的分组语义散落在调用点。"""
    iso = value.isocalendar()
    return iso.year, iso.week


def _iso_monday(value: date) -> date:
    """返回 value 所在 ISO 周的周一。"""
    return value - timedelta(days=value.isoweekday() - 1)


def _aggregate_daily_rows(
    values: tuple[tuple[date, dict[str, Any]], ...],
    *,
    bar_end: datetime,
) -> CanonicalBar:
    """从排序后的交易所日行情聚合周线，保持日线 OHLCV 事实口径。"""
    if not values:
        raise InfrastructureError("RQDATA_WEEKLY_SOURCE_EMPTY")
    rows = tuple(row for _, row in values)
    first_day, first_row = values[0]
    last_day, last_row = values[-1]
    turnovers = tuple(
        _optional_decimal(
            _row_value(row, "turnover", "total_turnover", "amount", required=False)
        )
        for row in rows
    )
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=last_day,
        open=_decimal(first_row, "open"),
        high=max(_decimal(row, "high") for row in rows),
        low=min(_decimal(row, "low") for row in rows),
        close=_decimal(last_row, "close"),
        volume=sum((_decimal(row, "volume") for row in rows), start=Decimal(0)),
        turnover=(
            None
            if all(value is None for value in turnovers)
            else sum((value or Decimal(0) for value in turnovers), start=Decimal(0))
        ),
        open_interest=_optional_decimal(
            _row_value(last_row, "open_interest", "open_oi", "close_oi", required=False)
        ),
    )


def _canonical_bar(
    row: dict[str, Any], bar_end: datetime, trading_day: date
) -> CanonicalBar:
    """将 provider OHLCV 行映射为 CanonicalBar（Decimal 字段）。"""
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=trading_day,
        open=_decimal(row, "open"),
        high=_decimal(row, "high"),
        low=_decimal(row, "low"),
        close=_decimal(row, "close"),
        volume=_decimal(row, "volume"),
        turnover=_optional_decimal(
            _row_value(row, "turnover", "total_turnover", "amount", required=False)
        ),
        open_interest=_optional_decimal(
            _row_value(row, "open_interest", "open_oi", "close_oi", required=False)
        ),
    )


def _decimal(row: dict[str, Any], field: str) -> Decimal:
    """必填 Decimal 字段；缺失时 fail-closed。"""
    value = _optional_decimal(_row_value(row, field))
    if value is None:
        raise InfrastructureError("RQDATA_DECIMAL_MISSING")
    return value


def _optional_decimal(value: Any) -> Decimal | None:
    """可空 Decimal 解析；非法值抛出 RQDATA_DECIMAL_INVALID。"""
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise InfrastructureError("RQDATA_DECIMAL_INVALID") from exc


def _row_value(row: dict[str, Any], *fields: Any, required: bool = True) -> Any:
    """按候选字段名取首个非空值；required 时缺失抛 RQDATA_FIELD_MISSING。"""
    for field in fields:
        if field in row and row[field] is not None:
            return row[field]
    if required:
        raise InfrastructureError("RQDATA_FIELD_MISSING")
    return None


def _row_text(row: dict[str, Any], *fields: Any) -> str:
    """解析非空字符串字段。"""
    value = _row_value(row, *fields)
    if not isinstance(value, str) or not value.strip():
        raise InfrastructureError("RQDATA_TEXT_INVALID")
    return value.strip()


def _optional_date(value: Any) -> date | None:
    """可空日期；RQData 占位 0000 日期视为 None。"""
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str) and value.strip().startswith("0000"):
        return None
    return pd.Timestamp(value).date()


def _optional_int(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _optional_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    result = str(value).strip()
    return result or None


def _historical_session_rows(
    periods: tuple[dict[str, Any], ...],
    main_contracts: list[tuple[str, date, str]],
    symbol_exchanges: Mapping[str, str],
) -> tuple[dict[str, object], ...]:
    """将 get_trading_periods 结果转为按日 TradingSession 行；须与主力映射日全集一致。"""
    expected = {(contract, day): symbol for symbol, day, contract in main_contracts}
    values: dict[tuple[str, date], str] = {}
    for row in periods:
        contract = _row_text(row, "order_book_id", "level_0").upper()
        trading_day = _row_date(row)
        key = (contract, trading_day)
        if key not in expected:
            continue
        hours = _optional_text(row.get("trading_hours"))
        if hours is None or key in values:
            raise InfrastructureError("RQDATA_TRADING_SESSIONS_MISSING")
        values[key] = hours
    if set(values) != set(expected):
        raise InfrastructureError("RQDATA_TRADING_SESSIONS_MISSING")
    rows: list[dict[str, object]] = []
    for contract, trading_day in sorted(values, key=lambda item: (item[1], item[0])):
        symbol = expected[(contract, trading_day)]
        exchange = symbol_exchanges.get(symbol)
        if exchange is None:
            raise InfrastructureError("RQDATA_TRADING_SESSIONS_MISSING")
        matches = tuple(_SESSION.finditer(values[(contract, trading_day)]))
        if not matches:
            raise InfrastructureError("RQDATA_TRADING_SESSIONS_MISSING")
        for index, match in enumerate(matches, start=1):
            start_time = time.fromisoformat(match.group("start"))
            end_time = time.fromisoformat(match.group("end"))
            rows.append(
                {
                    "exchange_code": exchange,
                    "instrument_symbol": symbol,
                    "session_name": f"session_{index}",
                    "start_time": start_time,
                    "end_time": end_time,
                    "effective_from": trading_day,
                    "effective_to": trading_day,
                    "crosses_midnight": end_time <= start_time,
                    "is_active": True,
                    "provider": "rqdata",
                }
            )
    return tuple(rows)


def _days(start: date, end: date):
    """闭区间自然日迭代。"""
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


def _is_rqdata_quota_error(exc: Exception) -> bool:
    """识别 RQData 配额/限流错误，供 fetch 转为可恢复的 PROVIDER_QUOTA_EXHAUSTED。"""
    code = str(getattr(exc, "code", "")).upper()
    if code in {"RQDATA_QUOTA_EXCEEDED", "RQDATA_DAILY_QUOTA_EXCEEDED"}:
        return True
    if not type(exc).__module__.startswith("rqdatac"):
        return False
    text = str(exc).lower()
    return "quota" in text or "rate limit" in text or "daily download limit" in text
