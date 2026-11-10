from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from guiyi_quant.reference_trading import RecordingMode, StreamIdentity
from guiyi_quant.reference_trading.htdy import MODEL_VERSION
from app.market_data.domain import CanonicalBar
from app.market_data.newow.product_reader import NewowProductReadError, NewowProductReader
from app.market_data.market_read_service import MarketObservationSnapshot, MarketReadWindow
from app.reference_trading.forward_inputs import (
    ForwardInputUnavailable, capture_htdy_live, capture_subing_live,
)
from guiyi_quant.newow.product_contracts import ProductFrequency
from guiyi_quant.newow.product_identity import InputQualityPolicy, build_calculation_segment_id


@pytest.mark.parametrize("case", ("pre_owner_gap", "owned_gap", "missing_endpoint"))
def test_daily_rollover_proves_the_new_owners_physical_prefix(monkeypatch, case):
    owner_start = datetime(2026, 10, 28, 13, tzinfo=UTC)
    end = datetime(2026, 10, 29, 7, tzinfo=UTC)
    after = datetime(2026, 10, 28, 7, tzinfo=UTC)
    now = end + timedelta(hours=4)
    price = Decimal("3500")
    bar = CanonicalBar(end, end.date(), price, price, price, price, Decimal(1), None, None)
    owner = SimpleNamespace(symbol="rb", contract="RB2612", start_trading_day=end.date(),
                            end_trading_day=end.date())
    result = SimpleNamespace(bars=(bar,), resolved_contract_segments=(owner,))
    gap_at = owner_start if case == "owned_gap" else owner_start - timedelta(days=2)
    prefix = SimpleNamespace(bars=() if case == "missing_endpoint" else (bar,),
                             source_quality=(SimpleNamespace(bar_end=gap_at),))

    def read_prefix(**kwargs):
        assert kwargs["owner"] is owner and kwargs["cutoff"] == end
        assert kwargs["through"] == end.date()
        assert kwargs["quality_policy"] is InputQualityPolicy.DAILY_V2
        yield prefix

    market = SimpleNamespace(
        query_actual_dominant_trading_days_quality_union=lambda *_args, **_kwargs: (result, ()),
        dominant_segment_for_day=lambda *_: owner,
        session_windows=lambda **_: (SimpleNamespace(start=owner_start),),
        iter_actual_dominant_owner_replay_chunks=read_prefix,
    )
    reader = NewowProductReader(market, coverage=SimpleNamespace(latest_complete_day=lambda _: end.date()),
        active_products=("rb",), now=lambda: now, input_quality_policy=InputQualityPolicy.DAILY_V2)
    monkeypatch.setattr(reader, "_forward_published_through", lambda *_: end.date())
    query = dict(product="rb", frequency=ProductFrequency.DAILY, after=after, as_of=now,
                 prior_owner_segment_id="old-owner", prior_calculation_segment_id="old-calculation")
    if case == "owned_gap":
        with pytest.raises(NewowProductReadError, match="NEWOW_DATA_INTERRUPTED"):
            reader.forward_incremental_bar(**query)
    elif case == "missing_endpoint":
        with pytest.raises(NewowProductReadError, match="NEWOW_DATA_IDENTITY_INVALID"):
            reader.forward_incremental_bar(**query)
    else:
        captured, policy = reader.forward_incremental_bar(**query)
        assert captured.calculation_segment_id == build_calculation_segment_id(
            captured.bar.segment_id, gap_at, policy,
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
        owner_segments=lambda *_: ("owner", "calc"),
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


def test_retained_original_conflict_is_not_classified_as_history_preparation():
    from app.market_data.market_read_service import MarketReadWindowError
    read = _Read()
    def conflicted(*args,**kwargs):
        raise MarketReadWindowError('MARKET_READ_RETAINED_ORIGINAL_INVALID')
    read.retained_contract_replay_window = conflicted
    identity = StreamIdentity('subing-reference',('subing_ths_v1',),'subing-v1','subing-v1',
        'actual_dominant_v1','RB','15m','actual_dominant',RecordingMode.FORWARD_OBSERVATION,
        'subing_physical_prefix_forward_v2')
    latest=read.bars[-1]
    with pytest.raises(ForwardInputUnavailable, match='SUBING_RETAINED_ORIGINAL_CONFLICT'):
        capture_subing_live(read,identity,revision_id='r',generation=1,after=None,
            now=latest.bar_end+timedelta(seconds=2),wake_kind='scan',
            owner_segments=lambda *_:('owner','calc'),expected_endpoints=lambda *_:(latest.bar_end,),
            retained_observations=(object(),))


def test_legacy_htdy_snapshot_still_rejects_a_recovered_window(monkeypatch):
    from dataclasses import replace
    from app.market_data.live_market import LiveRecoveryState
    read = _Read()
    get_window = read.bars_until
    def recovered(*args, **kwargs):
        window = get_window(*args, **kwargs)
        return replace(window, recovery_state=LiveRecoveryState(2, read.bars[-1].bar_end))
    monkeypatch.setattr(read, 'bars_until', recovered)
    identity = StreamIdentity(
        'htdy', ('huotian_dayou_original_v0',), 'htdy-v1', MODEL_VERSION,
        'actual_dominant_v1', 'RB', '15m', 'actual_dominant',
        RecordingMode.FORWARD_OBSERVATION, 'latest_only_32_v1')
    with pytest.raises(ForwardInputUnavailable, match='HTDY_WINDOW_UNAVAILABLE'):
        capture_htdy_live(read, identity, revision_id='r', generation=1, after=None,
            now=read.bars[-1].bar_end + timedelta(seconds=2), wake_kind='live_event',
            event_bar_end=read.bars[-1].bar_end, owner_segments=lambda *_: ('owner', 'calc'))
