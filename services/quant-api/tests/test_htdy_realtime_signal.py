from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import numpy as np

from app.db.base import Base
from app.models.signal import SignalEvent, StrategySignal
from app.services.htdy_realtime_signal import (
    HTDY_SIGNAL_POLICY,
    HTDY_SOURCE_MODE,
    HTDY_STRATEGY_CODE,
    HTDY_STRATEGY_VERSION,
    HtdyRealtimeSignalCandidate,
    HtdyRealtimeSignalEventService,
    build_15m_snapshots,
    candidates_from_output,
)
from guiyi_quant.indicators.htdy_original import HtdyOriginalResult


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _minute_rows(count: int, *, start: datetime | None = None) -> list[dict[str, object]]:
    first = start or datetime(2026, 7, 27, 1, 1, tzinfo=UTC)
    return [
        {
            "id": index + 1,
            "revision": 0,
            "datetime": first + timedelta(minutes=index),
            "trading_day": date(2026, 7, 27),
            "open": 100.0 + index,
            "high": 101.0 + index,
            "low": 99.0 + index,
            "close": 100.5 + index,
            "volume": 10.0,
            "quality_status": "passed",
            "bar_status": "confirmed",
        }
        for index in range(count)
    ]


def test_partial_15m_snapshot_keeps_stable_bucket_identity() -> None:
    first = build_15m_snapshots(_minute_rows(3))
    second = build_15m_snapshots(_minute_rows(4))

    assert len(first) == len(second) == 1
    assert first[0].bar_start == second[0].bar_start
    assert first[0].bar_end == second[0].bar_end
    assert first[0].bar_status == second[0].bar_status == "partial"
    assert first[0].source_bar_count == 3
    assert second[0].source_bar_count == 4
    assert first[0].source_bar_ids == (1, 2, 3)
    assert second[0].source_bar_ids == (1, 2, 3, 4)


def test_15m_snapshot_becomes_confirmed_after_fifteen_passed_minutes() -> None:
    snapshot = build_15m_snapshots(_minute_rows(15))[0]

    assert snapshot.bar_status == "confirmed"
    assert snapshot.source_bar_count == snapshot.expected_bar_count == 15
    assert snapshot.bar_end == datetime(2026, 7, 27, 1, 15, tzinfo=UTC)
    assert snapshot.open == 100.0
    assert snapshot.close == 114.5
    assert snapshot.volume == 150.0


def test_session_gap_starts_a_new_stable_bucket() -> None:
    rows = _minute_rows(2)
    rows.extend(_minute_rows(2, start=datetime(2026, 7, 27, 5, 31, tzinfo=UTC)))

    snapshots = build_15m_snapshots(rows)

    assert len(snapshots) == 2
    assert snapshots[0].bar_start == datetime(2026, 7, 27, 1, 0, tzinfo=UTC)
    assert snapshots[1].bar_start == datetime(2026, 7, 27, 5, 30, tzinfo=UTC)


def test_first_seen_signal_creates_strategy_signal_and_signal_event() -> None:
    factory = _session_factory()
    with factory() as session:
        result = HtdyRealtimeSignalEventService(session).persist([_candidate()])

        assert result.created == 1
        assert result.changed == 0
        assert result.unchanged == 0
        assert result.blocked == 0
        signal = session.scalar(select(StrategySignal))
        event = session.scalar(select(SignalEvent))
        assert signal is not None
        assert event is not None
        assert signal.strategy_name == HTDY_STRATEGY_CODE
        assert signal.strategy_version == HTDY_STRATEGY_VERSION
        assert signal.features["signal_policy"] == HTDY_SIGNAL_POLICY
        assert signal.features["future_looking"] is True
        assert signal.features["repainting_accepted"] is True
        assert signal.features["first_seen_no_retraction"] is True
        assert event.source_mode == HTDY_SOURCE_MODE
        assert event.event_type == "signal_created"
        assert event.payload["formal_lineage"]["schema_version"] == "signal_review_lineage_v2"
        assert event.payload["formal_lineage"]["live_detection_snapshot"]["snapshot_hash"] == "a" * 64


def test_same_bar_revision_and_direction_change_are_unchanged() -> None:
    factory = _session_factory()
    with factory() as session:
        service = HtdyRealtimeSignalEventService(session)
        first = service.persist([_candidate(direction="long", revision=1)])
        second = service.persist([_candidate(direction="short", revision=8)])

        assert first.created == 1
        assert second.unchanged == 1
        assert second.created == second.changed == 0
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 1
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 1
        signal = session.scalar(select(StrategySignal))
        assert signal is not None
        assert signal.direction == "long"
        assert signal.features["trigger_live_bar_revision"] == 1


def test_candidate_conflict_and_invalid_source_fail_closed() -> None:
    factory = _session_factory()
    with factory() as session:
        service = HtdyRealtimeSignalEventService(session)
        result = service.persist(
            [
                _candidate(direction="conflict"),
                _candidate(source_quality_status="warning", bar_end_minute=30),
                _candidate(actual_contract="JM.MAIN", bar_end_minute=45),
            ]
        )

        assert result.blocked == 3
        assert result.created == 0
        assert {item["code"] for item in result.blocked_reasons} == {
            "HTDY_DIRECTION_BLOCKED",
            "HTDY_SOURCE_1M_QUALITY_BLOCKED",
            "HTDY_ACTUAL_CONTRACT_REQUIRED",
        }
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0


