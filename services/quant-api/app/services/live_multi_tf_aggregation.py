from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import LiveAggregatedBar, LiveAggregationCheckpoint, LiveMinuteBar, utc_now


PROVIDER = "rqdata"
SOURCE_PERIOD = "1m"
SOURCE_MODE = "live_1m_sequential_bucket"
SUPPORTED_PERIODS = ("5m", "15m", "30m", "60m")


@dataclass
class LiveAggregationConfig:
    contract: str
    symbol: str
    exchange: str | None = None
    periods: tuple[str, ...] = SUPPORTED_PERIODS
    provider: str = PROVIDER
    source_period: str = SOURCE_PERIOD
    source_mode: str = SOURCE_MODE


@dataclass
class LiveAggregationResult:
    dry_run: bool
    provider: str
    contract_code: str
    instrument_symbol: str
    source_period: str
    source_mode: str
    periods: list[str]
    source_row_count: int
    excluded_row_count: int
    min_source_datetime: datetime | None
    max_source_datetime: datetime | None
    period_results: dict[str, dict[str, Any]]
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "provider": self.provider,
            "contract_code": self.contract_code,
            "instrument_symbol": self.instrument_symbol,
            "source_period": self.source_period,
            "source_mode": self.source_mode,
            "periods": self.periods,
            "source_row_count": self.source_row_count,
            "excluded_row_count": self.excluded_row_count,
            "min_source_datetime": _json_datetime(self.min_source_datetime),
            "max_source_datetime": _json_datetime(self.max_source_datetime),
            "period_results": self.period_results,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


@dataclass
class _Bucket:
    rows: list[LiveMinuteBar]
    block_index: int
    bucket_index: int


@dataclass
class _Candidate:
    period: str
    bar_datetime: datetime
    trading_day: Any
    source_start_datetime: datetime
    source_end_datetime: datetime
    source_bar_count: int
    expected_bar_count: int
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


