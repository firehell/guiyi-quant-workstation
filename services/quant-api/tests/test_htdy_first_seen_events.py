from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.signal import SignalEvent, SignalNotification, StrategySignal
from app.services.htdy_realtime_models import (
    BlockedObservation,
    BucketIdentity,
    HistoricalWarmupIdentity,
    HtDy15mBarSnapshot,
    HtDyEvaluationResult,
    HtDyObservationCandidate,
    SourceMinuteRef,
)


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _candidate(
    *,
    observation_key: str = "a" * 64,
    direction: str = "long",
    revision: int = 1,
    snapshot_sha256: str = "b" * 64,
) -> HtDyObservationCandidate:
    from zoneinfo import ZoneInfo

    shanghai = ZoneInfo("Asia/Shanghai")
    bucket_start = datetime(2026, 7, 24, 14, 45, tzinfo=shanghai)
    bucket_end = datetime(2026, 7, 24, 15, 0, tzinfo=shanghai)
    detected_at = datetime(2026, 7, 27, 1, 4, tzinfo=UTC)
    source_time = datetime(2026, 7, 27, 9, 4, tzinfo=shanghai)
    source = SourceMinuteRef(
        live_bar_id=101,
        datetime=source_time,
        trading_day=date(2026, 7, 27),
        provider="rqdata",
        product="jm",
        actual_contract="JM2609",
        period="1m",
        bar_status="confirmed",
        quality_status="passed",
        revision=revision,
        open=Decimal("1234.0"),
        high=Decimal("1235.0"),
        low=Decimal("1233.0"),
        close=Decimal("1234.5"),
        volume=Decimal("12"),
        confirmed_at=source_time.astimezone(UTC),
    )
    bucket = HtDy15mBarSnapshot(
        identity=BucketIdentity(
            product="jm",
            actual_contract="JM2609",
            trading_day=date(2026, 7, 24),
            session_id="DCE:jm:day_pm",
            bucket_start=bucket_start,
            bucket_end=bucket_end,
            period="15m",
            session_name="day_pm",
        ),
        trading_day=date(2026, 7, 24),
        status="confirmed",
        open=Decimal("1230"),
        high=Decimal("1236"),
        low=Decimal("1229"),
        close=Decimal("1233"),
        volume=Decimal("180"),
        source_minutes=(),
    )
    binding = {
        "profile_id": "live_observation_v1",
        "instrument_symbol": "jm",
        "contract_code": "JM2609",
        "contract_role": "actual_contract",
        "period": "15m",
        "data_version": "rqdata-jm-15m-v1",
        "market_data_file_id": 42,
        "binding_status": "active",
        "activated_at": "2026-07-25T00:00:00+00:00",
        "superseded_at": None,
        "updated_at": "2026-07-25T00:00:00+00:00",
        "quality_policy": "active_entry",
        "provider": "rqdata",
        "data_role": "primary",
        "quality_status": "passed",
        "file_data_version": "rqdata-jm-15m-v1",
        "source_interval": "1m",
        "source_interval_basis": "parquet_column",
    }
    return HtDyObservationCandidate(
        observation_key=observation_key,
        direction=direction,
        detected_at=detected_at,
        detection_price=source.close,
        observed_bar_close=bucket.close,
        bucket=bucket,
        actual_contract="JM2609",
        continuous_contract="jm.MAIN",
        mapping_date=date(2026, 7, 27),
        strategy_code="htdy_original_realtime_first_seen",
        strategy_version="v1.0",
        indicator_code="huotian_dayou_original_v0",
        indicator_version="original-v0",
        policy_id="htdy_original_xma_15m_first_seen_v1",
        source_minutes=(source,),
        historical_identity=HistoricalWarmupIdentity(
            profile_id="live_observation_v1",
            binding_snapshot=binding,
            market_data_file_id=42,
            data_version="rqdata-jm-15m-v1",
            checksum="c" * 64,
            window_sha256="d" * 64,
            previous_trading_day=date(2026, 7, 24),
        ),
        snapshot_sha256=snapshot_sha256,
        source_sha256="e" * 64,
        policy_sha256="f" * 64,
    )


