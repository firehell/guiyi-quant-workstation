from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.reference_trading.runtime import ForwardReferenceWorker
from app.reference_trading.forward_inputs import ForwardInputUnavailable


def test_one_delivery_does_not_expand_work_group_and_does_not_block_other_stream():
    calls = []

    class Repo:
        def read_pending_capture(self, stream):
            return None

        def capture_forward(self, capture):
            calls.append(("capture", capture.stream_id, capture.source_proof))

        def forward_work_key(self, stream):
            return "shared"

        def enabled_forward_work_routes(self, key):
            return ("bad", "good")

    class Service:
        def process_pending(self, stream):
            calls.append(("compute", stream))
            return object()

    from app.reference_trading.capture import ForwardCapture

    end = datetime(2026, 10, 26, 13, 5, tzinfo=UTC)

    def read(stream, kind, at):
        if stream == "bad":
            raise ForwardInputUnavailable("SUBING_PHYSICAL_PREFIX_UNAVAILABLE")
        return ForwardCapture(
            stream,
            "revision",
            1,
            "EG2701:" + at.isoformat(),
            at,
            at,
            "completed_live",
            {},
            {},
            "first_seen",
        )

    w = ForwardReferenceWorker(Repo(), lambda _: Service(), read, enabled=True)
    with pytest.raises(ForwardInputUnavailable):
        w.process_inbox_delivery("bad", end, delivery_id="delivery-bad")
    w.process_inbox_delivery("good", end, delivery_id="delivery-good")
    assert [x[:2] for x in calls] == [("capture", "good"), ("compute", "good")]
    assert calls[0][2]["inbox_delivery_id"] == "delivery-good"


def test_delivery_requires_enabled_worker_and_actual_capture():
    w = ForwardReferenceWorker(
        SimpleNamespace(read_pending_capture=lambda _: None),
        lambda _: None,
        lambda *_: None,
    )
    with pytest.raises(RuntimeError, match="REFERENCE_WORKER_NOT_ENABLED"):
        w.process_inbox_delivery("a", datetime.now(UTC), delivery_id="d")
    w._enabled = True
    with pytest.raises(RuntimeError, match="REFERENCE_INBOX_NO_CALCULATION"):
        w.process_inbox_delivery("a", datetime.now(UTC), delivery_id="d")
