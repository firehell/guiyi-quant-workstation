from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.reference_trading.messages import read_messages
from app.reference_trading.models import (
    ReferenceBatch,
    ReferenceRevision,
    ReferenceStream,
)
from app.reference_trading.presentation import envelope, presentation_point
from app.reference_trading.query import QueryConflict
from tests.reference_trading.test_repository import _seed_repository, _open_batch


def saved():
    repository, factory, stream, revision, manifest, seed = _seed_repository()
    points = [
        presentation_point(
            kind="action",
            value={
                "bar_end": "2026-09-19T07:00:00+00:00",
                "kind": "BUILD",
                "physical_contract": "RB2610",
            },
            trading_day=date(2026, 9, 19),
            formula_versions=("v1",),
        ),
        presentation_point(
            kind="hint",
            value={
                "bar_end": "2026-09-19T07:00:00+00:00",
                "kind": "J",
                "physical_contract": "RB2610",
            },
            trading_day=date(2026, 9, 19),
            formula_versions=("v1",),
        ),
    ]
    repository.commit_batch(
        seed,
        _open_batch(
            stream,
            revision,
            manifest,
            seed,
            evidence={"presentation_v1": envelope(points)},
        ),
    )
    with factory() as session:
        row = session.get(ReferenceStream, stream.stream_id)
        row.recording_mode = "forward_observation"
        row.observation_policy_version = "v1"
        row.strategy_code = "newow_trend"
        row.frequency = "60m"
        row.health = "READY"
        row.active_revision_id = revision
        row.latest_seq = 2
        session.get(ReferenceRevision, (stream.stream_id, revision)).status = "active"
        batch = session.scalar(
            select(ReferenceBatch).where(ReferenceBatch.kind == "calculation")
        )
        batch.observed_at = datetime(2026, 9, 19, 7, 1, tzinfo=UTC)
        session.commit()
    return factory


def test_feed_filters_preserves_hints_and_has_no_delivery_or_execution():
    factory = saved()
    args = dict(since=date(2026, 9, 19), through=date(2026, 9, 19))
    page = read_messages(factory, **args)
    assert len(page["items"]) == 2
    assert {row["point"]["kind"] for row in page["items"]} == {"action", "hint"}
    assert len({row["id"] for row in page["items"]}) == 2
    assert all(
        row["page_parity"]
        and not row["executable"]
        and "notification_attempted_at" not in row
        for row in page["items"]
    )
    assert read_messages(factory, **args, strategy="oscillation")["items"] == []
    assert read_messages(factory, **args, frequency="1w")["items"] == []
    assert read_messages(factory, **args, product="jm")["items"] == []
    assert read_messages(factory, **args, limit=1)["truncated"] is True
    with factory() as session:
        row = session.scalar(select(ReferenceStream))
        row.health = "STALE_INVALID"
        session.commit()
    assert read_messages(factory, **args)["items"] == []


def test_feed_never_uses_historical_or_seed_facts():
    factory = saved()
    with factory() as session:
        row = session.scalar(select(ReferenceStream))
        row.recording_mode = "historical_replay"
        row.observation_policy_version = None
        session.commit()
    assert (
        read_messages(factory, since=date(2026, 9, 19), through=date(2026, 9, 19))[
            "items"
        ]
        == []
    )


@pytest.mark.parametrize(
    "kwargs",
    [{"strategy": "invented"}, {"frequency": "5m"}, {"product": "../"}, {"limit": 501}],
)
def test_feed_rejects_unknown_scope(kwargs):
    with pytest.raises(QueryConflict):
        read_messages(
            None, since=date(2026, 9, 19), through=date(2026, 9, 19), **kwargs
        )
