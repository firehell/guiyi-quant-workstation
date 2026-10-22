from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
import json

import pytest
from sqlalchemy import select

from app.market_data.observation_stream import ObservationEnvelope, ObservationStream
from app.reference_trading.models import ReferenceBatch, ReferenceRevision, ReferenceStream
from app.reference_trading.repository import RepositoryConflict
from app.reference_trading.retired_original_warmup import FinalizeRetiredDayOriginalWarmup
from guiyi_quant.newow.product_adapters import seed_replay_state
from tests.reference_trading.test_retired_conflict_recovery import prepared


NOW = datetime(2026, 10, 22, 15, 5, tzinfo=UTC)
START = datetime(2026, 10, 22, 15, 30, tzinfo=UTC)
ENDS = (datetime(2026, 10, 22, 14, tzinfo=UTC), datetime(2026, 10, 22, 15, tzinfo=UTC))


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def fixture(monkeypatch):
    import app.reference_trading.retired_conflict_recovery as reset_module
    import app.reference_trading.retired_original_warmup as warm_module
    factory, repo, targets, reset, _, _ = prepared()
    old_start = datetime(2026, 10, 22, 14, 55, tzinfo=UTC)
    class Before(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 22, 14, 40, tzinfo=UTC)
    monkeypatch.setattr(reset_module, "datetime", Before)
    reset.recording_start = old_start
    p = reset.plan(targets, recording_start=old_start, expires_at=old_start-timedelta(minutes=1), now=Before.now())
    reset.apply(p, expected_plan_hash=p["plan_hash"], now=Before.now())
    monkeypatch.setattr(warm_module, "datetime", Clock)
    day = date(2026, 10, 23)
    events = []
    for i, end in enumerate(ENDS):
        raw = {"contract": "L2701", "trading_day": str(day), "bar_end": end.isoformat(),
               "open": "7000", "high": "7002", "low": "6998", "close": str(7000+i),
               "volume": "100", "open_interest": "200", "turnover": "700000"}
        events.append(ObservationEnvelope(f"{day}:L2701:60m:{end.isoformat()}", day,
            end+timedelta(seconds=1), "live:bar:l:60m", raw, True, f"{100+i}-0",
            end+timedelta(seconds=1), end+timedelta(seconds=2)))
    def rows(*args, **kwargs):
        return [(event.stream_id, {"envelope": event.to_json()}) for event in events]
    def index(key, identity):
        event = next(e for e in events if e.observation_id == identity)
        return json.dumps({"id": event.stream_id, "payload": event.to_json()})
    journal = ObservationStream(SimpleNamespace(xrange=rows, hget=index), kind="completed")
    market = SimpleNamespace(dominant_segment_for_day=lambda *a: SimpleNamespace(contract="L2701"),
                             historical_metadata_evidence=lambda **kw: {"session": "fixed"})
    service = FinalizeRetiredDayOriginalWarmup(factory, journal=journal, market=market,
        recording_start=START, knowledge_at=NOW, assert_fenced=lambda: None,
        capability_ready=lambda _: True)
    service.authority = SimpleNamespace(owner_segments=lambda *a: ("owner", "calculation"),
        expected_endpoints=lambda identity, contract, day, after, cutoff: tuple(e for e in ENDS if after < e <= cutoff))
    return factory, repo, targets, service, events


def test_real_two_originals_warm_native_kernels_with_atomic_future_flat(monkeypatch):
    factory, repo, targets, service, _ = fixture(monkeypatch)
    old = {sid: repo.load_checkpoint(sid)[0].revision_id for sid in targets}
    with factory() as db:
        before = {b.batch_id: (b.payload_hash, b.source_evidence) for b in db.scalars(select(ReferenceBatch))}
    plan = service.plan(targets, recording_start=START, expires_at=START-timedelta(minutes=1), now=NOW)
    result = service.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    for sid in targets:
        token, cp = repo.load_checkpoint(sid)
        assert token.revision_id == result[sid] != old[sid]
        assert cp.computed_through == ENDS[-1] and cp.physical_contract == "L2701"
        assert cp.reference_state.open_trade is None and cp.reference_state.recording_start == START
        if cp.stream.strategy_code != "newow_dual_fusion":
            assert cp.strategy_state != seed_replay_state()
        assert repo.read_state(sid).stream.health == "OBSERVATION_LAGGING"
        with factory() as db:
            assert db.get(ReferenceRevision, (sid, old[sid])).invalid_reason == "PREACTIVATION_WARMUP_FINALIZED"
    with factory() as db:
        assert all((db.get(ReferenceBatch, key).payload_hash, db.get(ReferenceBatch, key).source_evidence) == value for key, value in before.items())
    assert service.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW) == result


