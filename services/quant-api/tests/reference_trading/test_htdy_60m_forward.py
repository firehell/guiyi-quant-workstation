"""HTDY 60m consumes a frozen original, never a later Live snapshot."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import MarketReadWindow
from app.market_data.observation_stream import ObservationEnvelope
from app.reference_trading.forward_inputs import ForwardInputUnavailable, _bar_wire, capture_htdy_live
from guiyi_quant.reference_trading import RecordingMode, StreamIdentity
from guiyi_quant.reference_trading.htdy import MODEL_VERSION


def identity():
    return StreamIdentity("htdy", ("huotian_dayou_original_v0",), "htdy-v1", MODEL_VERSION,
        "actual_dominant_v1", "RB", "60m", "actual_dominant",
        RecordingMode.FORWARD_OBSERVATION, "latest_only_32_v1")


class Read:
    def __init__(self):
        end = datetime(2026, 10, 28, 7, tzinfo=UTC)
        self.bars = tuple(CanonicalBar(end-timedelta(hours=31-index), end.date(),
            Decimal("3500"), Decimal("3510"), Decimal("3490"), Decimal("3500"),
            Decimal("100"), None, None) for index in range(32))
        self.reads = 0
        self.checks = 0

    def observation_snapshot(self, *args):
        raise AssertionError("frozen deliveries must not consult latest snapshot")

    def bars_until(self, query, *, trading_day, end, limit):
        self.reads += 1
        assert query.frequency.value == "60m" and limit == 32
        assert end == self.bars[-1].bar_end
        return MarketReadWindow(symbol="rb", series_kind="actual_dominant", frequency="60m",
            trading_day=trading_day, contract="RB2610", cutoff=end,
            bars=self.bars, bar_contracts=("RB2610",)*len(self.bars))

    def validate_alert_window(self, window, *, context_bars):
        assert context_bars == 32

    def assert_window_current(self, window):
        self.checks += 1


def original(read):
    bar = read.bars[-1]
    return ObservationEnvelope("htdy-60m-original", bar.trading_day,
        bar.bar_end+timedelta(milliseconds=1), "live:bar:rb:60m",
        {**_bar_wire(bar), "contract": "RB2610"}, True, "100-0",
        bar.bar_end+timedelta(milliseconds=1), bar.bar_end+timedelta(milliseconds=2))


_DEFAULT = object()


def capture(read, observation=_DEFAULT, **overrides):
    observation = original(read) if observation is _DEFAULT else observation
    args = dict(revision_id="r", generation=1, after=None, now=original(read).confirmed_at,
        wake_kind="live_event", event_bar_end=read.bars[-1].bar_end, observation=observation,
        expected_endpoints=lambda *_: (read.bars[-1].bar_end,),
        owner_segments=lambda *_: ("owner", "calc"))
    args.update(overrides)
    return capture_htdy_live(read, identity(), **args)


def test_original_bound_60m_window_has_provenance_and_no_latest_read():
    read = Read()
    event = original(read)
    result = capture(read, event)
    assert result.observed_at == event.confirmed_at
    assert result.input_payload["bars"][-1] == _bar_wire(read.bars[-1])
    assert result.source_proof["observation_id"] == event.observation_id
    assert result.source_proof["journal_id"] == event.stream_id
    assert result.source_proof["frequency"] == "60m"
    assert read.reads == 1 and read.checks >= 1


def test_60m_scan_cannot_invent_first_seen_or_read_current_tail():
    read = Read()
    with pytest.raises(ForwardInputUnavailable, match="FIRST_SEEN_NOT_PROVEN"):
        capture(read, observation=None, wake_kind="scan")
    assert read.reads == 0
    with pytest.raises(ForwardInputUnavailable, match="FIRST_SEEN_NOT_PROVEN"):
        capture(read, observation=None)


@pytest.mark.parametrize("field,value", [("channel", "live:bar:rb:15m"),
    ("notification_eligible", False), ("stream_id", ""),
    ("confirmed_at", datetime(2026, 10, 28, 9, tzinfo=UTC))])
def test_original_identity_changes_rejected_before_market_read(field, value):
    read = Read()
    event = replace(original(read), **{field: value})
    with pytest.raises(ForwardInputUnavailable, match="LIVE_EVENT_IDENTITY_CONFLICT"):
        capture(read, event, now=original(read).confirmed_at)
    assert read.reads == 0


def test_changed_original_bar_cannot_be_replaced_by_current_mds_value():
    read = Read()
    event = original(read)
    event = replace(event, data={**event.data, "close": "3501"})
    with pytest.raises(ForwardInputUnavailable, match="HTDY_WINDOW_UNAVAILABLE"):
        capture(read, event)


def test_missing_context_and_missing_endpoint_do_not_advance():
    read = Read()
    read.bars = read.bars[1:]
    with pytest.raises(ForwardInputUnavailable, match="HTDY_WINDOW_UNAVAILABLE"):
        capture(read)
    read = Read()
    with pytest.raises(ForwardInputUnavailable, match="OBSERVATION_GAP"):
        capture(read, after=read.bars[-3].bar_end,
            expected_endpoints=lambda *_: tuple(bar.bar_end for bar in read.bars[-2:]))


def test_duplicate_original_does_not_read_or_recalculate():
    read = Read()
    assert capture(read, after=read.bars[-1].bar_end) is None
    assert read.reads == 0


def test_cancel_before_preparation_never_reads_input():
    read = Read()
    def cancelled():
        raise InterruptedError("cooperative stop")
    with pytest.raises(InterruptedError):
        capture(read, check_cancelled=cancelled)
    assert read.reads == 0


def test_60m_evaluator_binds_window_tail_to_original_payload():
    from hashlib import sha256
    from app.reference_trading.contracts import CheckpointToken
    from app.reference_trading.htdy import evaluate_htdy_capture
    from guiyi_quant.reference_trading import ReferenceState
    from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
    from guiyi_quant.reference_trading.htdy import HtdyForwardState
    read = Read()
    import json
    captured = json.loads(json.dumps(capture(read).evidence()))
    checkpoint = AdapterCheckpoint(HtdyForwardState(MODEL_VERSION, "latest_only_32_v1"),
        stream=identity(), reference_state=ReferenceState.flat(identity(), recording_start=read.bars[-1].bar_end))
    token = CheckpointToken(identity().stream_id, "r", 1, 1, sha256(b"seed").hexdigest())
    captured["forward_capture_v1"]["input_payload"]["bar"]["close"] = "3501"
    with pytest.raises(ValueError, match="HTDY_CAPTURE_IDENTITY_CONFLICT"):
        evaluate_htdy_capture(token, checkpoint, {**captured, "capture_id": "capture"}, dependency_manifest={})
