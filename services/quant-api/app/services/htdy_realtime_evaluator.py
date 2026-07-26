"""Pure candidate evaluation for the frozen HTDY realtime observation policy."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from guiyi_quant.indicators import (
    RealtimeRepaintingObservationPolicy,
    compute_htdy_original,
    htdy_original_source_sha256,
    realtime_observation_policy_sha256,
    require_realtime_repainting_observation_policy,
)

from app.services.htdy_realtime_models import (
    BlockedObservation,
    HtDy15mBarSnapshot,
    HtDyEvaluationResult,
    HtDyObservationCandidate,
    HtDyRealtimeSnapshot,
    validate_htdy_realtime_snapshot,
)
from app.services.htdy_realtime_snapshot import (
    recompute_historical_window_sha256,
    recompute_snapshot_sha256,
)


class HtDyRealtimeCandidateEvaluator:
    """Stateless evaluator; it deliberately has no Session or writer dependency."""

    def evaluate(
        self, snapshot: HtDyRealtimeSnapshot, *, detected_at: datetime
    ) -> HtDyEvaluationResult:
        validate_htdy_realtime_snapshot(snapshot)
        current = _require_aware(detected_at)
        if current != _require_aware(snapshot.as_of):
            raise ValueError("HTDY_SNAPSHOT_AS_OF_MISMATCH")
        policy = require_realtime_repainting_observation_policy(
            RealtimeRepaintingObservationPolicy()
        )
        expected_source_sha256 = htdy_original_source_sha256()
        expected_policy_sha256 = realtime_observation_policy_sha256()
        if snapshot.source_sha256 != expected_source_sha256:
            raise ValueError("HTDY_SNAPSHOT_SOURCE_HASH_MISMATCH")
        if snapshot.policy_sha256 != expected_policy_sha256:
            raise ValueError("HTDY_SNAPSHOT_POLICY_HASH_MISMATCH")
        if (
            recompute_historical_window_sha256(snapshot.historical_bars)
            != snapshot.historical_identity.window_sha256
        ):
            raise ValueError("HTDY_HISTORICAL_WINDOW_HASH_MISMATCH")
        if recompute_snapshot_sha256(snapshot) != snapshot.snapshot_sha256:
            raise ValueError("HTDY_SNAPSHOT_HASH_MISMATCH")
        historical = list(snapshot.historical_bars)
        all_buckets = [*historical, *snapshot.buckets]
        ordered = [_bar(item) for item in all_buckets]
        result = compute_htdy_original(
            [item["datetime"] for item in ordered],
            [item["open"] for item in ordered],
            [item["high"] for item in ordered],
            [item["low"] for item in ordered],
            [item["close"] for item in ordered],
            [item["volume"] for item in ordered],
        )
        return _scan_observations(
            snapshot,
            policy=policy,
            kernel_result=result,
            current=current,
        )


def _scan_observations(
    snapshot: HtDyRealtimeSnapshot,
    *,
    policy: RealtimeRepaintingObservationPolicy,
    kernel_result: Any,
    current: datetime,
) -> HtDyEvaluationResult:
    all_buckets = [*snapshot.historical_bars, *snapshot.buckets]
    candidates: list[HtDyObservationCandidate] = []
    blocked: list[BlockedObservation] = []
    for index in range(max(0, len(all_buckets) - 27), len(all_buckets)):
        bucket = all_buckets[index]
        buy, sell = (
            bool(kernel_result.buy_observation[index]),
            bool(kernel_result.sell_observation[index]),
        )
        if buy and sell:
            blocked.append(
                BlockedObservation(bucket=bucket, reason="dual_direction_conflict")
            )
        elif buy or sell:
            candidates.append(
                _candidate(
                    snapshot, policy, bucket, "long" if buy else "short", current
                )
            )
    return HtDyEvaluationResult(
        candidates=tuple(candidates),
        blocked=tuple(blocked),
        snapshot_sha256=snapshot.snapshot_sha256,
        evaluated_at=current,
    )


def _candidate(
    snapshot: HtDyRealtimeSnapshot,
    policy: RealtimeRepaintingObservationPolicy,
    bucket: HtDy15mBarSnapshot,
    direction: str,
    detected_at: datetime,
) -> HtDyObservationCandidate:
    if not snapshot.source_minutes:
        raise ValueError("HTDY_SOURCE_MINUTE_MISSING")
    observation_key = hashlib.sha256(
        json.dumps(
            {
                "policy_id": policy.policy_id,
                "strategy_code": policy.strategy_code,
                "strategy_version": policy.strategy_version,
                "product": policy.product,
                "actual_contract": snapshot.actual_contract,
                "bucket": {
                    "trading_day": bucket.identity.trading_day.isoformat(),
                    "session_id": bucket.identity.session_id,
                    "start": bucket.identity.bucket_start.isoformat(),
                    "end": bucket.identity.bucket_end.isoformat(),
                    "period": bucket.identity.period,
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return HtDyObservationCandidate(
        observation_key=observation_key,
        direction=direction,
        detected_at=detected_at,
        detection_price=snapshot.source_minutes[-1].close,
        observed_bar_close=bucket.close,
        bucket=bucket,
        actual_contract=snapshot.actual_contract,
        continuous_contract=snapshot.continuous_contract,
        mapping_date=snapshot.mapping_date,
        strategy_code=policy.strategy_code,
        strategy_version=policy.strategy_version,
        indicator_code=policy.indicator_code,
        indicator_version=policy.indicator_version,
        policy_id=policy.policy_id,
        source_minutes=snapshot.source_minutes,
        historical_identity=snapshot.historical_identity,
        snapshot_sha256=snapshot.snapshot_sha256,
        source_sha256=snapshot.source_sha256,
        policy_sha256=snapshot.policy_sha256,
        period=policy.period,
        source_mode=policy.source_mode,
        detection_mode=policy.detection_mode,
        contract_mode=policy.contract_mode,
        main_contract_rank=policy.main_contract_rank,
        future_looking=policy.future_looking,
        repainting_accepted=policy.repainting_accepted,
        first_seen_no_retraction=policy.first_seen_no_retraction,
    )


def _bar(bucket: HtDy15mBarSnapshot) -> dict[str, Any]:
    return {
        "datetime": bucket.identity.bucket_end,
        "open": bucket.open,
        "high": bucket.high,
        "low": bucket.low,
        "close": bucket.close,
        "volume": bucket.volume,
    }


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("HTDY_DETECTED_AT_TIMEZONE_REQUIRED")
    return value.astimezone(UTC)
