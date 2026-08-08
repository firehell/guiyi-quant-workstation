from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import (
    Contract,
    Exchange,
    FeeMarginRule,
    FuturesBasis,
    FuturesContinuousContractMap,
    FuturesContractUniverse,
    FuturesExFactor,
    FuturesMemberRank,
    FuturesRollYield,
    FuturesTradingParameter,
    FuturesWarehouseStock,
    Instrument,
    MainContractMap,
    TradingCalendar,
    TradingSession,
)
from app.services.futures_contract_utils import (
    is_synthetic_futures_contract,
    is_valid_listed_date,
    resolve_instrument_display_name,
    should_update_instrument_name,
)
from app.services.rqdata_ingest.db import IngestRecorder, as_date, as_decimal, as_int, row_payload, upsert_one
from app.services.rqdata_ingest.parquet import write_parquet_atomic
from app.services.rqdata_ingest.quality import validate_frame


PROVIDER = "rqdata"
DATA_VERSION = "rqdata_structured_v1"


@dataclass
class IngestResult:
    rows: int
    files: int


def _value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and not pd.isna(row[name]):
            return row[name]
    return None


DATE_FIELDS = ("date", "trade_date", "trading_date", "datetime", "index", "ex_date")


def _date_value(row: dict[str, Any]) -> Any:
    return _value(row, *DATE_FIELDS)


def _symbol(value: Any) -> str:
    return str(value or "").lower()


def _contract(value: Any) -> str:
    return str(value or "").upper()


def _contract_from_record(record: dict[str, Any], *names: str) -> str:
    value = _value(record, *names, "contract", "order_book_id", "dominant", "symbol")
    if value is None:
        for item in record.values():
            if isinstance(item, str) and item:
                value = item
                break
    return _contract(value)


def _clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    return df.copy().where(pd.notna(df), None)


def _instrument_for_product(session: Session, product: str) -> Instrument | None:
    for pending in session.new:
        if isinstance(pending, Instrument) and pending.symbol == product:
            return pending
    return session.scalar(select(Instrument).where(Instrument.symbol == product))


def _resolve_calendar_exchanges(
    session: Session, products: list[str] | None
) -> tuple[str, ...]:
    """Actual exchange codes for calendar materialization (never CNFE)."""
    query = select(Instrument.exchange_code).where(Instrument.exchange_code.is_not(None))
    if products:
        allowed = {item.strip().lower() for item in products if item.strip()}
        query = query.where(Instrument.symbol.in_(sorted(allowed)))
    codes = {
        str(code).strip().upper()
        for code in session.scalars(query).all()
        if code and str(code).strip().upper() not in {"", "CNFE", "UNKNOWN"}
    }
    return tuple(sorted(codes))


def _exchange_has_night_session_template(session: Session, exchange_code: str) -> bool:
    """Evidence from TradingSession templates: evening/overnight segments imply nights."""
    rows = session.scalars(
        select(TradingSession).where(
            TradingSession.exchange_code == exchange_code,
            TradingSession.is_active.is_(True),
        )
    ).all()
    for row in rows:
        if bool(getattr(row, "crosses_midnight", False)):
            return True
        start_time = getattr(row, "start_time", None)
        if start_time is not None and getattr(start_time, "hour", 0) >= 20:
            return True
    return False


def _normalize_session_clock(raw: str) -> Any:
    """Normalize RQData :01/:31 opens to wall-clock session starts used by readers."""
    value = pd.to_datetime(str(raw).strip()).time()
    if value.minute in {1, 31} and value.second == 0:
        # 09:01→09:00, 10:31→10:30, 21:01→21:00, 13:31→13:30
        minute = 0 if value.minute == 1 else 30
        from datetime import time as time_cls

        return time_cls(hour=value.hour, minute=minute)
    return value


def _parse_instrument_trading_hours(raw: str) -> tuple[tuple[str, Any, Any], ...]:
    """Parse RQData instrument trading_hours into named session segments."""
    segments: list[tuple[str, Any, Any]] = []
    am_index = 0
    night_index = 0
    for part in str(raw or "").split(","):
        token = part.strip()
        if not token or "-" not in token:
            continue
        start_raw, end_raw = token.split("-", 1)
        start = _normalize_session_clock(start_raw)
        end = _normalize_session_clock(end_raw)
        crosses = end < start
        if start.hour >= 20 or crosses:
            night_index += 1
            name = "night" if night_index == 1 else f"night_{night_index}"
        elif start.hour < 12:
            am_index += 1
            name = f"day_am_{am_index}"
        else:
            name = "day_pm" if not any(item[0] == "day_pm" for item in segments) else f"day_pm_{len(segments)+1}"
        segments.append((name, start, end))
    return tuple(segments)


