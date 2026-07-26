from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from app.services.jm_session_contract import JM_SESSION_ROWS
from app.services.htdy_realtime_models import (
    BucketIdentity,
    HistoricalWarmupIdentity,
    HtDy15mBarSnapshot,
    HtDyRealtimeSnapshot,
    SourceMinuteRef,
)
from guiyi_quant.indicators import (
    RealtimeRepaintingObservationPolicy,
    htdy_original_source_sha256,
    realtime_observation_policy_sha256,
    require_realtime_repainting_observation_policy,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _snapshot() -> HtDyRealtimeSnapshot:
    length = 129
    values = np.full(length, 10.0)
    close = values.copy()
    close[-1] = 10.5
    return _resolver_compatible_snapshot(
        open_=values,
        high=np.maximum(values, close) + 1,
        low=values - 1,
        close=close,
        volume=np.arange(1000, 1000 + length),
    )


def test_evaluator_is_deterministic_read_only_and_exposes_observation_metadata() -> (
    None
):
    from app.services.htdy_realtime_evaluator import _scan_observations

    snapshot = _snapshot()
    total = len(snapshot.historical_bars) + len(snapshot.buckets)
    buy = [False] * total
    buy[-1] = True
    kernel_result = SimpleNamespace(
        buy_observation=buy,
        sell_observation=[False] * total,
    )
    policy = require_realtime_repainting_observation_policy(
        RealtimeRepaintingObservationPolicy()
    )
    first = _scan_observations(
        snapshot,
        policy=policy,
        kernel_result=kernel_result,
        current=snapshot.as_of,
    )
    second = _scan_observations(
        snapshot,
        policy=policy,
        kernel_result=kernel_result,
        current=snapshot.as_of,
    )

    assert first == second
    assert len(first.candidates) == 1
    assert first.writes_enabled is False
    assert first.signal_event_enabled is False
    assert first.notification_enabled is False
    assert first.evaluated_at == snapshot.as_of


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("source_sha256", "wrong", "HTDY_SNAPSHOT_SOURCE_HASH_MISMATCH"),
        ("policy_sha256", "wrong", "HTDY_SNAPSHOT_POLICY_HASH_MISMATCH"),
    ],
)
def test_evaluator_fail_closes_snapshot_kernel_and_policy_hash_drift(
    field: str,
    value: str,
    reason: str,
) -> None:
    from app.services.htdy_realtime_evaluator import HtDyRealtimeCandidateEvaluator

    snapshot = replace(_snapshot(), **{field: value})
    with pytest.raises(ValueError, match=reason):
        HtDyRealtimeCandidateEvaluator().evaluate(snapshot, detected_at=snapshot.as_of)


def test_public_evaluator_rejects_arbitrary_kernel_injection() -> None:
    from app.services.htdy_realtime_evaluator import HtDyRealtimeCandidateEvaluator

    with pytest.raises(TypeError):
        HtDyRealtimeCandidateEvaluator(kernel=lambda *args: None)


def test_public_evaluate_calls_frozen_kernel_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.htdy_realtime_evaluator as module

    snapshot = _snapshot()
    frozen_kernel = module.compute_htdy_original
    calls = 0

    def counted_kernel(*args, **kwargs):
        nonlocal calls
        calls += 1
        return frozen_kernel(*args, **kwargs)

    monkeypatch.setattr(module, "compute_htdy_original", counted_kernel)
    module.HtDyRealtimeCandidateEvaluator().evaluate(
        snapshot,
        detected_at=snapshot.as_of,
    )

    assert calls == 1


def test_evaluator_requires_timezone_and_matching_snapshot_as_of() -> None:
    from app.services.htdy_realtime_evaluator import HtDyRealtimeCandidateEvaluator

    snapshot = _snapshot()
    evaluator = HtDyRealtimeCandidateEvaluator()
    try:
        evaluator.evaluate(snapshot, detected_at=datetime(2026, 7, 27, 1, 15))
    except ValueError as exc:
        assert "HTDY_DETECTED_AT" in str(exc)
    else:
        raise AssertionError("naive detected_at must fail")
    try:
        evaluator.evaluate(snapshot, detected_at=snapshot.as_of + timedelta(seconds=1))
    except ValueError as exc:
        assert "HTDY_SNAPSHOT_AS_OF_MISMATCH" in str(exc)
    else:
        raise AssertionError("as-of drift must fail")