def _result(*candidates: HtDyObservationCandidate) -> HtDyEvaluationResult:
    snapshot_sha256 = candidates[0].snapshot_sha256 if candidates else "b" * 64
    return HtDyEvaluationResult(
        candidates=candidates,
        snapshot_sha256=snapshot_sha256,
        evaluated_at=datetime(2026, 7, 27, 1, 4, tzinfo=UTC),
    )


def test_first_seen_writer_creates_one_frozen_signal_event_without_notification() -> None:
    from app.services.htdy_first_seen_events import HtDyFirstSeenEventService

    factory = _session_factory()
    with factory() as session:
        result = HtDyFirstSeenEventService(session).persist(_result(_candidate()))

        assert (result.created, result.unchanged, result.blocked) == (1, 0, 0)
        signal = session.scalar(select(StrategySignal))
        event = session.scalar(select(SignalEvent))
        assert signal is not None and event is not None
        assert signal.dedupe_key == f"htdy-first-seen:{'a' * 64}"
        assert signal.strategy_name == "htdy_original_realtime_first_seen"
        assert signal.signal_time == datetime(2026, 7, 27, 1, 4)
        assert signal.bar_end == datetime(2026, 7, 24, 15, 0)
        assert signal.trigger_price == 1234.5
        assert signal.features["observed_bar_close"] == "1233"
        assert signal.features["historical_backtest_allowed"] is False
        assert signal.features["notification_ready"] is False
        assert signal.features["auto_order"] is False
        assert event.event_type == "signal_created"
        assert event.source_mode == "live_realtime_repainting"
        lineage = event.payload["formal_lineage"]
        assert lineage["schema_version"] == "signal_review_lineage_v2"
        assert lineage["bar"]["observed_bar_close"] == "1233"
        assert lineage["live_detection_snapshot"]["detection_price"] == "1234.5"
        assert lineage["live_detection_snapshot"]["source_1m"][0]["revision"] == 1
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0


def test_review_lineage_wraps_exact_htdy_v2_and_rejects_schema_drift() -> None:
    from app.services.htdy_first_seen_events import HtDyFirstSeenEventService
    from app.services.review_lineage import (
        ReviewLineageError,
        resolve_review_source_lineage,
    )

    factory = _session_factory()
    with factory() as session:
        HtDyFirstSeenEventService(session).persist(_result(_candidate()))
        event = session.scalar(select(SignalEvent))
        assert event is not None

        resolved = resolve_review_source_lineage(
            session,
            source_type="signal_event",
            source_id=event.id,
        )
        assert resolved["schema_version"] == "review_source_lineage_v1"
        assert (
            resolved["source_snapshot_schema_version"]
            == "signal_review_lineage_v2"
        )
        assert resolved["primary"]["market_data_file_id"] == 42

        event.payload["formal_lineage"]["schema_version"] = (
            "signal_review_lineage_v1"
        )
        with pytest.raises(
            ReviewLineageError,
            match="REVIEW_HTDY_LINEAGE_SCHEMA_INVALID",
        ):
            resolve_review_source_lineage(
                session,
                source_type="signal_event",
                source_id=event.id,
            )


def test_same_observation_freezes_first_direction_revision_and_snapshot() -> None:
    from app.services.htdy_first_seen_events import HtDyFirstSeenEventService

    factory = _session_factory()
    with factory() as session:
        service = HtDyFirstSeenEventService(session)
        first = service.persist(_result(_candidate()))
        later = service.persist(
            _result(
                _candidate(
                    direction="short",
                    revision=9,
                    snapshot_sha256="9" * 64,
                )
            )
        )

        assert first.created == 1
        assert (later.created, later.unchanged, later.blocked) == (0, 1, 0)
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 1
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 1
        signal = session.scalar(select(StrategySignal))
        event = session.scalar(select(SignalEvent))
        assert signal is not None and event is not None
        assert signal.direction == "long"
        assert signal.features["snapshot_sha256"] == "b" * 64
        assert event.payload["formal_lineage"]["live_detection_snapshot"]["source_1m"][0]["revision"] == 1


