import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from app.market_data.observation_stream import ObservationEnvelope, ObservationStream
from app.reference_trading.repository import RepositoryConflict

DAY = date(2026, 10, 22)
END = datetime(2026, 10, 21, 14, tzinfo=UTC)


class ReadOnlyRedis:
    def __init__(self, event):
        self.raw = event.to_json()
        self.index = json.dumps(
            {"id": "100-0", "payload": self.raw, "content": self.raw}
        )

    def xrange(self, *args, **kwargs):
        return [(b"100-0", {b"envelope": self.raw.encode()})]

    def hget(self, *args):
        return self.index


def event():
    return ObservationEnvelope(
        "2026-10-22:M2701:60m:2026-10-21T14:00:00+00:00",
        DAY,
        END + timedelta(seconds=1),
        "live:bar:m:60m",
        {
            "contract": "M2701",
            "bar_end": END.isoformat(),
            "trading_day": DAY.isoformat(),
            "open": "1",
            "high": "2",
            "low": "1",
            "close": "2",
            "volume": "3",
            "turnover": "4",
            "open_interest": "5",
        },
        True,
        raw_received_at=END + timedelta(seconds=1),
        confirmed_at=END + timedelta(seconds=2),
    )


def read(redis, expected=(END,)):
    from app.reference_trading import retained_observation_authority as module

    return module.read_retained_interval(
        ObservationStream(redis, kind="completed"),
        product="m",
        day=DAY,
        after=END - timedelta(hours=1),
        before=END + timedelta(hours=1),
        expected_endpoints=expected,
        knowledge_at=END + timedelta(hours=2),
    )


def test_original_index_and_payload_prove_complete_interval_without_writes():
    values = read(ReadOnlyRedis(event()))
    assert len(values) == 1
    original, proof = values[0]
    assert original.stream_id == "100-0"
    assert proof["provenance"] == "retained_completed_observation_v1"
    assert len(proof["original_readback_sha256"]) == 64
    assert not any("repair" in key or "recovery" in key for key in proof)


@pytest.mark.parametrize(
    "mutation", ["payload", "id", "timestamp", "day", "missing", "duplicate"]
)
def test_changed_index_time_identity_or_incomplete_interval_fails_closed(mutation):
    original = event()
    redis = ReadOnlyRedis(original)
    expected = (END,)
    if mutation == "payload":
        index = json.loads(redis.index)
        index["payload"] = "{}"
        redis.index = json.dumps(index)
    if mutation == "id":
        index = json.loads(redis.index)
        index["id"] = "101-0"
        redis.index = json.dumps(index)
    if mutation == "timestamp":
        redis = ReadOnlyRedis(
            replace(original, confirmed_at=END - timedelta(seconds=1))
        )
    if mutation == "day":
        redis = ReadOnlyRedis(replace(original, observation_id="wrong-id"))
    if mutation == "missing":
        expected = (END, END + timedelta(minutes=30))
    if mutation == "duplicate":
        redis.xrange = lambda *a, **kw: [
            (b"100-0", {b"envelope": redis.raw.encode()}),
            (b"101-0", {b"envelope": redis.raw.encode()}),
        ]
    with pytest.raises(RepositoryConflict):
        read(redis, expected)


def test_future_recording_boundary_allows_only_already_confirmed_endpoints():
    from app.reference_trading.retained_observation_authority import (
        read_retained_interval,
    )

    result = read_retained_interval(
        ObservationStream(ReadOnlyRedis(event()), kind="completed"),
        product="m",
        day=DAY,
        after=END - timedelta(hours=1),
        before=END + timedelta(hours=8),
        expected_endpoints=(END,),
        knowledge_at=END + timedelta(minutes=1),
    )
    assert len(result) == 1
