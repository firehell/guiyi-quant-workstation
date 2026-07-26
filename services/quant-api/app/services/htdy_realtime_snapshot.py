"""Read-only session-aware 15m snapshot construction for HTDY observation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import (
    DataProfile,
    LiveMinuteBar,
    TradingCalendar,
)
from app.services.actual_contract_semantics import (
    has_main_contract_mapping_before,
    load_strict_main_contract_mapping,
)
from app.services.market_data_reader import MarketDataReader
from app.services.market_dominant_reader import continuous_contract_for
from app.services.profile_lineage import ProfileLineageResolver
from app.services.rqdata_ingest.parquet import sha256_file
from app.services.trading_session_clock import TradingSessionClock
from guiyi_quant.indicators import (
    htdy_original_source_sha256,
    realtime_observation_policy_sha256,
)

from app.services.htdy_realtime_models import (
    BucketIdentity,
    HistoricalWarmupIdentity,
    HtDy15mBarSnapshot,
    HtDyRealtimeSnapshot,
    SourceMinuteRef,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
PRODUCT = "jm"
EXCHANGE = "DCE"


class HtDyRealtimeSnapshotResolver:
    """Build one deterministic data state; it intentionally performs no writes."""

    def __init__(self, session: Session, *, project_root: Path) -> None:
        self.session = session
        self.project_root = Path(project_root)
        self.clock = TradingSessionClock(session)
        self.reader = MarketDataReader(session, project_root=self.project_root)

    def resolve(
        self,
        *,
        trading_day: date,
        detected_at: datetime,
        requested_contract: str | None = None,
    ) -> HtDyRealtimeSnapshot:
        with self.session.no_autoflush:
            return self._resolve(
                trading_day=trading_day,
                detected_at=detected_at,
                requested_contract=requested_contract,
            )

    def _resolve(
        self,
        *,
        trading_day: date,
        detected_at: datetime,
        requested_contract: str | None = None,
    ) -> HtDyRealtimeSnapshot:
        as_of = _require_aware(detected_at, code="HTDY_DETECTED_AT")
        calendar_rows = list(
            self.session.scalars(
                select(TradingCalendar).where(
                    TradingCalendar.exchange_code == EXCHANGE,
                    TradingCalendar.trade_date == trading_day,
                )
            )
        )
        _validate_target_calendar_rows(calendar_rows, trading_day)
        actual_contract, mapping_date, mapping_identity = self._mapping(trading_day)
        if (
            requested_contract is not None
            and requested_contract.strip().upper() != actual_contract.upper()
        ):
            raise ValueError("HTDY_REQUESTED_CONTRACT_MISMATCH")
        windows = self.clock.windows_for_trading_day(
            trading_day, product=PRODUCT, exchange=EXCHANGE
        )
        if not windows:
            raise ValueError("HTDY_TRADING_SESSION_MISSING")
        historical, historical_identity = self._historical(
            actual_contract, trading_day, windows[0].start
        )
        source_rows = list(
            self.session.scalars(
                select(LiveMinuteBar)
                .where(
                    LiveMinuteBar.instrument_symbol == PRODUCT,
                    LiveMinuteBar.contract_code == actual_contract,
                    LiveMinuteBar.period == "1m",
                    LiveMinuteBar.trading_day == trading_day,
                )
                .order_by(LiveMinuteBar.bar_datetime, LiveMinuteBar.id)
            )
        )
        source_minutes = self._validate_sources(
            source_rows,
            actual_contract=actual_contract,
            trading_day=trading_day,
            as_of=as_of,
            windows=windows,
        )
        buckets = self._buckets(
            trading_day=trading_day,
            actual_contract=actual_contract,
            as_of=as_of,
            windows=windows,
            sources=source_minutes,
        )
        snapshot_hash = _snapshot_hash(
            mapping=mapping_identity,
            historical_identity=historical_identity,
            historical_bars=historical,
            buckets=buckets,
            source_minutes=source_minutes,
        )
        return HtDyRealtimeSnapshot(
            trading_day=trading_day,
            as_of=as_of,
            actual_contract=actual_contract,
            continuous_contract=continuous_contract_for(PRODUCT),
            mapping_date=mapping_date,
            mapping_identity=mapping_identity,
            historical_bars=tuple(historical),
            historical_identity=historical_identity,
            buckets=tuple(buckets),
            source_minutes=tuple(source_minutes),
            snapshot_sha256=snapshot_hash,
            source_sha256=htdy_original_source_sha256(),
            policy_sha256=realtime_observation_policy_sha256(),
        )

    def _mapping(self, trading_day: date) -> tuple[str, date, dict[str, Any]]:
        try:
            selected = load_strict_main_contract_mapping(
                self.session,
                instrument_symbol=PRODUCT,
                trade_date=trading_day,
            )
        except ValueError as exc:
            codes = {
                "ACTUAL_CONTRACT_MAPPING_CONFLICT": "HTDY_MAPPING_CONFLICT",
                "ACTUAL_CONTRACT_MAPPING_DUPLICATE": "HTDY_MAPPING_DUPLICATE",
                "ACTUAL_CONTRACT_MAPPING_INVALID": (
                    "HTDY_MAPPING_NOT_ACTUAL_CONTRACT"
                ),
            }
            translated = codes.get(str(exc))
            if translated is None:
                raise
            raise ValueError(translated) from exc
        if selected is None:
            earlier = has_main_contract_mapping_before(
                self.session,
                instrument_symbol=PRODUCT,
                trade_date=trading_day,
            )
            raise ValueError(
                "HTDY_MAPPING_STALE" if earlier else "HTDY_MAPPING_MISSING"
            )
        contract = str(selected.contract_code or "").strip().upper()
        if not contract or contract.endswith(".MAIN"):
            raise ValueError("HTDY_MAPPING_NOT_ACTUAL_CONTRACT")
        return (
            contract,
            selected.trade_date,
            {
                "mapping_id": selected.id,
                "product": PRODUCT,
                "provider": selected.provider,
                "rule": selected.rule,
                "rank": selected.rank,
                "mapping_date": selected.trade_date,
                "actual_contract": contract,
                "data_version": selected.data_version,
                "created_at": selected.created_at,
            },
        )

    def _historical(
        self,
        actual_contract: str,
        trading_day: date,
        first_session_start: datetime,
    ) -> tuple[list[HtDy15mBarSnapshot], HistoricalWarmupIdentity]:
        lineage = ProfileLineageResolver(
            self.session, project_root=self.project_root
        ).resolve(
            consumer="signal",
            symbol=PRODUCT,
            contract=actual_contract,
            period="15m",
            profile_id="live_observation_v1",
        )
        if (
            lineage.blocked
            or lineage.market_file is None
            or lineage.market_data_file_id is None
        ):
            raise ValueError(
                f"HTDY_HISTORICAL_PROFILE_BLOCKED:{lineage.blocked_reason or 'missing'}"
            )
        asset = lineage.market_file
        profile = self.session.scalar(
            select(DataProfile).where(
                DataProfile.profile_id == "live_observation_v1",
                DataProfile.is_active.is_(True),
            )
        )
        binding = lineage.binding_snapshot or {}
        if (
            profile is None
            or profile.provider != "rqdata"
            or profile.quality_policy != "active_entry"
            or "actual_contract" not in (profile.contract_roles or [])
            or "15m" not in (profile.periods or [])
            or lineage.profile_id != "live_observation_v1"
            or lineage.quality_policy != "active_entry"
            or lineage.source_interval != "1m"
            or lineage.source_interval_basis != "parquet_column"
            or lineage.data_version != asset.data_version
            or binding.get("profile_id") != "live_observation_v1"
            or binding.get("instrument_symbol") != PRODUCT
            or binding.get("contract_code") != actual_contract
            or binding.get("contract_role") != "actual_contract"
            or binding.get("period") != "15m"
            or binding.get("data_version") != asset.data_version
            or binding.get("market_data_file_id") != asset.id
            or binding.get("binding_status") != "active"
            or binding.get("quality_policy") != "active_entry"
            or binding.get("provider") != "rqdata"
            or binding.get("data_role") != "primary"
            or binding.get("quality_status") != "passed"
            or binding.get("file_data_version") != asset.data_version
            or binding.get("source_interval") != lineage.source_interval
            or binding.get("source_interval_basis") != lineage.source_interval_basis
            or asset.data_type != "bars"
            or asset.instrument_symbol != PRODUCT
            or asset.contract_code != actual_contract
            or asset.period != "15m"
            or asset.provider != "rqdata"
            or asset.data_role != "primary"
            or asset.quality_status != "passed"
        ):
            raise ValueError("HTDY_HISTORICAL_PROFILE_IDENTITY")
        if not asset.checksum:
            raise ValueError("HTDY_HISTORICAL_CHECKSUM_MISSING")
        path = Path(asset.file_path)
        path = path if path.is_absolute() else self.project_root / path
        if not path.is_file() or sha256_file(path) != asset.checksum:
            raise ValueError("HTDY_HISTORICAL_CHECKSUM_DRIFT")
        end = min(
            _market_naive(asset.end_time),
            _market_naive(first_session_start) - timedelta(minutes=1),
        )
        rows = self.reader.load_bars_from_market_file(
            market_data_file_id=asset.id,
            symbol=PRODUCT,
            contract=actual_contract,
            period="15m",
            start=_market_naive(asset.start_time),
            end=end,
            tail=True,
            limit=128,
            passed_only=True,
            expected_provider="rqdata",
            expected_data_role="primary",
            expected_quality_status="passed",
            expected_checksum=asset.checksum,
        )
        if len(rows) != 128:
            raise ValueError("HTDY_HISTORICAL_WARMUP_INSUFFICIENT")
        previous = self.session.scalar(
            select(TradingCalendar.trade_date)
            .where(
                TradingCalendar.exchange_code.in_((EXCHANGE, "CNFE")),
                TradingCalendar.trade_date < trading_day,
                TradingCalendar.is_trading_day.is_(True),
            )
            .order_by(TradingCalendar.trade_date.desc())
            .limit(1)
        )
        if (
            previous is None
            or max(_as_date(row.get("trading_day")) for row in rows) != previous
        ):
            raise ValueError("HTDY_HISTORICAL_PREVIOUS_DAY_STALE")
        normalized = _historical_bars(
            rows,
            self.clock,
            actual_contract=actual_contract,
            data_version=str(lineage.data_version or ""),
        )
        identity = HistoricalWarmupIdentity(
            profile_id="live_observation_v1",
            binding_snapshot=lineage.binding_snapshot or {},
            market_data_file_id=asset.id,
            data_version=str(lineage.data_version or ""),
            checksum=asset.checksum,
            window_sha256=recompute_historical_window_sha256(normalized),
        )
        return normalized, identity

    def _validate_sources(
        self,
        rows: list[LiveMinuteBar],
        *,
        actual_contract: str,
        trading_day: date,
        as_of: datetime,
        windows: list[Any],
    ) -> list[SourceMinuteRef]:
        as_of_utc = _utc(as_of)
        limit = _instant_local_naive(as_of).replace(
            second=0, microsecond=0
        ) - timedelta(minutes=1)
        seen: dict[datetime, SourceMinuteRef] = {}
        output: list[SourceMinuteRef] = []
        for row in rows:
            if (
                row.provider != "rqdata"
                or row.instrument_symbol != PRODUCT
                or row.contract_code != actual_contract
                or row.period != "1m"
                or row.trading_day != trading_day
            ):
                raise ValueError("HTDY_SOURCE_MINUTE_IDENTITY")
            timestamp = _market_naive(row.bar_datetime)
            if timestamp > limit:
                raise ValueError("HTDY_SOURCE_MINUTE_FUTURE")
            if not _inside_window(timestamp, windows):
                raise ValueError("HTDY_SOURCE_MINUTE_OUTSIDE_SESSION")
            if (
                row.bar_status != "confirmed"
                or row.quality_status != "passed"
                or row.confirmed_at is None
            ):
                raise ValueError("HTDY_SOURCE_MINUTE_QUALITY")
            confirmed_at = _utc(row.confirmed_at)
            confirmation_boundary = timestamp.replace(tzinfo=SHANGHAI).astimezone(UTC)
            if not confirmation_boundary <= confirmed_at <= as_of_utc:
                raise ValueError("HTDY_SOURCE_MINUTE_CONFIRMATION_TIME")
            values = [
                _decimal(getattr(row, field))
                for field in ("open", "high", "low", "close", "volume")
            ]
            if (
                values[2] > values[0]
                or values[2] > values[3]
                or values[1] < values[0]
                or values[1] < values[3]
                or values[4] < 0
                or not isinstance(row.id, int)
                or row.id <= 0
                or not isinstance(row.revision, int)
                or isinstance(row.revision, bool)
                or row.revision < 0
            ):
                raise ValueError("HTDY_SOURCE_MINUTE_OHLCV")
            current = SourceMinuteRef(
                live_bar_id=row.id,
                datetime=_shanghai(timestamp),
                trading_day=trading_day,
                provider=row.provider,
                product=row.instrument_symbol,
                actual_contract=row.contract_code,
                period=row.period,
                bar_status=row.bar_status,
                quality_status=row.quality_status,
                revision=row.revision,
                open=values[0],
                high=values[1],
                low=values[2],
                close=values[3],
                volume=values[4],
                confirmed_at=confirmed_at,
            )
            previous = seen.get(timestamp)
            if previous is not None:
                same_payload = (
                    previous.revision == current.revision
                    and previous.open == current.open
                    and previous.high == current.high
                    and previous.low == current.low
                    and previous.close == current.close
                    and previous.volume == current.volume
                    and previous.confirmed_at == current.confirmed_at
                )
                raise ValueError(
                    "HTDY_SOURCE_MINUTE_DUPLICATE"
                    if same_payload
                    else "HTDY_SOURCE_MINUTE_CONFLICT"
                )
            seen[timestamp] = current
            output.append(current)
        return output

    def _buckets(
        self,
        *,
        trading_day: date,
        actual_contract: str,
        as_of: datetime,
        windows: list[Any],
        sources: list[SourceMinuteRef],
    ) -> list[HtDy15mBarSnapshot]:
        local_as_of = _instant_local_naive(as_of).replace(
            second=0, microsecond=0
        ) - timedelta(minutes=1)
        source_by_time = {_market_naive(item.datetime): item for item in sources}
        output: list[HtDy15mBarSnapshot] = []
        for window in windows:
            start = _market_naive(window.start)
            end = _market_naive(window.end)
            cursor = start
            while cursor < end:
                bucket_end = min(cursor + timedelta(minutes=15), end)
                required_end = min(bucket_end, local_as_of)
                if required_end > cursor:
                    expected = [
                        cursor + timedelta(minutes=index)
                        for index in range(
                            1, int((required_end - cursor).total_seconds() // 60) + 1
                        )
                    ]
                    missing = [item for item in expected if item not in source_by_time]
                    if missing:
                        raise ValueError("HTDY_SOURCE_MINUTE_MISSING")
                    members = tuple(source_by_time[item] for item in expected)
                    status = "confirmed" if required_end == bucket_end else "partial"
                    output.append(
                        _aggregate_bucket(
                            trading_day,
                            window.name,
                            cursor,
                            bucket_end,
                            status,
                            members,
                            actual_contract=actual_contract,
                        )
                    )
                cursor = bucket_end
        return output


def _aggregate_bucket(
    trading_day: date,
    session_name: str,
    start: datetime,
    end: datetime,
    status: str,
    members: tuple[SourceMinuteRef, ...],
    *,
    actual_contract: str = "",
) -> HtDy15mBarSnapshot:
    return HtDy15mBarSnapshot(
        identity=BucketIdentity(
            product=PRODUCT,
            actual_contract=actual_contract,
            trading_day=trading_day,
            session_id=f"DCE:jm:{session_name}",
            session_name=session_name,
            bucket_start=_shanghai(start),
            bucket_end=_shanghai(end),
            period="15m",
        ),
        trading_day=trading_day,
        status=status,
        open=members[0].open,
        high=max(item.high for item in members),
        low=min(item.low for item in members),
        close=members[-1].close,
        volume=sum((item.volume for item in members), Decimal("0")),
        source_minutes=members,
    )


def _inside_window(value: datetime, windows: list[Any]) -> bool:
    return any(
        _market_naive(window.start) < value <= _market_naive(window.end)
        for window in windows
    )


def _historical_bars(
    rows: list[dict[str, Any]],
    clock: TradingSessionClock,
    *,
    actual_contract: str,
    data_version: str,
) -> list[HtDy15mBarSnapshot]:
    days = sorted({_as_date(row["trading_day"]) for row in rows})
    identities: dict[tuple[date, datetime], BucketIdentity] = {}
    for window in clock.windows_for_trading_days(
        days, product=PRODUCT, exchange=EXCHANGE
    ):
        cursor = _market_naive(window.start)
        session_end = _market_naive(window.end)
        while cursor < session_end:
            bucket_end = min(cursor + timedelta(minutes=15), session_end)
            key = (window.trading_day, bucket_end)
            if key in identities:
                raise ValueError("HTDY_HISTORICAL_SESSION_CONFLICT")
            identities[key] = BucketIdentity(
                product=PRODUCT,
                actual_contract=actual_contract,
                trading_day=window.trading_day,
                session_id=f"{EXCHANGE}:{PRODUCT}:{window.name}",
                bucket_start=_shanghai(cursor),
                bucket_end=_shanghai(bucket_end),
                period="15m",
                session_name=window.name,
            )
            cursor = bucket_end

    normalized: list[HtDy15mBarSnapshot] = []
    for row in rows:
        row_day = _as_date(row["trading_day"])
        identity = identities.get((row_day, _market_naive(row["datetime"])))
        if identity is None:
            raise ValueError("HTDY_HISTORICAL_SESSION_INVALID")
        normalized.append(
            _historical_bar(
                row,
                identity=identity,
                actual_contract=actual_contract,
                data_version=data_version,
            )
        )
    return normalized


def _historical_bar(
    row: dict[str, Any],
    *,
    identity: BucketIdentity,
    actual_contract: str,
    data_version: str,
) -> HtDy15mBarSnapshot:
    if (
        row.get("symbol") != PRODUCT
        or row.get("contract") != actual_contract
        or row.get("exchange") != EXCHANGE
        or row.get("period") != "15m"
        or row.get("provider") != "rqdata"
        or str(row.get("data_version") or "") != data_version
    ):
        raise ValueError("HTDY_HISTORICAL_BAR_IDENTITY")
    values = {
        field: _decimal(row.get(field))
        for field in ("open", "high", "low", "close", "volume")
    }
    if (
        values["low"] > min(values["open"], values["close"])
        or values["high"] < max(values["open"], values["close"])
        or values["volume"] < 0
    ):
        raise ValueError("HTDY_HISTORICAL_OHLCV")
    return HtDy15mBarSnapshot(
        identity=identity,
        trading_day=identity.trading_day,
        status="confirmed",
        open=values["open"],
        high=values["high"],
        low=values["low"],
        close=values["close"],
        volume=values["volume"],
        source_minutes=(),
    )


def _snapshot_hash(**payload: Any) -> str:
    return _hash(payload)


def recompute_historical_window_sha256(
    bars: tuple[HtDy15mBarSnapshot, ...] | list[HtDy15mBarSnapshot],
) -> str:
    return _hash(tuple(bars))


def recompute_snapshot_sha256(snapshot: HtDyRealtimeSnapshot) -> str:
    return _snapshot_hash(
        mapping=snapshot.mapping_identity,
        historical_identity=snapshot.historical_identity,
        historical_bars=snapshot.historical_bars,
        buckets=snapshot.buckets,
        source_minutes=snapshot.source_minutes,
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f") if value != 0 else "0"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return {
            field: _canonical(getattr(value, field))
            for field in value.__dataclass_fields__
        }
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _validate_target_calendar_rows(
    rows: list[Any],
    trading_day: date,
) -> Any:
    if not rows:
        raise ValueError("HTDY_TRADING_CALENDAR_MISSING")
    signatures = {
        (
            row.exchange_code,
            row.trade_date,
            bool(row.is_trading_day),
            bool(row.has_night_session),
            row.provider,
        )
        for row in rows
    }
    if len(rows) > 1:
        raise ValueError(
            "HTDY_TRADING_CALENDAR_DUPLICATE"
            if len(signatures) == 1
            else "HTDY_TRADING_CALENDAR_CONFLICT"
        )
    selected = rows[0]
    if selected.exchange_code != EXCHANGE or selected.trade_date != trading_day:
        raise ValueError("HTDY_TRADING_CALENDAR_CONFLICT")
    if selected.trade_date.weekday() >= 5 or selected.is_trading_day is not True:
        raise ValueError("HTDY_TRADING_DAY_NOT_OPEN")
    return selected


def _require_aware(value: datetime, *, code: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{code}_TIMEZONE_REQUIRED")
    return _utc(value)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _market_naive(value: datetime) -> datetime:
    """Market DB timestamps encode DCE wall clock even when drivers attach tzinfo."""
    return value.replace(tzinfo=None)


def _instant_local_naive(value: datetime) -> datetime:
    return value.astimezone(SHANGHAI).replace(tzinfo=None)


def _shanghai(value: datetime) -> datetime:
    return value.replace(tzinfo=None).replace(tzinfo=SHANGHAI)


def _as_date(value: Any) -> date:
    return (
        value
        if isinstance(value, date) and not isinstance(value, datetime)
        else date.fromisoformat(str(value))
    )


def _decimal(value: Any) -> Decimal:
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("HTDY_SOURCE_MINUTE_OHLCV") from exc
    if not converted.is_finite():
        raise ValueError("HTDY_SOURCE_MINUTE_OHLCV")
    return converted
