"""Persist immutable HTDY realtime first-seen observations.

This service is intentionally not wired into Runtime.  It reuses the existing
StrategySignal and SignalEvent tables and never creates notifications.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.signal import SignalEvent, StrategySignal
from app.services.futures_contract_utils import continuous_contract_for
from app.services.htdy_realtime_models import (
    HtDyEvaluationResult,
    HtDyObservationCandidate,
)
from app.signal.events import record_htdy_first_seen_event


STRATEGY_CODE = "htdy_original_realtime_first_seen"
STRATEGY_VERSION = "v1.0"
INDICATOR_CODE = "huotian_dayou_original_v0"
INDICATOR_VERSION = "original-v0"
SIGNAL_POLICY = "htdy_original_xma_15m_first_seen_v1"
SOURCE_MODE = "live_realtime_repainting"
SOURCE = "htdy_realtime_snapshot"
PROFILE_ID = "live_observation_v1"


@dataclass(frozen=True)
class HtDyFirstSeenWriteResult:
    created: int
    unchanged: int
    blocked: int
    event_ids: tuple[int, ...]
    blocked_reasons: tuple[str, ...]


class HtDyFirstSeenEventService:
    """Write a first-seen event once and never revise its frozen snapshot."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def persist(
        self,
        result: HtDyEvaluationResult,
    ) -> HtDyFirstSeenWriteResult:
        candidates = tuple(result.candidates)
        for candidate in candidates:
            _validate_candidate(candidate, result)

        created = 0
        unchanged = 0
        event_ids: list[int] = []
        for candidate in candidates:
            event, outcome = self._persist_candidate(candidate)
            if outcome == "created":
                created += 1
            else:
                unchanged += 1
            if event.id is not None:
                event_ids.append(event.id)
        return HtDyFirstSeenWriteResult(
            created=created,
            unchanged=unchanged,
            blocked=len(result.blocked),
            event_ids=tuple(event_ids),
            blocked_reasons=tuple(item.reason for item in result.blocked),
        )

    def _persist_candidate(
        self,
        candidate: HtDyObservationCandidate,
    ) -> tuple[SignalEvent, str]:
        dedupe_key = _dedupe_key(candidate)
        signal = self.session.scalar(
            select(StrategySignal).where(
                StrategySignal.dedupe_key == dedupe_key,
            )
        )
        if signal is not None:
            event = self.session.scalar(
                select(SignalEvent).where(
                    SignalEvent.event_key
                    == f"signal_created:{dedupe_key}:created",
                )
            )
            if event is None:
                raise RuntimeError("HTDY_FIRST_SEEN_EVENT_MISSING")
            return event, "unchanged"

        lineage = _lineage_v2(candidate)
        signal = _new_signal(candidate, dedupe_key, lineage)
        self.session.add(signal)
        self.session.flush()
        event = record_htdy_first_seen_event(self.session, signal)
        if event is None:
            raise RuntimeError("HTDY_FIRST_SEEN_EVENT_CREATE_FAILED")
        return event, "created"