def _with_date_column(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "date" in df.columns:
        return df
    for column in DATE_FIELDS:
        if column in df.columns:
            result = df.copy()
            result["date"] = pd.to_datetime(result[column], errors="coerce").dt.date
            return result
    return df


def _start_end_from_frame(df: pd.DataFrame, start_date: date, end_date: date) -> tuple[date, date]:
    if df.empty:
        return start_date, end_date
    date_columns = [column for column in DATE_FIELDS if column in df.columns]
    if not date_columns:
        return start_date, end_date
    values = pd.to_datetime(df[date_columns[0]], errors="coerce").dropna()
    if values.empty:
        return start_date, end_date
    return values.min().date(), values.max().date()


class BaseIngestor:
    data_type = "rqdata_structured"

    def __init__(self, session: Session, client: Any, project_root: Path) -> None:
        self.session = session
        self.client = client
        self.project_root = project_root
        self.recorder = IngestRecorder(session=session, project_root=project_root)

    def _raw_path(self, *parts: str) -> Path:
        return self.project_root / "data" / "raw" / "rqdata" / Path(*parts)

    def _record_raw_frame(
        self,
        *,
        df: pd.DataFrame,
        path: Path,
        data_type: str,
        quality_required: list[str],
        duplicate_keys: list[str] | None,
        start_date: date,
        end_date: date,
        instrument_symbol: str | None = None,
        contract_code: str | None = None,
        period: str | None = None,
    ) -> None:
        frame = _with_date_column(_clean_frame(df))
        task = self.recorder.start_task(
            data_type=data_type,
            start_date=start_date,
            end_date=end_date,
            instrument_symbol=instrument_symbol,
            contract_code=contract_code,
            period=period,
        )
        try:
            output_path = write_parquet_atomic(frame, path)
            quality = validate_frame(frame, quality_required, duplicate_keys)
            frame_start, frame_end = _start_end_from_frame(frame, start_date, end_date)
            self.recorder.record_file(
                task=task,
                path=output_path,
                data_type=data_type,
                row_count=len(frame),
                data_version=DATA_VERSION,
                quality=quality,
                start_date=frame_start,
                end_date=frame_end,
                instrument_symbol=instrument_symbol,
                contract_code=contract_code,
                period=period,
            )
            self.recorder.finish_task(task, row_count=len(frame), file_path=output_path)
        except Exception as exc:
            self.recorder.finish_task(task, row_count=0, file_path=None, status="failed", error=str(exc))
            raise


class CatalogIngestor(BaseIngestor):
    data_type = "futures_contracts"

    def run(self, start_date: date, end_date: date, products: list[str] | None = None) -> IngestResult:
        contracts = _clean_frame(self.client.all_future_instruments())
        if products:
            allowed = {item.lower() for item in products}
            contracts = contracts[contracts.apply(lambda row: _symbol(_value(row, "underlying_symbol", "product")) in allowed, axis=1)]
        self._upsert_contract_catalog(contracts)
        session_rows = self._upsert_sessions(contracts)
        self._upsert_calendar(start_date, end_date, products=products)
        self._record_raw_frame(
            df=contracts,
            path=self._raw_path("catalog", "futures_contracts.parquet"),
            data_type=self.data_type,
            quality_required=["order_book_id"],
            duplicate_keys=["order_book_id"] if "order_book_id" in contracts.columns else None,
            start_date=start_date,
            end_date=end_date,
        )
        return IngestResult(rows=len(contracts) + len(self.client.trading_dates(start_date, end_date)) + session_rows, files=1)

    def run_calendar(
        self,
        start_date: date,
        end_date: date,
        products: list[str] | None = None,
    ) -> IngestResult:
        self._upsert_calendar(start_date, end_date, products=products)
        return IngestResult(
            rows=len(self.client.trading_dates(start_date, end_date)),
            files=0,
        )

    def run_sessions(
        self,
        start_date: date,
        end_date: date,
        products: list[str] | None = None,
    ) -> IngestResult:
        del start_date, end_date  # session templates are product-scoped, not dated
        contracts = _clean_frame(self.client.all_future_instruments())
        if products:
            allowed = {item.lower() for item in products}
            contracts = contracts[
                contracts.apply(
                    lambda row: _symbol(_value(row, "underlying_symbol", "product"))
                    in allowed,
                    axis=1,
                )
            ]
        session_rows = self._upsert_sessions(contracts)
        return IngestResult(rows=session_rows, files=0)

    def _upsert_contract_catalog(self, contracts: pd.DataFrame) -> None:
        for record in contracts.to_dict("records"):
            product = _symbol(_value(record, "underlying_symbol", "product", "underlying_order_book_id"))
            exchange_code = str(_value(record, "exchange", "exchange_code") or "UNKNOWN")
            name = str(_value(record, "symbol", "name") or product)
            contract_code = _contract(_value(record, "order_book_id", "contract", "contract_code"))
            synthetic = bool(contract_code) and is_synthetic_futures_contract(contract_code)
            listed_date = _value(record, "listed_date", "listed")

            upsert_one(
                self.session,
                Exchange,
                {"code": exchange_code},
                {"name": exchange_code, "country": "CN", "timezone": "Asia/Shanghai", "is_active": True},
            )
            existing = _instrument_for_product(self.session, product)
            if not synthetic and is_valid_listed_date(listed_date):
                resolved_name = resolve_instrument_display_name(
                    product,
                    name,
                    existing_name=existing.name if existing else None,
                )
                if existing is None or should_update_instrument_name(resolved_name, existing.name, product):
                    upsert_one(
                        self.session,
                        Instrument,
                        {"symbol": product},
                        {
                            "name": resolved_name,
                            "exchange_code": exchange_code,
                            "sector": None,
                            "category": "future",
                            "is_active": True,
                            "remark": "synced from rqdata",
                        },
                    )
            elif existing is None:
                upsert_one(
                    self.session,
                    Instrument,
                    {"symbol": product},
                    {
                        "name": product.upper(),
                        "exchange_code": exchange_code,
                        "sector": None,
                        "category": "future",
                        "is_active": True,
                        "remark": "synced from rqdata",
                    },
                )
            if not contract_code:
                continue
            upsert_one(
                self.session,
                Contract,
                {"contract_code": contract_code},
                {
                    "instrument_symbol": product,
                    "exchange_code": exchange_code,
                    "name": name,
                    "contract_month": str(_value(record, "contract_month") or "") or None,
                    "contract_multiplier": as_int(_value(record, "contract_multiplier", "multiplier")),
                    "trading_code": _value(record, "trading_code"),
                    "maturity_date": as_date(_value(record, "maturity_date")),
                    "start_delivery_date": as_date(_value(record, "start_delivery_date")),
                    "end_delivery_date": as_date(_value(record, "end_delivery_date")),
                    "product": product,
                    "trading_hours": _value(record, "trading_hours"),
                    "listed_date": as_date(_value(record, "listed_date", "listed")),
                    "expired_date": as_date(_value(record, "de_listed_date", "expired_date", "delisted_date")),
                    "status": "active",
                    "raw_symbol": contract_code,
                    "provider": PROVIDER,
                },
            )

    def _upsert_calendar(
        self,
        start_date: date,
        end_date: date,
        products: list[str] | None = None,
    ) -> None:
        trading_dates = set(self.client.trading_dates(start_date, end_date))
        exchanges = _resolve_calendar_exchanges(self.session, products)
        night_by_exchange = {
            exchange: _exchange_has_night_session_template(self.session, exchange)
            for exchange in exchanges
        }
        for exchange_code in exchanges:
            current = start_date
            while current <= end_date:
                existing = self.session.scalar(
                    select(TradingCalendar).where(
                        TradingCalendar.exchange_code == exchange_code,
                        TradingCalendar.trade_date == current,
                    )
                )
                night_flag = night_by_exchange[exchange_code]
                if existing is not None and existing.has_night_session and not night_flag:
                    # Preserve historically observed night flags when templates are incomplete.
                    night_flag = True
                upsert_one(
                    self.session,
                    TradingCalendar,
                    {"exchange_code": exchange_code, "trade_date": current},
                    {
                        "is_trading_day": current in trading_dates,
                        "has_night_session": night_flag,
                        "provider": PROVIDER,
                        "remark": "rqdata trading calendar materialized by exchange",
                    },
                )
                current = date.fromordinal(current.toordinal() + 1)

    def _upsert_sessions(self, contracts: pd.DataFrame) -> int:
        """Materialize product session templates from instrument trading_hours.

        RQData ``get_trading_periods`` expects concrete order_book_ids and cannot
        build product templates. Instrument catalog rows already carry
        ``trading_hours`` + ``exchange``; parse those and resolve identity from
        Instrument when needed. Never invent CNFE rows.
        """
        written = 0
        seen_products: set[str] = set()
        for record in contracts.to_dict("records"):
            product = _symbol(_value(record, "underlying_symbol", "product"))
            if not product or product in seen_products:
                continue
            hours_raw = _value(record, "trading_hours")
            exchange_code = str(_value(record, "exchange", "exchange_code") or "").strip().upper()
            if not exchange_code or exchange_code == "CNFE":
                instrument = _instrument_for_product(self.session, product)
                if instrument is not None and instrument.exchange_code:
                    exchange_code = str(instrument.exchange_code).strip().upper()
            if not exchange_code or exchange_code == "CNFE":
                continue
            segments = _parse_instrument_trading_hours(str(hours_raw or ""))
            if not segments:
                continue
            seen_products.add(product)
            upsert_one(
                self.session,
                Exchange,
                {"code": exchange_code},
                {
                    "name": exchange_code,
                    "country": "CN",
                    "timezone": "Asia/Shanghai",
                    "is_active": True,
                },
            )
            for session_name, start, end in segments:
                upsert_one(
                    self.session,
                    TradingSession,
                    {
                        "exchange_code": exchange_code,
                        "instrument_symbol": product,
                        "session_name": session_name,
                    },
                    {
                        "start_time": start,
                        "end_time": end,
                        "crosses_midnight": end < start,
                        "is_active": True,
                        "provider": PROVIDER,
                    },
                )
                written += 1
        return written


class MainMappingIngestor(BaseIngestor):
    data_type = "main_contract_mapping"

    def run(self, products: list[str], start_date: date, end_date: date, ranks: list[int]) -> IngestResult:
        total_rows = 0
        files = 0
        for product in products:
            product_key = _symbol(product)
            frames = []
            for rank in ranks:
                frame = _clean_frame(self.client.dominant_contracts(product, start_date, end_date, rank))
                frame["rank"] = rank
                frame["product"] = product_key
                frames.append(frame)
                self._upsert_mapping(product_key, rank, frame)
            continuous = _clean_frame(self.client.continuous_contracts(product, start_date, end_date))
            if not continuous.empty:
                continuous["product"] = product_key
                continuous["rank"] = 0
                frames.append(continuous)
            output = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            self._record_raw_frame(
                df=output,
                path=self._raw_path("main_contract_mapping", f"product={product_key}", f"{product_key}_{start_date:%Y}_{end_date:%Y}.parquet"),
                data_type=self.data_type,
                quality_required=["product", "rank"],
                duplicate_keys=None,
                start_date=start_date,
                end_date=end_date,
                instrument_symbol=product_key,
            )
            total_rows += len(output)
            files += 1
        return IngestResult(rows=total_rows, files=files)

    def _upsert_mapping(self, product: str, rank: int, frame: pd.DataFrame) -> None:
        for record in frame.to_dict("records"):
            trade_date = as_date(_date_value(record))
            contract_code = _contract_from_record(record)
            if trade_date is None or not contract_code:
                continue
            upsert_one(
                self.session,
                MainContractMap,
                {
                    "instrument_symbol": product,
                    "trade_date": trade_date,
                    "rank": rank,
                    "rule": "volume_open_interest",
                    "provider": PROVIDER,
                    "data_version": DATA_VERSION,
                },
                {"contract_code": contract_code, "raw_payload": row_payload(record)},
            )


class ExFactorIngestor(BaseIngestor):
    data_type = "futures_ex_factor"

    def run(self, products: list[str], start_date: date, end_date: date) -> IngestResult:
        total_rows = 0
        for product in products:
            product_key = _symbol(product)
            frame = _clean_frame(self.client.ex_factor(product, start_date, end_date))
            frame["product"] = product_key
            for record in frame.to_dict("records"):
                trade_date = as_date(_date_value(record))
                if trade_date is None:
                    continue
                upsert_one(
                    self.session,
                    FuturesExFactor,
                    {
                        "instrument_symbol": product_key,
                        "trade_date": trade_date,
                        "contract_code": _contract(_value(record, "contract", "order_book_id")) or None,
                        "provider": PROVIDER,
                        "data_version": DATA_VERSION,
                    },
                    {
                        "prev_close_spread": as_decimal(_value(record, "prev_close_spread", "ex_factor")),
                        "open_spread": as_decimal(_value(record, "open_spread")),
                        "prev_close_ratio": as_decimal(_value(record, "prev_close_ratio", "ex_cum_factor")),
                        "open_ratio": as_decimal(_value(record, "open_ratio")),
                        "raw_payload": row_payload(record),
                    },
                )
            self._record_raw_frame(
                df=frame,
                path=self._raw_path("futures_ex_factor", f"product={product_key}", f"{product_key}_{start_date:%Y}_{end_date:%Y}.parquet"),
                data_type=self.data_type,
                quality_required=["product"],
                duplicate_keys=None,
                start_date=start_date,
                end_date=end_date,
                instrument_symbol=product_key,
            )
            total_rows += len(frame)
        return IngestResult(rows=total_rows, files=len(products))


class ContractUniverseIngestor(BaseIngestor):
    data_type = "contract_universe"

    def run(self, products: list[str], start_date: date, end_date: date) -> IngestResult:
        total_rows = 0
        files = 0
        trading_dates = self.client.trading_dates(start_date, end_date)
        for product in products:
            product_key = _symbol(product)
            frames = []
            for trade_date in trading_dates:
                frame = _clean_frame(self.client.listed_contracts(product, trade_date))
                frame["product"] = product_key
                frame["date"] = trade_date
                frames.append(frame)
                self._upsert_universe(product_key, trade_date, frame)
            output = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["product", "date"])
            self._record_raw_frame(
                df=output,
                path=self._raw_path("contract_universe", f"product={product_key}", f"{product_key}_{start_date:%Y}_{end_date:%Y}.parquet"),
                data_type=self.data_type,
                quality_required=["product", "date"],
                duplicate_keys=None,
                start_date=start_date,
                end_date=end_date,
                instrument_symbol=product_key,
            )
            total_rows += len(output)
            files += 1
        return IngestResult(rows=total_rows, files=files)

    def _upsert_universe(self, product: str, trade_date: date, frame: pd.DataFrame) -> None:
        for sort_order, record in enumerate(frame.to_dict("records")):
            contract_code = _contract_from_record(record)
            if not contract_code:
                continue
            upsert_one(
                self.session,
                FuturesContractUniverse,
                {
                    "instrument_symbol": product,
                    "trade_date": trade_date,
                    "contract_code": contract_code,
                    "provider": PROVIDER,
                    "data_version": DATA_VERSION,
                },
                {"sort_order": sort_order, "raw_payload": row_payload(record)},
            )


