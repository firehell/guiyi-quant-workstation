from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.reference_trading import RecordingMode, StreamIdentity
from guiyi_quant.reference_trading.htdy import MODEL_VERSION
from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import MarketObservationSnapshot, MarketReadWindow
from app.reference_trading.forward_inputs import (
    ForwardInputUnavailable, capture_htdy_live, capture_subing_live,
)


class _Read:
    def __init__(self):
        base = datetime(2026, 9, 23, 0, tzinfo=UTC)
        self.bars = tuple(CanonicalBar(
            base + timedelta(minutes=15 * index), date(2026, 9, 23),
            Decimal("3500"), Decimal("3510"), Decimal("3490"), Decimal("3500"),
            Decimal("100"), None, None,
        ) for index in range(32))

    def observation_snapshot(self, identity, after, now):
        return MarketObservationSnapshot(
            state=None, source="realtime", trading_day=date(2026, 9, 23),
            contract="RB2610", bars=(self.bars[-1],),
        )

    def bars_until(self, identity, *, trading_day, end, limit):
        return MarketReadWindow(
            symbol="RB", series_kind="actual_dominant", frequency="15m",
            trading_day=trading_day, contract="RB2610", cutoff=end,
            bars=self.bars, bar_contracts=("RB2610",) * 32,
        )

    def validate_alert_window(self, window, *, context_bars):
        assert context_bars == 32


def test_htdy_reader_captures_exact_live_window_and_scan_cannot_invent_first_seen():
    read = _Read()
    identity = StreamIdentity(
        "htdy", ("huotian_dayou_original_v0",), "htdy-v1", MODEL_VERSION,
        "actual_dominant_v1", "RB", "15m", "actual_dominant",
        RecordingMode.FORWARD_OBSERVATION, "latest_only_32_v1",
    )
    now = read.bars[-1].bar_end + timedelta(seconds=2)
    capture = capture_htdy_live(
        read, identity, revision_id="revision", generation=1, after=None,
        now=now, wake_kind="live_event", event_bar_end=read.bars[-1].bar_end,
        owner_segments=lambda _contract, _instant: ("owner", "calc"),
    )
    assert capture.observed_at == now
    assert len(capture.input_payload["bars"]) == 32
    assert capture.source_proof["event_bar_end"] == read.bars[-1].bar_end.isoformat()
    with pytest.raises(ForwardInputUnavailable, match="LIVE_EVENT_IDENTITY_CONFLICT"):
        capture_htdy_live(
            read, identity, revision_id="revision", generation=1, after=None,
            now=now, wake_kind="live_event",
            event_bar_end=read.bars[-2].bar_end,
            owner_segments=lambda *_: ("owner", "calc"),
        )
    with pytest.raises(ForwardInputUnavailable, match="FIRST_SEEN_NOT_PROVEN"):
        capture_htdy_live(
            read, identity, revision_id="revision", generation=1, after=None,
            now=now, wake_kind="scan", owner_segments=lambda *_: ("owner", "calc"),
        )


def test_subing_reader_requires_one_session_proven_completed_bar():
    read = _Read()
    identity = StreamIdentity(
        "subing-reference", ("subing_ths_v1",), "subing-v1", "subing-v1",
        "actual_dominant_v1", "RB", "15m", "actual_dominant",
        RecordingMode.FORWARD_OBSERVATION, "completed_live_v1",
    )
    latest = read.bars[-1]
    now = latest.bar_end + timedelta(seconds=2)
    capture = capture_subing_live(
        read, identity, revision_id="revision", generation=1,
        after=None, now=now, wake_kind="scan",
        owner_segments=lambda *_: ("owner", "calc"),
        expected_endpoints=lambda *_: (latest.bar_end,),
    )
    assert capture.input_payload["bar"]["close"] == "3500"
    assert capture.source_proof["expected_endpoints"] == [latest.bar_end.isoformat()]
    with pytest.raises(ForwardInputUnavailable, match="OBSERVATION_GAP"):
        capture_subing_live(
            read, identity, revision_id="revision", generation=1,
            after=None, now=now, wake_kind="scan",
            owner_segments=lambda *_: ("owner", "calc"),
            expected_endpoints=lambda *_: (latest.bar_end - timedelta(minutes=15), latest.bar_end),
        )