def _validate_candidate(
    candidate: HtDyObservationCandidate,
    result: HtDyEvaluationResult,
) -> None:
    if candidate.direction not in {"long", "short"}:
        raise ValueError("HTDY_FIRST_SEEN_DIRECTION")
    if (
        candidate.strategy_code != STRATEGY_CODE
        or candidate.strategy_version != STRATEGY_VERSION
        or candidate.indicator_code != INDICATOR_CODE
        or candidate.indicator_version != INDICATOR_VERSION
        or candidate.policy_id != SIGNAL_POLICY
        or candidate.period != "15m"
        or candidate.source_mode != SOURCE_MODE
        or candidate.detection_mode != "first_seen"
        or candidate.contract_mode != "actual_rank1"
        or candidate.main_contract_rank != 1
        or candidate.repaint_scan_bars != 27
        or candidate.future_dependency_horizon_bars != 24
        or candidate.future_looking is not True
        or candidate.repainting_accepted is not True
        or candidate.first_seen_no_retraction is not True
    ):
        raise ValueError("HTDY_FIRST_SEEN_POLICY")
    if (
        not _sha256(candidate.observation_key)
        or not _sha256(candidate.snapshot_sha256)
        or not _sha256(candidate.source_sha256)
        or not _sha256(candidate.policy_sha256)
        or result.snapshot_sha256 != candidate.snapshot_sha256
    ):
        raise ValueError("HTDY_FIRST_SEEN_HASH")
    if (
        candidate.actual_contract.upper().endswith(".MAIN")
        or candidate.continuous_contract != continuous_contract_for("jm")
        or candidate.bucket.identity.product != "jm"
        or candidate.bucket.identity.actual_contract
        != candidate.actual_contract
        or candidate.bucket.identity.period != "15m"
        or candidate.bucket.trading_day > candidate.mapping_date
    ):
        raise ValueError("HTDY_FIRST_SEEN_CONTRACT")
    if (
        candidate.historical_identity.profile_id != PROFILE_ID
        or candidate.historical_identity.market_data_file_id <= 0
        or not candidate.source_minutes
        or candidate.detection_price != candidate.source_minutes[-1].close
        or candidate.observed_bar_close != candidate.bucket.close
    ):
        raise ValueError("HTDY_FIRST_SEEN_LINEAGE")
    detected_at = _utc(candidate.detected_at)
    previous_time: datetime | None = None
    source_ids: set[int] = set()
    for source in candidate.source_minutes:
        if (
            source.live_bar_id <= 0
            or source.live_bar_id in source_ids
            or source.provider != "rqdata"
            or source.product != "jm"
            or source.actual_contract != candidate.actual_contract
            or source.trading_day != candidate.mapping_date
            or source.period != "1m"
            or source.bar_status != "confirmed"
            or source.quality_status != "passed"
            or source.revision < 0
            or _utc(source.confirmed_at) > detected_at
            or (
                previous_time is not None
                and source.datetime <= previous_time
            )
        ):
            raise ValueError("HTDY_FIRST_SEEN_SOURCE")
        source_ids.add(source.live_bar_id)
        previous_time = source.datetime


def _new_signal(
    candidate: HtDyObservationCandidate,
    dedupe_key: str,
    lineage: dict[str, Any],
) -> StrategySignal:
    return StrategySignal(
        task_no=None,
        dedupe_key=dedupe_key,
        strategy_name=STRATEGY_CODE,
        strategy_version=STRATEGY_VERSION,
        watchlist_code="htdy_realtime_first_seen",
        symbol="jm",
        contract=candidate.actual_contract,
        product="jm",
        continuous_contract=candidate.continuous_contract,
        actual_contract=candidate.actual_contract,
        dominant_mapping_date=candidate.mapping_date,
        exchange="DCE",
        period=candidate.period,
        signal_time=_utc(candidate.detected_at),
        bar_start=candidate.bucket.identity.bucket_start,
        bar_end=candidate.bucket.identity.bucket_end,
        trigger_price=float(candidate.detection_price),
        provider="rqdata",
        source=SOURCE,
        data_role="primary",
        status="entry_signal",
        direction=candidate.direction,
        signal_level=0,
        score_bucket=0,
        bucket_label="重绘观察",
        current_price=float(candidate.detection_price),
        target_price=None,
        stop_loss_price=None,
        risk_reward_ratio=None,
        open_volume=0,
        margin_required=0.0,
        risk_amount=0.0,
        account_equity=0.0,
        reasons=["htdy_original_xma_first_seen"],
        features={
            "source_mode": SOURCE_MODE,
            "signal_policy": SIGNAL_POLICY,
            "indicator_code": INDICATOR_CODE,
            "indicator_version": INDICATOR_VERSION,
            "observation_only": True,
            "future_looking": True,
            "repainting_accepted": True,
            "first_seen_no_retraction": True,
            "historical_backtest_allowed": False,
            "notification_ready": False,
            "not_trading_instruction": True,
            "auto_order": False,
            "observed_bar_close": _decimal(candidate.observed_bar_close),
            "snapshot_sha256": candidate.snapshot_sha256,
            "formal_lineage": deepcopy(lineage),
        },
        quality_status={
            "status": "passed",
            "scope": "source_evidence_only",
            "strategy_validity": "rejected_research_candidate",
        },
        profile_id=candidate.historical_identity.profile_id,
        market_data_file_id=(
            candidate.historical_identity.market_data_file_id
        ),
        research_contract=True,
        spec_source="htdy_original_realtime_first_seen_v1",
        alert_status="unread",
        is_active=True,
    )