def test_repaint_zone_detects_signal_on_earlier_bar_and_freezes_trigger_snapshot() -> None:
    trigger = build_15m_snapshots(_minute_rows(3))[0]
    bars = [
        {
            "datetime": datetime(2026, 7, 27, 0, 45, tzinfo=UTC)
            + timedelta(minutes=15 * index),
            "bar_start": datetime(2026, 7, 27, 0, 30, tzinfo=UTC)
            + timedelta(minutes=15 * index),
            "bar_end": datetime(2026, 7, 27, 0, 45, tzinfo=UTC)
            + timedelta(minutes=15 * index),
            "bar_status": "confirmed" if index < 3 else "partial",
            "open": 100.0 + index,
            "high": 101.0 + index,
            "low": 99.0 + index,
            "close": 100.5 + index,
            "volume": 10.0,
        }
        for index in range(4)
    ]
    flags = np.asarray([False, True, False, False])
    output = HtdyOriginalResult(
        datetimes=np.asarray([row["datetime"] for row in bars], dtype=object),
        open=np.asarray([row["open"] for row in bars]),
        high=np.asarray([row["high"] for row in bars]),
        low=np.asarray([row["low"] for row in bars]),
        close=np.asarray([row["close"] for row in bars]),
        volume=np.asarray([row["volume"] for row in bars]),
        fields={
            "zk1": np.zeros(4),
            "zd1": np.zeros(4),
            "zd2": np.zeros(4),
            "yellow_candle": np.zeros(4, dtype=bool),
            "white_candle": np.zeros(4, dtype=bool),
            "buy_observation": flags,
            "sell_observation": np.zeros(4, dtype=bool),
        },
        metadata={"future_looking": True, "repainting_risk": "known"},
    )

    candidates = candidates_from_output(
        output,
        bars=bars,
        trigger_snapshot=trigger,
        detected_at=datetime(2026, 7, 27, 1, 4, tzinfo=UTC),
        continuous_contract="JM.MAIN",
        actual_contract="JM2609",
        dominant_mapping_date=date(2026, 7, 27),
        profile_id="live_observation_v1",
        market_data_file_id=42,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.direction == "long"
    assert candidate.bar_end == bars[1]["bar_end"]
    assert candidate.detected_at == datetime(2026, 7, 27, 1, 4, tzinfo=UTC)
    assert candidate.trigger_snapshot_hash == trigger.snapshot_hash
    assert candidate.lineage["live_detection_snapshot"]["source_1m_ids"] == [1, 2, 3]
    assert candidate.lineage["indicator"]["repaint_zone_bars"] == 27


def _candidate(
    *,
    direction: str = "long",
    revision: int = 1,
    source_quality_status: str = "passed",
    actual_contract: str = "JM2609",
    bar_end_minute: int = 15,
) -> HtdyRealtimeSignalCandidate:
    detected_at = datetime(2026, 7, 27, 1, 4, tzinfo=UTC)
    bar_end = datetime(2026, 7, 27, 1, bar_end_minute, tzinfo=UTC)
    return HtdyRealtimeSignalCandidate(
        symbol="jm",
        continuous_contract="JM.MAIN",
        actual_contract=actual_contract,
        dominant_mapping_date=date(2026, 7, 27),
        period="15m",
        bar_start=bar_end - timedelta(minutes=15),
        bar_end=bar_end,
        detected_at=detected_at,
        trigger_price=1234.5,
        direction=direction,
        observation_bar_status="partial",
        source_quality_status=source_quality_status,
        profile_id="live_observation_v1",
        market_data_file_id=42,
        trigger_live_bar_id=101,
        trigger_live_bar_revision=revision,
        trigger_snapshot_hash="a" * 64,
        lineage={
            "schema_version": "signal_review_lineage_v2",
            "resolver_name": "ProfileLineageResolver",
            "resolver_contract_version": "signal_profile_v1",
            "quality_policy": "passed_source_1m_realtime_snapshot_v1",
            "source_mode": HTDY_SOURCE_MODE,
            "primary": {
                "profile_id": "live_observation_v1",
                "market_data_file_id": 42,
                "instrument_symbol": "jm",
                "contract_code": actual_contract,
                "period": "15m",
                "provider": "rqdata",
                "data_role": "primary",
                "quality_status": "passed",
            },
            "contract": {
                "continuous_contract": "JM.MAIN",
                "actual_contract": actual_contract,
                "dominant_mapping_date": "2026-07-27",
            },
            "bar": {
                "bar_start": (bar_end - timedelta(minutes=15)).isoformat(),
                "bar_end": bar_end.isoformat(),
                "trigger_price": 1234.5,
                "confirmation_mode": HTDY_SOURCE_MODE,
                "bar_status": "partial",
            },
            "live_detection_snapshot": {
                "detected_at": detected_at.isoformat(),
                "trigger_live_bar_id": 101,
                "trigger_live_bar_revision": revision,
                "snapshot_hash": "a" * 64,
                "source_1m_ids": [99, 100, 101],
                "source_1m_revisions": [0, 0, revision],
                "source_bar_count": 3,
                "expected_bar_count": 15,
                "bar_status": "partial",
                "source_quality_status": source_quality_status,
                "ohlcv": {
                    "open": 1230.0,
                    "high": 1236.0,
                    "low": 1229.0,
                    "close": 1234.5,
                    "volume": 120.0,
                },
            },
            "indicator": {
                "indicator_code": "huotian_dayou_original_v0",
                "indicator_version": "original-v0",
                "future_looking": True,
                "repainting_accepted": True,
                "repaint_zone_bars": 27,
                "first_seen_no_retraction": True,
            },
        },
    )