class LiveMultiTfAggregationService:
    def __init__(self, *, session: Session, now: datetime | None = None) -> None:
        self.session = session
        self.now = _naive(now or utc_now())

    def aggregate_once(self, config: LiveAggregationConfig, *, dry_run: bool = False) -> LiveAggregationResult:
        normalized = _normalize_config(config)
        all_rows = self._source_rows(normalized)
        eligible_rows = [row for row in all_rows if row.bar_status == "confirmed" and row.quality_status != "failed"]
        excluded_count = len(all_rows) - len(eligible_rows)
        max_source_datetime = max((_naive(row.bar_datetime) for row in eligible_rows), default=None)
        min_source_datetime = min((_naive(row.bar_datetime) for row in eligible_rows), default=None)
        period_results: dict[str, dict[str, Any]] = {}

        for period in normalized.periods:
            checkpoint = None if dry_run else self._checkpoint(normalized, period)
            if checkpoint is not None:
                checkpoint.status = "running"
                checkpoint.last_run_at = self.now
                checkpoint.last_source_bar_at = max_source_datetime

            candidates = self._candidates_for_period(eligible_rows, normalized, period, max_source_datetime)
            stats = {"upserted": 0, "revised": 0, "unchanged": 0}
            if not dry_run:
                for candidate in candidates:
                    changed = self._upsert_candidate(normalized, candidate)
                    stats[changed] += 1
                self.session.flush()

            warning_count = sum(1 for candidate in candidates if candidate.quality_status == "warning")
            last_aggregated_at = max((candidate.bar_datetime for candidate in candidates), default=None)
            status = "success" if candidates else "warning"
            lag_seconds = _lag_seconds(self.now, last_aggregated_at)
            result = {
                "candidate_count": len(candidates),
                "upserted_count": 0 if dry_run else stats["upserted"],
                "revised_count": 0 if dry_run else stats["revised"],
                "unchanged_count": 0 if dry_run else stats["unchanged"],
                "warning_count": warning_count,
                "last_aggregated_bar_at": _json_datetime(last_aggregated_at),
                "lag_seconds": lag_seconds,
            }
            period_results[period] = result

            if checkpoint is not None:
                self._mark_checkpoint_result(
                    checkpoint,
                    status=status,
                    last_aggregated_at=last_aggregated_at,
                    lag_seconds=lag_seconds,
                    result=result,
                )

        return LiveAggregationResult(
            dry_run=dry_run,
            provider=normalized.provider,
            contract_code=normalized.contract,
            instrument_symbol=normalized.symbol,
            source_period=normalized.source_period,
            source_mode=normalized.source_mode,
            periods=list(normalized.periods),
            source_row_count=len(eligible_rows),
            excluded_row_count=excluded_count,
            min_source_datetime=min_source_datetime,
            max_source_datetime=max_source_datetime,
            period_results=period_results,
        )

    def _source_rows(self, config: LiveAggregationConfig) -> list[LiveMinuteBar]:
        query = (
            select(LiveMinuteBar)
            .where(
                LiveMinuteBar.provider == config.provider,
                LiveMinuteBar.contract_code == config.contract,
                LiveMinuteBar.period == config.source_period,
            )
            .order_by(LiveMinuteBar.bar_datetime)
        )
        return list(self.session.scalars(query))

    def _candidates_for_period(
        self,
        rows: list[LiveMinuteBar],
        config: LiveAggregationConfig,
        period: str,
        max_source_datetime: datetime | None,
    ) -> list[_Candidate]:
        if not rows or max_source_datetime is None:
            return []
        expected_count = _period_minutes(period)
        candidates: list[_Candidate] = []
        for bucket in _buckets(rows, expected_count):
            end_time = _naive(bucket.rows[-1].bar_datetime)
            if end_time >= max_source_datetime:
                continue
            candidates.append(_candidate_from_bucket(bucket, config=config, period=period, expected_count=expected_count))
        return candidates

    def _checkpoint(self, config: LiveAggregationConfig, period: str) -> LiveAggregationCheckpoint:
        checkpoint = self.session.scalar(
            select(LiveAggregationCheckpoint).where(
                LiveAggregationCheckpoint.provider == config.provider,
                LiveAggregationCheckpoint.contract_code == config.contract,
                LiveAggregationCheckpoint.period == period,
                LiveAggregationCheckpoint.source_mode == config.source_mode,
            )
        )
        if checkpoint is None:
            checkpoint = LiveAggregationCheckpoint(
                provider=config.provider,
                instrument_symbol=config.symbol,
                contract_code=config.contract,
                period=period,
                source_period=config.source_period,
                source_mode=config.source_mode,
                status="idle",
                consecutive_error_count=0,
                last_result={},
            )
            self.session.add(checkpoint)
            self.session.flush()
        checkpoint.instrument_symbol = config.symbol
        checkpoint.source_period = config.source_period
        return checkpoint

    def _upsert_candidate(self, config: LiveAggregationConfig, candidate: _Candidate) -> str:
        existing = self.session.scalar(
            select(LiveAggregatedBar).where(
                LiveAggregatedBar.provider == config.provider,
                LiveAggregatedBar.contract_code == config.contract,
                LiveAggregatedBar.period == candidate.period,
                LiveAggregatedBar.bar_datetime == candidate.bar_datetime,
                LiveAggregatedBar.source_mode == config.source_mode,
            )
        )
        values = {
            "instrument_symbol": config.symbol,
            "exchange_code": config.exchange,
            "source_period": config.source_period,
            "source_mode": config.source_mode,
            "trading_day": candidate.trading_day,
            "source_start_datetime": candidate.source_start_datetime,
            "source_end_datetime": candidate.source_end_datetime,
            "source_bar_count": candidate.source_bar_count,
            "expected_bar_count": candidate.expected_bar_count,
            "open": candidate.open,
            "high": candidate.high,
            "low": candidate.low,
            "close": candidate.close,
            "volume": candidate.volume,
            "open_interest": candidate.open_interest,
            "turnover": candidate.turnover,
            "bar_status": candidate.bar_status,
            "quality_status": candidate.quality_status,
            "last_seen_at": self.now,
            "confirmed_at": self.now if candidate.bar_status == "confirmed" else None,
            "raw_payload": candidate.raw_payload,
        }
        if existing is None:
            self.session.add(
                LiveAggregatedBar(
                    provider=config.provider,
                    contract_code=config.contract,
                    period=candidate.period,
                    bar_datetime=candidate.bar_datetime,
                    first_seen_at=self.now,
                    revision=0,
                    **values,
                )
            )
            return "upserted"

        changed = any(getattr(existing, key) != value for key, value in values.items() if key not in {"last_seen_at", "raw_payload"})
        for key, value in values.items():
            setattr(existing, key, value)
        if changed:
            existing.revision += 1
            return "revised"
        return "unchanged"

    def _mark_checkpoint_result(
        self,
        checkpoint: LiveAggregationCheckpoint,
        *,
        status: str,
        last_aggregated_at: datetime | None,
        lag_seconds: int | None,
        result: dict[str, Any],
    ) -> None:
        checkpoint.status = status
        checkpoint.last_success_at = self.now if status == "success" else checkpoint.last_success_at
        checkpoint.last_aggregated_bar_at = last_aggregated_at or checkpoint.last_aggregated_bar_at
        checkpoint.lag_seconds = lag_seconds
        checkpoint.last_error_type = None if status == "success" else "NoClosedBuckets"
        checkpoint.last_error_message = None if status == "success" else "no closed live aggregation buckets were accepted"
        checkpoint.consecutive_error_count = 0 if status == "success" else checkpoint.consecutive_error_count + 1
        checkpoint.last_result = result