def _lineage_v2(
    candidate: HtDyObservationCandidate,
) -> dict[str, Any]:
    historical = candidate.historical_identity
    primary = {
        **_plain(historical.binding_snapshot),
        "checksum": historical.checksum,
        "historical_window_sha256": historical.window_sha256,
        "previous_trading_day": (
            historical.previous_trading_day.isoformat()
        ),
        "previous_trading_day_exchange": (
            historical.previous_trading_day_exchange
        ),
    }
    bucket = candidate.bucket
    return {
        "schema_version": "signal_review_lineage_v2",
        "resolver_name": "HtDyRealtimeSnapshotResolver",
        "resolver_contract_version": "htdy_realtime_snapshot_v1",
        "quality_policy": "passed_source_1m_realtime_snapshot_v1",
        "source_mode": SOURCE_MODE,
        "primary": primary,
        "context_assets": [],
        "contract": {
            "continuous_contract": candidate.continuous_contract,
            "actual_contract": candidate.actual_contract,
            "dominant_mapping_date": candidate.mapping_date.isoformat(),
            "contract_mode": candidate.contract_mode,
            "main_contract_rank": candidate.main_contract_rank,
        },
        "bar": {
            "trading_day": bucket.trading_day.isoformat(),
            "session_id": bucket.identity.session_id,
            "session_name": bucket.identity.session_name,
            "bar_start": bucket.identity.bucket_start.isoformat(),
            "bar_end": bucket.identity.bucket_end.isoformat(),
            "bar_status": bucket.status,
            "confirmation_mode": SOURCE_MODE,
            "trigger_price": float(candidate.detection_price),
            "observed_bar_close": _decimal(
                candidate.observed_bar_close,
            ),
        },
        "live_detection_snapshot": {
            "observation_key": candidate.observation_key,
            "detected_at": _utc(candidate.detected_at).isoformat(),
            "detection_price": _decimal(candidate.detection_price),
            "snapshot_sha256": candidate.snapshot_sha256,
            "source_sha256": candidate.source_sha256,
            "policy_sha256": candidate.policy_sha256,
            "source_1m": [
                {
                    "live_bar_id": source.live_bar_id,
                    "datetime": source.datetime.isoformat(),
                    "trading_day": source.trading_day.isoformat(),
                    "provider": source.provider,
                    "product": source.product,
                    "actual_contract": source.actual_contract,
                    "period": source.period,
                    "bar_status": source.bar_status,
                    "quality_status": source.quality_status,
                    "revision": source.revision,
                    "open": _decimal(source.open),
                    "high": _decimal(source.high),
                    "low": _decimal(source.low),
                    "close": _decimal(source.close),
                    "volume": _decimal(source.volume),
                    "confirmed_at": _utc(
                        source.confirmed_at,
                    ).isoformat(),
                }
                for source in candidate.source_minutes
            ],
        },
        "indicator": {
            "indicator_code": candidate.indicator_code,
            "indicator_version": candidate.indicator_version,
            "strategy_code": candidate.strategy_code,
            "strategy_version": candidate.strategy_version,
            "signal_policy": candidate.policy_id,
            "repaint_scan_bars": candidate.repaint_scan_bars,
            "future_dependency_horizon_bars": (
                candidate.future_dependency_horizon_bars
            ),
            "future_looking": True,
            "repainting_accepted": True,
            "first_seen_no_retraction": True,
            "historical_backtest_allowed": False,
            "notification_ready": False,
            "auto_order": False,
        },
    }


def _dedupe_key(candidate: HtDyObservationCandidate) -> str:
    return f"htdy-first-seen:{candidate.observation_key}"


def _sha256(value: str) -> bool:
    if len(value) != 64 or value != value.lower():
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("HTDY_FIRST_SEEN_TIMEZONE")
    return value.astimezone(UTC)


def _decimal(value: Decimal) -> str:
    return format(value, "f")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, Decimal):
        return _decimal(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