class ContinuousContractIngestor(BaseIngestor):
    data_type = "continuous_contracts"

    def run(self, products: list[str], start_date: date, end_date: date, continuous_types: list[str]) -> IngestResult:
        rows = 0
        files = 0
        for product in products:
            product_key = _symbol(product)
            frames = []
            for continuous_type in continuous_types:
                frame = _clean_frame(self.client.continuous_contract_by_type(product, start_date, end_date, continuous_type))
                frame["product"] = product_key
                frame["continuous_type"] = continuous_type
                frames.append(frame)
                self._upsert_continuous(product_key, continuous_type, frame)
            output = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["product", "continuous_type"])
            self._record_raw_frame(
                df=output,
                path=self._raw_path("continuous_contracts", f"product={product_key}", f"{product_key}_{start_date:%Y}_{end_date:%Y}.parquet"),
                data_type=self.data_type,
                quality_required=["product", "continuous_type"],
                duplicate_keys=None,
                start_date=start_date,
                end_date=end_date,
                instrument_symbol=product_key,
            )
            rows += len(output)
            files += 1
        return IngestResult(rows=rows, files=files)

    def _upsert_continuous(self, product: str, continuous_type: str, frame: pd.DataFrame) -> None:
        for record in frame.to_dict("records"):
            trade_date = as_date(_date_value(record))
            contract_code = _contract_from_record(record, continuous_type)
            if trade_date is None or not contract_code:
                continue
            upsert_one(
                self.session,
                FuturesContinuousContractMap,
                {
                    "instrument_symbol": product,
                    "trade_date": trade_date,
                    "continuous_type": continuous_type,
                    "provider": PROVIDER,
                    "data_version": DATA_VERSION,
                },
                {"contract_code": contract_code, "raw_payload": row_payload(record)},
            )


