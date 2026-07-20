from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import TradingCalendar
from app.services.live_market_reader import LiveMarketReader
from app.services.market_data_reader import MarketDataReader
from app.services.profile_lineage import ProfileLineageResolver
from app.services.rqdata_ingest.parquet import sha256_file


class HistoricalLiveContextError(ValueError):
    """Fail-closed historical/live context contract violation."""


@dataclass(frozen=True)
class HistoricalLiveMerge:
    bars: list[dict[str, Any]]
    live_trigger: dict[str, Any]
    exact_duplicate_count: int


@dataclass(frozen=True)
class HistoricalLiveContext:
    status: str
    historical_bars: list[dict[str, Any]]
    live_bars: list[dict[str, Any]]
    merged_bars: list[dict[str, Any]]
    live_trigger: dict[str, Any]
    historical_context_file_id: int
    historical_context_data_version: str
    historical_context_hash: str
    historical_context_file_checksum: str
    historical_context_max_trading_day: date
    previous_trading_day: date
    exact_duplicate_count: int
    live_quality: dict[str, Any]


class HistoricalLiveContextResolver:
    def __init__(self, session: Session, *, project_root: Any) -> None:
        self.session = session
        self.project_root = project_root
        self.live_reader = LiveMarketReader(session)
        self.market_reader = MarketDataReader(session, project_root=project_root)

    def resolve(
        self,
        *,
        symbol: str,
        actual_contract: str,
        period: str,
        profile_id: str,
        provider: str | None,
        source_mode: str | None,
        limit: int,
    ) -> HistoricalLiveContext:
        lineage = ProfileLineageResolver(self.session, project_root=self.project_root).resolve(
            consumer="signal",
            symbol=symbol,
            contract=actual_contract,
            period=period,
            profile_id=profile_id,
            allow_warning_quality=False,
        )
        if lineage.blocked or lineage.market_file is None or lineage.market_data_file_id is None:
            reason = str(lineage.blocked_reason or "profile_binding_missing")
            raise HistoricalLiveContextError(f"historical_context_{reason}")
        market_file = lineage.market_file
        if market_file.quality_status != "passed" or market_file.data_role != "primary":
            raise HistoricalLiveContextError("historical_context_quality_blocked")
        if not market_file.checksum:
            raise HistoricalLiveContextError("historical_context_checksum_missing")
        raw_path = Path(market_file.file_path)
        physical_path = raw_path if raw_path.is_absolute() else Path(self.project_root) / raw_path
        if not physical_path.is_file() or sha256_file(physical_path) != market_file.checksum:
            raise HistoricalLiveContextError("historical_context_file_drift")

        live_response = self.live_reader.get_latest_confirmed_trading_day_bars(
            symbol=symbol,
            contract=actual_contract,
            period=period,
            provider=provider,
            source_mode=source_mode,
            limit=limit,
        )
        live_bars = [{**row, "context_source": "live"} for row in live_response.bars]
        if not live_bars:
            raise HistoricalLiveContextError("live_confirmed_bar_missing")
        live_trigger = live_bars[-1]
        if live_trigger.get("quality_status") != "passed" or not live_trigger.get("confirmed_at"):
            raise HistoricalLiveContextError("live_trigger_quality_blocked")
        live_trading_day = _date_value(live_trigger.get("trading_day"))
        previous_trading_day = self.session.scalar(
            select(TradingCalendar.trade_date)
            .where(
                TradingCalendar.exchange_code.in_(("DCE", "CNFE")),
                TradingCalendar.trade_date < live_trading_day,
                TradingCalendar.is_trading_day.is_(True),
            )
            .order_by(TradingCalendar.trade_date.desc())
        )
        if previous_trading_day is None:
            raise HistoricalLiveContextError("historical_context_calendar_missing")

        trigger_time = _datetime_value(live_trigger.get("datetime"))
        context_end = min(_naive(market_file.end_time), trigger_time)
        if context_end < _naive(market_file.start_time):
            raise HistoricalLiveContextError("historical_context_missing")
        try:
            historical_bars = self.market_reader.load_bars_from_market_file(
                market_data_file_id=market_file.id,
                symbol=symbol,
                contract=actual_contract,
                period=period,
                start=_naive(market_file.start_time),
                end=context_end,
                passed_only=True,
                expected_provider=market_file.provider,
                expected_data_role="primary",
                expected_quality_status="passed",
                expected_data_version=market_file.data_version,
                expected_checksum=market_file.checksum,
                limit=limit,
                tail=True,
            )
        except ValueError as exc:
            raise HistoricalLiveContextError("historical_context_file_invalid") from exc
        historical_bars = [{**row, "context_source": "historical"} for row in historical_bars]
        if not historical_bars:
            raise HistoricalLiveContextError("historical_context_missing")
        max_trading_day = max(_date_value(row.get("trading_day")) for row in historical_bars)
        if max_trading_day < previous_trading_day:
            raise HistoricalLiveContextError("historical_context_stale")

        merged = merge_historical_live_bars(
            historical_bars=historical_bars,
            live_bars=live_bars,
            actual_contract=actual_contract,
            period=period,
        )
        return HistoricalLiveContext(
            status="ready",
            historical_bars=historical_bars,
            live_bars=live_bars,
            merged_bars=merged.bars[-limit:],
            live_trigger=merged.live_trigger,
            historical_context_file_id=market_file.id,
            historical_context_data_version=str(lineage.data_version or market_file.data_version),
            historical_context_hash=historical_context_hash(historical_bars),
            historical_context_file_checksum=market_file.checksum,
            historical_context_max_trading_day=max_trading_day,
            previous_trading_day=previous_trading_day,
            exact_duplicate_count=merged.exact_duplicate_count,
            live_quality=live_response.quality.model_dump(),
        )


