from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import LiveIngestCheckpoint, LiveMinuteBar, utc_now
from app.services.rqdata_ingest.db import as_date, as_decimal, row_payload


PROVIDER = "rqdata"
PERIOD = "1m"
SOURCE_MODE = "poll_get_price_1m"
SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass
class LiveIngestConfig:
    contract: str
    symbol: str
    exchange: str | None = None
    lookback_minutes: int = 10
    provider: str = PROVIDER
    period: str = PERIOD
    source_mode: str = SOURCE_MODE
    expected_trading_day: date | None = None


@dataclass
class LiveBarCandidate:
    bar_datetime: datetime
    trading_day: date | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: Decimal | None
    open_interest: Decimal | None
    turnover: Decimal | None
    bar_status: str
    quality_status: str
    raw_payload: dict[str, Any]
    validation_errors: list[str] = field(default_factory=list)


@dataclass
class LiveIngestResult:
    dry_run: bool
    provider: str
    contract_code: str
    instrument_symbol: str
    period: str
    source_mode: str
    row_count: int
    confirmed_candidates: int
    upserted_count: int
    revised_count: int
    unchanged_count: int
    skipped_count: int
    rejected_count: int
    min_bar_datetime: datetime | None
    max_bar_datetime: datetime | None
    max_trading_day: date | None
    checkpoint_status: str
    lag_seconds: int | None
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "provider": self.provider,
            "contract_code": self.contract_code,
            "instrument_symbol": self.instrument_symbol,
            "period": self.period,
            "source_mode": self.source_mode,
            "row_count": self.row_count,
            "confirmed_candidates": self.confirmed_candidates,
            "upserted_count": self.upserted_count,
            "revised_count": self.revised_count,
            "unchanged_count": self.unchanged_count,
            "skipped_count": self.skipped_count,
            "rejected_count": self.rejected_count,
            "min_bar_datetime": _json_datetime(self.min_bar_datetime),
            "max_bar_datetime": _json_datetime(self.max_bar_datetime),
            "max_trading_day": None if self.max_trading_day is None else self.max_trading_day.isoformat(),
            "checkpoint_status": self.checkpoint_status,
            "lag_seconds": self.lag_seconds,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