class TradingParameterIngestor(BaseIngestor):
    data_type = "trading_parameters"

    def run(self, contracts: list[str], start_date: date, end_date: date) -> IngestResult:
        total_rows = 0
        for contract in contracts:
            frame = _clean_frame(self.client.trading_parameters(contract, start_date, end_date))
            frame["contract"] = contract
            contract_meta = self.session.scalar(select(Contract).where(Contract.contract_code == contract))
            contract_multiplier = None if contract_meta is None else contract_meta.contract_multiplier
            fallback_price_tick = self.client.price_tick(contract) if hasattr(self.client, "price_tick") else None
            for record in frame.to_dict("records"):
                trade_date = as_date(_date_value(record))
                if trade_date is None:
                    continue
                symbol = _symbol(_value(record, "product", "underlying_symbol")) or (contract_meta.instrument_symbol if contract_meta else None)
                exchange = str(_value(record, "exchange", "exchange_code") or (contract_meta.exchange_code if contract_meta else "UNKNOWN"))
                upsert_one(
                    self.session,
                    Exchange,
                    {"code": exchange},
                    {"name": exchange, "country": "CN", "timezone": "Asia/Shanghai", "is_active": True},
                )
                multiplier = as_int(_value(record, "contract_multiplier")) or contract_multiplier or self.client.contract_multiplier(contract)
                price_tick = as_decimal(_value(record, "price_tick", "tick_size")) or as_decimal(fallback_price_tick)
                upsert_one(
                    self.session,
                    FuturesTradingParameter,
                    {"contract_code": contract, "trade_date": trade_date, "provider": PROVIDER, "data_version": DATA_VERSION},
                    {
                        "instrument_symbol": symbol,
                        "exchange_code": exchange,
                        "long_margin_ratio": as_decimal(_value(record, "long_margin_ratio", "margin_rate")),
                        "short_margin_ratio": as_decimal(_value(record, "short_margin_ratio", "margin_rate")),
                        "open_commission": as_decimal(_value(record, "open_commission", "open_fee")),
                        "close_commission": as_decimal(_value(record, "close_commission", "close_fee")),
                        "close_today_commission": as_decimal(_value(record, "close_today_commission", "close_commission_today", "close_today_fee")),
                        "commission_type": _value(record, "commission_type", "fee_type"),
                        "price_tick": price_tick,
                        "contract_multiplier": multiplier,
                        "min_order_quantity": as_int(_value(record, "min_order_quantity", "min_volume")),
                        "max_order_quantity": as_int(_value(record, "max_order_quantity", "client_limit", "non_member_limit", "max_volume")),
                        "raw_payload": row_payload(record),
                    },
                )
                upsert_one(
                    self.session,
                    FeeMarginRule,
                    {
                        "provider": PROVIDER,
                        "exchange_code": exchange,
                        "contract_code": contract,
                        "effective_date": trade_date,
                    },
                    {
                        "instrument_symbol": symbol,
                        "price_tick": price_tick,
                        "volume_multiple": multiplier,
                        "margin_rate": as_decimal(_value(record, "short_margin_ratio", "long_margin_ratio", "min_margin_ratio", "margin_rate")),
                        "open_fee": as_decimal(_value(record, "open_commission", "open_fee")),
                        "close_fee": as_decimal(_value(record, "close_commission", "close_fee")),
                        "close_today_fee": as_decimal(_value(record, "close_today_commission", "close_commission_today", "close_today_fee")),
                        "fee_type": _value(record, "commission_type", "fee_type"),
                        "source": "rqdata_trading_parameters",
                    },
                )
            self._record_raw_frame(
                df=frame,
                path=self._raw_path("trading_parameters", f"contract={contract}", f"{contract}_{start_date:%Y}_{end_date:%Y}.parquet"),
                data_type=self.data_type,
                quality_required=["contract"],
                duplicate_keys=None,
                start_date=start_date,
                end_date=end_date,
                contract_code=contract,
            )
            total_rows += len(frame)
        return IngestResult(rows=total_rows, files=len(contracts))