def test_real_kernel_tail_can_create_an_old_warmup_candidate() -> None:
    """Step 1's frozen centered-XMA regression must survive evaluator bucket mapping."""
    from app.services.htdy_realtime_evaluator import HtDyRealtimeCandidateEvaluator

    length = 130
    rng = np.random.default_rng(3838)
    center = 10 + np.cumsum(rng.normal(0, 0.08, length))
    body = rng.normal(0, 0.12, length)
    open_ = center - body / 2
    close = center + body / 2
    spread = np.abs(rng.normal(0.12, 0.08, length)) + 0.01
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = 1000 + rng.integers(0, 100, length)
    before = _resolver_compatible_snapshot(
        open_=open_[:129],
        high=high[:129],
        low=low[:129],
        close=close[:129],
        volume=volume[:129],
    )
    after = _resolver_compatible_snapshot(
        open_=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )
    target_end = before.historical_bars[127].identity.bucket_end

    assert not any(
        item.bucket.identity.bucket_end == target_end
        for item in HtDyRealtimeCandidateEvaluator()
        .evaluate(before, detected_at=before.as_of)
        .candidates
    )
    candidates = (
        HtDyRealtimeCandidateEvaluator()
        .evaluate(after, detected_at=after.as_of)
        .candidates
    )
    assert any(
        item.direction == "long" and item.bucket.identity.bucket_end == target_end
        for item in candidates
    )


def test_real_kernel_future_live_tail_removes_existing_candidate() -> None:
    """A new resolver-shaped live bucket can repaint an older first-seen candidate."""
    from app.services.htdy_realtime_evaluator import HtDyRealtimeCandidateEvaluator

    length = 151
    rng = np.random.default_rng(20260729)
    for _trial in range(278):
        center = 10 + np.cumsum(rng.normal(0, 0.08, length))
        body = rng.normal(0, 0.12, length)
        open_ = center - body / 2
        close = center + body / 2
        spread = np.abs(rng.normal(0.12, 0.08, length)) + 0.01
        high = np.maximum(open_, close) + spread
        low = np.minimum(open_, close) - spread
        volume = 1000 + rng.integers(0, 100, length)

    after_open = open_.copy()
    after_high = high.copy()
    after_low = low.copy()
    after_close = close.copy()
    after_open[-1] = after_high[-1] = after_low[-1] = after_close[-1] = center[-1] + 20
    before = _resolver_compatible_snapshot(
        open_=open_[:150],
        high=high[:150],
        low=low[:150],
        close=close[:150],
        volume=volume[:150],
    )
    after = _resolver_compatible_snapshot(
        open_=after_open,
        high=after_high,
        low=after_low,
        close=after_close,
        volume=volume,
    )

    before_result = HtDyRealtimeCandidateEvaluator().evaluate(
        before, detected_at=before.as_of
    )
    after_result = HtDyRealtimeCandidateEvaluator().evaluate(
        after, detected_at=after.as_of
    )
    target = before.buckets[19]
    assert len(before.historical_bars) == len(after.historical_bars) == 128
    assert len(before.buckets) == 22
    assert len(after.buckets) == 23
    assert (*before.historical_bars, *before.buckets)[147] == target
    assert [
        item.direction
        for item in before_result.candidates
        if item.bucket == target
    ] == ["long"]
    assert not any(item.bucket == target for item in before_result.blocked)
    assert not any(
        item.bucket == target
        for item in (*after_result.candidates, *after_result.blocked)
    )