class LiveMinuteIngestService:
    def __init__(self, *, session: Session, client: Any, now: datetime | None = None) -> None:
        self.session = session
        self.client = client
        current = now or utc_now()
        self.now = _naive(current)
        self.local_now = _local_naive(current)

    def poll_once(self, config: LiveIngestConfig, *, dry_run: bool = False) -> LiveIngestResult:
        normalized = _normalize_config(config)
        checkpoint = None if dry_run else self._checkpoint(normalized)
        if checkpoint is not None:
            checkpoint.status = "running"
            checkpoint.last_polled_at = self.now

        try:
            start_at = self._start_at(checkpoint, normalized)
            query_end_date = normalized.expected_trading_day or self.local_now.date()
            frame = self.client.contract_bars(normalized.contract, start_at.date(), query_end_date, normalized.period)
            candidates, skipped_count = normalize_live_1m_frame(frame, config=normalized, now=self.local_now)
        except Exception as exc:  # noqa: BLE001 - checkpoint must capture live ingest failures.
            if checkpoint is not None:
                self._mark_checkpoint_failure(checkpoint, exc)
            return LiveIngestResult(
                dry_run=dry_run,
                provider=normalized.provider,
                contract_code=normalized.contract,
                instrument_symbol=normalized.symbol,
                period=normalized.period,
                source_mode=normalized.source_mode,
                row_count=0,
                confirmed_candidates=0,
                upserted_count=0,
                revised_count=0,
                unchanged_count=0,
                skipped_count=0,
                rejected_count=0,
                min_bar_datetime=None,
                max_bar_datetime=None,
                max_trading_day=None,
                checkpoint_status="failed",
                lag_seconds=None,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        stats = {"upserted": 0, "revised": 0, "unchanged": 0}
        if not dry_run:
            for candidate in candidates:
                changed = self._upsert_candidate(normalized, candidate)
                stats[changed] += 1
            self.session.flush()

        confirmed = [candidate for candidate in candidates if candidate.bar_status == "confirmed" and candidate.quality_status != "failed"]
        rejected_count = sum(1 for candidate in candidates if candidate.quality_status == "failed" or candidate.bar_status == "rejected")
        max_bar_datetime = max((candidate.bar_datetime for candidate in confirmed), default=None)
        min_bar_datetime = min((candidate.bar_datetime for candidate in confirmed), default=None)
        max_trading_day = max((candidate.trading_day for candidate in confirmed if candidate.trading_day is not None), default=None)
        status = "success" if confirmed else "warning"
        lag_seconds = _lag_seconds(self.local_now, max_bar_datetime)

        if checkpoint is not None:
            self._mark_checkpoint_result(
                checkpoint,
                status=status,
                max_bar_datetime=max_bar_datetime,
                lag_seconds=lag_seconds,
                result={
                    "row_count": len(frame) if isinstance(frame, pd.DataFrame) else 0,
                    "confirmed_candidates": len(confirmed),
                    "upserted_count": stats["upserted"],
                    "revised_count": stats["revised"],
                    "unchanged_count": stats["unchanged"],
                    "skipped_count": skipped_count,
                    "rejected_count": rejected_count,
                    "min_bar_datetime": _json_datetime(min_bar_datetime),
                    "max_bar_datetime": _json_datetime(max_bar_datetime),
                    "max_trading_day": None if max_trading_day is None else max_trading_day.isoformat(),
                },
            )

        return LiveIngestResult(
            dry_run=dry_run,
            provider=normalized.provider,
            contract_code=normalized.contract,
            instrument_symbol=normalized.symbol,
            period=normalized.period,
            source_mode=normalized.source_mode,
            row_count=len(frame) if isinstance(frame, pd.DataFrame) else 0,
            confirmed_candidates=len(confirmed),
            upserted_count=0 if dry_run else stats["upserted"],
            revised_count=0 if dry_run else stats["revised"],
            unchanged_count=0 if dry_run else stats["unchanged"],
            skipped_count=skipped_count,
            rejected_count=rejected_count,
            min_bar_datetime=min_bar_datetime,
            max_bar_datetime=max_bar_datetime,
            max_trading_day=max_trading_day,
            checkpoint_status=status,
            lag_seconds=lag_seconds,
        )

    def _checkpoint(self, config: LiveIngestConfig) -> LiveIngestCheckpoint:
        checkpoint = self.session.scalar(
            select(LiveIngestCheckpoint).where(
                LiveIngestCheckpoint.provider == config.provider,
                LiveIngestCheckpoint.contract_code == config.contract,
                LiveIngestCheckpoint.period == config.period,
                LiveIngestCheckpoint.source_mode == config.source_mode,
            )
        )
        if checkpoint is None:
            checkpoint = LiveIngestCheckpoint(
                provider=config.provider,
                instrument_symbol=config.symbol,
                contract_code=config.contract,
                period=config.period,
                source_mode=config.source_mode,
                status="idle",
                consecutive_error_count=0,
                last_result={},
            )
            self.session.add(checkpoint)
            self.session.flush()
        checkpoint.instrument_symbol = config.symbol
        return checkpoint

    def _start_at(self, checkpoint: LiveIngestCheckpoint | None, config: LiveIngestConfig) -> datetime:
        if checkpoint is not None and checkpoint.last_confirmed_bar_at is not None:
            return _naive(checkpoint.last_confirmed_bar_at) - timedelta(minutes=config.lookback_minutes)
        return self.local_now - timedelta(minutes=config.lookback_minutes)

    def _upsert_candidate(self, config: LiveIngestConfig, candidate: LiveBarCandidate) -> str:
        existing = self.session.scalar(
            select(LiveMinuteBar).where(
                LiveMinuteBar.provider == config.provider,
                LiveMinuteBar.contract_code == config.contract,
                LiveMinuteBar.period == config.period,
                LiveMinuteBar.bar_datetime == candidate.bar_datetime,
            )
        )
        values = {
            "instrument_symbol": config.symbol,
            "exchange_code": config.exchange,
            "trading_day": candidate.trading_day,
            "open": candidate.open,
            "high": candidate.high,
            "low": candidate.low,
            "close": candidate.close,
            "volume": candidate.volume,
            "open_interest": candidate.open_interest,
            "turnover": candidate.turnover,
            "bar_status": candidate.bar_status,
            "quality_status": candidate.quality_status,
            "source_mode": config.source_mode,
            "last_seen_at": self.now,
            "raw_payload": candidate.raw_payload,
        }
        if existing is None:
            values["confirmed_at"] = self.now if candidate.bar_status == "confirmed" else None
            self.session.add(
                LiveMinuteBar(
                    provider=config.provider,
                    contract_code=config.contract,
                    period=config.period,
                    bar_datetime=candidate.bar_datetime,
                    first_seen_at=self.now,
                    revision=0,
                    **values,
                )
            )
            return "upserted"

        changed = any(getattr(existing, key) != value for key, value in values.items() if key not in {"last_seen_at", "raw_payload"})
        if candidate.bar_status == "confirmed":
            values["confirmed_at"] = self.now if changed or existing.confirmed_at is None else existing.confirmed_at
        else:
            values["confirmed_at"] = None
        for key, value in values.items():
            setattr(existing, key, value)
        if changed:
            existing.revision += 1
            return "revised"
        return "unchanged"

    def _mark_checkpoint_result(
        self,
        checkpoint: LiveIngestCheckpoint,
        *,
        status: str,
        max_bar_datetime: datetime | None,
        lag_seconds: int | None,
        result: dict[str, Any],
    ) -> None:
        checkpoint.status = status
        checkpoint.last_success_at = self.now if status == "success" else checkpoint.last_success_at
        checkpoint.last_confirmed_bar_at = max_bar_datetime or checkpoint.last_confirmed_bar_at
        checkpoint.lag_seconds = lag_seconds
        checkpoint.last_error_type = None if status == "success" else "NoConfirmedBars"
        checkpoint.last_error_message = None if status == "success" else "no confirmed live 1m bars were accepted"
        checkpoint.consecutive_error_count = 0 if status == "success" else checkpoint.consecutive_error_count + 1
        checkpoint.last_result = result

    def _mark_checkpoint_failure(self, checkpoint: LiveIngestCheckpoint, exc: Exception) -> None:
        checkpoint.status = "failed"
        checkpoint.last_error_type = type(exc).__name__
        checkpoint.last_error_message = str(exc)
        checkpoint.consecutive_error_count += 1
        checkpoint.last_result = {"error_type": type(exc).__name__, "error_message": str(exc)}


def normalize_live_1m_frame(frame: Any, *, config: LiveIngestConfig, now: datetime) -> tuple[list[LiveBarCandidate], int]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return [], 0
    cutoff = _minute_floor(_naive(now))
    candidates: list[LiveBarCandidate] = []
    skipped_count = 0
    for record in frame.copy().where(pd.notna(frame), None).to_dict("records"):
        bar_datetime = _datetime_value(record)
        if bar_datetime is None:
            skipped_count += 1
            continue
        bar_datetime = _naive(bar_datetime)
        if bar_datetime >= cutoff:
            skipped_count += 1
            continue
        candidate = _candidate_from_record(record, config=config, bar_datetime=bar_datetime)
        if config.expected_trading_day is not None and candidate.trading_day != config.expected_trading_day:
            skipped_count += 1
            continue
        candidates.append(candidate)
    return candidates, skipped_count


def _candidate_from_record(record: dict[str, Any], *, config: LiveIngestConfig, bar_datetime: datetime) -> LiveBarCandidate:
    trading_day = as_date(_value(record, "trading_day", "trading_date", "date"))
    open_price = as_decimal(_value(record, "open"))
    high = as_decimal(_value(record, "high"))
    low = as_decimal(_value(record, "low"))
    close = as_decimal(_value(record, "close"))
    volume = as_decimal(_value(record, "volume"))
    open_interest = as_decimal(_value(record, "open_interest", "total_turnover", "oi"))
    turnover = as_decimal(_value(record, "turnover", "total_turnover"))

    errors = _quality_errors(
        contract=config.contract,
        bar_datetime=bar_datetime,
        trading_day=trading_day,
        open_price=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        open_interest=open_interest,
    )
    payload = row_payload(record)
    if errors:
        payload["validation_errors"] = errors
    quality_status = "passed" if not errors else "failed" if any(error != "missing_trading_day" for error in errors) else "warning"
    bar_status = "confirmed" if quality_status != "failed" else "rejected"
    return LiveBarCandidate(
        bar_datetime=bar_datetime,
        trading_day=trading_day,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        open_interest=open_interest,
        turnover=turnover,
        bar_status=bar_status,
        quality_status=quality_status,
        raw_payload=payload,
        validation_errors=errors,
    )


def _quality_errors(
    *,
    contract: str,
    bar_datetime: datetime | None,
    trading_day: date | None,
    open_price: Decimal | None,
    high: Decimal | None,
    low: Decimal | None,
    close: Decimal | None,
    volume: Decimal | None,
    open_interest: Decimal | None,
) -> list[str]:
    errors: list[str] = []
    if not contract:
        errors.append("missing_contract")
    if bar_datetime is None:
        errors.append("missing_bar_datetime")
    if trading_day is None:
        errors.append("missing_trading_day")
    if open_price is None or high is None or low is None or close is None:
        errors.append("missing_ohlc")
    elif high < max(open_price, close, low) or low > min(open_price, close, high):
        errors.append("invalid_ohlc")
    if volume is not None and volume < 0:
        errors.append("negative_volume")
    if open_interest is not None and open_interest < 0:
        errors.append("negative_open_interest")
    return errors


def _normalize_config(config: LiveIngestConfig) -> LiveIngestConfig:
    return LiveIngestConfig(
        contract=str(config.contract or "").upper(),
        symbol=str(config.symbol or "").lower(),
        exchange=str(config.exchange).upper() if config.exchange else None,
        lookback_minutes=max(1, int(config.lookback_minutes)),
        provider=config.provider,
        period=config.period,
        source_mode=config.source_mode,
        expected_trading_day=config.expected_trading_day,
    )


def _value(record: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in record and record[name] is not None:
            return record[name]
    return None


def _datetime_value(record: dict[str, Any]) -> datetime | None:
    value = _value(record, "datetime", "bar_datetime", "date", "index")
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


def _local_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(SHANGHAI).replace(tzinfo=None)


def _minute_floor(value: datetime) -> datetime:
    return value.replace(second=0, microsecond=0)


def _lag_seconds(now: datetime, max_bar_datetime: datetime | None) -> int | None:
    if max_bar_datetime is None:
        return None
    return max(0, int((_naive(now) - _naive(max_bar_datetime)).total_seconds()))


def _json_datetime(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
