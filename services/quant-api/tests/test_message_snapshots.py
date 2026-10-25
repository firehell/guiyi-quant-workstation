from concurrent.futures import ThreadPoolExecutor

import pytest

from app.market_messages import MessageCursorError
from app.services.message_snapshots import decode_cursor, encode_cursor
from app.services.message_snapshots import MessageSnapshotBudgetError, MessageSnapshots


def rows(count=65):
    return [
        dict(source="alert", id=str(i), bar_end="2026-10-25T00:00:00Z", event={})
        for i in range(count)
    ]


def create(cache, **kw):
    return cache.create(
        rows(),
        {"alert": {"status": "ready"}},
        {"source": "alert"},
        {"cutoff": "2026-10-25T00:00:00Z", "alert_max_id": 65},
        **kw,
    )


def test_twenty_rows_stable_pages_and_resuming_frozen_snapshot():
    cache = MessageSnapshots()
    first = create(cache, resume_count=40)
    second = cache.read(first["next_cursor"], {"source": "alert"})
    resumed = cache.read(first["resume_cursor"], {"source": "alert"})
    assert len(first["items"]) == len(second["items"]) == len(resumed["items"]) == 20
    assert len({r["id"] for p in (first, second, resumed) for r in p["items"]}) == 60
    assert second["snapshot"] == first["snapshot"]
    first["items"][0]["event"]["changed"] = True
    assert cache.read(first["next_cursor"], {"source": "alert"}) == second


def test_expiration_does_not_extend_on_pagination():
    now = [0]
    cache = MessageSnapshots(clock=lambda: now[0])
    first = create(cache)
    now[0] = 119
    assert cache.read(first["next_cursor"], {"source": "alert"})["items"]
    now[0] = 120
    with pytest.raises(MessageCursorError):
        cache.read(first["next_cursor"], {"source": "alert"})


def test_lru_capacity_byte_budget_and_restart():
    cache = MessageSnapshots(max_entries=2)
    first, second = create(cache), create(cache)
    cache.read(first["next_cursor"], {"source": "alert"})
    create(cache)
    with pytest.raises(MessageCursorError):
        cache.read(second["next_cursor"], {"source": "alert"})
    with pytest.raises(MessageCursorError):
        MessageSnapshots().read(first["next_cursor"], {"source": "alert"})
    with pytest.raises(MessageSnapshotBudgetError):
        create(MessageSnapshots(max_bytes=1))
    size = next(iter(cache._entries.values())).size
    bounded = MessageSnapshots(max_bytes=size + 1)
    old = create(bounded)
    create(bounded)
    assert sum(item.size for item in bounded._entries.values()) <= bounded.max_bytes
    with pytest.raises(MessageCursorError):
        bounded.read(old["next_cursor"], {"source": "alert"})


@pytest.mark.parametrize(
    "field,value",
    [
        ("query", {}),
        ("snapshot", {}),
        ("digest", "0" * 64),
        ("token", "x" * 32),
        ("offset", 0),
        ("offset", 10000),
        ("v", True),
    ],
)
def test_cursor_tampering_and_query_isolation(field, value):
    cache = MessageSnapshots()
    first = create(cache)
    payload = decode_cursor(first["next_cursor"])
    payload[field] = value
    with pytest.raises(MessageCursorError):
        cache.read(encode_cursor(payload), {"source": "alert"})
    with pytest.raises(MessageCursorError):
        cache.read(first["next_cursor"], {"source": "newow"})


def test_partial_states_and_parallel_access():
    cache = MessageSnapshots()

    def work(_):
        first = cache.create(rows(), {"newow": {"status": "unavailable"}}, {}, {})
        assert first["coverage"] == "partial"
        return cache.read(first["next_cursor"], {})

    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(work, range(12)))
    assert all(
        len(page["items"]) == 20 and page["coverage"] == "partial" for page in result
    )