def _resolver_compatible_snapshot(
    *,
    open_,
    high,
    low,
    close,
    volume,
) -> HtDyRealtimeSnapshot:
    from app.services.htdy_realtime_snapshot import (
        recompute_historical_window_sha256,
        recompute_snapshot_sha256,
    )

    historical_days = [
        date(2026, 7, 14),
        date(2026, 7, 15),
        date(2026, 7, 16),
        date(2026, 7, 17),
        date(2026, 7, 20),
        date(2026, 7, 21),
        date(2026, 7, 22),
        date(2026, 7, 23),
        date(2026, 7, 24),
    ]
    historical_layout = [
        (day, session_name, bucket_end)
        for day in historical_days
        for session_name, bucket_end in _canonical_bucket_layout(
            trading_day=day,
        )
    ][-128:]
    historical: list[HtDy15mBarSnapshot] = []
    for index, (day, session_name, bucket_end) in enumerate(historical_layout):
        historical.append(
            _bar_from_arrays(
                index=index,
                trading_day=day,
                session_name=session_name,
                bucket_end=bucket_end,
                open_=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                source_minutes=(),
            )
        )

    live: list[HtDy15mBarSnapshot] = []
    all_sources: list[SourceMinuteRef] = []
    live_count = len(open_) - 128
    live_layout = _canonical_bucket_layout(
        trading_day=date(2026, 7, 27),
        night_anchor=date(2026, 7, 24),
    )
    if not 1 <= live_count <= len(live_layout):
        raise ValueError("fixture live bucket count exceeds canonical JM sessions")
    for live_index, (session_name, bucket_end) in enumerate(
        live_layout[:live_count]
    ):
        index = 128 + live_index
        bucket_start = bucket_end - timedelta(minutes=15)
        members = tuple(
            SourceMinuteRef(
                live_bar_id=live_index * 15 + minute,
                datetime=(bucket_start + timedelta(minutes=minute)).replace(
                    tzinfo=SHANGHAI
                ),
                trading_day=date(2026, 7, 27),
                provider="rqdata",
                product="jm",
                actual_contract="JM2609",
                period="1m",
                bar_status="confirmed",
                quality_status="passed",
                revision=0,
                open=Decimal(str(open_[index])),
                high=Decimal(str(high[index])),
                low=Decimal(str(low[index])),
                close=Decimal(str(close[index])),
                volume=(
                    Decimal("0")
                    if minute < 15
                    else Decimal(str(volume[index]))
                ),
                confirmed_at=(bucket_start + timedelta(minutes=minute))
                .replace(tzinfo=SHANGHAI)
                .astimezone(UTC),
            )
            for minute in range(1, 16)
        )
        all_sources.extend(members)
        live.append(
            _bar_from_arrays(
                index=index,
                trading_day=date(2026, 7, 27),
                session_name=session_name,
                bucket_end=bucket_end,
                open_=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                source_minutes=members,
            )
        )

    as_of = (live[-1].identity.bucket_end + timedelta(minutes=1)).astimezone(UTC)
    historical_identity = HistoricalWarmupIdentity(
        profile_id="live_observation_v1",
        binding_snapshot={
            "contract_role": "actual_contract",
            "period": "15m",
            "market_data_file_id": 1,
            "quality_policy": "active_entry",
            "source_interval": "1m",
        },
        market_data_file_id=1,
        data_version="fixture",
        checksum="abc",
        window_sha256=recompute_historical_window_sha256(historical),
    )
    snapshot = HtDyRealtimeSnapshot(
        trading_day=date(2026, 7, 27),
        as_of=as_of,
        actual_contract="JM2609",
        continuous_contract="JM889",
        mapping_date=date(2026, 7, 27),
        mapping_identity={
            "mapping_id": 7,
            "product": "jm",
            "provider": "rqdata",
            "rule": "volume_open_interest",
            "rank": 1,
            "mapping_date": date(2026, 7, 27),
            "actual_contract": "JM2609",
            "data_version": "fixture",
            "created_at": datetime(2026, 7, 27, tzinfo=UTC),
        },
        historical_bars=tuple(historical),
        historical_identity=historical_identity,
        buckets=tuple(live),
        source_minutes=tuple(all_sources),
        snapshot_sha256="",
        source_sha256=htdy_original_source_sha256(),
        policy_sha256=realtime_observation_policy_sha256(),
    )
    return replace(snapshot, snapshot_sha256=recompute_snapshot_sha256(snapshot))