def historical_context_hash(bars: list[dict[str, Any]]) -> str:
    payload = [
        {
            "key": _bar_key(row, actual_contract=str(row.get("contract") or ""), period=str(row.get("period") or "")),
            "ohlcv": _ohlcv_signature(row),
        }
        for row in bars
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def merge_historical_live_bars(
    *,
    historical_bars: list[dict[str, Any]],
    live_bars: list[dict[str, Any]],
    actual_contract: str,
    period: str,
) -> HistoricalLiveMerge:
    if not live_bars:
        raise HistoricalLiveContextError("live_confirmed_bar_missing")

    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in historical_bars:
        key = _bar_key(row, actual_contract=actual_contract, period=period)
        merged[key] = dict(row)

    exact_duplicates = 0
    for row in live_bars:
        key = _bar_key(row, actual_contract=actual_contract, period=period)
        existing = merged.get(key)
        if existing is not None:
            if _ohlcv_signature(existing) != _ohlcv_signature(row):
                raise HistoricalLiveContextError("historical_live_bar_conflict")
            exact_duplicates += 1
            continue
        merged[key] = dict(row)

    ordered = [merged[key] for key in sorted(merged)]
    live_trigger = dict(live_bars[-1])
    if not ordered or _bar_key(ordered[-1], actual_contract=actual_contract, period=period) != _bar_key(
        live_trigger,
        actual_contract=actual_contract,
        period=period,
    ):
        raise HistoricalLiveContextError("live_trigger_not_latest_merged_bar")
    return HistoricalLiveMerge(
        bars=ordered,
        live_trigger=live_trigger,
        exact_duplicate_count=exact_duplicates,
    )


def _bar_key(row: dict[str, Any], *, actual_contract: str, period: str) -> tuple[str, str, str]:
    contract = str(row.get("contract") or actual_contract).upper()
    row_period = str(row.get("period") or period)
    if contract != actual_contract.upper() or row_period != period:
        raise HistoricalLiveContextError("historical_live_context_identity_mismatch")
    value = row.get("datetime") or row.get("time")
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        raise HistoricalLiveContextError("historical_live_context_datetime_missing")
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return contract, row_period, value.isoformat()


def _ohlcv_signature(row: dict[str, Any]) -> tuple[str, ...]:
    try:
        return tuple(_decimal_text(row.get(field)) for field in ("open", "high", "low", "close", "volume"))
    except (ValueError, TypeError) as exc:
        raise HistoricalLiveContextError("historical_live_context_ohlcv_invalid") from exc


def _decimal_text(value: Any) -> str:
    if value is None:
        raise ValueError("missing numeric value")
    normalized = Decimal(str(value)).normalize()
    if normalized == 0:
        normalized = Decimal(0)
    return format(normalized, "f")


def _date_value(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise HistoricalLiveContextError("historical_live_context_trading_day_missing")


def _datetime_value(value: Any) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        raise HistoricalLiveContextError("historical_live_context_datetime_missing")
    return _naive(value)


def _naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


__all__ = [
    "HistoricalLiveContextError",
    "HistoricalLiveContext",
    "HistoricalLiveContextResolver",
    "HistoricalLiveMerge",
    "historical_context_hash",
    "merge_historical_live_bars",
]
