from datetime import UTC, date, datetime
from types import SimpleNamespace

from app.reference_trading.live_wake import InboxForwardLiveWake


class Journal:
    def __init__(self, events, timeline):
        self.events = events
        self.timeline = timeline
        self.offset = 0

    def days(self):
        return (date(2026, 10, 27),)

    def cursor(self, *args):
        return str(self.offset)

    def read(self, *args, **kwargs):
        return self.events[self.offset : self.offset + kwargs.get("count", 128)]

    def ack(self, *args, **kwargs):
        self.timeline.append("ack")
        self.offset += 1


def test_ingest_commits_before_ack_and_one_waiting_stream_does_not_block_another():
    end = datetime(2026, 10, 26, 13, 5, tzinfo=UTC)
    timeline = []
    e = SimpleNamespace(
        notification_eligible=True,
        confirmed_at=end,
        source_observed_at=end,
        raw_received_at=end,
        stream_id="1-0",
        data={"bar_end": end.isoformat(), "contract": "EG2701"},
        channel="live:bar:eg:5m",
        trading_day=date(2026, 10, 27),
    )

    class Inbox:
        def ingest(self, observation, **kwargs):
            timeline.append("commit")

        def next_heads(self, **kwargs):
            return tuple(
                SimpleNamespace(
                    delivery_id=k, stream_id=k, status="PENDING", envelope=e
                )
                for k in ("bad", "good")
            )

        def validate_delivery(self, identifier):
            pass

        def mark_waiting(self, *args):
            timeline.append("wait")

        def mark_blocked(self, *args):
            timeline.append("blocked")

        def mark_unknown(self, *args):
            timeline.append("unknown")

    class Worker:
        def assert_owned(self):
            pass

        def process_inbox_delivery(self, stream, end, **kwargs):
            from app.reference_trading.forward_inputs import ForwardInputUnavailable

            if stream == "bad":
                raise ForwardInputUnavailable("SUBING_PHYSICAL_PREFIX_UNAVAILABLE")
            timeline.append("good")

    wake = object.__new__(InboxForwardLiveWake)
    wake._stream = Journal([e], timeline)
    wake._inbox = Inbox()
    wake._worker = Worker()
    wake._market_data = SimpleNamespace(
        dominant_segment_for_day=lambda *_: SimpleNamespace(contract="EG2701")
    )
    wake._after_stream_id = None
    wake._last_poll_count = 0
    wake.stop_requested = lambda: False
    wake._retry_after_by_stream = {}
    wake.request_history = lambda *_: timeline.append("request")
    wake.poll()
    assert timeline[:2] == ["commit", "ack"]
    assert "wait" in timeline and "good" in timeline and "request" in timeline


def test_ingest_error_never_acknowledges_original():
    timeline = []

    class Inbox:
        def ingest(self, *args, **kwargs):
            raise RuntimeError("unknown")

    wake = object.__new__(InboxForwardLiveWake)
    wake._stream = Journal([SimpleNamespace(notification_eligible=False)], timeline)
    wake._inbox = Inbox()
    wake._worker = SimpleNamespace(assert_owned=lambda: None)
    wake.stop_requested = lambda: False

    wake._calculate_heads = lambda: None
    wake.poll()
    assert wake.intake_error == "REFERENCE_INBOX_INTAKE_BLOCKED"
    assert timeline == []


def test_generic_processing_failure_uses_valid_code_and_keeps_other_heads_running():
    import re

    timeline = []
    end = datetime(2026, 10, 26, 13, 5, tzinfo=UTC)
    event = SimpleNamespace(
        confirmed_at=end,
        source_observed_at=end,
        raw_received_at=end,
        data={"bar_end": end.isoformat()},
    )

    class Inbox:
        def next_heads(self, **kwargs):
            return [
                SimpleNamespace(
                    delivery_id=k, stream_id=k, status="PENDING", envelope=event
                )
                for k in ("bad", "good")
            ]

        def validate_delivery(self, identifier):
            pass

        def mark_blocked(self, identifier, code):
            assert re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", code), code
            timeline.append((identifier, code))

    class Worker:
        def process_inbox_delivery(self, stream, *args, **kwargs):
            if stream == "bad":
                raise RuntimeError("REFERENCE_INBOX_NO_CALCULATION")
            timeline.append((stream, "computed"))

    wake = object.__new__(InboxForwardLiveWake)
    wake._inbox, wake._worker = Inbox(), Worker()
    wake._after_stream_id = None
    wake._retry_after_by_stream = {}
    wake.stop_requested = lambda: False
    wake._calculate_heads()
    assert timeline == [("bad", "REFERENCE_INBOX_NO_CALCULATION"), ("good", "computed")]


def test_expired_redis_cursor_blocks_only_intake_not_durable_pending_calculations():
    timeline = []

    class Expired:
        def days(self):
            return (date(2026, 10, 27),)

        def cursor(self, *args):
            raise ValueError("OBSERVATION_CURSOR_MISSING")

    wake = object.__new__(InboxForwardLiveWake)
    wake._stream = Expired()
    wake._calculate_heads = lambda: timeline.append("compute-durable")
    wake._worker = SimpleNamespace(assert_owned=lambda: None)
    wake.stop_requested = lambda: False
    wake.subscribe()
    wake.poll()
    assert timeline == ["compute-durable"]
    assert wake.intake_error == "OBSERVATION_CURSOR_MISSING"