def _canonical_bucket_layout(
    *,
    trading_day: date,
    night_anchor: date | None = None,
) -> list[tuple[str, datetime]]:
    layout: list[tuple[str, datetime]] = []
    for session_name, start, end in JM_SESSION_ROWS:
        if session_name == "night":
            if night_anchor is None:
                continue
            anchor = night_anchor
        else:
            anchor = trading_day
        cursor = datetime.combine(anchor, start)
        session_end = datetime.combine(anchor, end)
        while cursor < session_end:
            cursor = min(cursor + timedelta(minutes=15), session_end)
            layout.append((session_name, cursor))
    return layout


def _bar_from_arrays(
    *,
    index: int,
    trading_day: date,
    session_name: str,
    bucket_end: datetime,
    open_,
    high,
    low,
    close,
    volume,
    source_minutes: tuple[SourceMinuteRef, ...],
) -> HtDy15mBarSnapshot:
    aware_end = bucket_end.replace(tzinfo=SHANGHAI)
    return HtDy15mBarSnapshot(
        identity=BucketIdentity(
            product="jm",
            actual_contract="JM2609",
            trading_day=trading_day,
            session_id=f"DCE:jm:{session_name}",
            session_name=session_name,
            bucket_start=aware_end - timedelta(minutes=15),
            bucket_end=aware_end,
            period="15m",
        ),
        trading_day=trading_day,
        status="confirmed",
        open=Decimal(str(open_[index])),
        high=Decimal(str(high[index])),
        low=Decimal(str(low[index])),
        close=Decimal(str(close[index])),
        volume=Decimal(str(volume[index])),
        source_minutes=source_minutes,
    )


def _snapshot_from_values(values) -> HtDyRealtimeSnapshot:
    return _resolver_compatible_snapshot(
        open_=values["open"],
        high=values["high"],
        low=values["low"],
        close=values["close"],
        volume=values["volume"],
    )


def test_injected_kernel_scans_27_bars_and_preserves_observation_contract() -> None:
    from app.services.htdy_realtime_evaluator import _scan_observations

    snapshot = _snapshot()
    total = len(snapshot.historical_bars) + len(snapshot.buckets)
    buy = [False] * total
    sell = [False] * total
    buy[total - 28] = True  # excluded
    buy[total - 27] = True  # included long
    sell[total - 2] = True  # included short
    buy[total - 1] = sell[total - 1] = True  # blocked only

    policy = require_realtime_repainting_observation_policy(
        RealtimeRepaintingObservationPolicy()
    )
    result = _scan_observations(
        snapshot,
        policy=policy,
        kernel_result=SimpleNamespace(
            buy_observation=buy,
            sell_observation=sell,
        ),
        current=snapshot.as_of,
    )

    assert [item.direction for item in result.candidates] == ["long", "short"]
    assert (
        len(result.blocked) == 1
        and result.blocked[0].reason == "dual_direction_conflict"
    )
    long = result.candidates[0]
    assert (
        long.detection_price
        == snapshot.source_minutes[-1].close
        != long.observed_bar_close
    )
    assert (
        long.strategy_code,
        long.strategy_version,
        long.indicator_code,
        long.indicator_version,
        long.policy_id,
    ) == (
        "htdy_original_realtime_first_seen",
        "v1.0",
        "huotian_dayou_original_v0",
        "original-v0",
        "htdy_original_xma_15m_first_seen_v1",
    )
    assert (
        long.period,
        long.source_mode,
        long.detection_mode,
        long.contract_mode,
        long.main_contract_rank,
    ) == ("15m", "live_realtime_repainting", "first_seen", "actual_rank1", 1)
    assert (
        long.source_sha256,
        long.policy_sha256,
        long.repaint_scan_bars,
        long.future_dependency_horizon_bars,
    ) == (htdy_original_source_sha256(), realtime_observation_policy_sha256(), 27, 24)
    assert (
        long.future_looking,
        long.repainting_accepted,
        long.first_seen_no_retraction,
        long.source_minutes,
    ) == (True, True, True, snapshot.source_minutes)
    assert long.detected_at == snapshot.as_of
    assert long.bucket == snapshot.historical_bars[total - 27]
    assert long.historical_identity == snapshot.historical_identity
    assert (long.actual_contract, long.continuous_contract, long.mapping_date) == (
        "JM2609",
        "JM889",
        date(2026, 7, 27),
    )
    assert long.bucket.identity.period == "15m"
    assert long.bucket.status == "confirmed"

    changed_sources = (
        replace(snapshot.source_minutes[0], revision=99),
        *snapshot.source_minutes[1:],
    )
    changed_bucket = replace(
        snapshot.buckets[0],
        source_minutes=changed_sources,
    )
    changed = replace(
        snapshot,
        buckets=(changed_bucket,),
        source_minutes=changed_sources,
        snapshot_sha256="different",
    )
    sell_only = [False] * total
    sell_only[total - 27] = True
    flipped = _scan_observations(
        changed,
        policy=policy,
        kernel_result=SimpleNamespace(
            buy_observation=[False] * total,
            sell_observation=sell_only,
        ),
        current=changed.as_of,
    )
    assert flipped.candidates[0].direction == "short"
    assert flipped.candidates[0].observation_key == long.observation_key