def test_missing_original_blocks(monkeypatch):
    factory, repo, targets, service, events = fixture(monkeypatch)
    old = {sid: repo.load_checkpoint(sid)[0].revision_id for sid in targets}
    events.pop()
    with pytest.raises(RepositoryConflict, match="RETAINED_OBSERVATION_UNVERIFIED"):
        service.plan(targets, recording_start=START, expires_at=START-timedelta(minutes=1), now=NOW)
    assert {sid: repo.load_checkpoint(sid)[0].revision_id for sid in targets} == old


def test_lost_final_fence_rolls_back_four_routes(monkeypatch):
    factory, repo, targets, service, events = fixture(monkeypatch)
    old = {sid: repo.load_checkpoint(sid)[0].revision_id for sid in targets}
    plan = service.plan(targets, recording_start=START, expires_at=START-timedelta(minutes=1), now=NOW)
    calls = []
    def fence():
        calls.append(1)
        # Base admissions and repeated original/fence checks precede final flush.
        if len(calls) == 22:
            raise RuntimeError("FENCE_LOST")
    service.assert_fenced = fence
    with pytest.raises(RuntimeError, match="FENCE_LOST"):
        service.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    assert {sid: repo.load_checkpoint(sid)[0].revision_id for sid in targets} == old


def test_changed_original_after_plan_cannot_commit(monkeypatch):
    _, repo, targets, service, events = fixture(monkeypatch)
    old = {sid: repo.load_checkpoint(sid)[0].revision_id for sid in targets}
    plan = service.plan(targets, recording_start=START, expires_at=START-timedelta(minutes=1), now=NOW)
    events[0] = replace(events[0], data={**events[0].data, "close": "7001"})
    with pytest.raises(RepositoryConflict, match="PREIMAGE_DRIFT"):
        service.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    assert {sid: repo.load_checkpoint(sid)[0].revision_id for sid in targets} == old


def test_modified_pristine_manifest_blocks(monkeypatch):
    factory, _, targets, service, _ = fixture(monkeypatch)
    with factory() as db, db.begin():
        stream = db.get(ReferenceStream, targets[0])
        revision = db.get(ReferenceRevision, (targets[0], stream.active_revision_id))
        seal = db.get(ReferenceBatch, revision.checkpoint_batch_id)
        seal.dependency_manifest = {**seal.dependency_manifest, "warm_state": "changed"}
    with pytest.raises(RepositoryConflict):
        service.plan(targets, recording_start=START, expires_at=START-timedelta(minutes=1), now=NOW)


@pytest.mark.parametrize("drift", ["original", "metadata", "contract"])
def test_drift_during_single_warm_admission_is_rejected(monkeypatch, drift):
    _, _, targets, service, events = fixture(monkeypatch)
    calls = []
    if drift == "original":
        original_read = service.journal.redis.xrange
        def changed(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                events[0] = replace(events[0], data={**events[0].data, "close": "7001"})
            return original_read(*args, **kwargs)
        service.journal.redis.xrange = changed
    elif drift == "metadata":
        def metadata(**kwargs):
            calls.append(1)
            return {"session": str(len(calls))}
        service.market.historical_metadata_evidence = metadata
    else:
        def owner(*args):
            calls.append(1)
            return SimpleNamespace(contract="L2701" if len(calls) == 1 else "L2702")
        service.market.dominant_segment_for_day = owner
    with pytest.raises(RepositoryConflict, match="SOURCE_DRIFT"):
        service.plan(targets, recording_start=START, expires_at=START-timedelta(minutes=1), now=NOW)
