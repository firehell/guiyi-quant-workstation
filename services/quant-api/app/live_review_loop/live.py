from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.live_review_loop.contracts import canonical_digest
from app.models.live_review_loop import LiveObservationBar


SHANGHAI = ZoneInfo("Asia/Shanghai")


class LiveObservationConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LiveObservationInput:
    provider: str
    source_mode: str
    product: str
    actual_contract: str
    trading_day: date
    period: str
    bar_end: datetime
    revision: int
    confirmed: bool
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    open_interest: Decimal | None
    turnover: Decimal | None
    source_start: datetime
    source_end: datetime
    source_bar_count: int
    expected_bar_count: int

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


class LiveObservationStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def put(self, item: LiveObservationInput) -> LiveObservationBar:
        normalized = _validated(item)
        existing = self.session.scalar(
            select(LiveObservationBar).where(
                LiveObservationBar.provider == normalized.provider,
                LiveObservationBar.source_mode == normalized.source_mode,
                LiveObservationBar.actual_contract == normalized.actual_contract,
                LiveObservationBar.period == normalized.period,
                LiveObservationBar.trading_day == normalized.trading_day,
                LiveObservationBar.bar_end == normalized.bar_end,
                LiveObservationBar.revision == normalized.revision,
                LiveObservationBar.confirmed == normalized.confirmed,
            )
        )
        identity_digest = canonical_digest(_identity_payload(normalized))
        payload_digest = canonical_digest(normalized.to_payload())
        if existing is not None:
            if existing.identity_digest != identity_digest or existing.payload_digest != payload_digest:
                raise LiveObservationConflictError("LIVE_OBSERVATION_CONFLICT")
            return existing
        row = LiveObservationBar(
            **normalized.to_payload(),
            identity_digest=identity_digest,
            payload_digest=payload_digest,
        )
        self.session.add(row)
        self.session.flush()
        return row