def test_observation_key_ignores_next_mapping_date_direction_revision_and_hash() -> (
    None
):
    from app.services.htdy_realtime_evaluator import _scan_observations

    first = _snapshot()
    total = len(first.historical_bars) + len(first.buckets)
    target_index = total - 2
    first_buy = [False] * total
    first_buy[target_index] = True
    policy = require_realtime_repainting_observation_policy(
        RealtimeRepaintingObservationPolicy()
    )
    first_result = _scan_observations(
        first,
        policy=policy,
        kernel_result=SimpleNamespace(
            buy_observation=first_buy,
            sell_observation=[False] * total,
        ),
        current=first.as_of,
    )

    next_day = date(2026, 7, 28)
    next_as_of = datetime(2026, 7, 28, 1, 15, tzinfo=UTC)
    revised_sources = tuple(
        replace(
            source,
            datetime=datetime(2026, 7, 28, 9, tzinfo=SHANGHAI)
            + timedelta(minutes=index),
            trading_day=next_day,
            revision=99,
            confirmed_at=(
                datetime(2026, 7, 28, 9, tzinfo=SHANGHAI)
                + timedelta(minutes=index)
            ).astimezone(UTC),
        )
        for index, source in enumerate(first.source_minutes, start=1)
    )
    next_identity = replace(
        first.buckets[0].identity,
        trading_day=next_day,
        session_id="DCE:jm:day_am_1",
        session_name="day_am_1",
        bucket_start=datetime(2026, 7, 28, 9, tzinfo=SHANGHAI),
        bucket_end=datetime(2026, 7, 28, 9, 15, tzinfo=SHANGHAI),
    )
    next_bucket = replace(
        first.buckets[0],
        identity=next_identity,
        trading_day=next_day,
        source_minutes=revised_sources,
    )
    later = replace(
        first,
        trading_day=next_day,
        as_of=next_as_of,
        mapping_date=next_day,
        mapping_identity={
            **dict(first.mapping_identity),
            "mapping_id": 8,
            "mapping_date": next_day,
            "data_version": "fixture-next",
        },
        buckets=(next_bucket,),
        source_minutes=revised_sources,
        snapshot_sha256="next-state",
    )
    later_sell = [False] * total
    later_sell[target_index] = True
    later_result = _scan_observations(
        later,
        policy=policy,
        kernel_result=SimpleNamespace(
            buy_observation=[False] * total,
            sell_observation=later_sell,
        ),
        current=later.as_of,
    )

    assert first_result.candidates[0].bucket == later_result.candidates[0].bucket
    assert first_result.candidates[0].direction == "long"
    assert later_result.candidates[0].direction == "short"
    assert (
        first_result.candidates[0].observation_key
        == later_result.candidates[0].observation_key
    )