def _buckets(rows: list[LiveMinuteBar], expected_count: int) -> list[_Bucket]:
    buckets: list[_Bucket] = []
    current_rows: list[LiveMinuteBar] = []
    current_block = 0
    previous: LiveMinuteBar | None = None
    offset = 0
    bucket_index = 0

    for row in rows:
        if previous is None:
            current_rows = []
            offset = 0
            bucket_index = 0
        elif _is_new_block(previous, row):
            if current_rows:
                buckets.append(_Bucket(rows=current_rows, block_index=current_block, bucket_index=bucket_index))
            current_block += 1
            offset = 0
            bucket_index = 0
            current_rows = []
        next_bucket_index = offset // expected_count
        if current_rows and next_bucket_index != bucket_index:
            buckets.append(_Bucket(rows=current_rows, block_index=current_block, bucket_index=bucket_index))
            current_rows = []
            bucket_index = next_bucket_index
        current_rows.append(row)
        previous = row
        offset += 1

    if current_rows:
        buckets.append(_Bucket(rows=current_rows, block_index=current_block, bucket_index=bucket_index))
    return buckets


def _is_new_block(previous: LiveMinuteBar, current: LiveMinuteBar) -> bool:
    previous_day = previous.trading_day
    current_day = current.trading_day
    if previous_day is not None and current_day is not None and previous_day != current_day:
        return True
    gap_seconds = (_naive(current.bar_datetime) - _naive(previous.bar_datetime)).total_seconds()
    return gap_seconds > 90


def _candidate_from_bucket(bucket: _Bucket, *, config: LiveAggregationConfig, period: str, expected_count: int) -> _Candidate:
    rows = bucket.rows
    first = rows[0]
    last = rows[-1]
    quality_reasons: list[str] = []
    if len(rows) != expected_count:
        quality_reasons.append("incomplete_source_bucket")
    if any(row.quality_status != "passed" for row in rows):
        quality_reasons.append("source_quality_warning")
    quality_status = "passed" if not quality_reasons else "warning"
    return _Candidate(
        period=period,
        bar_datetime=_naive(last.bar_datetime),
        trading_day=first.trading_day,
        source_start_datetime=_naive(first.bar_datetime),
        source_end_datetime=_naive(last.bar_datetime),
        source_bar_count=len(rows),
        expected_bar_count=expected_count,
        open=first.open,
        high=_max_decimal(row.high for row in rows),
        low=_min_decimal(row.low for row in rows),
        close=last.close,
        volume=_sum_decimal(row.volume for row in rows),
        open_interest=last.open_interest,
        turnover=_sum_decimal(row.turnover for row in rows),
        bar_status="confirmed",
        quality_status=quality_status,
        raw_payload={
            "source_period": config.source_period,
            "source_mode": config.source_mode,
            "block_index": bucket.block_index,
            "bucket_index": bucket.bucket_index,
            "quality_reasons": quality_reasons,
        },
    )


def _normalize_config(config: LiveAggregationConfig) -> LiveAggregationConfig:
    periods = tuple(_normalize_period(period) for period in config.periods)
    if not periods:
        periods = SUPPORTED_PERIODS
    unsupported = sorted(set(periods) - set(SUPPORTED_PERIODS))
    if unsupported:
        raise ValueError(f"unsupported live aggregation periods: {unsupported}")
    return LiveAggregationConfig(
        contract=str(config.contract or "").upper(),
        symbol=str(config.symbol or "").lower(),
        exchange=str(config.exchange).upper() if config.exchange else None,
        periods=periods,
        provider=str(config.provider or PROVIDER).lower(),
        source_period=str(config.source_period or SOURCE_PERIOD).lower(),
        source_mode=str(config.source_mode or SOURCE_MODE),
    )


def _normalize_period(period: str) -> str:
    return str(period).strip().lower()


def _period_minutes(period: str) -> int:
    if not period.endswith("m"):
        raise ValueError(f"unsupported live aggregation period: {period}")
    minutes = int(period.removesuffix("m"))
    if minutes <= 1:
        raise ValueError(f"unsupported live aggregation period: {period}")
    return minutes


def _sum_decimal(values: Any) -> Decimal | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present, Decimal("0"))


def _max_decimal(values: Any) -> Decimal | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _min_decimal(values: Any) -> Decimal | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


def _lag_seconds(now: datetime, value: datetime | None) -> int | None:
    if value is None:
        return None
    return max(0, int((_naive(now) - _naive(value)).total_seconds()))


def _json_datetime(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
