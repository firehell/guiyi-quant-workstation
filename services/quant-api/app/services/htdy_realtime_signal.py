from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT
from app.models.data_center import LiveMinuteBar, TradingCalendar
from app.models.signal import SignalEvent, StrategySignal
from app.signal.events import record_htdy_realtime_signal_event
from app.services.live_target_contracts import LiveTargetContractResolver
from app.services.market_data_reader import MarketDataReader
from app.services.profile_lineage import ProfileLineageResolver
from app.services.rqdata_ingest.parquet import sha256_file
from guiyi_quant.indicators.htdy_original import HtdyOriginalResult
from guiyi_quant.indicators.htdy_original import compute_htdy_original


HTDY_STRATEGY_CODE = "htdy_original_realtime_first_seen"
HTDY_STRATEGY_VERSION = "v1.0"
HTDY_INDICATOR_CODE = "huotian_dayou_original_v0"
HTDY_INDICATOR_VERSION = "original-v0"
HTDY_SIGNAL_POLICY = "htdy_original_xma_15m_first_seen_v1"
HTDY_SOURCE_MODE = "live_realtime_repainting"
HTDY_SOURCE = "live_db_actual_contract_snapshot"
HTDY_PERIOD = "15m"
HTDY_REPAINT_ZONE_BARS = 27


