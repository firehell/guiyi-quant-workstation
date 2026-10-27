from datetime import UTC, date, datetime, timedelta
from fnmatch import fnmatch
import json

import pytest

from app.market_data.observation_stream import ObservationEnvelope, ObservationStream
from app.reference_trading.inbox_protocol import ReceivingProtocol
from app.runtime_handover import _write
from app.reference_trading.receiving_handover import (
    freeze_receiving_intent,
    seal_receiving_backlog,
    verify_receiving_backlog,
    ReceivingHandoverError,
    KIND,
)

DAY = date(2026, 10, 27)
TARGET = {
    "service": "reference-worker",
    "root": "/verified/release-v1.16.14",
    "commit": "a" * 40,
    "tag": "v1.16.14",
    "generation": 31,
}
SCHEMA = {"schema_sha256": "c" * 64, "database_identity_sha256": "d" * 64}
CAPACITY = {"unfinished_bytes": 0, "day_inputs": {DAY.isoformat(): 0}}


class Redis:
    def __init__(self):
        self.values, self.rows, self.hashes = {}, {}, {}

    def get(self, key):
        return self.values.get(key)

    def scan_iter(self, match):
        return iter(key for key in (*self.values, *self.rows) if fnmatch(key, match))

    def xrange(self, key, min="-", max="+", count=None):
        def identifier(value):
            return tuple(map(int, value.split("-")))

        rows = [
            (key, value)
            for key, value in self.rows.get(key, [])
            if (
                min == "-" or identifier(key) > identifier(min[1:])
                if min.startswith("(")
                else min == "-" or identifier(key) >= identifier(min)
            )
            and (max == "+" or identifier(key) <= identifier(max))
        ]
        return rows[:count] if count else rows

    def xrevrange(self, key, count):
        return list(reversed(self.rows.get(key, [])))[:count]

    def hlen(self, key):
        return len(self.hashes.get(key, {}))

    def hscan_iter(self, key, count=512):
        return iter(self.hashes.get(key, {}).items())


def setup(tmp_path, *, status="requested"):
    redis = Redis()
    journal = ObservationStream(redis, kind="completed")
    redis.values[journal.registration_key("reference")] = DAY.isoformat()
    redis.values[journal.cursor_key("reference", DAY)] = "10-0"
    rows = []
    identities = {}
    for index in (10, 11, 12):
        end = datetime(2026, 10, 27, 1, index, tzinfo=UTC)
        event = ObservationEnvelope(
            f"source-{index}",
            DAY,
            end + timedelta(seconds=1),
            "live:bar:rb:1m",
            {
                "bar_end": end.isoformat(),
                "trading_day": DAY.isoformat(),
                "contract": "RB2701",
                "close": "100",
            },
            True,
            f"{index}-0",
            end + timedelta(seconds=1),
            end + timedelta(seconds=2),
        )
        raw = event.to_json()
        rows.append((event.stream_id, {"envelope": raw}))
        identities[event.observation_id] = json.dumps(
            {"id": event.stream_id, "payload": raw, "content": raw}
        )
    redis.rows[journal.key(DAY)] = rows
    redis.hashes[journal.identity_key(DAY)] = identities
    protocol = ReceivingProtocol(tmp_path / "receiving.json", binding="b" * 64)
    value = {
        "schema_version": 1,
        "protocol_version": 2,
        "status": status,
        "binding": protocol.binding,
        "requested_at": datetime(2026, 10, 27, tzinfo=UTC).isoformat(),
    }
    if status == "active":
        value["boundaries"] = {DAY.isoformat(): {"cursor": "0-0", "tail": "9-0"}}
    _write(protocol.path, value)
    intent = freeze_receiving_intent(
        protocol, journal, target=TARGET, schema_proof=SCHEMA
    )
    return protocol, journal, intent


@pytest.mark.parametrize("status", ("requested", "active"))
def test_freezes_readonly_reference_suffix_without_advancing_or_activating(
    tmp_path, status
):
    protocol, journal, intent = setup(tmp_path, status=status)
    before = protocol.path.read_bytes()
    progress = intent["baseline"]
    proof = seal_receiving_backlog(
        protocol,
        journal,
        intent,
        target=TARGET,
        schema_proof=SCHEMA,
        progress=progress,
        capacity=CAPACITY,
    )
    assert proof["kind"] == KIND
    assert proof["count"] == 2 and proof["bytes"] > 0
    assert proof["progress"] == progress
    assert '"close"' not in json.dumps(proof)
    verify_receiving_backlog(
        protocol,
        journal,
        intent,
        proof,
        target=TARGET,
        schema_proof=SCHEMA,
        capacity=CAPACITY,
    )
    assert journal.cursor("reference", DAY) == "10-0"
    assert protocol.path.read_bytes() == before


