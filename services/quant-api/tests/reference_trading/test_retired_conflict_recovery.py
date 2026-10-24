from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.reference_trading.capture import ForwardCapture
from app.reference_trading.contracts import SeedChunk, manifest_sha256
from app.reference_trading.models import ReferenceActivationReceipt, ReferenceBatch, ReferenceRevision
from app.reference_trading.newow_bootstrap import NewowForwardBootstrap
from app.reference_trading.reconciliation import CanonicalEvidence, ForwardReconciler
from app.reference_trading.retired_conflict_recovery import RetiredDayConflictReset
from app.reference_trading.repository import RepositoryConflict
from guiyi_quant.newow.fusion_reference import FusionReferenceReplayState, build_fusion_stream_identity
from guiyi_quant.newow.product_adapters import build_product_identity, seed_replay_state
from guiyi_quant.reference_trading import ReferenceState
from tests.reference_trading.test_newow_bootstrap import setup_source, NOW, START, plan_for


BOUNDARY = datetime(2026, 10, 22, 7, tzinfo=UTC)


def prepared():
    factory, repo, template, _, old = setup_source(frequency="60m")
    sources, targets = [], []
    for strategy in ("trend", "oscillation", "main_rise", "dual_fusion"):
        if strategy == "dual_fusion":
            identity = build_fusion_stream_identity("l", "60m")
            state, schema = FusionReferenceReplayState(), "newow_dual_fusion_reference_v1"
        else:
            product = build_product_identity("l", strategy, "60m")
            identity = replace(template, product="l", strategy_code="newow_"+strategy,
                               formula_versions=product.formula_versions, profile_id=product.profile_id)
            state, schema = old.strategy_state, "newow_product_replay_v1"
        row = repo.ensure_stream(identity)
        manifest = {"fixture": strategy}
        revision = repo.create_revision(identity.stream_id, row.row_version, manifest_sha256(manifest))
        checkpoint = replace(old, stream=identity, strategy_state=state,
                             reference_state=ReferenceState.flat(identity))
        repo.stage_seed_chunk(revision, SeedChunk("fixture", 0, 1, sha256(b"fixture").hexdigest(), "fixture"))
        repo.seal_seed(revision, manifest, checkpoint, schema)
        repo.publish_revision(identity.stream_id, revision, row.row_version, manifest_sha256(manifest))
        sources.append(identity)
    bootstrap = NewowForwardBootstrap(factory)
    for identity in sources:
        plan = plan_for(bootstrap, identity)
        targets.append(bootstrap.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)["target_stream_id"])
    for target in targets:
        token, _ = repo.load_checkpoint(target)
        capture = ForwardCapture(target, token.revision_id, 1, "mismatch", START,
            START+timedelta(seconds=1), "completed_live", {"close": "1"},
            {"source_sha256": sha256(b"old").hexdigest()}, "first_seen")
        cid = repo.capture_forward(capture)
        ForwardReconciler(factory, lambda _: CanonicalEvidence("new", sha256(b"new").hexdigest())).reconcile(cid, now=START+timedelta(seconds=2))
    start = datetime.now(UTC)+timedelta(hours=1)
    proof = {"kind": "RETIRED_DAY_ABSENCE_V1", "missing_endpoints": [BOUNDARY.isoformat()]}
    authority = SimpleNamespace(freeze=lambda *args: (dict(proof), (BOUNDARY,)))
    service = RetiredDayConflictReset(factory, absence_authority=authority,
                                     recording_start=start, assert_fenced=lambda: None)
    return factory, repo, tuple(targets), service, start, proof


def test_atomic_four_route_reset_keeps_conflict_and_never_claims_warm():
    factory, repo, targets, service, start, _ = prepared()
    old = {sid: repo.load_checkpoint(sid)[0].revision_id for sid in targets}
    with factory() as db:
        before = {b.batch_id: b.source_evidence for b in db.scalars(select(ReferenceBatch))}
    now = datetime.now(UTC)
    plan = service.plan(targets, recording_start=start, expires_at=start-timedelta(minutes=1), now=now)
    result = service.apply(plan, expected_plan_hash=plan["plan_hash"], now=now)
    assert set(result) == set(targets)
    for sid in targets:
        token, checkpoint = repo.load_checkpoint(sid)
        expected = FusionReferenceReplayState() if checkpoint.stream.strategy_code == "newow_dual_fusion" else seed_replay_state()
        assert checkpoint.strategy_state == expected
        assert checkpoint.computed_through == BOUNDARY
        assert checkpoint.physical_contract is None
        assert checkpoint.reference_state == ReferenceState.flat(checkpoint.stream, recording_start=start)
        with factory() as db:
            assert db.get(ReferenceRevision, (sid, old[sid])).invalid_reason == "DATA_CONFLICT"
            assert db.get(ReferenceRevision, (sid, token.revision_id)).status == "active"
        assert repo.read_state(sid).stream.health == "OBSERVATION_LAGGING"
    with factory() as db:
        assert all(db.get(ReferenceBatch, key).source_evidence == value for key, value in before.items())
    assert service.apply(plan, expected_plan_hash=plan["plan_hash"], now=start+timedelta(days=1)) == result


def test_absence_drift_and_fence_loss_preserve_every_active_revision():
    factory, repo, targets, service, start, proof = prepared()
    old = {sid: repo.load_checkpoint(sid)[0].revision_id for sid in targets}
    now = datetime.now(UTC)
    plan = service.plan(targets, recording_start=start, expires_at=start-timedelta(minutes=1), now=now)
    proof["changed"] = True
    with pytest.raises(RepositoryConflict, match="PREIMAGE_DRIFT"):
        service.apply(plan, expected_plan_hash=plan["plan_hash"], now=now)
    proof.pop("changed")
    calls = []
    def fence():
        calls.append(1)
        if len(calls) == 6:
            raise RuntimeError("FENCE_LOST")
    service.assert_fenced = fence
    with pytest.raises(RuntimeError, match="FENCE_LOST"):
        service.apply(plan, expected_plan_hash=plan["plan_hash"], now=now)
    assert {sid: repo.load_checkpoint(sid)[0].revision_id for sid in targets} == old
    with factory() as db:
        assert len(db.scalars(select(ReferenceActivationReceipt)).all()) == 4