class DailyBaselineIngestor(BaseIngestor):
    data_type = "daily_baseline"

    def run(self, contracts: list[str], start_date: date, end_date: date) -> IngestResult:
        total_rows = 0
        for contract in contracts:
            frame = _clean_frame(self.client.exchange_daily(contract, start_date, end_date))
            frame["contract"] = contract
            self._record_raw_frame(
                df=frame,
                path=self._raw_path("futures_daily_provider", f"contract={contract}", f"{contract}_{start_date:%Y}_{end_date:%Y}.parquet"),
                data_type=self.data_type,
                quality_required=["contract"],
                duplicate_keys=["date"] if "date" in frame.columns else None,
                start_date=start_date,
                end_date=end_date,
                contract_code=contract,
                period="1d",
            )
            total_rows += len(frame)
        return IngestResult(rows=total_rows, files=len(contracts))


class DominantDailyBaselineIngestor(BaseIngestor):
    data_type = "dominant_daily_baseline"

    def run(self, products: list[str], start_date: date, end_date: date) -> IngestResult:
        rows = 0
        files = 0
        for product in products:
            product_key = _symbol(product)
            frame = _clean_frame(self.client.dominant_daily_price(product, start_date, end_date))
            frame["product"] = product_key
            self._record_raw_frame(
                df=frame,
                path=self._raw_path("dominant_daily_baseline", f"product={product_key}", f"{product_key}_1d_{start_date:%Y%m%d}_{end_date:%Y%m%d}.parquet"),
                data_type=self.data_type,
                quality_required=["product", "dominant_id"],
                duplicate_keys=["date"] if "date" in frame.columns else None,
                start_date=start_date,
                end_date=end_date,
                instrument_symbol=product_key,
                period="1d",
            )
            rows += len(frame)
            files += 1
        return IngestResult(rows=rows, files=files)