@pytest.mark.parametrize(
    "drift",
    (
        "cursor",
        "tail",
        "middle",
        "identity",
        "missing_row",
        "registration",
        "partition",
        "protocol",
        "intake",
        "target",
    ),
)
def test_every_frozen_boundary_original_and_intent_is_revalidated(tmp_path, drift):
    protocol, journal, intent = setup(tmp_path)
    proof = seal_receiving_backlog(
        protocol,
        journal,
        intent,
        target=TARGET,
        schema_proof=SCHEMA,
        progress=intent["baseline"],
        capacity=CAPACITY,
    )
    target = TARGET
    if drift == "cursor":
        journal.redis.values[journal.cursor_key("reference", DAY)] = "11-0"
    elif drift == "tail":
        journal.redis.rows[journal.key(DAY)].pop()
    elif drift == "middle":
        journal.redis.rows[journal.key(DAY)][1][1]["envelope"] = journal.redis.rows[
            journal.key(DAY)
        ][1][1]["envelope"].replace("100", "101")
    elif drift == "identity":
        journal.redis.hashes[journal.identity_key(DAY)].pop("source-11")
    elif drift == "missing_row":
        journal.redis.rows[journal.key(DAY)].pop(1)
    elif drift == "registration":
        journal.redis.values[journal.registration_key("reference")] = "2026-10-28"
    elif drift == "partition":
        journal.redis.rows["live:observations:completed:2026-10-28"] = []
    elif drift == "target":
        target = {**TARGET, "commit": "e" * 40}
    else:
        value = protocol.read()
        value["status" if drift == "protocol" else "intake_error"] = (
            "active" if drift == "protocol" else "UNKNOWN"
        )
        if drift == "protocol":
            value["boundaries"] = {}
        _write(protocol.path, value)
    with pytest.raises(ReceivingHandoverError):
        verify_receiving_backlog(
            protocol,
            journal,
            intent,
            proof,
            target=target,
            schema_proof=SCHEMA,
            capacity=CAPACITY,
        )


def test_invalid_completed_envelope_fails_same_native_ingest_validation(tmp_path):
    protocol, journal, intent = setup(tmp_path)
    raw = json.loads(journal.redis.rows[journal.key(DAY)][1][1]["envelope"])
    raw["confirmed_at"] = None
    changed = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    journal.redis.rows[journal.key(DAY)][1][1]["envelope"] = changed
    journal.redis.hashes[journal.identity_key(DAY)]["source-11"] = json.dumps(
        {"id": "11-0", "payload": changed, "content": changed}
    )
    with pytest.raises(ReceivingHandoverError):
        seal_receiving_backlog(
            protocol,
            journal,
            intent,
            target=TARGET,
            schema_proof=SCHEMA,
            progress=intent["baseline"],
            capacity=CAPACITY,
        )


def test_zero_cursor_is_legal_and_missing_cursor_never_reconstructed(tmp_path):
    protocol, journal, _ = setup(tmp_path)
    journal.redis.values[journal.cursor_key("reference", DAY)] = "0-0"
    intent = freeze_receiving_intent(
        protocol, journal, target=TARGET, schema_proof=SCHEMA
    )
    proof = seal_receiving_backlog(
        protocol,
        journal,
        intent,
        target=TARGET,
        schema_proof=SCHEMA,
        progress=intent["baseline"],
        capacity=CAPACITY,
    )
    assert proof["count"] == 3
    journal.redis.values.pop(journal.cursor_key("reference", DAY))
    with pytest.raises(ReceivingHandoverError):
        verify_receiving_backlog(
            protocol,
            journal,
            intent,
            proof,
            target=TARGET,
            schema_proof=SCHEMA,
            capacity=CAPACITY,
        )


def test_safe_boundary_deadline_and_conservative_existing_capacity_are_not_widened(
    tmp_path,
):
    protocol, journal, intent = setup(tmp_path)

    def expired():
        raise RuntimeError("deadline")

    with pytest.raises(ReceivingHandoverError):
        seal_receiving_backlog(
            protocol,
            journal,
            intent,
            target=TARGET,
            schema_proof=SCHEMA,
            progress=intent["baseline"],
            capacity=CAPACITY,
            check_budget=expired,
        )
    with pytest.raises(ReceivingHandoverError):
        seal_receiving_backlog(
            protocol,
            journal,
            intent,
            target=TARGET,
            schema_proof=SCHEMA,
            progress=intent["baseline"],
            capacity={
                "unfinished_bytes": 6 * 1024**3,
                "day_inputs": {DAY.isoformat(): 0},
            },
        )
