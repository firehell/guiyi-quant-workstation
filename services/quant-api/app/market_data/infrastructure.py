from __future__ import annotations

from collections.abc import Callable, Mapping
import csv
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.env import load_project_env
from app.market_data.aggregation import SessionWindow
from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey, DatasetKind
from app.market_data.maintenance import BarBatch
from app.market_data.metadata import MetadataSnapshot
from app.models import ContractSpec, Instrument, MainContractMap, TradingCalendar, TradingSession


SHANGHAI = ZoneInfo("Asia/Shanghai")
_SESSION = re.compile(r"(?P<start>\d{1,2}:\d{2})\s*[-~]\s*(?P<end>\d{1,2}:\d{2})")


class InfrastructureError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class DatabaseCoverageSource:
    """Build deterministic expected bar ends from actual-exchange metadata."""

    def __init__(
        self,
        session: Session,
        product_starts_path: Path,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.starts = _load_product_starts(product_starts_path)
        self._now = now or (lambda: datetime.now(SHANGHAI))

    def product_start(self, symbol: str) -> date:
        try:
            return self.starts[symbol.strip().lower()]
        except KeyError as exc:
            raise InfrastructureError("PRODUCT_WINDOW_START_MISSING") from exc

    def latest_complete_day(self, products: tuple[str, ...]) -> date:
        values: list[date] = []
        current = self._now().astimezone(SHANGHAI)
        today = current.date()
        for symbol in products:
            exchange = self._exchange(symbol)
            value = self.session.scalar(
                select(func.max(TradingCalendar.trade_date)).where(
                    TradingCalendar.exchange_code == exchange,
                    TradingCalendar.is_trading_day.is_(True),
                    TradingCalendar.trade_date <= today,
                )
            )
            if value is None:
                raise InfrastructureError("TRADING_CALENDAR_MISSING")
            if value == today:
                session_end = max(window.end for window in self._sessions_for_day(symbol, value))
                if current < session_end:
                    value = self.session.scalar(
                        select(func.max(TradingCalendar.trade_date)).where(
                            TradingCalendar.exchange_code == exchange,
                            TradingCalendar.is_trading_day.is_(True),
                            TradingCalendar.trade_date < today,
                        )
                    )
                    if value is None:
                        raise InfrastructureError("COMPLETE_TRADING_DAY_MISSING")
            values.append(value)
        return min(values)

    def metadata_complete(self, products: tuple[str, ...], through: date) -> bool:
        for symbol in products:
            try:
                exchange = self._exchange(symbol)
            except InfrastructureError as exc:
                if exc.code == "INSTRUMENT_EXCHANGE_MISSING":
                    return False
                raise
            calendar_end = self.session.scalar(
                select(func.max(TradingCalendar.trade_date)).where(
                    TradingCalendar.exchange_code == exchange,
                    TradingCalendar.is_trading_day.is_(True),
                )
            )
            if calendar_end is None or calendar_end < through:
                return False
            if self.session.scalar(
                select(TradingSession.id).where(
                    TradingSession.exchange_code == exchange,
                    TradingSession.instrument_symbol == symbol,
                    TradingSession.is_active.is_(True),
                    TradingSession.effective_from <= through,
                    (
                        TradingSession.effective_to.is_(None)
                        | (TradingSession.effective_to >= through)
                    ),
                ).limit(1)
            ) is None:
                return False
            last_trading_day = self.session.scalar(
                select(func.max(TradingCalendar.trade_date)).where(
                    TradingCalendar.exchange_code == exchange,
                    TradingCalendar.trade_date <= through,
                    TradingCalendar.is_trading_day.is_(True),
                )
            )
            if last_trading_day is None:
                return False
            expected_days = self._trading_days(
                symbol,
                self.product_start(symbol),
                through,
            )
            mapped_days = tuple(self.session.scalars(
                select(MainContractMap.trade_date).where(
                    MainContractMap.symbol == symbol,
                    MainContractMap.trade_date >= self.product_start(symbol),
                    MainContractMap.trade_date <= through,
                ).order_by(MainContractMap.trade_date)
            ))
            if mapped_days != expected_days:
                return False
            missing_spec = self.session.scalar(
                select(MainContractMap.id)
                .where(
                    MainContractMap.symbol == symbol,
                    MainContractMap.trade_date <= through,
                    ~exists().where(
                        ContractSpec.contract_code == MainContractMap.contract_code,
                        ContractSpec.trade_date == MainContractMap.trade_date,
                    ),
                )
                .limit(1)
            )
            if missing_spec is not None:
                return False
        return True

    def expected_bar_ends(
        self,
        key: DatasetKey,
        year: int,
        month: int,
        start: date,
        end: date,
    ) -> tuple[datetime, ...]:
        lower = max(start, date(year, month, 1), self.product_start(key.symbol))
        upper = min(end, _month_end(year, month))
        if lower > upper:
            return ()
        days = self._trading_days(key.symbol, lower, upper)
        return self.expected_bar_ends_for_trading_days(key, days)

    def expected_bar_ends_for_trading_days(
        self,
        key: DatasetKey,
        trading_days: tuple[date, ...],
    ) -> tuple[datetime, ...]:
        days = tuple(sorted(dict.fromkeys(trading_days)))
        if not days:
            return ()
        sessions_by_day = {
            day: self._sessions_for_day(key.symbol, day) for day in days
        }
        if key.frequency is BarFrequency.M1:
            return tuple(
                window.start + timedelta(minutes=minute)
                for day in days
                for window in sessions_by_day[day]
                for minute in range(1, _minutes(window) + 1)
            )
        if key.frequency in {
            BarFrequency.M5,
            BarFrequency.M15,
            BarFrequency.M30,
            BarFrequency.H1,
        }:
            width = {
                BarFrequency.M5: 5,
                BarFrequency.M15: 15,
                BarFrequency.M30: 30,
                BarFrequency.H1: 60,
            }[key.frequency]
            result: list[datetime] = []
            for day in days:
                for window in sessions_by_day[day]:
                    count = _minutes(window)
                    result.extend(
                        window.start + timedelta(minutes=min(offset, count))
                        for offset in range(width, count + width, width)
                    )
            return tuple(dict.fromkeys(result))
        daily = tuple(sessions_by_day[day][-1].end for day in days)
        if key.frequency is BarFrequency.D1:
            return daily
        result = []
        grouped: dict[tuple[int, int], list[tuple[date, datetime]]] = {}
        for day, bar_end in zip(days, daily, strict=True):
            iso = day.isocalendar()
            grouped.setdefault((iso.year, iso.week), []).append((day, bar_end))
        for values in grouped.values():
            candidate_day, bar_end = values[-1]
            monday = candidate_day - timedelta(days=candidate_day.isoweekday() - 1)
            sunday = monday + timedelta(days=6)
            full_week = self._trading_days(key.symbol, monday, sunday)
            if full_week and full_week[-1] == candidate_day:
                result.append(bar_end)
        return tuple(result)

    def sessions(
        self,
        key: DatasetKey,
        year: int,
        month: int,
    ) -> tuple[SessionWindow, ...]:
        lower = max(date(year, month, 1), self.product_start(key.symbol))
        upper = _month_end(year, month)
        return tuple(
            window
            for day in self._trading_days(key.symbol, lower, upper)
            for window in self._sessions_for_day(key.symbol, day)
        )

    def valid_boundary(self, key: DatasetKey, bar: CanonicalBar) -> bool:
        expected = self.expected_bar_ends(
            key,
            bar.trading_day.year,
            bar.trading_day.month,
            bar.trading_day,
            bar.trading_day,
        )
        return bar.bar_end in expected

    def _exchange(self, symbol: str) -> str:
        value = self.session.scalar(
            select(Instrument.exchange_code).where(
                Instrument.symbol == symbol.strip().lower(),
                Instrument.is_active.is_(True),
            )
        )
        if value is None:
            raise InfrastructureError("INSTRUMENT_EXCHANGE_MISSING")
        return value

    def _trading_days(self, symbol: str, start: date, end: date) -> tuple[date, ...]:
        exchange = self._exchange(symbol)
        return tuple(
            self.session.scalars(
                select(TradingCalendar.trade_date)
                .where(
                    TradingCalendar.exchange_code == exchange,
                    TradingCalendar.trade_date >= start,
                    TradingCalendar.trade_date <= end,
                    TradingCalendar.is_trading_day.is_(True),
                )
                .order_by(TradingCalendar.trade_date)
            )
        )

    def _sessions_for_day(self, symbol: str, trading_day: date) -> tuple[SessionWindow, ...]:
        exchange = self._exchange(symbol)
        templates = tuple(
            self.session.scalars(
                select(TradingSession)
                .where(
                    TradingSession.exchange_code == exchange,
                    TradingSession.instrument_symbol == symbol.strip().lower(),
                    TradingSession.is_active.is_(True),
                    TradingSession.effective_from <= trading_day,
                    (
                        TradingSession.effective_to.is_(None)
                        | (TradingSession.effective_to >= trading_day)
                    ),
                )
                .order_by(TradingSession.start_time)
            )
        )
        if not templates:
            raise InfrastructureError("TRADING_SESSION_MISSING")
        prior = self.session.scalar(
            select(func.max(TradingCalendar.trade_date)).where(
                TradingCalendar.exchange_code == exchange,
                TradingCalendar.trade_date < trading_day,
                TradingCalendar.is_trading_day.is_(True),
            )
        )
        windows: list[SessionWindow] = []
        for template in templates:
            is_night = template.start_time >= time(18)
            if is_night and prior is None:
                raise InfrastructureError("PREVIOUS_TRADING_DAY_MISSING")
            base = prior if is_night else trading_day
            assert base is not None
            local_start = datetime.combine(base, template.start_time, tzinfo=SHANGHAI)
            end_day = base
            if template.crosses_midnight or template.end_time <= template.start_time:
                end_day += timedelta(days=1)
            local_end = datetime.combine(end_day, template.end_time, tzinfo=SHANGHAI)
            windows.append(SessionWindow(local_start, local_end))
        windows.sort(key=lambda item: item.start)
        return tuple(windows)


class RQDataMarketAdapter:
    """Single fixed RQData adapter for bars and current metadata facts."""

    def __init__(self, *, session: Session, client: Any | None = None) -> None:
        self.session = session
        self._client = client

    @property
    def client(self) -> Any:
        """Initialize rqdatac only when an apply path actually needs provider data."""
        if self._client is None:
            self._client = _RqdatacClient()
        return self._client

    def fetch(self, key: DatasetKey, expected: tuple[datetime, ...]) -> BarBatch:
        if not expected:
            raise InfrastructureError("PROVIDER_WINDOW_EMPTY")
        order_book_id = (
            f"{key.symbol.upper()}88"
            if key.kind is DatasetKind.CONTINUOUS
            else key.series_or_contract
        )
        frame = self.client.price(
            order_book_id,
            min(expected).date(),
            max(expected).date(),
            key.frequency.value,
        )
        rows = _records(frame)
        expected_by_day: dict[date, list[datetime]] = {}
        for value in expected:
            expected_by_day.setdefault(value.astimezone(SHANGHAI).date(), []).append(value)
        bars: list[CanonicalBar] = []
        for index, row in enumerate(rows):
            trading_day = _row_date(row)
            if key.frequency in {BarFrequency.D1, BarFrequency.W1}:
                candidates = expected_by_day.get(trading_day)
                if not candidates and key.frequency is BarFrequency.W1 and index < len(expected):
                    candidates = [expected[index]]
                if not candidates:
                    continue
                bar_end = candidates[-1]
            else:
                bar_end = _row_datetime(row)
                if bar_end not in expected:
                    continue
            bars.append(_canonical_bar(row, bar_end, trading_day))
        bars.sort(key=lambda item: item.bar_end)
        digest_payload = [
            {field: str(value) for field, value in bar.as_record().items()} for bar in bars
        ]
        digest = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return BarBatch(tuple(bars), digest, "rqdata")

    def fetch_metadata(
        self,
        products: tuple[str, ...],
        through: date,
        starts: Mapping[str, date],
    ) -> MetadataSnapshot:
        requested_starts: dict[str, date] = {}
        for symbol in products:
            floor = starts[symbol]
            current = self.session.scalar(
                select(func.max(MainContractMap.trade_date)).where(
                    MainContractMap.symbol == symbol
                )
            )
            refresh_start = max(floor, current - timedelta(days=14)) if current else floor
            exchange = self.session.scalar(
                select(Instrument.exchange_code).where(Instrument.symbol == symbol)
            )
            if exchange is not None:
                calendar_days = tuple(self.session.scalars(
                    select(TradingCalendar.trade_date).where(
                        TradingCalendar.exchange_code == exchange,
                        TradingCalendar.trade_date >= floor,
                        TradingCalendar.trade_date <= through,
                        TradingCalendar.is_trading_day.is_(True),
                    ).order_by(TradingCalendar.trade_date)
                ))
                mapped_days = set(self.session.scalars(
                    select(MainContractMap.trade_date).where(
                        MainContractMap.symbol == symbol,
                        MainContractMap.trade_date >= floor,
                        MainContractMap.trade_date <= through,
                    )
                ))
                missing_map = next((day for day in calendar_days if day not in mapped_days), None)
                if missing_map is not None:
                    refresh_start = min(refresh_start, missing_map)
            missing_spec = self.session.scalar(
                select(func.min(MainContractMap.trade_date)).where(
                    MainContractMap.symbol == symbol,
                    MainContractMap.trade_date >= floor,
                    MainContractMap.trade_date <= through,
                    ~exists().where(
                        ContractSpec.contract_code == MainContractMap.contract_code,
                        ContractSpec.trade_date == MainContractMap.trade_date,
                    ),
                )
            )
            if missing_spec is not None:
                refresh_start = min(refresh_start, missing_spec)
            requested_starts[symbol] = refresh_start
        return self.client.metadata_snapshot(products, through, requested_starts)


class _RqdatacClient:
    def __init__(self) -> None:
        load_project_env()
        try:
            import rqdatac  # type: ignore[import-not-found]
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
        return self.api.get_price(
            order_book_id,
            start_date=start,
            end_date=end,
            frequency=frequency,
            adjust_type="none",
        )

    def metadata_snapshot(
        self,
        products: tuple[str, ...],
        through: date,
        starts: Mapping[str, date],
    ) -> MetadataSnapshot:
        frame = _frame(self.api.all_instruments(type="Future"))
        product_set = {item.upper() for item in products}
        if "underlying_symbol" not in frame.columns:
            raise InfrastructureError("RQDATA_INSTRUMENT_SCHEMA_INVALID")
        frame = frame[frame["underlying_symbol"].astype(str).str.upper().isin(product_set)]
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
                    "contract_multiplier": _optional_int(row.get("contract_multiplier")),
                    "listed_date": listed,
                    "maturity_date": _optional_date(row.get("maturity_date")),
                    "trading_hours": _optional_text(row.get("trading_hours")),
                    "provider": "rqdata",
                }
            )
        # Fetch one week past the bar watermark so a holiday-short ISO week can
        # still be proven complete without storing a second calendar watermark.
        earliest = min(starts.values())
        calendar_end = through + timedelta(days=7)
        trading_dates = tuple(
            pd.Timestamp(item).date()
            for item in self.api.get_trading_dates(start_date=earliest, end_date=calendar_end)
        )
        sessions = _session_rows(contracts, starts)
        night_exchanges = {
            str(row["exchange_code"])
            for row in sessions
            if (
                isinstance(row["start_time"], time)
                and row["start_time"] >= time(18)
            )
            or bool(row["crosses_midnight"])
        }
        calendars = tuple(
            {
                "exchange_code": exchange,
                "trade_date": day,
                "is_trading_day": True,
                "has_night_session": exchange in night_exchanges,
                "provider": "rqdata",
            }
            for exchange in exchanges
            for day in trading_dates
        )
        main_contracts: list[tuple[str, date, str]] = []
        for symbol in products:
            values = _frame(
                self.api.futures.get_dominant(
                    symbol.upper(), start_date=starts[symbol], end_date=through, rank=1
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
        contract_multipliers = {
            str(values["contract_code"]): Decimal(str(values["contract_multiplier"]))
            for values in contracts
            if values.get("contract_multiplier") is not None
        }
        specs = self._contract_specs(
            main_contracts,
            symbol_exchanges,
            contract_multipliers,
        )
        return MetadataSnapshot(
            exchanges=tuple(exchanges.values()),
            instruments=tuple(instruments.values()),
            contracts=tuple(contracts),
            calendars=calendars,
            sessions=sessions,
            main_contracts=tuple(main_contracts),
            contract_specs=specs,
        )

    def _contract_specs(
        self,
        mappings: list[tuple[str, date, str]],
        symbol_exchanges: dict[str, str],
        contract_multipliers: Mapping[str, Decimal],
    ) -> tuple[dict[str, object], ...]:
        result = []
        by_contract: dict[str, list[tuple[str, date]]] = {}
        for symbol, day, contract in mappings:
            by_contract.setdefault(contract, []).append((symbol, day))
        for contract, facts in by_contract.items():
            start, end = min(day for _, day in facts), max(day for _, day in facts)
            parameters = _frame(
                self.api.futures.get_trading_parameters(
                    contract, start_date=start, end_date=end
                )
            )
            rows_by_day = {_row_date(row): row for row in parameters.to_dict("records")}
            tick = self.api.get_tick_size(contract)
            multiplier = contract_multipliers.get(contract)
            for symbol, day in facts:
                row = rows_by_day.get(day, {})
                exchange = symbol_exchanges.get(symbol)
                if exchange is None or tick is None or multiplier is None:
                    raise InfrastructureError("RQDATA_CONTRACT_SPEC_INCOMPLETE")
                result.append(
                    {
                        "contract_code": contract,
                        "symbol": symbol,
                        "exchange_code": exchange,
                        "trade_date": day,
                        "price_tick": Decimal(str(tick)),
                        "contract_multiplier": Decimal(str(multiplier)),
                        "long_margin_rate": _optional_decimal(row.get("long_margin_ratio")),
                        "short_margin_rate": _optional_decimal(row.get("short_margin_ratio")),
                        "open_fee": _optional_decimal(row.get("open_commission")),
                        "close_fee": _optional_decimal(row.get("close_commission")),
                        "close_today_fee": _optional_decimal(
                            row.get("close_commission_today", row.get("close_today_commission"))
                        ),
                        "fee_type": _optional_text(row.get("commission_type")),
                    }
                )
        return tuple(result)


def _load_product_starts(path: Path) -> dict[str, date]:
    if not path.is_file() or path.is_symlink():
        raise InfrastructureError("PRODUCT_WINDOW_STARTS_INVALID")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle)
        result = {
            str(row["product"]).strip().lower(): date.fromisoformat(row["window_start"])
            for row in rows
        }
    if not result:
        raise InfrastructureError("PRODUCT_WINDOW_STARTS_INVALID")
    return result


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def _minutes(window: SessionWindow) -> int:
    return int((window.end - window.start).total_seconds() // 60)


def _records(value: Any) -> tuple[dict[str, Any], ...]:
    return tuple(_frame(value).to_dict("records"))


def _frame(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        result = value.copy()
        if not isinstance(result.index, pd.RangeIndex):
            result = result.reset_index()
        return result
    if isinstance(value, pd.Series):
        return value.reset_index()
    return pd.DataFrame(value)


def _row_date(row: dict[str, Any]) -> date:
    value = _row_value(row, "trading_date", "trade_date", "date", "index")
    parsed = pd.Timestamp(value)
    if pd.isna(parsed):
        raise InfrastructureError("RQDATA_TRADING_DAY_INVALID")
    return parsed.date()


def _row_datetime(row: dict[str, Any]) -> datetime:
    parsed = pd.Timestamp(_row_value(row, "datetime", "index"))
    if pd.isna(parsed):
        raise InfrastructureError("RQDATA_BAR_END_INVALID")
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize(SHANGHAI)
    return parsed.tz_convert(UTC).to_pydatetime()


def _canonical_bar(row: dict[str, Any], bar_end: datetime, trading_day: date) -> CanonicalBar:
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=trading_day,
        open=_decimal(row, "open"),
        high=_decimal(row, "high"),
        low=_decimal(row, "low"),
        close=_decimal(row, "close"),
        volume=_decimal(row, "volume"),
        turnover=_optional_decimal(_row_value(row, "turnover", "total_turnover", "amount", required=False)),
        open_interest=_optional_decimal(
            _row_value(row, "open_interest", "open_oi", "close_oi", required=False)
        ),
    )


def _decimal(row: dict[str, Any], field: str) -> Decimal:
    value = _optional_decimal(_row_value(row, field))
    if value is None:
        raise InfrastructureError("RQDATA_DECIMAL_MISSING")
    return value


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise InfrastructureError("RQDATA_DECIMAL_INVALID") from exc


def _row_value(row: dict[str, Any], *fields: Any, required: bool = True) -> Any:
    for field in fields:
        if field in row and row[field] is not None:
            return row[field]
    if required:
        raise InfrastructureError("RQDATA_FIELD_MISSING")
    return None


def _row_text(row: dict[str, Any], *fields: Any) -> str:
    value = _row_value(row, *fields)
    if not isinstance(value, str) or not value.strip():
        raise InfrastructureError("RQDATA_TEXT_INVALID")
    return value.strip()


def _optional_date(value: Any) -> date | None:
    if value is None or pd.isna(value):
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


def _session_rows(
    contracts: list[dict[str, object]],
    starts: Mapping[str, date],
) -> tuple[dict[str, object], ...]:
    identities: dict[tuple[object, ...], dict[str, object]] = {}
    for contract in contracts:
        raw = _optional_text(contract.get("trading_hours"))
        if raw is None:
            continue
        for index, match in enumerate(_SESSION.finditer(raw), start=1):
            start_time = time.fromisoformat(match.group("start"))
            end_time = time.fromisoformat(match.group("end"))
            row = {
                "exchange_code": contract["exchange_code"],
                "instrument_symbol": contract["instrument_symbol"],
                "session_name": f"session_{index}",
                "start_time": start_time,
                "end_time": end_time,
                "effective_from": starts[str(contract["instrument_symbol"])],
                "effective_to": None,
                "crosses_midnight": end_time <= start_time,
                "is_active": True,
                "provider": "rqdata",
            }
            identity = (
                row["exchange_code"],
                row["instrument_symbol"],
                start_time,
                end_time,
                row["effective_from"],
            )
            identities[identity] = row
    if not identities:
        raise InfrastructureError("RQDATA_TRADING_SESSIONS_MISSING")
    return tuple(identities.values())
