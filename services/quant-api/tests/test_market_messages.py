from datetime import UTC, datetime

import pytest

from app.market_messages import MessageCursorError, paginate_messages


def row(source, ident, bar):
    return {
        "source": source,
        "id": str(ident),
        "bar_end": f"2026-10-{bar:02d}T00:00:00Z",
        "symbol": "jm",
    }


def test_stable_mixed_order_and_query_bound_snapshot():
    rows = [row("alert", 2, 10), row("newow", 1, 11), row("alert", 1, 10)]
    first = paginate_messages(rows, {}, {"q": ""}, {"cutoff": "x"}, None, limit=2)
    assert [x["id"] for x in first["items"]] == ["1", "2"]
    second = paginate_messages(
        rows, {}, {"q": ""}, {"cutoff": "x"}, first["next_cursor"], limit=2
    )
    assert [x["id"] for x in second["items"]] == ["1"]
    assert second["next_cursor"] is None
    with pytest.raises(MessageCursorError):
        paginate_messages(
            rows, {}, {"q": "changed"}, {"cutoff": "x"}, first["next_cursor"], limit=2
        )
    with pytest.raises(MessageCursorError):
        paginate_messages(
            rows + [row("newow", 5, 9)],
            {},
            {"q": ""},
            {"cutoff": "x"},
            first["next_cursor"],
            limit=2,
        )


def test_partial_and_truncated_are_not_empty_complete():
    page = paginate_messages(
        [],
        {
            "newow": {"status": "unavailable"},
            "alert": {"status": "ready", "truncated": True},
        },
        {},
        {},
        None,
    )
    assert page["coverage"] == "partial"
    assert page["items"] == []


def test_endpoint_freezes_alert_highwater_and_excludes_new_inserts(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.alerts.models import AlertEvent, AlertRule, SubingSignalAlignment
    from app.main import app
    from app.api import market_messages as api
    from datetime import date, timedelta

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (AlertRule, AlertEvent, SubingSignalAlignment):
        model.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(
        api,
        "read_messages",
        lambda *a, **kw: {
            "items": [
                dict(
                    id="newow-1",
                    symbol="jm",
                    contract="JM2612",
                    bar_end="2026-10-11T01:00:00+08:00",
                    revision_id="r1",
                )
            ],
            "truncated": False,
            "revision_snapshot": [("s", "r1")],
        },
    )
    monkeypatch.setattr(api, "load_product_taxonomy", lambda: {})
    with factory() as session:
        rule = AlertRule(
            rule_code="htdy_original_15m", enabled=True, scope_product_frequencies={}
        )
        session.add(rule)
        session.flush()
        for index in range(155):
            session.add(
                AlertEvent(
                    rule_id=rule.id,
                    symbol="jm",
                    contract="JM2612",
                    trading_day=date(2026, 10, 11),
                    frequency="15m",
                    bar_end=datetime(2026, 10, 11, tzinfo=UTC)
                    + timedelta(minutes=index),
                    detected_at=datetime(2026, 10, 11, tzinfo=UTC)
                    + timedelta(seconds=index),
                    result_codes=["buy"],
                )
            )
        session.commit()
    reads = []
    conversions = []
    original_reader, original_outs = api.read_alert_history, api._event_outs
    def counted_reader(session, query):
        reads.append(query.limit)
        return original_reader(session, query)
    def counted_outs(session, events):
        conversions.append(len(events))
        return original_outs(session, events)
    monkeypatch.setattr(api, "read_alert_history", counted_reader)
    monkeypatch.setattr(api, "_event_outs", counted_outs)
    params = {"start_day": "2026-10-01", "end_day": "2026-10-15"}
    with TestClient(app) as client:
        first = client.get("/api/market/messages", params=params)
        assert first.status_code == 200
        assert len(first.json()["items"]) == 50
        assert reads == [500]
        assert conversions == [155]
        with factory() as session:
            session.add(
                AlertEvent(
                    rule_id=rule.id,
                    symbol="jm",
                    contract="JM2612",
                    trading_day=date(2026, 10, 11),
                    frequency="15m",
                    bar_end=datetime(2026, 10, 11, tzinfo=UTC) + timedelta(minutes=200),
                    detected_at=datetime(2026, 10, 11, tzinfo=UTC),
                    result_codes=["buy"],
                )
            )
            session.commit()
        second = client.get(
            "/api/market/messages",
            params={**params, "cursor": first.json()["next_cursor"]},
        )
        assert second.status_code == 200
        all_rows = first.json()["items"] + second.json()["items"]
        while second.json()["next_cursor"]:
            second = client.get("/api/market/messages", params={**params, "cursor": second.json()["next_cursor"]})
            assert second.status_code == 200
            all_rows.extend(second.json()["items"])
        assert len(all_rows) == 156
        assert len({(row["source"], row["id"]) for row in all_rows}) == 156
        assert "156" not in [row["id"] for row in all_rows if row["source"] == "alert"]
        assert all_rows[-1]["source"] == "newow"  # timezone is parsed, not lexical
        monkeypatch.setattr(
            api,
            "read_messages",
            lambda *a, **kw: {
                "items": [],
                "truncated": False,
                "revision_snapshot": [("s", "r2")],
            },
        )
        stale = client.get(
            "/api/market/messages",
            params={**params, "cursor": first.json()["next_cursor"]},
        )
        assert stale.status_code == 409
        partial = client.get("/api/market/messages", params=params)
        assert partial.json()["coverage"] == "complete"
        monkeypatch.setattr(
            api,
            "read_messages",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("private error")),
        )
        failure = client.get("/api/market/messages", params=params)
        assert failure.status_code == 200
        assert failure.json()["coverage"] == "partial"
        assert failure.json()["sources"]["newow"]["status"] == "unavailable"
        assert "private" not in failure.text
        assert (
            client.get(
                "/api/market/messages",
                params={**params, "source": "alert", "frequency": "1w"},
            ).json()["items"]
            == []
        )
        searched = client.get(
            "/api/market/messages",
            params={**params, "source": "alert", "search": "JM2612"},
        )
        assert searched.status_code == 200 and len(searched.json()["items"]) == 50
        assert (
            client.get(
                "/api/market/messages", params={**params, "unknown": "bad"}
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/market/messages", params={**params, "start_day": "2025-10-01"}
            ).status_code
            == 422
        )
    engine.dispose()


def test_nonready_newow_streams_make_coverage_partial():
    page = paginate_messages(
        [],
        {"newow": {"status": "ready", "truncated": False, "excluded_streams": 1}},
        {},
        {},
        None,
    )
    assert page["coverage"] == "partial"


@pytest.mark.parametrize("cursor", ["", "garbage", "e30", "W10", "x" * 4097])
def test_invalid_cursors_rejected(cursor):
    from app.market_messages import decode_cursor

    with pytest.raises(MessageCursorError):
        decode_cursor(cursor)