def test_snapshot_ingress_deep_freezes_mapping_and_forces_collection_tuples() -> None:
    base = _snapshot()
    raw_mapping = {
        "mapping_id": 7,
        "product": "jm",
        "provider": "rqdata",
        "rule": "volume_open_interest",
        "rank": 1,
        "mapping_date": date(2026, 7, 27),
        "actual_contract": "JM2609",
        "data_version": "fixture",
        "created_at": datetime(2026, 7, 27, tzinfo=UTC),
        "nested": {"ids": [7]},
    }

    snapshot = HtDyRealtimeSnapshot(
        trading_day=base.trading_day,
        as_of=base.as_of,
        actual_contract=base.actual_contract,
        continuous_contract=base.continuous_contract,
        mapping_date=base.mapping_date,
        mapping_identity=raw_mapping,
        historical_bars=list(base.historical_bars),
        historical_identity=base.historical_identity,
        buckets=list(base.buckets),
        source_minutes=list(base.source_minutes),
        snapshot_sha256=base.snapshot_sha256,
        source_sha256=base.source_sha256,
        policy_sha256=base.policy_sha256,
    )
    raw_mapping["nested"]["ids"].append(8)

    assert isinstance(snapshot.historical_bars, tuple)
    assert isinstance(snapshot.buckets, tuple)
    assert isinstance(snapshot.source_minutes, tuple)
    assert snapshot.mapping_identity["nested"]["ids"] == (7,)
    with pytest.raises(TypeError):
        snapshot.mapping_identity["data_version"] = "mutated"


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("product", "HTDY_SNAPSHOT_BAR_IDENTITY"),
        ("contract", "HTDY_SNAPSHOT_BAR_IDENTITY"),
        ("period", "HTDY_SNAPSHOT_BAR_IDENTITY"),
        ("trading_day", "HTDY_SNAPSHOT_TRADING_DAY_IDENTITY"),
        ("timezone", "HTDY_SNAPSHOT_SOURCE_TIMEZONE_REQUIRED"),
        ("membership", "HTDY_SNAPSHOT_SOURCE_MEMBERSHIP"),
        ("source_bucket", "HTDY_SNAPSHOT_SOURCE_MEMBERSHIP"),
    ],
)
def test_snapshot_ingress_rejects_cross_identity_drift(
    mutation: str,
    reason: str,
) -> None:
    snapshot = _snapshot()
    bucket = snapshot.buckets[0]
    source = snapshot.source_minutes[0]
    changes = {}
    if mutation in {"product", "contract", "period"}:
        identity_changes = {
            "product": {"product": "i"},
            "contract": {"actual_contract": "JM2611"},
            "period": {"period": "5m"},
        }[mutation]
        changes["buckets"] = (
            replace(
                bucket,
                identity=replace(bucket.identity, **identity_changes),
            ),
        )
    elif mutation == "trading_day":
        changes["buckets"] = (
            replace(
                bucket,
                trading_day=date(2026, 7, 28),
                identity=replace(
                    bucket.identity,
                    trading_day=date(2026, 7, 28),
                ),
            ),
        )
    elif mutation == "timezone":
        naive = replace(source, datetime=source.datetime.replace(tzinfo=None))
        changes["buckets"] = (
            replace(
                bucket,
                source_minutes=(naive, *bucket.source_minutes[1:]),
            ),
        )
        changes["source_minutes"] = (
            naive,
            *snapshot.source_minutes[1:],
        )
    elif mutation == "source_bucket":
        outside = replace(
            source,
            datetime=bucket.identity.bucket_start,
            confirmed_at=bucket.identity.bucket_start.astimezone(UTC),
        )
        changes["buckets"] = (
            replace(
                bucket,
                source_minutes=(outside, *bucket.source_minutes[1:]),
            ),
        )
        changes["source_minutes"] = (
            outside,
            *snapshot.source_minutes[1:],
        )
    else:
        changes["source_minutes"] = ()

    with pytest.raises(ValueError, match=reason):
        replace(snapshot, **changes)


