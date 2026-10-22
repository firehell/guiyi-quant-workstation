"""Concrete loader composition: real journal validation and real kernel stepping."""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.market_data.observation_stream import ObservationEnvelope, ObservationStream
from app.reference_trading.newow_bootstrap import NewowForwardBootstrap
from app.reference_trading.retained_warm_loader import RetainedWarmSourceLoader
from app.reference_trading.repository import RepositoryConflict
from test_original_conflict_warm_seed import fixture, START


def setup(monkeypatch):
    baseline, snapshot, inputs, _, _, _, _ = fixture()
    ends = tuple(item.product_bar.bar.bar_end for item in inputs)
    day = ends[-1].date()
    events = []
    for index, item in enumerate(inputs):
        b = item.product_bar.bar
        data = dict(
            contract=b.physical_contract,
            bar_end=b.bar_end.isoformat(),
            trading_day=day.isoformat(),
            open=str(b.open),
            high=str(b.high),
            low=str(b.low),
            close=str(b.close),
            volume=str(b.volume),
            open_interest=None if b.open_interest is None else str(b.open_interest),
            turnover=None,
        )
        events.append(
            ObservationEnvelope(
                f"{day}:{b.physical_contract}:60m:{b.bar_end.isoformat()}",
                day,
                b.bar_end + timedelta(seconds=1),
                "live:bar:rb:60m",
                data,
                True,
                stream_id=f"{100 + index}-0",
                raw_received_at=b.bar_end + timedelta(seconds=1),
                confirmed_at=b.bar_end + timedelta(seconds=2),
            )
        )

    class Redis:
        calls = 0
        drift = False

        def xrange(self, *a, **kw):
            self.calls += 1
            values = events if not (self.drift and self.calls > 1) else events[:-1]
            return [
                (e.stream_id.encode(), {b"envelope": e.to_json().encode()})
                for e in values
            ]

        def hget(self, key, identity):
            e = next(e for e in events if e.observation_id == identity)
            return json.dumps({"id": e.stream_id, "payload": e.to_json()})

    redis = Redis()
    reader = SimpleNamespace(
        plan_stream=lambda request: snapshot, revalidate=lambda *a, **kw: True
    )
    market = SimpleNamespace(
        historical_metadata_evidence=lambda **kw: {"session": "fixed"}
    )
    monkeypatch.setattr(
        NewowForwardBootstrap,
        "_source",
        lambda *a, **kw: (
            baseline.identity,
            baseline.checkpoint,
            baseline.schema,
            baseline.saved_manifest,
            baseline.binding,
        ),
    )
    loader = RetainedWarmSourceLoader(
        None,
        ObservationStream(redis, kind="completed"),
        reader,
        market,
        trading_day=day,
        recording_start=START,
        knowledge_at=ends[-1] + timedelta(minutes=1),
        assert_fenced=lambda: None,
        capability_ready=lambda identity: True,
    )
    loader.authority = SimpleNamespace(
        expected_endpoints=lambda identity, contract, day, after, cutoff: tuple(
            e for e in ends if after < e <= cutoff
        ),
        owner_segments=lambda *a: ("owner", "calc"),
    )
    return loader, baseline, ends, events, redis


def test_future_start_concrete_loader_steps_complete_originals(monkeypatch):
    loader, baseline, ends, _, _ = setup(monkeypatch)
    seed = loader(None, baseline.identity.stream_id)
    assert seed.checkpoint.computed_through == ends[-1]
    assert seed.proof["warm_step_count"] == 2
    assert seed.proof["interval_authority"]["remaining_endpoints_before_start"] == []
    assert seed.checkpoint.reference_state.open_trade is None


@pytest.mark.parametrize("failure", ["missing", "owner", "reread", "fence", "baseline"])
def test_concrete_loader_rejects_source_gaps_owner_changes_and_drift(
    monkeypatch, failure
):
    loader, baseline, _, events, redis = setup(monkeypatch)
    if failure == "missing":
        events.pop()
    if failure == "owner":
        loader.authority.owner_segments = lambda *a: ("new-owner", "calc")
    if failure == "reread":
        redis.drift = True
    if failure == "fence":
        loader.assert_fenced = lambda: (_ for _ in ()).throw(
            RepositoryConflict("FENCE_LOST")
        )
    if failure == "baseline":
        loader.reader.revalidate = lambda *a, **kw: False
    with pytest.raises(RepositoryConflict):
        loader(None, baseline.identity.stream_id)