def test_blocked_observation_is_counted_without_any_database_write() -> None:
    from app.services.htdy_first_seen_events import HtDyFirstSeenEventService

    candidate = _candidate()
    blocked_result = HtDyEvaluationResult(
        blocked=(
            BlockedObservation(
                bucket=candidate.bucket,
                reason="dual_direction_conflict",
            ),
        ),
        snapshot_sha256=candidate.snapshot_sha256,
        evaluated_at=candidate.detected_at,
    )
    factory = _session_factory()
    with factory() as session:
        result = HtDyFirstSeenEventService(session).persist(blocked_result)

        assert (result.created, result.unchanged, result.blocked) == (0, 0, 1)
        assert result.blocked_reasons == ("dual_direction_conflict",)
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"direction": "conflict"}, "HTDY_FIRST_SEEN_DIRECTION"),
        ({"period": "5m"}, "HTDY_FIRST_SEEN_POLICY"),
        ({"source_mode": "live_confirmed"}, "HTDY_FIRST_SEEN_POLICY"),
        ({"future_looking": False}, "HTDY_FIRST_SEEN_POLICY"),
        ({"first_seen_no_retraction": False}, "HTDY_FIRST_SEEN_POLICY"),
    ],
)
def test_invalid_candidate_fails_before_any_database_write(
    change: dict[str, object],
    code: str,
) -> None:
    from dataclasses import replace

    from app.services.htdy_first_seen_events import HtDyFirstSeenEventService

    valid = _candidate()
    invalid = replace(valid, observation_key="1" * 64, **change)
    factory = _session_factory()
    with factory() as session:
        with pytest.raises(ValueError, match=code):
            HtDyFirstSeenEventService(session).persist(_result(valid, invalid))

        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0


def test_existing_signal_without_created_event_fails_closed() -> None:
    from app.services.htdy_first_seen_events import HtDyFirstSeenEventService

    factory = _session_factory()
    with factory() as session:
        service = HtDyFirstSeenEventService(session)
        service.persist(_result(_candidate()))
        event = session.scalar(select(SignalEvent))
        assert event is not None
        session.delete(event)
        session.flush()

        with pytest.raises(RuntimeError, match="HTDY_FIRST_SEEN_EVENT_MISSING"):
            service.persist(_result(_candidate()))


def test_forged_result_or_duplicate_candidates_fail_before_database_write() -> None:
    from dataclasses import replace

    from app.services.htdy_first_seen_events import HtDyFirstSeenEventService

    candidate = _candidate()
    factory = _session_factory()
    with factory() as session:
        service = HtDyFirstSeenEventService(session)
        with pytest.raises(ValueError, match="HTDY_FIRST_SEEN_RESULT"):
            service.persist(
                replace(
                    _result(candidate),
                    evaluated_at=datetime(2026, 7, 27, 1, 5, tzinfo=UTC),
                )
            )
        with pytest.raises(ValueError, match="HTDY_FIRST_SEEN_RESULT"):
            service.persist(_result(candidate, candidate))

        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0


def test_existing_frozen_signal_or_event_drift_fails_closed() -> None:
    from app.services.htdy_first_seen_events import HtDyFirstSeenEventService

    factory = _session_factory()
    with factory() as session:
        service = HtDyFirstSeenEventService(session)
        service.persist(_result(_candidate()))
        signal = session.scalar(select(StrategySignal))
        event = session.scalar(select(SignalEvent))
        assert signal is not None and event is not None

        signal.strategy_name = "tampered"
        session.flush()
        with pytest.raises(RuntimeError, match="HTDY_FIRST_SEEN_SIGNAL_DRIFT"):
            service.persist(_result(_candidate()))

        signal.strategy_name = "htdy_original_realtime_first_seen"
        event.event_type = "signal_changed"
        session.flush()
        with pytest.raises(RuntimeError, match="HTDY_FIRST_SEEN_EVENT_DRIFT"):
            service.persist(_result(_candidate()))
