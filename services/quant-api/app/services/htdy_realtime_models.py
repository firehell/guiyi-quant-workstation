"""Immutable, observation-only value objects for the HTDY realtime pilot."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

from app.services.jm_session_contract import JM_SESSION_BOUNDS, JM_SESSION_RANK


SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class SourceMinuteRef:
    live_bar_id: int
    datetime: datetime
    trading_day: date
    provider: str
    product: str
    actual_contract: str
    period: str
    bar_status: str
    quality_status: str
    revision: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    confirmed_at: datetime


@dataclass(frozen=True)
class BucketIdentity:
    product: str
    actual_contract: str
    trading_day: date
    session_id: str
    bucket_start: datetime
    bucket_end: datetime
    period: str
    session_name: str = ""


@dataclass(frozen=True)
class HtDy15mBarSnapshot:
    identity: BucketIdentity
    trading_day: date
    status: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    source_minutes: tuple[SourceMinuteRef, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_minutes", tuple(self.source_minutes))

    @property
    def observed_bar_close(self) -> Decimal:
        return self.close


@dataclass(frozen=True)
class HistoricalWarmupIdentity:
    profile_id: str
    binding_snapshot: Mapping[str, Any]
    market_data_file_id: int
    data_version: str
    checksum: str
    window_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "binding_snapshot",
            _deep_freeze(self.binding_snapshot),
        )


@dataclass(frozen=True)
class HtDyRealtimeSnapshot:
    trading_day: date
    as_of: datetime
    actual_contract: str
    continuous_contract: str
    mapping_date: date
    mapping_identity: Mapping[str, Any]
    historical_bars: tuple[HtDy15mBarSnapshot, ...]
    historical_identity: HistoricalWarmupIdentity
    buckets: tuple[HtDy15mBarSnapshot, ...]
    source_minutes: tuple[SourceMinuteRef, ...]
    snapshot_sha256: str
    source_sha256: str = ""
    policy_sha256: str = ""
    product: str = "jm"
    exchange: str = "DCE"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "mapping_identity",
            _deep_freeze(self.mapping_identity),
        )
        object.__setattr__(self, "historical_bars", tuple(self.historical_bars))
        object.__setattr__(self, "buckets", tuple(self.buckets))
        object.__setattr__(self, "source_minutes", tuple(self.source_minutes))
        _validate_snapshot_identity(self)


@dataclass(frozen=True)
class HtDyObservationCandidate:
    observation_key: str
    direction: str
    detected_at: datetime
    detection_price: Decimal
    observed_bar_close: Decimal
    bucket: HtDy15mBarSnapshot
    actual_contract: str
    continuous_contract: str
    mapping_date: date
    strategy_code: str
    strategy_version: str
    indicator_code: str
    indicator_version: str
    policy_id: str
    source_minutes: tuple[SourceMinuteRef, ...]
    historical_identity: HistoricalWarmupIdentity
    snapshot_sha256: str
    source_sha256: str
    policy_sha256: str
    period: str = "15m"
    source_mode: str = "live_realtime_repainting"
    detection_mode: str = "first_seen"
    contract_mode: str = "actual_rank1"
    main_contract_rank: int = 1
    repaint_scan_bars: int = 27
    future_dependency_horizon_bars: int = 24
    future_looking: bool = True
    repainting_accepted: bool = True
    first_seen_no_retraction: bool = True


@dataclass(frozen=True)
class BlockedObservation:
    bucket: HtDy15mBarSnapshot
    reason: str


@dataclass(frozen=True)
class HtDyEvaluationResult:
    candidates: tuple[HtDyObservationCandidate, ...] = ()
    blocked: tuple[BlockedObservation, ...] = ()
    snapshot_sha256: str = ""
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    writes_enabled: bool = False
    signal_event_enabled: bool = False
    notification_enabled: bool = False


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _validate_snapshot_identity(snapshot: HtDyRealtimeSnapshot) -> None:
    mapping = snapshot.mapping_identity
    if (
        snapshot.product != "jm"
        or snapshot.exchange != "DCE"
        or not snapshot.actual_contract
        or snapshot.actual_contract.endswith(".MAIN")
        or snapshot.mapping_date != snapshot.trading_day
        or not isinstance(mapping.get("mapping_id"), int)
        or isinstance(mapping.get("mapping_id"), bool)
        or mapping["mapping_id"] <= 0
        or mapping.get("product") != snapshot.product
        or mapping.get("provider") != "rqdata"
        or mapping.get("rule") != "volume_open_interest"
        or mapping.get("rank") != 1
        or mapping.get("mapping_date") != snapshot.mapping_date
        or mapping.get("actual_contract") != snapshot.actual_contract
        or not str(mapping.get("data_version") or "").strip()
        or not isinstance(mapping.get("created_at"), datetime)
    ):
        raise ValueError("HTDY_SNAPSHOT_MAPPING_IDENTITY")
    _require_utc(snapshot.as_of, "HTDY_SNAPSHOT_AS_OF_TIMEZONE_REQUIRED")
    if len(snapshot.historical_bars) != 128:
        raise ValueError("HTDY_SNAPSHOT_HISTORICAL_STRUCTURE")
    all_bars = (*snapshot.historical_bars, *snapshot.buckets)
    for bar in all_bars:
        identity = bar.identity
        if (
            bar.trading_day != identity.trading_day
            or identity.product != snapshot.product
            or identity.actual_contract != snapshot.actual_contract
            or identity.period != "15m"
            or identity.bucket_end <= identity.bucket_start
        ):
            raise ValueError("HTDY_SNAPSHOT_BAR_IDENTITY")
        _require_shanghai(
            identity.bucket_start,
            "HTDY_SNAPSHOT_BAR_TIMEZONE_REQUIRED",
        )
        _require_shanghai(
            identity.bucket_end,
            "HTDY_SNAPSHOT_BAR_TIMEZONE_REQUIRED",
        )
        _validate_session_geometry(identity)
        _validate_ohlcv(bar)
    if any(bar.trading_day != snapshot.trading_day for bar in snapshot.buckets):
        raise ValueError("HTDY_SNAPSHOT_TRADING_DAY_IDENTITY")
    _validate_historical_structure(snapshot)
    _validate_live_structure(snapshot)
    flattened = tuple(
        source for bucket in snapshot.buckets for source in bucket.source_minutes
    )
    if flattened != snapshot.source_minutes:
        raise ValueError("HTDY_SNAPSHOT_SOURCE_MEMBERSHIP")
    for bucket in snapshot.buckets:
        previous_time: datetime | None = None
        expected_count = (
            15 if bucket.status == "confirmed" else len(bucket.source_minutes)
        )
        if (
            expected_count != len(bucket.source_minutes)
            or not 1 <= len(bucket.source_minutes) <= 15
            or (
                bucket.status == "partial"
                and len(bucket.source_minutes) >= 15
            )
        ):
            raise ValueError("HTDY_SNAPSHOT_SOURCE_MEMBERSHIP")
        for source_index, source in enumerate(bucket.source_minutes, start=1):
            _require_shanghai(
                source.datetime,
                "HTDY_SNAPSHOT_SOURCE_TIMEZONE_REQUIRED",
            )
            expected_datetime = bucket.identity.bucket_start + timedelta(
                minutes=source_index
            )
            if (
                source.trading_day != bucket.trading_day
                or not (
                    bucket.identity.bucket_start
                    < source.datetime
                    <= bucket.identity.bucket_end
                )
                or (previous_time is not None and source.datetime <= previous_time)
                or source.datetime != expected_datetime
            ):
                raise ValueError("HTDY_SNAPSHOT_SOURCE_MEMBERSHIP")
            previous_time = source.datetime
        if (
            bucket.open != bucket.source_minutes[0].open
            or bucket.high != max(source.high for source in bucket.source_minutes)
            or bucket.low != min(source.low for source in bucket.source_minutes)
            or bucket.close != bucket.source_minutes[-1].close
            or bucket.volume
            != sum(
                (source.volume for source in bucket.source_minutes),
                Decimal("0"),
            )
        ):
            raise ValueError("HTDY_SNAPSHOT_SOURCE_MEMBERSHIP")
    source_ids: set[int] = set()
    source_datetimes: set[datetime] = set()
    for source in snapshot.source_minutes:
        if (
            source.trading_day != snapshot.trading_day
            or not isinstance(source.live_bar_id, int)
            or isinstance(source.live_bar_id, bool)
            or source.live_bar_id <= 0
            or source.live_bar_id in source_ids
            or source.datetime in source_datetimes
        ):
            raise ValueError("HTDY_SNAPSHOT_SOURCE_IDENTITY")
        source_ids.add(source.live_bar_id)
        source_datetimes.add(source.datetime)
        if (
            source.provider != "rqdata"
            or source.product != snapshot.product
            or source.actual_contract != snapshot.actual_contract
            or source.period != "1m"
            or source.bar_status != "confirmed"
            or source.quality_status != "passed"
            or not isinstance(source.revision, int)
            or isinstance(source.revision, bool)
            or source.revision < 0
        ):
            raise ValueError("HTDY_SNAPSHOT_SOURCE_IDENTITY")
        _validate_ohlcv(source)
        _require_shanghai(
            source.datetime,
            "HTDY_SNAPSHOT_SOURCE_TIMEZONE_REQUIRED",
        )
        _require_utc(
            source.confirmed_at,
            "HTDY_SNAPSHOT_SOURCE_TIMEZONE_REQUIRED",
        )
        confirmation_boundary = source.datetime.astimezone(UTC)
        if not confirmation_boundary <= source.confirmed_at <= snapshot.as_of:
            raise ValueError("HTDY_SNAPSHOT_SOURCE_CONFIRMATION_TIME")


def _validate_historical_structure(snapshot: HtDyRealtimeSnapshot) -> None:
    previous: HtDy15mBarSnapshot | None = None
    for bar in snapshot.historical_bars:
        if bar.status != "confirmed" or bar.source_minutes:
            raise ValueError("HTDY_SNAPSHOT_HISTORICAL_STRUCTURE")
        if previous is not None and (
            bar.identity.bucket_end <= previous.identity.bucket_end
            or not _legal_transition(previous, bar)
        ):
            raise ValueError("HTDY_SNAPSHOT_HISTORICAL_STRUCTURE")
        previous = bar


def _validate_live_structure(snapshot: HtDyRealtimeSnapshot) -> None:
    if not snapshot.buckets:
        raise ValueError("HTDY_SNAPSHOT_LIVE_STRUCTURE")
    previous: HtDy15mBarSnapshot | None = None
    for index, bar in enumerate(snapshot.buckets):
        if bar.status not in {"confirmed", "partial"}:
            raise ValueError("HTDY_SNAPSHOT_LIVE_STRUCTURE")
        if bar.status == "partial" and index != len(snapshot.buckets) - 1:
            raise ValueError("HTDY_SNAPSHOT_LIVE_STRUCTURE")
        if previous is not None and (
            bar.identity.bucket_end <= previous.identity.bucket_end
            or not _legal_transition(previous, bar)
        ):
            raise ValueError("HTDY_SNAPSHOT_LIVE_STRUCTURE")
        previous = bar


def _legal_transition(
    previous: HtDy15mBarSnapshot,
    current: HtDy15mBarSnapshot,
) -> bool:
    left = previous.identity
    right = current.identity
    if left.trading_day == right.trading_day:
        if left.session_name == right.session_name:
            return left.bucket_end == right.bucket_start
        left_bounds = JM_SESSION_BOUNDS.get(left.session_name)
        right_bounds = JM_SESSION_BOUNDS.get(right.session_name)
        return (
            left_bounds is not None
            and right_bounds is not None
            and JM_SESSION_RANK.get(right.session_name, -1)
            == JM_SESSION_RANK.get(left.session_name, -1) + 1
            and left.bucket_end.timetz().replace(tzinfo=None) == left_bounds[1]
            and right.bucket_start.timetz().replace(tzinfo=None)
            == right_bounds[0]
        )
    return left.trading_day < right.trading_day


def _validate_session_geometry(identity: BucketIdentity) -> None:
    bounds = JM_SESSION_BOUNDS.get(identity.session_name)
    if (
        bounds is None
        or identity.session_id
        != f"DCE:{identity.product}:{identity.session_name}"
        or identity.bucket_end - identity.bucket_start != timedelta(minutes=15)
        or identity.bucket_start.minute % 15 != 0
        or identity.bucket_end.minute % 15 != 0
    ):
        raise ValueError("HTDY_SNAPSHOT_SESSION_GEOMETRY")
    start_time = identity.bucket_start.timetz().replace(tzinfo=None)
    end_time = identity.bucket_end.timetz().replace(tzinfo=None)
    if not bounds[0] <= start_time < end_time <= bounds[1]:
        raise ValueError("HTDY_SNAPSHOT_SESSION_GEOMETRY")
    if identity.session_name == "night":
        valid_dates = (
            identity.bucket_start.date() == identity.bucket_end.date()
            and identity.bucket_start.date() < identity.trading_day
        )
    else:
        valid_dates = (
            identity.bucket_start.date()
            == identity.bucket_end.date()
            == identity.trading_day
        )
    if not valid_dates:
        raise ValueError("HTDY_SNAPSHOT_SESSION_GEOMETRY")


def _validate_ohlcv(value: Any) -> None:
    fields = tuple(
        getattr(value, field)
        for field in ("open", "high", "low", "close", "volume")
    )
    if (
        any(not isinstance(item, Decimal) or not item.is_finite() for item in fields)
        or value.low > value.open
        or value.low > value.close
        or value.high < value.open
        or value.high < value.close
        or value.volume < 0
    ):
        raise ValueError("HTDY_SNAPSHOT_OHLCV")


def _require_shanghai(value: datetime, code: str) -> None:
    if value.tzinfo != SHANGHAI:
        raise ValueError(code)


def _require_utc(value: datetime, code: str) -> None:
    if value.tzinfo != UTC:
        raise ValueError(code)
