from datetime import UTC, date, datetime
import os
from types import SimpleNamespace

import pytest

from app.market_data.after_market import _evidence_hash
from app.runtime_cohort_errors import CohortError
from app import runtime_market_scope_cutover as cutover

DAY = date(2026, 11, 30)
NOW = datetime(2026, 11, 30, 10, 10, tzinfo=UTC)
COMMIT = "a" * 40
PRODUCTS = ("rb", "rs")
SUBSCRIPTIONS = {"rb": "RB2701", "rs": "RS2701"}


@pytest.fixture
def scope_archive(monkeypatch):
    revisions = dict.fromkeys(PRODUCTS, "proof")
    receipt = SimpleNamespace(identity="archive", trading_day=DAY, revisions=revisions)
    evidence = {"code_commit": COMMIT, "canonical_readback": revisions, "rank1_matches_snapshot": True,
                "formal_rank1_sha256": _evidence_hash(SUBSCRIPTIONS), "snapshot_sha256": _evidence_hash(SUBSCRIPTIONS)}
    monkeypatch.setattr(cutover, "current_retained_receipt", lambda *a, **kw: receipt)
    monkeypatch.setattr(cutover, "verified_retained_cleanup", lambda *a, **kw: evidence)


def test_missing_archive_stops_before_reading_redis(monkeypatch, tmp_path):
    monkeypatch.setattr(cutover, "current_retained_receipt", lambda *a, **kw: None)
    monkeypatch.setattr(cutover, "verified_retained_cleanup", lambda *a, **kw: None)
    with pytest.raises(CohortError, match="MARKET_SCOPE_CUTOVER_ARCHIVE_UNPROVEN"):
        cutover.archived_tick_frontier(object(), tmp_path, day=DAY, products=PRODUCTS,
                                       archive_commit=COMMIT, now=NOW)


def test_old_tick_journal_and_cursor_are_preserved(scope_archive, tmp_path):
    from redis import Redis
    from app.market_data.observation_stream import ObservationEnvelope, ObservationStream

    port = os.environ.get("GUIYI_TEST_REDIS_PORT")
    if not port:
        pytest.skip("requires dedicated test Redis")
    assert int(port) >= 1024 and int(port) != 6379
    with Redis(host="127.0.0.1", port=int(port)) as client:
        assert client.dbsize() == 0
        keys = []
        try:
            for kind in ("source", "completed"):
                stream = ObservationStream(client, kind=kind)
                key, index = stream.key(DAY), stream.identity_key(DAY)
                keys.extend((key, index))
                data = {"contract": "RB2701"}
                if kind == "source":
                    data["subscription_snapshot"] = SUBSCRIPTIONS
                event = ObservationEnvelope("original", DAY, NOW, "live:bar:rb:1m", data, True,
                    raw_received_at=NOW, confirmed_at=NOW if kind == "completed" else None,
                    source_generation="rqdata-tick:" + "a" * 32 + ":1")
                identifier = stream.append(event)
                if kind == "source":
                    cursor, reg = stream.cursor_key("live", DAY), stream.registration_key("live")
                    keys.extend((cursor, reg))
                    client.set(reg, DAY.isoformat())
                    client.set(cursor, identifier)

            def proof():
                return cutover.archived_tick_frontier(client, tmp_path, day=DAY, products=PRODUCTS,
                                                       archive_commit=COMMIT, now=NOW)

            before = client.mget(cursor, reg)
            first = proof()
            assert proof() == first
            assert client.mget(cursor, reg) == before
            assert set(first["streams"]) == {"source", "completed"}
            assert all(row[DAY.isoformat()]["count"] == 1 for row in first["streams"].values())

            completed = ObservationStream(client, kind="completed")
            unexpected = completed.registration_key("alert")
            client.set(unexpected, DAY.isoformat())
            keys.append(unexpected)
            with pytest.raises(CohortError, match="MARKET_SOURCE_(CONSUMER_SCOPE_CHANGED|OLD_BACKLOG)"):
                proof()
            client.delete(unexpected)
            client.set(cursor, "0-0")
            with pytest.raises(CohortError, match="MARKET_SOURCE_(CONSUMER_SCOPE_CHANGED|OLD_BACKLOG)"):
                proof()
        finally:
            client.delete(*keys)