def _two_live_resolver_snapshot() -> HtDyRealtimeSnapshot:
    length = 130
    values = np.full(length, 10.0)
    volume = np.full(length, 1000.0)
    return _resolver_compatible_snapshot(
        open_=values,
        high=values + 1,
        low=values - 1,
        close=values,
        volume=volume,
    )


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("historical_count", "HTDY_SNAPSHOT_HISTORICAL_STRUCTURE"),
        ("historical_status", "HTDY_SNAPSHOT_HISTORICAL_STRUCTURE"),
        ("historical_sources", "HTDY_SNAPSHOT_HISTORICAL_STRUCTURE"),
        ("historical_order", "HTDY_SNAPSHOT_HISTORICAL_STRUCTURE"),
        ("live_order", "HTDY_SNAPSHOT_LIVE_STRUCTURE"),
        ("live_nonfinal_partial", "HTDY_SNAPSHOT_LIVE_STRUCTURE"),
        ("illegal_session", "HTDY_SNAPSHOT_SESSION_GEOMETRY"),
        ("mapping_date", "HTDY_SNAPSHOT_MAPPING_IDENTITY"),
        ("mapping_created_at", "HTDY_SNAPSHOT_MAPPING_IDENTITY"),
        ("bucket_timezone", "HTDY_SNAPSHOT_BAR_TIMEZONE_REQUIRED"),
        ("as_of_timezone", "HTDY_SNAPSHOT_AS_OF_TIMEZONE_REQUIRED"),
        ("confirmed_at_timezone", "HTDY_SNAPSHOT_SOURCE_TIMEZONE_REQUIRED"),
        ("confirmed_source_count", "HTDY_SNAPSHOT_SOURCE_MEMBERSHIP"),
    ],
)
def test_public_snapshot_rejects_resolver_impossible_structure(
    mutation: str,
    reason: str,
) -> None:
    snapshot = _two_live_resolver_snapshot()
    changes: dict[str, object] = {}
    if mutation == "historical_count":
        changes["historical_bars"] = snapshot.historical_bars[:-1]
    elif mutation == "historical_status":
        changes["historical_bars"] = (
            replace(snapshot.historical_bars[0], status="partial"),
            *snapshot.historical_bars[1:],
        )
    elif mutation == "historical_sources":
        changes["historical_bars"] = (
            replace(
                snapshot.historical_bars[0],
                source_minutes=(snapshot.source_minutes[0],),
            ),
            *snapshot.historical_bars[1:],
        )
    elif mutation == "historical_order":
        changes["historical_bars"] = (
            snapshot.historical_bars[1],
            snapshot.historical_bars[0],
            *snapshot.historical_bars[2:],
        )
    elif mutation == "live_order":
        changes["buckets"] = (snapshot.buckets[1], snapshot.buckets[0])
        changes["source_minutes"] = (
            *snapshot.buckets[1].source_minutes,
            *snapshot.buckets[0].source_minutes,
        )
    elif mutation == "live_nonfinal_partial":
        changes["buckets"] = (
            replace(snapshot.buckets[0], status="partial"),
            snapshot.buckets[1],
        )
    elif mutation == "illegal_session":
        first = snapshot.buckets[0]
        changes["buckets"] = (
            replace(
                first,
                identity=replace(
                    first.identity,
                    bucket_start=datetime(
                        2026, 7, 24, 12, 0, tzinfo=SHANGHAI
                    ),
                    bucket_end=datetime(
                        2026, 7, 24, 12, 15, tzinfo=SHANGHAI
                    ),
                ),
            ),
            snapshot.buckets[1],
        )
    elif mutation == "mapping_date":
        changes["mapping_date"] = date(2026, 7, 28)
    elif mutation == "mapping_created_at":
        changes["mapping_identity"] = {
            key: value
            for key, value in snapshot.mapping_identity.items()
            if key != "created_at"
        }
    elif mutation == "bucket_timezone":
        first = snapshot.buckets[0]
        changes["buckets"] = (
            replace(
                first,
                identity=replace(
                    first.identity,
                    bucket_start=first.identity.bucket_start.astimezone(UTC),
                    bucket_end=first.identity.bucket_end.astimezone(UTC),
                ),
            ),
            snapshot.buckets[1],
        )
    elif mutation == "as_of_timezone":
        changes["as_of"] = snapshot.as_of.astimezone(SHANGHAI)
    elif mutation == "confirmed_at_timezone":
        source = replace(
            snapshot.source_minutes[0],
            confirmed_at=snapshot.source_minutes[0].confirmed_at.astimezone(
                SHANGHAI
            ),
        )
        first = replace(
            snapshot.buckets[0],
            source_minutes=(source, *snapshot.buckets[0].source_minutes[1:]),
        )
        changes["buckets"] = (first, snapshot.buckets[1])
        changes["source_minutes"] = (
            source,
            *snapshot.source_minutes[1:],
        )
    else:
        first = replace(
            snapshot.buckets[0],
            source_minutes=snapshot.buckets[0].source_minutes[:-1],
        )
        changes["buckets"] = (first, snapshot.buckets[1])
        changes["source_minutes"] = (
            *first.source_minutes,
            *snapshot.buckets[1].source_minutes,
        )

    with pytest.raises(ValueError, match=reason):
        replace(snapshot, **changes)


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "other"),
        ("product", "i"),
        ("actual_contract", "JM2611"),
        ("period", "5m"),
        ("bar_status", "partial"),
        ("quality_status", "candidate"),
        ("revision", -1),
    ],
)
def test_public_snapshot_rejects_source_identity_drift(
    field: str,
    value: object,
) -> None:
    snapshot = _snapshot()
    changed_source = replace(
        snapshot.source_minutes[0],
        **{field: value},
    )
    changed_sources = (changed_source, *snapshot.source_minutes[1:])
    changed_bucket = replace(
        snapshot.buckets[0],
        source_minutes=changed_sources,
    )

    with pytest.raises(ValueError, match="HTDY_SNAPSHOT_SOURCE_IDENTITY"):
        replace(
            snapshot,
            buckets=(changed_bucket,),
            source_minutes=changed_sources,
        )