class ResearchEnhancerIngestor(BaseIngestor):
    data_type = "research_enhancers"

    def run(self, products: list[str], contracts: list[str], start_date: date, end_date: date, include_basis: bool = False) -> IngestResult:
        rows = 0
        files = 0
        for product in products:
            product_key = _symbol(product)
            warehouse = _clean_frame(self.client.warehouse_stocks(product, start_date, end_date))
            warehouse["product"] = product_key
            self._upsert_warehouse(product_key, warehouse)
            self._record_raw_frame(
                df=warehouse,
                path=self._raw_path("warehouse_stocks", f"product={product_key}", f"{product_key}_{start_date:%Y}_{end_date:%Y}.parquet"),
                data_type="warehouse_stocks",
                quality_required=["product"],
                duplicate_keys=None,
                start_date=start_date,
                end_date=end_date,
                instrument_symbol=product_key,
            )
            roll = _clean_frame(self.client.roll_yield(product, start_date, end_date))
            roll["product"] = product_key
            self._upsert_roll_yield(product_key, roll)
            self._record_raw_frame(
                df=roll,
                path=self._raw_path("roll_yield", f"product={product_key}", f"{product_key}_{start_date:%Y}_{end_date:%Y}.parquet"),
                data_type="roll_yield",
                quality_required=["product"],
                duplicate_keys=None,
                start_date=start_date,
                end_date=end_date,
                instrument_symbol=product_key,
            )
            rows += len(warehouse) + len(roll)
            files += 2
        if not include_basis:
            return IngestResult(rows=rows, files=files)
        for contract in contracts:
            basis = _clean_frame(self.client.basis(contract, start_date, end_date))
            basis["contract"] = contract
            self._upsert_basis(contract, basis)
            self._record_raw_frame(
                df=basis,
                path=self._raw_path("basis", f"contract={contract}", f"{contract}_{start_date:%Y}_{end_date:%Y}.parquet"),
                data_type="basis",
                quality_required=["contract"],
                duplicate_keys=None,
                start_date=start_date,
                end_date=end_date,
                contract_code=contract,
            )
            rows += len(basis)
            files += 1
        return IngestResult(rows=rows, files=files)

    def _upsert_warehouse(self, product: str, frame: pd.DataFrame) -> None:
        for record in frame.to_dict("records"):
            trade_date = as_date(_date_value(record))
            if trade_date is None:
                continue
            upsert_one(
                self.session,
                FuturesWarehouseStock,
                {
                    "instrument_symbol": product,
                    "trade_date": trade_date,
                    "warehouse": str(_value(record, "warehouse", "warehouse_name") or ""),
                    "provider": PROVIDER,
                    "data_version": DATA_VERSION,
                },
                {"quantity": as_decimal(_value(record, "quantity", "volume", "on_warrant")), "unit": _value(record, "unit"), "raw_payload": row_payload(record)},
            )

    def _upsert_roll_yield(self, product: str, frame: pd.DataFrame) -> None:
        for record in frame.to_dict("records"):
            trade_date = as_date(_date_value(record))
            if trade_date is None:
                continue
            upsert_one(
                self.session,
                FuturesRollYield,
                {
                    "instrument_symbol": product,
                    "trade_date": trade_date,
                    "near_contract": _contract(_value(record, "near_contract")) or None,
                    "far_contract": _contract(_value(record, "far_contract")) or None,
                    "provider": PROVIDER,
                    "data_version": DATA_VERSION,
                },
                {"roll_yield": as_decimal(_value(record, "roll_yield", "yield")), "raw_payload": row_payload(record)},
            )

    def _upsert_basis(self, contract: str, frame: pd.DataFrame) -> None:
        for record in frame.to_dict("records"):
            trade_date = as_date(_date_value(record))
            if trade_date is None:
                continue
            upsert_one(
                self.session,
                FuturesBasis,
                {"contract_code": contract, "trade_date": trade_date, "provider": PROVIDER, "data_version": DATA_VERSION},
                {
                    "instrument_symbol": _symbol(_value(record, "product", "underlying_symbol")) or None,
                    "spot_price": as_decimal(_value(record, "spot_price", "spot")),
                    "futures_price": as_decimal(_value(record, "futures_price", "future_price", "close")),
                    "basis": as_decimal(_value(record, "basis")),
                    "raw_payload": row_payload(record),
                },
            )