def test_metadata_probe_matches_authoritative_reader_scope_and_detects_health_changes():
    from datetime import date
    from sqlalchemy import select
    from tests.reference_trading.test_messages import saved
    from app.reference_trading.messages import read_messages
    from app.reference_trading.models import ReferenceStream
    from app.services.message_source_scope import read_message_scope

    factory = saved()
    args = dict(since=date(2026, 9, 19), through=date(2026, 9, 19))
    for filters in (
        {},
        {"product": "rb"},
        {"strategy": "trend"},
        {"frequency": "60m"},
        {"product": "jm"},
        {"strategy": "oscillation"},
        {"frequency": "1w"},
    ):
        assert (
            read_message_scope(factory, **filters)
            == read_messages(factory, **args, **filters)["revision_snapshot"]
        )
    old = read_message_scope(factory)
    with factory() as session:
        stream = session.scalar(select(ReferenceStream))
        stream.health = "STALE_INVALID"
        session.commit()
    assert read_message_scope(factory) != old
    assert (
        read_message_scope(factory)
        == read_messages(factory, **args)["revision_snapshot"]
    )


def test_http_snapshot_reuse_resume_expiry_and_revision_failure(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import market_messages as api

    now = [0]
    monkeypatch.setattr(api, "_snapshots", MessageSnapshots(clock=lambda: now[0]))
    reads = []
    scope = [("stream", "revision", "READY", "active")]

    def reader(*args, **kw):
        reads.append(kw)
        return dict(
            items=[
                dict(id=str(i), symbol="jm", bar_end="2026-10-25T00:00:00Z")
                for i in range(65)
            ],
            truncated=True,
            revision_snapshot=scope,
            excluded_streams=1,
        )

    monkeypatch.setattr(api, "read_messages", reader)
    monkeypatch.setattr(api, "read_message_scope", lambda *a, **kw: scope)
    params = dict(start_day="2026-10-19", end_day="2026-10-25", source="newow")
    with TestClient(app) as client:
        first = client.get(
            "/api/market/messages", params={**params, "resume_count": 40}
        )
        assert first.status_code == 200
        data = first.json()
        assert len(data["items"]) == 20 and data["coverage"] == "partial"
        next_page = client.get(
            "/api/market/messages", params={**params, "cursor": data["next_cursor"]}
        )
        resumed = client.get(
            "/api/market/messages", params={**params, "cursor": data["resume_cursor"]}
        )
        assert next_page.status_code == resumed.status_code == 200
        assert len(reads) == 1
        assert {r["id"] for r in resumed.json()["items"]}.isdisjoint(
            r["id"] for r in next_page.json()["items"]
        )
        for bad in (-1, 301):
            assert (
                client.get(
                    "/api/market/messages", params={**params, "resume_count": bad}
                ).status_code
                == 422
            )
        assert (
            client.get(
                "/api/market/messages",
                params={**params, "cursor": data["next_cursor"], "resume_count": 20},
            ).status_code
            == 422
        )
        scope[:] = [("stream", "revision", "STALE_INVALID", "active")]
        assert (
            client.get(
                "/api/market/messages", params={**params, "cursor": data["next_cursor"]}
            ).status_code
            == 409
        )
        assert len(reads) == 1
        now[0] = 120
        assert (
            client.get(
                "/api/market/messages", params={**params, "cursor": data["next_cursor"]}
            ).status_code
            == 409
        )
        assert len(reads) == 1
        fresh = client.get("/api/market/messages", params=params)
        assert fresh.status_code == 200 and len(reads) == 2
        monkeypatch.setattr(
            api,
            "read_message_scope",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("secret")),
        )
        failed = client.get(
            "/api/market/messages",
            params={**params, "cursor": fresh.json()["next_cursor"]},
        )
        assert failed.status_code == 409 and "secret" not in failed.text


def test_cursor_cannot_relabel_server_snapshot_as_another_query():
    cache = MessageSnapshots()
    first = create(cache)
    payload = decode_cursor(first["next_cursor"])
    payload["query"] = {"source": "newow"}
    with pytest.raises(MessageCursorError):
        cache.read(encode_cursor(payload), {"source": "newow"})


def test_resume_short_last_page_and_arbitrary_retained_count():
    cache = MessageSnapshots()
    first = cache.create(rows(45), {}, {}, {}, resume_count=45)
    assert first["resume_cursor"] is None
    partial = cache.create(rows(45), {}, {}, {}, resume_count=7)
    next_page = cache.read(partial["resume_cursor"], {})
    assert len(next_page["items"]) == 20
    assert next_page["items"][0]["id"] == "37"