def test_public_snapshot_rejects_source_bucket_aggregate_drift() -> None:
    snapshot = _snapshot()

    with pytest.raises(ValueError, match="HTDY_SNAPSHOT_SOURCE_MEMBERSHIP"):
        replace(
            snapshot,
            buckets=(
                replace(
                    snapshot.buckets[0],
                    close=snapshot.buckets[0].close + Decimal("0.25"),
                    high=snapshot.buckets[0].high + Decimal("0.25"),
                ),
            ),
        )


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("historical", "HTDY_HISTORICAL_WINDOW_HASH_MISMATCH"),
        ("snapshot", "HTDY_SNAPSHOT_HASH_MISMATCH"),
    ],
)
def test_public_evaluator_recomputes_ingress_hashes_before_kernel(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    reason: str,
) -> None:
    import app.services.htdy_realtime_evaluator as module
    from app.services.htdy_realtime_snapshot import (
        recompute_historical_window_sha256,
        recompute_snapshot_sha256,
    )

    snapshot = _snapshot()
    assert (
        recompute_historical_window_sha256(snapshot.historical_bars)
        == snapshot.historical_identity.window_sha256
    )
    assert recompute_snapshot_sha256(snapshot) == snapshot.snapshot_sha256
    if mutation == "historical":
        first = snapshot.historical_bars[0]
        changed = replace(
            first,
            close=first.close + Decimal("0.25"),
            high=first.high + Decimal("0.25"),
        )
        snapshot = replace(
            snapshot,
            historical_bars=(changed, *snapshot.historical_bars[1:]),
        )
    else:
        snapshot = replace(snapshot, snapshot_sha256="forged")
    calls = 0
    frozen_kernel = module.compute_htdy_original

    def counted_kernel(*args, **kwargs):
        nonlocal calls
        calls += 1
        return frozen_kernel(*args, **kwargs)

    monkeypatch.setattr(module, "compute_htdy_original", counted_kernel)
    with pytest.raises(ValueError, match=reason):
        module.HtDyRealtimeCandidateEvaluator().evaluate(
            snapshot,
            detected_at=snapshot.as_of,
        )

    assert calls == 0