def aggregate_confirmed_15m(
    rows: Sequence[LiveObservationInput],
    *,
    session_start: datetime,
    session_end: datetime,
) -> LiveObservationInput:
    ordered = sorted(rows, key=lambda row: row.bar_end)
    if len(ordered) != 15:
        raise ValueError("LIVE_15M_SOURCE_INCOMPLETE")
    first = ordered[0]
    if any(
        row.provider != "rqdata"
        or row.source_mode != "rqdata_live_1m_v2"
        or row.product != "jm"
        or row.actual_contract != first.actual_contract
        or row.trading_day != first.trading_day
        or row.period != "1m"
        or row.confirmed is not True
        or row.revision < 0
        or row.source_bar_count != 1
        or row.expected_bar_count != 1
        or row.source_end != row.bar_end
        or row.bar_end - row.source_start != timedelta(minutes=1)
        for row in ordered
    ):
        raise ValueError("LIVE_15M_SOURCE_IDENTITY_INVALID")
    expected_ends = [ordered[0].bar_end + timedelta(minutes=index) for index in range(15)]
    if [row.bar_end for row in ordered] != expected_ends:
        raise ValueError("LIVE_15M_SOURCE_INCOMPLETE")
    bucket_end = ordered[-1].bar_end
    if ordered[0].bar_end <= session_start or bucket_end > session_end:
        raise ValueError("LIVE_15M_SESSION_BOUNDARY")
    elapsed = int((bucket_end - session_start).total_seconds() // 60)
    if elapsed <= 0 or elapsed % 15 != 0:
        raise ValueError("LIVE_15M_BUCKET_ALIGNMENT")
    return replace(
        first,
        source_mode="session_aggregate_15m_v2",
        period="15m",
        bar_end=bucket_end,
        revision=0,
        open=ordered[0].open,
        high=max(row.high for row in ordered),
        low=min(row.low for row in ordered),
        close=ordered[-1].close,
        volume=sum((row.volume for row in ordered), Decimal(0)),
        open_interest=ordered[-1].open_interest,
        turnover=sum((row.turnover or Decimal(0) for row in ordered), Decimal(0)),
        source_start=ordered[0].source_start,
        source_end=ordered[-1].source_end,
        source_bar_count=15,
        expected_bar_count=15,
    )


def aggregate_trading_day_15m(
    session: Session,
    *,
    trading_day: date,
    actual_contract: str,
    trading_clock: Any,
) -> list[LiveObservationBar]:
    normalized_contract = actual_contract.strip().upper()
    source_rows = list(
        session.scalars(
            select(LiveObservationBar)
            .where(
                LiveObservationBar.provider == "rqdata",
                LiveObservationBar.source_mode == "rqdata_live_1m_v2",
                LiveObservationBar.product == "jm",
                LiveObservationBar.actual_contract == normalized_contract,
                LiveObservationBar.trading_day == trading_day,
                LiveObservationBar.period == "1m",
                LiveObservationBar.confirmed.is_(True),
            )
            .order_by(LiveObservationBar.bar_end)
        )
    )
    latest_by_end: dict[datetime, LiveObservationBar] = {}
    for row in source_rows:
        key = _aware_utc(row.bar_end)
        current = latest_by_end.get(key)
        if current is None or row.revision > current.revision:
            latest_by_end[key] = row
    inputs = [_model_input(latest_by_end[key]) for key in sorted(latest_by_end)]
    store = LiveObservationStore(session)
    persisted: list[LiveObservationBar] = []
    windows = trading_clock.windows_for_trading_day(
        trading_day,
        product="jm",
        exchange="DCE",
    )
    for window in windows:
        start = _shanghai_window_to_utc(window.start)
        end = _shanghai_window_to_utc(window.end)
        bucket_end = start + timedelta(minutes=15)
        while bucket_end <= end:
            bucket_start = bucket_end - timedelta(minutes=15)
            bucket = [row for row in inputs if bucket_start < row.bar_end <= bucket_end]
            if len(bucket) == 15:
                candidate = aggregate_confirmed_15m(
                    bucket,
                    session_start=start,
                    session_end=end,
                )
                existing = list(
                    session.scalars(
                        select(LiveObservationBar)
                        .where(
                            LiveObservationBar.provider == "rqdata",
                            LiveObservationBar.source_mode == "session_aggregate_15m_v2",
                            LiveObservationBar.actual_contract == normalized_contract,
                            LiveObservationBar.period == "15m",
                            LiveObservationBar.trading_day == trading_day,
                            LiveObservationBar.bar_end == candidate.bar_end,
                            LiveObservationBar.confirmed.is_(True),
                        )
                        .order_by(LiveObservationBar.revision.desc())
                    )
                )
                if existing:
                    latest = existing[0]
                    same_revision = replace(candidate, revision=latest.revision)
                    if canonical_digest(same_revision.to_payload()) == latest.payload_digest:
                        persisted.append(latest)
                        bucket_end += timedelta(minutes=15)
                        continue
                    candidate = replace(candidate, revision=latest.revision + 1)
                persisted.append(store.put(candidate))
            bucket_end += timedelta(minutes=15)
    return persisted


def _validated(item: LiveObservationInput) -> LiveObservationInput:
    if not isinstance(item, LiveObservationInput):
        raise TypeError("LIVE_OBSERVATION_INPUT_TYPE")
    normalized = replace(
        item,
        provider=item.provider.strip().lower(),
        product=item.product.strip().lower(),
        actual_contract=item.actual_contract.strip().upper(),
        period=item.period.strip().lower(),
        source_mode=item.source_mode.strip(),
    )
    if normalized.provider != "rqdata" or normalized.product != "jm":
        raise ValueError("LIVE_OBSERVATION_SCOPE_INVALID")
    if normalized.actual_contract.endswith(".MAIN") or not normalized.actual_contract.startswith("JM"):
        raise ValueError("LIVE_OBSERVATION_ACTUAL_CONTRACT_REQUIRED")
    if normalized.period not in {"1m", "15m"} or normalized.confirmed is not True:
        raise ValueError("LIVE_OBSERVATION_CONFIRMED_PERIOD_REQUIRED")
    expected_source = {
        "1m": ("rqdata_live_1m_v2", 1),
        "15m": ("session_aggregate_15m_v2", 15),
    }[normalized.period]
    if (
        normalized.source_mode != expected_source[0]
        or normalized.source_bar_count != expected_source[1]
        or normalized.expected_bar_count != expected_source[1]
    ):
        raise ValueError("LIVE_OBSERVATION_SOURCE_MODE_INVALID")
    if normalized.revision < 0 or normalized.source_bar_count != normalized.expected_bar_count:
        raise ValueError("LIVE_OBSERVATION_SOURCE_INCOMPLETE")
    if normalized.bar_end.tzinfo is None or normalized.source_start.tzinfo is None or normalized.source_end.tzinfo is None:
        raise ValueError("LIVE_OBSERVATION_TIMEZONE_REQUIRED")
    if normalized.source_end != normalized.bar_end:
        raise ValueError("LIVE_OBSERVATION_SOURCE_WINDOW_INVALID")
    if not (normalized.low <= normalized.open <= normalized.high and normalized.low <= normalized.close <= normalized.high):
        raise ValueError("LIVE_OBSERVATION_OHLC_INVALID")
    if normalized.volume < 0 or (normalized.open_interest is not None and normalized.open_interest < 0):
        raise ValueError("LIVE_OBSERVATION_VOLUME_INVALID")
    return normalized


def _identity_payload(item: LiveObservationInput) -> dict[str, Any]:
    return {
        "provider": item.provider,
        "source_mode": item.source_mode,
        "product": item.product,
        "actual_contract": item.actual_contract,
        "trading_day": item.trading_day,
        "period": item.period,
        "bar_end": item.bar_end,
        "revision": item.revision,
        "confirmed": item.confirmed,
    }


def _model_input(row: LiveObservationBar) -> LiveObservationInput:
    return LiveObservationInput(
        provider=row.provider,
        source_mode=row.source_mode,
        product=row.product,
        actual_contract=row.actual_contract,
        trading_day=row.trading_day,
        period=row.period,
        bar_end=_aware_utc(row.bar_end),
        revision=row.revision,
        confirmed=row.confirmed,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=row.volume,
        open_interest=row.open_interest,
        turnover=row.turnover,
        source_start=_aware_utc(row.source_start),
        source_end=_aware_utc(row.source_end),
        source_bar_count=row.source_bar_count,
        expected_bar_count=row.expected_bar_count,
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _shanghai_window_to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI).astimezone(UTC)
    return value.astimezone(UTC)