class MemberRankIngestor(BaseIngestor):
    data_type = "member_rank"

    def run(self, products: list[str], start_date: date, end_date: date, rank_by: str = "volume") -> IngestResult:
        rows = 0
        files = 0
        for product in products:
            product_key = _symbol(product)
            frame = _with_date_column(_clean_frame(self.client.member_rank(product, start_date, end_date, rank_by=rank_by)))
            frame["product"] = product_key
            frame["rank_by"] = rank_by
            self._upsert_member_rank(product_key, rank_by, frame)
            self._record_raw_frame(
                df=frame,
                path=self._raw_path(
                    "member_ranks",
                    f"product={product_key}",
                    f"rank_by={rank_by}",
                    f"{product_key}_{rank_by}_{start_date:%Y%m%d}_{end_date:%Y%m%d}.parquet",
                ),
                data_type=self.data_type,
                quality_required=["product", "rank_by"],
                duplicate_keys=None,
                start_date=start_date,
                end_date=end_date,
                instrument_symbol=product_key,
            )
            rows += len(frame)
            files += 1
        return IngestResult(rows=rows, files=files)

    def _upsert_member_rank(self, product: str, rank_by: str, frame: pd.DataFrame) -> None:
        for record in frame.to_dict("records"):
            trade_date = as_date(_date_value(record))
            member_name = str(_value(record, "member_name") or "").strip()
            rank = as_int(_value(record, "rank"))
            if trade_date is None or not member_name or rank is None:
                continue
            upsert_one(
                self.session,
                FuturesMemberRank,
                {
                    "instrument_symbol": product,
                    "trade_date": trade_date,
                    "rank_by": rank_by,
                    "member_name": member_name,
                    "provider": PROVIDER,
                    "data_version": DATA_VERSION,
                },
                {
                    "rank": rank,
                    "volume": as_decimal(_value(record, "volume")),
                    "volume_change": as_decimal(_value(record, "volume_change")),
                    "commodity_id": _value(record, "commodity_id"),
                    "target_type": "product",
                    "raw_payload": row_payload(record),
                },
            )


class MarketSampleIngestor(BaseIngestor):
    data_type = "market_sample"

    def run(self, products: list[str], start_date: date, end_date: date, frequencies: list[str]) -> IngestResult:
        rows = 0
        files = 0
        for product in products:
            product_key = _symbol(product)
            for frequency in frequencies:
                frame = _clean_frame(self.client.main_price(product, start_date, end_date, frequency))
                frame["product"] = product_key
                frame["frequency"] = frequency
                self._record_raw_frame(
                    df=frame,
                    path=self._raw_path("market_samples", f"product={product_key}", f"frequency={frequency}", f"{product_key}_{frequency}_{start_date:%Y%m%d}_{end_date:%Y%m%d}.parquet"),
                    data_type=self.data_type,
                    quality_required=["product", "frequency"],
                    duplicate_keys=None,
                    start_date=start_date,
                    end_date=end_date,
                    instrument_symbol=product_key,
                    period=frequency,
                )
                rows += len(frame)
                files += 1
        return IngestResult(rows=rows, files=files)
