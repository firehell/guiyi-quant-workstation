from datetime import UTC, date, datetime
from types import SimpleNamespace
import json

import pytest

from app.market_data.observation_stream import ObservationEnvelope
from app.reference_trading.retired_day_recovery import RetiredDayAbsenceAuthority
from app.reference_trading.repository import RepositoryConflict


DAY = date(2026, 10, 22)
NEXT = date(2026, 10, 23)
BEFORE = datetime(2026, 10, 21, 7, tzinfo=UTC)
END = datetime(2026, 10, 22, 7, tzinfo=UTC)


def setup():
    rows, indexes = {}, {}
    keys = set()
    for kind in ("source", "completed"):
        for day in (date(2026, 10, 21), DAY):
            end = datetime(day.year, day.month, day.day, 7, tzinfo=UTC)
            event = ObservationEnvelope("other", day, end, "live:bar:cu:5m",
                {"bar_end": end.isoformat()}, True, "1-0", end, end)
            rows[kind, day] = [("1-0", {"envelope": event.to_json()})]
            content = json.loads(event.to_json())
            if kind == "source":
                content.pop("source_observed_at")
                content.pop("raw_received_at")
            indexes[kind, day] = {"other": json.dumps({"id": "1-0", "payload": event.to_json(),
                "content": json.dumps(content, sort_keys=True, separators=(",", ":"))})}
            keys.add((kind, day))
    registrations = {"source:live": NEXT, "completed:alert": NEXT, "completed:reference": NEXT}
    def stream(kind):
        return SimpleNamespace(kind=kind,
            days=lambda: (date(2026, 10, 21), DAY, NEXT),
            registered_day=lambda c: registrations[kind+":"+c],
            cursor=lambda c, d: "0-0" if not rows.get((kind, d)) else rows[kind, d][-1][0],
            tail=lambda d: "0-0" if not rows.get((kind, d)) else rows[kind, d][-1][0],
            key=lambda d: (kind, d), identity_key=lambda d: (kind, d),
            redis=SimpleNamespace(xrange=lambda key, **kw: rows.get(key, []),
                                  hgetall=lambda key: indexes.get(key, {}), exists=lambda key: key in keys))
    fence = {"generation": 22, "native_cleanup": True}
    authority = SimpleNamespace(expected_endpoints=lambda *a: (END,),
                                owner_segments=lambda *a: ("owner", "calc"))
    completed = stream("completed")
    service = RetiredDayAbsenceAuthority(completed, authority, source=stream("source"),
        contract_for_day=lambda *a: "RB2610", verify_fence=lambda: dict(fence))
    identity = SimpleNamespace(product="rb", frequency="60m")
    return service, identity, rows, indexes, registrations, fence, authority


def test_retired_absence_is_exact_and_cannot_include_open_day():
    service, identity, *_ = setup()
    proof, missing = service.freeze(identity, BEFORE)
    assert missing == (END,)
    assert proof["cutoff"] == END.isoformat()
    assert not any("2026-10-23" in key for key in proof["journals"])
    assert service.verify_gap(identity, BEFORE, proof) == missing


@pytest.mark.parametrize("consumer", ["source:live", "completed:alert", "completed:reference"])
def test_registration_not_advanced_never_grants_absence(consumer):
    service, identity, _, _, registrations, *_ = setup()
    registrations[consumer] = DAY
    with pytest.raises(RepositoryConflict, match="NOT_SEALED"):
        service.freeze(identity, BEFORE)


def test_saved_cross_day_original_and_index_conflict_block():
    service, identity, rows, indexes, *_ = setup()
    event = ObservationEnvelope("one", DAY, END, "live:bar:rb:60m",
        {"bar_end": END.isoformat()}, True, "1-0", END, END)
    rows["completed", DAY] = [("1-0", {"envelope": event.to_json()})]
    indexes["completed", DAY] = {"one": json.dumps({"id": "1-0", "payload": event.to_json()})}
    with pytest.raises(RepositoryConflict, match="SAVED_ORIGINAL_FIRST"):
        service.freeze(identity, BEFORE)
    indexes["completed", DAY] = {}
    with pytest.raises(RepositoryConflict, match="JOURNAL_CHANGED"):
        service.freeze(identity, BEFORE)
    service = RetiredDayAbsenceAuthority(service.journal, service.authority, source=service.source,
        contract_for_day=service.contract_for_day, verify_fence=service.verify_fence)
    with pytest.raises(RepositoryConflict, match="JOURNAL_INVALID"):
        service.freeze(identity, BEFORE)


@pytest.mark.parametrize("drift", ["fence", "owner", "endpoints", "index"])
def test_apply_rechecks_every_authority_layer(drift):
    service, identity, _, indexes, _, fence, authority = setup()
    proof, _ = service.freeze(identity, BEFORE)
    if drift == "fence":
        fence["generation"] = 23
    elif drift == "owner":
        authority.owner_segments = lambda *a: ("changed", "calc")
    elif drift == "endpoints":
        authority.expected_endpoints = lambda *a: (datetime(2026, 10, 22, 6, tzinfo=UTC), END)
    else:
        indexes["source", DAY] = {"unmatched": "{}"}
    with pytest.raises(RepositoryConflict):
        service.verify_gap(identity, BEFORE, proof)


def test_future_endpoint_and_missing_cross_day_journal_block():
    service, identity, *_rest, authority = setup()
    authority.expected_endpoints = lambda *a: (datetime(2026, 10, 23, 7, tzinfo=UTC),)
    with pytest.raises(RepositoryConflict, match="ENDPOINTS_INVALID"):
        service.freeze(identity, BEFORE)
    service.journal.redis.exists = lambda key: False
    with pytest.raises(RepositoryConflict, match="JOURNAL_MISSING"):
        service.freeze(identity, BEFORE)


def test_corrupted_content_cannot_grant_initial_proof():
    service, identity, _, indexes, *_ = setup()
    record = json.loads(indexes["source", DAY]["other"])
    record["content"] = "corrupt"
    indexes["source", DAY]["other"] = json.dumps(record)
    with pytest.raises(RepositoryConflict, match="INDEX_CONFLICT"):
        service.freeze(identity, BEFORE)