@dataclass(frozen=True)
class HtdyRealtimeBarSnapshot:
    trading_day: date
    bar_start: datetime
    bar_end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_status: str
    source_quality_status: str
    source_bar_count: int
    expected_bar_count: int
    source_bar_ids: tuple[int, ...]
    source_bar_revisions: tuple[int, ...]

    @property
    def snapshot_hash(self) -> str:
        payload = {
            "trading_day": self.trading_day.isoformat(),
            "bar_start": self.bar_start.isoformat(),
            "bar_end": self.bar_end.isoformat(),
            "ohlcv": [self.open, self.high, self.low, self.close, self.volume],
            "bar_status": self.bar_status,
            "source_quality_status": self.source_quality_status,
            "source_bar_ids": list(self.source_bar_ids),
            "source_bar_revisions": list(self.source_bar_revisions),
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class HtdyRealtimeSignalCandidate:
    symbol: str
    continuous_contract: str
    actual_contract: str
    dominant_mapping_date: date
    period: str
    bar_start: datetime
    bar_end: datetime
    detected_at: datetime
    trigger_price: float
    direction: str
    observation_bar_status: str
    source_quality_status: str
    profile_id: str
    market_data_file_id: int
    trigger_live_bar_id: int
    trigger_live_bar_revision: int
    trigger_snapshot_hash: str
    lineage: dict[str, object]


@dataclass(frozen=True)
class HtdyRealtimeEvaluationContext:
    bars: tuple[dict[str, object], ...]
    trigger_snapshot: HtdyRealtimeBarSnapshot
    profile_id: str
    market_data_file_id: int


@dataclass(frozen=True)
class HtdyRealtimeSignalWriteResult:
    created: int
    changed: int
    unchanged: int
    blocked: int
    event_ids: tuple[int, ...]
    blocked_reasons: tuple[dict[str, object], ...]


def build_15m_snapshots(
    rows: Sequence[Mapping[str, object]],
) -> list[HtdyRealtimeBarSnapshot]:
    ordered = sorted(rows, key=lambda row: _datetime_value(row.get("datetime")))
    if not ordered:
        return []

    blocks: list[list[Mapping[str, object]]] = []
    current: list[Mapping[str, object]] = []
    previous_time: datetime | None = None
    previous_day: date | None = None
    for row in ordered:
        row_time = _datetime_value(row.get("datetime"))
        row_day = _date_value(row.get("trading_day"))
        if (
            current
            and (
                row_day != previous_day
                or previous_time is None
                or (row_time - previous_time).total_seconds() > 90
            )
        ):
            blocks.append(current)
            current = []
        current.append(row)
        previous_time = row_time
        previous_day = row_day
    if current:
        blocks.append(current)

    snapshots: list[HtdyRealtimeBarSnapshot] = []
    for block in blocks:
        for offset in range(0, len(block), 15):
            bucket = block[offset : offset + 15]
            first = bucket[0]
            first_time = _datetime_value(first.get("datetime"))
            bar_start = first_time - timedelta(minutes=1)
            bar_end = first_time + timedelta(minutes=14)
            quality = (
                "passed"
                if all(
                    str(row.get("quality_status") or "") == "passed"
                    and str(row.get("bar_status") or "") == "confirmed"
                    for row in bucket
                )
                else "blocked"
            )
            snapshots.append(
                HtdyRealtimeBarSnapshot(
                    trading_day=_date_value(first.get("trading_day")),
                    bar_start=bar_start,
                    bar_end=bar_end,
                    open=_float_value(first.get("open")),
                    high=max(_float_value(row.get("high")) for row in bucket),
                    low=min(_float_value(row.get("low")) for row in bucket),
                    close=_float_value(bucket[-1].get("close")),
                    volume=sum(_float_value(row.get("volume")) for row in bucket),
                    bar_status="confirmed" if len(bucket) == 15 else "partial",
                    source_quality_status=quality,
                    source_bar_count=len(bucket),
                    expected_bar_count=15,
                    source_bar_ids=tuple(_int_value(row.get("id")) for row in bucket),
                    source_bar_revisions=tuple(
                        _int_value(row.get("revision")) for row in bucket
                    ),
                )
            )
    return snapshots


def candidates_from_output(
    output: HtdyOriginalResult,
    *,
    bars: Sequence[Mapping[str, object]],
    trigger_snapshot: HtdyRealtimeBarSnapshot,
    detected_at: datetime,
    continuous_contract: str,
    actual_contract: str,
    dominant_mapping_date: date,
    profile_id: str,
    market_data_file_id: int,
) -> list[HtdyRealtimeSignalCandidate]:
    if len(output.datetimes) != len(bars):
        raise ValueError("HTDY output and context bars must align")
    buy_flags = output.fields.get("buy_observation")
    sell_flags = output.fields.get("sell_observation")
    if buy_flags is None or sell_flags is None:
        raise ValueError("HTDY observation fields missing")

    start = max(0, len(bars) - HTDY_REPAINT_ZONE_BARS)
    candidates: list[HtdyRealtimeSignalCandidate] = []
    for index in range(start, len(bars)):
        buy = bool(buy_flags[index])
        sell = bool(sell_flags[index])
        if not buy and not sell:
            continue
        direction = "conflict" if buy and sell else "long" if buy else "short"
        row = bars[index]
        bar_end = _datetime_value(row.get("bar_end") or row.get("datetime"))
        bar_start = _datetime_value(
            row.get("bar_start") or (bar_end - timedelta(minutes=15))
        )
        trigger_live_bar_id = trigger_snapshot.source_bar_ids[-1]
        trigger_revision = trigger_snapshot.source_bar_revisions[-1]
        trigger_price = float(output.close[index])
        lineage = {
            "schema_version": "signal_review_lineage_v2",
            "resolver_name": "ProfileLineageResolver",
            "resolver_contract_version": "signal_profile_v1",
            "quality_policy": "passed_source_1m_realtime_snapshot_v1",
            "source_mode": HTDY_SOURCE_MODE,
            "primary": {
                "profile_id": profile_id,
                "market_data_file_id": market_data_file_id,
                "instrument_symbol": "jm",
                "contract_code": actual_contract,
                "period": HTDY_PERIOD,
                "provider": "rqdata",
                "data_role": "primary",
                "quality_status": "passed",
            },
            "contract": {
                "continuous_contract": continuous_contract,
                "actual_contract": actual_contract,
                "dominant_mapping_date": dominant_mapping_date.isoformat(),
            },
            "bar": {
                "bar_start": bar_start.isoformat(),
                "bar_end": bar_end.isoformat(),
                "trigger_price": trigger_price,
                "confirmation_mode": HTDY_SOURCE_MODE,
                "bar_status": str(row.get("bar_status") or "confirmed"),
            },
            "live_detection_snapshot": {
                "detected_at": _aware(detected_at).isoformat(),
                "trigger_live_bar_id": trigger_live_bar_id,
                "trigger_live_bar_revision": trigger_revision,
                "snapshot_hash": trigger_snapshot.snapshot_hash,
                "source_1m_ids": list(trigger_snapshot.source_bar_ids),
                "source_1m_revisions": list(
                    trigger_snapshot.source_bar_revisions
                ),
                "source_bar_count": trigger_snapshot.source_bar_count,
                "expected_bar_count": trigger_snapshot.expected_bar_count,
                "bar_status": trigger_snapshot.bar_status,
                "source_quality_status": trigger_snapshot.source_quality_status,
                "ohlcv": {
                    "open": trigger_snapshot.open,
                    "high": trigger_snapshot.high,
                    "low": trigger_snapshot.low,
                    "close": trigger_snapshot.close,
                    "volume": trigger_snapshot.volume,
                },
            },
            "indicator": {
                "indicator_code": HTDY_INDICATOR_CODE,
                "indicator_version": HTDY_INDICATOR_VERSION,
                "signal_policy": HTDY_SIGNAL_POLICY,
                "future_looking": True,
                "repainting_accepted": True,
                "repaint_zone_bars": HTDY_REPAINT_ZONE_BARS,
                "first_seen_no_retraction": True,
            },
        }
        candidates.append(
            HtdyRealtimeSignalCandidate(
                symbol="jm",
                continuous_contract=continuous_contract,
                actual_contract=actual_contract,
                dominant_mapping_date=dominant_mapping_date,
                period=HTDY_PERIOD,
                bar_start=bar_start,
                bar_end=bar_end,
                detected_at=_aware(detected_at),
                trigger_price=trigger_price,
                direction=direction,
                observation_bar_status=str(
                    row.get("bar_status") or "confirmed"
                ),
                source_quality_status=trigger_snapshot.source_quality_status,
                profile_id=profile_id,
                market_data_file_id=market_data_file_id,
                trigger_live_bar_id=trigger_live_bar_id,
                trigger_live_bar_revision=trigger_revision,
                trigger_snapshot_hash=trigger_snapshot.snapshot_hash,
                lineage=lineage,
            )
        )
    return candidates


class HtdyRealtimeContextResolver:
    """Resolve passed historical 15m warm-up plus current 1m-derived snapshots."""

    def __init__(
        self,
        session: Session,
        *,
        project_root: Path = PROJECT_ROOT,
    ) -> None:
        self.session = session
        self.project_root = project_root
        self.market_reader = MarketDataReader(session, project_root=project_root)

    def resolve(
        self,
        *,
        actual_contract: str,
        profile_id: str,
        limit: int,
    ) -> HtdyRealtimeEvaluationContext:
        lineage = ProfileLineageResolver(
            self.session,
            project_root=self.project_root,
        ).resolve(
            consumer="signal",
            symbol="jm",
            contract=actual_contract,
            period=HTDY_PERIOD,
            profile_id=profile_id,
            allow_warning_quality=False,
        )
        market_file = lineage.market_file
        if (
            lineage.blocked
            or market_file is None
            or lineage.market_data_file_id is None
        ):
            raise ValueError(
                f"htdy_historical_context_{lineage.blocked_reason or 'missing'}"
            )
        if (
            market_file.quality_status != "passed"
            or market_file.data_role != "primary"
            or market_file.provider not in {"rqdata", "local_parquet"}
        ):
            raise ValueError("htdy_historical_context_quality_blocked")
        raw_path = Path(market_file.file_path)
        physical_path = (
            raw_path if raw_path.is_absolute() else self.project_root / raw_path
        )
        if (
            not market_file.checksum
            or not physical_path.is_file()
            or sha256_file(physical_path) != market_file.checksum
        ):
            raise ValueError("htdy_historical_context_file_drift")

        latest_day = self.session.scalar(
            select(func.max(LiveMinuteBar.trading_day)).where(
                LiveMinuteBar.instrument_symbol == "jm",
                LiveMinuteBar.contract_code == actual_contract,
                LiveMinuteBar.period == "1m",
                LiveMinuteBar.provider == "rqdata",
                LiveMinuteBar.bar_status == "confirmed",
                LiveMinuteBar.quality_status == "passed",
            )
        )
        if latest_day is None:
            raise ValueError("htdy_live_1m_missing")
        minute_rows = list(
            self.session.scalars(
                select(LiveMinuteBar)
                .where(
                    LiveMinuteBar.instrument_symbol == "jm",
                    LiveMinuteBar.contract_code == actual_contract,
                    LiveMinuteBar.period == "1m",
                    LiveMinuteBar.provider == "rqdata",
                    LiveMinuteBar.trading_day == latest_day,
                    LiveMinuteBar.bar_status == "confirmed",
                    LiveMinuteBar.quality_status == "passed",
                )
                .order_by(LiveMinuteBar.bar_datetime.asc(), LiveMinuteBar.id.asc())
            )
        )
        snapshots = build_15m_snapshots(
            [_minute_row_payload(row) for row in minute_rows]
        )
        if not snapshots:
            raise ValueError("htdy_live_snapshot_missing")
        previous_day = self.session.scalar(
            select(TradingCalendar.trade_date)
            .where(
                TradingCalendar.exchange_code.in_(("DCE", "CNFE")),
                TradingCalendar.trade_date < latest_day,
                TradingCalendar.is_trading_day.is_(True),
            )
            .order_by(TradingCalendar.trade_date.desc())
        )
        if previous_day is None:
            raise ValueError("htdy_historical_context_calendar_missing")

        historical_rows = self.market_reader.load_bars_from_market_file(
            market_data_file_id=market_file.id,
            symbol="jm",
            contract=actual_contract,
            period=HTDY_PERIOD,
            start=_naive(market_file.start_time),
            end=_naive(market_file.end_time),
            passed_only=True,
            expected_provider=market_file.provider,
            expected_data_role="primary",
            expected_quality_status="passed",
            expected_data_version=market_file.data_version,
            expected_checksum=market_file.checksum,
            limit=max(limit, 128),
            tail=True,
        )
        if not historical_rows:
            raise ValueError("htdy_historical_context_missing")
        max_historical_day = max(
            _date_value(row.get("trading_day")) for row in historical_rows
        )
        if max_historical_day < previous_day:
            raise ValueError("htdy_historical_context_stale")

        merged: dict[str, dict[str, object]] = {}
        for row in historical_rows:
            bar_end = _datetime_value(row.get("datetime") or row.get("time"))
            merged[bar_end.isoformat()] = {
                **row,
                "datetime": bar_end,
                "bar_start": bar_end - timedelta(minutes=15),
                "bar_end": bar_end,
                "bar_status": "confirmed",
                "context_source": "historical",
            }
        for snapshot in snapshots:
            key = snapshot.bar_end.isoformat()
            payload = _snapshot_bar_payload(snapshot)
            existing = merged.get(key)
            if existing is not None and _ohlcv(existing) != _ohlcv(payload):
                raise ValueError("htdy_historical_live_bar_conflict")
            merged[key] = payload

        ordered = tuple(
            merged[key]
            for key in sorted(merged)
        )[-max(limit, 128) :]
        return HtdyRealtimeEvaluationContext(
            bars=ordered,
            trigger_snapshot=snapshots[-1],
            profile_id=profile_id,
            market_data_file_id=int(lineage.market_data_file_id),
        )


class HtdyRealtimeSignalEvaluator:
    def __init__(
        self,
        session: Session,
        *,
        project_root: Path = PROJECT_ROOT,
        target_resolver: object | None = None,
        context_resolver: object | None = None,
        kernel: object = compute_htdy_original,
        now: datetime | None = None,
    ) -> None:
        self.session = session
        self.target_resolver = target_resolver or LiveTargetContractResolver(
            session
        )
        self.context_resolver = context_resolver or HtdyRealtimeContextResolver(
            session,
            project_root=project_root,
        )
        self.kernel = kernel
        self.now = now or datetime.now(UTC)

    def evaluate(
        self,
        *,
        contract: str | None = None,
        profile_id: str = "live_observation_v1",
        limit: int = 500,
    ) -> list[HtdyRealtimeSignalCandidate]:
        target = self.target_resolver.resolve_ready_actual_contract(
            product="jm",
            requested_contract=contract,
        )
        actual_contract = str(target["actual_contract"])
        context = self.context_resolver.resolve(
            actual_contract=actual_contract,
            profile_id=profile_id,
            limit=max(128, min(limit, 10000)),
        )
        bars = list(context.bars)
        output = self.kernel(
            [row["datetime"] for row in bars],
            [row["open"] for row in bars],
            [row["high"] for row in bars],
            [row["low"] for row in bars],
            [row["close"] for row in bars],
            [row["volume"] for row in bars],
        )
        mapping_date = target["dominant_mapping_date"]
        if isinstance(mapping_date, str):
            mapping_date = date.fromisoformat(mapping_date)
        return candidates_from_output(
            output,
            bars=bars,
            trigger_snapshot=context.trigger_snapshot,
            detected_at=self.now,
            continuous_contract=str(target["continuous_contract"]),
            actual_contract=actual_contract,
            dominant_mapping_date=mapping_date,
            profile_id=context.profile_id,
            market_data_file_id=context.market_data_file_id,
        )


class HtdyRealtimeSignalEventService:
    """Append immutable first-seen HTDY SignalEvents."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def persist(
        self,
        candidates: Sequence[HtdyRealtimeSignalCandidate],
    ) -> HtdyRealtimeSignalWriteResult:
        counters = {"created": 0, "changed": 0, "unchanged": 0, "blocked": 0}
        event_ids: list[int] = []
        blocked_reasons: list[dict[str, object]] = []
        for candidate in candidates:
            reasons = _blocked_reasons(candidate)
            if reasons:
                counters["blocked"] += 1
                blocked_reasons.extend(reasons)
                continue
            event, outcome = self._persist_one(candidate)
            counters[outcome] += 1
            if event.id is not None:
                event_ids.append(event.id)
        return HtdyRealtimeSignalWriteResult(
            event_ids=tuple(event_ids),
            blocked_reasons=tuple(blocked_reasons),
            **counters,
        )

    def _persist_one(
        self,
        candidate: HtdyRealtimeSignalCandidate,
    ) -> tuple[SignalEvent, str]:
        dedupe_key = _dedupe_key(candidate)
        existing = self.session.scalar(
            select(StrategySignal).where(StrategySignal.dedupe_key == dedupe_key)
        )
        if existing is not None:
            event = self.session.scalar(
                select(SignalEvent).where(
                    SignalEvent.event_key
                    == f"signal_created:{existing.dedupe_key}:created"
                )
            )
            if event is None:
                raise RuntimeError("htdy signal exists without signal_created event")
            return event, "unchanged"

        signal = _new_signal(candidate, dedupe_key)
        self.session.add(signal)
        self.session.flush()
        event = record_htdy_realtime_signal_event(self.session, signal)
        if event is None:
            raise RuntimeError("failed to create HTDY first-seen SignalEvent")
        return event, "created"


def _blocked_reasons(
    candidate: HtdyRealtimeSignalCandidate,
) -> list[dict[str, object]]:
    checks = (
        (candidate.symbol.lower() == "jm", "HTDY_SYMBOL_BLOCKED"),
        (candidate.period == HTDY_PERIOD, "HTDY_PERIOD_BLOCKED"),
        (
            bool(candidate.actual_contract)
            and not candidate.actual_contract.upper().endswith(".MAIN"),
            "HTDY_ACTUAL_CONTRACT_REQUIRED",
        ),
        (candidate.direction in {"long", "short"}, "HTDY_DIRECTION_BLOCKED"),
        (
            candidate.observation_bar_status in {"partial", "confirmed"},
            "HTDY_BAR_STATUS_BLOCKED",
        ),
        (
            candidate.source_quality_status == "passed",
            "HTDY_SOURCE_1M_QUALITY_BLOCKED",
        ),
        (candidate.trigger_price > 0, "HTDY_TRIGGER_PRICE_BLOCKED"),
        (
            isinstance(candidate.lineage, dict)
            and candidate.lineage.get("schema_version")
            == "signal_review_lineage_v2",
            "HTDY_LINEAGE_BLOCKED",
        ),
    )
    return [
        {
            "code": code,
            "context": {
                "actual_contract": candidate.actual_contract,
                "period": candidate.period,
                "bar_end": candidate.bar_end.isoformat(),
            },
        }
        for allowed, code in checks
        if not allowed
    ]


def _dedupe_key(candidate: HtdyRealtimeSignalCandidate) -> str:
    return ":".join(
        (
            "live",
            HTDY_STRATEGY_CODE,
            HTDY_STRATEGY_VERSION,
            candidate.symbol.lower(),
            candidate.actual_contract.upper(),
            HTDY_PERIOD,
            candidate.bar_end.isoformat(),
            "entry",
        )
    )


def _new_signal(
    candidate: HtdyRealtimeSignalCandidate,
    dedupe_key: str,
) -> StrategySignal:
    return StrategySignal(
        task_no=None,
        dedupe_key=dedupe_key,
        strategy_name=HTDY_STRATEGY_CODE,
        strategy_version=HTDY_STRATEGY_VERSION,
        watchlist_code="htdy_live",
        symbol=candidate.symbol.lower(),
        contract=candidate.actual_contract.upper(),
        product=candidate.symbol.lower(),
        continuous_contract=candidate.continuous_contract.upper(),
        actual_contract=candidate.actual_contract.upper(),
        dominant_mapping_date=candidate.dominant_mapping_date,
        exchange="DCE",
        period=HTDY_PERIOD,
        signal_time=_aware(candidate.detected_at),
        bar_start=_aware(candidate.bar_start),
        bar_end=_aware(candidate.bar_end),
        trigger_price=float(candidate.trigger_price),
        provider="rqdata",
        source=HTDY_SOURCE,
        data_role="primary",
        status="entry_signal",
        direction=candidate.direction,
        signal_level=0,
        score_bucket=0,
        bucket_label="HTDY实时重绘观察",
        current_price=float(candidate.trigger_price),
        target_price=None,
        stop_loss_price=None,
        risk_reward_ratio=None,
        open_volume=0,
        margin_required=0.0,
        risk_amount=0.0,
        account_equity=0.0,
        reasons=[
            "HTDY原版XMA实时首次检测",
            "未来函数且可能重绘",
            "仅供观察，不是交易指令",
        ],
        features={
            "source_mode": HTDY_SOURCE_MODE,
            "signal_policy": HTDY_SIGNAL_POLICY,
            "indicator_code": HTDY_INDICATOR_CODE,
            "indicator_version": HTDY_INDICATOR_VERSION,
            "future_looking": True,
            "repainting_accepted": True,
            "first_seen_no_retraction": True,
            "partial_allowed": True,
            "confirmed_only": False,
            "observation_only": True,
            "not_trading_instruction": True,
            "auto_order": False,
            "observation_bar_status": candidate.observation_bar_status,
            "trigger_live_bar_id": candidate.trigger_live_bar_id,
            "trigger_live_bar_revision": candidate.trigger_live_bar_revision,
            "trigger_snapshot_hash": candidate.trigger_snapshot_hash,
            "formal_lineage": candidate.lineage,
        },
        quality_status={
            "status": "passed",
            "policy": "passed_source_1m_realtime_snapshot_v1",
            "source_1m_status": candidate.source_quality_status,
            "bar_completeness": candidate.observation_bar_status,
            "warnings": ["future_looking", "repainting_accepted"],
        },
        research_contract=False,
        spec_source="htdy_first_seen_v1",
        alert_status="unread",
        profile_id=candidate.profile_id,
        market_data_file_id=candidate.market_data_file_id,
    )


def _datetime_value(value: object) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        raise ValueError("minute datetime missing")
    return value


def _date_value(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise ValueError("minute trading_day missing")


def _float_value(value: object) -> float:
    if value is None:
        raise ValueError("minute numeric value missing")
    result = float(Decimal(str(value)))
    if not result == result:
        raise ValueError("minute numeric value invalid")
    return result


def _int_value(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("minute integer value missing")
    return value


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _minute_row_payload(row: LiveMinuteBar) -> dict[str, object]:
    return {
        "id": int(row.id),
        "revision": int(row.revision or 0),
        "datetime": row.bar_datetime,
        "trading_day": row.trading_day,
        "open": row.open,
        "high": row.high,
        "low": row.low,
        "close": row.close,
        "volume": row.volume,
        "quality_status": row.quality_status,
        "bar_status": row.bar_status,
    }


def _snapshot_bar_payload(
    snapshot: HtdyRealtimeBarSnapshot,
) -> dict[str, object]:
    return {
        "datetime": snapshot.bar_end,
        "bar_start": snapshot.bar_start,
        "bar_end": snapshot.bar_end,
        "trading_day": snapshot.trading_day,
        "open": snapshot.open,
        "high": snapshot.high,
        "low": snapshot.low,
        "close": snapshot.close,
        "volume": snapshot.volume,
        "bar_status": snapshot.bar_status,
        "context_source": "live_snapshot",
    }


def _ohlcv(row: Mapping[str, object]) -> tuple[Decimal, ...]:
    return tuple(
        Decimal(str(row.get(field))).normalize()
        for field in ("open", "high", "low", "close", "volume")
    )


__all__ = [
    "HTDY_INDICATOR_CODE",
    "HTDY_INDICATOR_VERSION",
    "HTDY_PERIOD",
    "HTDY_REPAINT_ZONE_BARS",
    "HTDY_SIGNAL_POLICY",
    "HTDY_SOURCE_MODE",
    "HTDY_STRATEGY_CODE",
    "HTDY_STRATEGY_VERSION",
    "HtdyRealtimeBarSnapshot",
    "HtdyRealtimeContextResolver",
    "HtdyRealtimeEvaluationContext",
    "HtdyRealtimeSignalCandidate",
    "HtdyRealtimeSignalEventService",
    "HtdyRealtimeSignalEvaluator",
    "HtdyRealtimeSignalWriteResult",
    "build_15m_snapshots",
    "candidates_from_output",
]
