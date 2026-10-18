"""Capture mismatch recovery uses final typed warm state without original transfer."""

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.reference_trading import conflict_recovery
from app.reference_trading.capture import ForwardCapture
from app.reference_trading.contracts import SeedChunk, manifest_sha256
from app.reference_trading.inputs import HistoricalInputBar, HistoricalInputSnapshot
from app.reference_trading.models import ReferenceBatch, ReferenceCaptureReconciliation
from app.reference_trading.newow_bootstrap import NewowForwardBootstrap
from app.reference_trading.original_conflict import OriginalObservationTransfer
from app.reference_trading.original_conflict_warm_seed import (
    WarmBaseline,
    WarmInput,
    WarmInterval,
    _hash,
    _input_facts,
    _result,
    materialize_warm_seed,
    materialize_fusion_warm_seed,
)
from app.reference_trading.reconciliation import ForwardReconciler, CanonicalEvidence
from app.reference_trading.repository import RepositoryConflict
from app.reference_trading.service import NewowHistoricalPayload
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_contracts import ProductBar
from tests.reference_trading.test_original_conflict import setup_group, proof
from tests.reference_trading.test_newow_bootstrap import NOW, START

NEW_START = START + timedelta(minutes=20)
EXPIRY = NEW_START - timedelta(minutes=1)


def prepared(engine=None, *, captures=True):
    factory, repo, sources, targets, original = setup_group(engine)
    bootstrap = NewowForwardBootstrap(factory)
    seeds = {}
    for sid in sources:
        with factory() as db:
            identity, cp, schema, saved, binding = bootstrap._source(db, sid)
        if identity.strategy_code == "newow_dual_fusion":
            fusion = (identity, binding)
            continue
        # Exact fixture policy comes from the native source identity, not an alternative strategy.
        from app.market_data.newow.product_release import candidate_input_quality_policy

        product = build_product_identity(
            "rb",
            identity.strategy_code.removeprefix("newow_"),
            "60m",
            input_quality_policy=candidate_input_quality_policy(
                "rb", "60m", candidate_weekly=False
            ),
        )
        end = cp.computed_through
        old = ProductBar(
            NewowDailyBar(
                "rb",
                "RB2610",
                "owner",
                end.date(),
                end,
                Decimal("3500"),
                Decimal("3510"),
                Decimal("3490"),
                Decimal("3505"),
                100,
                None,
                "fixture",
                True,
                True,
            ),
            "60m",
            calculation_segment_id="calc",
            source_bar_sha256="a" * 64,
        )
        value = HistoricalInputBar(
            end,
            end.date(),
            "RB2610",
            "owner",
            "calc",
            old.bar.close,
            cp.last_fingerprint,
            NewowHistoricalPayload(product, old, False),
        )
        saved = {
            "reader": "newow_product_reader_intraday_v3",
            "input_sha256": _hash((value,)),
            "input_count": 1,
            "source_evidence_sha256": "a" * 64,
            "quality_policy": product.input_quality_policy.value,
        }
        current = repo.read_state(sid)
        repo.invalidate_revision(
            sid, current.revision_id, current.stream.row_version, "fixture-publication"
        )
        current = repo.read_state(sid)
        revision = repo.create_revision(
            sid, current.stream.row_version, manifest_sha256(saved)
        )
        repo.stage_seed_chunk(
            revision,
            SeedChunk("fixture", 0, 1, sha256(b"fixture").hexdigest(), "fixture"),
        )
        repo.seal_seed(revision, saved, cp, schema)
        repo.publish_revision(
            sid, revision, current.stream.row_version, manifest_sha256(saved)
        )
        with factory() as db:
            identity, cp, schema, saved, binding = bootstrap._source(db, sid)
        fresh = {**saved, "source_evidence_sha256": "b" * 64}
        snapshot = HistoricalInputSnapshot(
            identity, end.date(), end, (value,), fresh, manifest_sha256(fresh), 1000
        )
        bar_end = NOW - timedelta(minutes=1)
        bar = replace(
            old,
            bar=replace(
                old.bar,
                bar_end=bar_end,
                trading_day=bar_end.date(),
                close=Decimal(3510),
            ),
            source_bar_sha256="c" * 64,
        )
        item = WarmInput(bar, "canonical_completed", bar_end, {})
        authority = {
            **_input_facts(item),
            "expected_endpoint": bar_end.isoformat(),
            "previous_watermark": end.isoformat(),
            "expected_endpoints": [bar_end.isoformat()],
            "source_manifest_sha256": "d" * 64,
            "owner_sha256": "e" * 64,
            "session_sha256": "f" * 64,
            "quality_sha256": "1" * 64,
            "rollover": False,
        }
        item = replace(item, source_proof=authority)

        def verify(
            value, *, identity=identity, end=end, bar_end=bar_end, snapshot=snapshot
        ):
            if isinstance(value, HistoricalInputSnapshot):
                return {
                    "kind": "canonical_baseline",
                    "stream_id": identity.stream_id,
                    "input_sha256": snapshot.dependency_manifest["input_sha256"],
                    "input_count": 1,
                    "source_evidence_sha256": "b" * 64,
                    "computed_through": end.isoformat(),
                    "range_sha256": _hash(snapshot.bars),
                    "physical_sha256": "2" * 64,
                    "session_sha256": "3" * 64,
                    "quality_sha256": "4" * 64,
                }
            if isinstance(value, WarmInterval):
                return {
                    "kind": "completed_warm_interval",
                    "stream_id": identity.stream_id,
                    "previous_watermark": end.isoformat(),
                    "cutoff": bar_end.isoformat(),
                    "recording_start": NEW_START.isoformat(),
                    "knowledge_at": NOW.isoformat(),
                    "stage": "final_observation",
                    "physical_contract": "RB2610",
                    "owner_segment_id": "owner",
                    "calculation_segment_id": "calc",
                    "expected_endpoints": [bar_end.isoformat()],
                    "computed_through": bar_end.isoformat(),
                    "remaining_endpoints_before_start": [],
                    "session_sha256": "3" * 64,
                    "owner_sha256": "5" * 64,
                    "quality_sha256": "4" * 64,
                }
            return value.source_proof

        seeds[sid] = materialize_warm_seed(
            WarmBaseline(identity, cp, schema, saved, binding),
            fresh_snapshot=snapshot,
            inputs=(item,),
            expected_endpoints=(bar_end,),
            recording_start=NEW_START,
            cutoff=bar_end,
            knowledge_at=NOW,
            verify_authority=verify,
        )
    identity, binding = fusion
    seeds[identity.stream_id] = materialize_fusion_warm_seed(
        identity,
        tuple(seeds.values()),
        original_binding=binding,
        recording_start=NEW_START,
    )
    if captures:
        for sid, target in zip(sources, targets):
            state = repo.read_state(target)
            if seeds[sid].identity.strategy_code == "newow_dual_fusion":
                continue
            capture = ForwardCapture(
                target,
                state.revision_id,
                1,
                "actual-capture",
                START,
                START + timedelta(seconds=1),
                "completed_live",
                {"close": "1"},
                {"source_sha256": sha256(b"old").hexdigest()},
                "first_seen",
            )
            capture_id = repo.capture_forward(capture)
            ForwardReconciler(
                factory,
                lambda _: CanonicalEvidence("new-source", sha256(b"new").hexdigest()),
            ).reconcile(capture_id, now=START + timedelta(seconds=2))

    def loader(db, sid, *, lock=False):
        return seeds[sid]

    def verified(identity, binding, manifest):
        with factory() as db:
            actual = bootstrap._source(db, identity.stream_id)[-1]
        assert binding["original_source_binding"] == actual
        assert manifest == seeds[identity.stream_id].manifest
        return {"manifest_sha256": manifest_sha256(manifest)}

    recovery_class = getattr(
        conflict_recovery, "FinalWarmConflictRevisionRecovery", None
    )
    assert recovery_class is not None, (
        "capture mismatch recovery lacks final typed warm source admission"
    )
    service = recovery_class(
        factory,
        source_loader=loader,
        verify_source=verified,
        assert_fenced=lambda: None,
    )
    return factory, repo, sources, targets, original, seeds, service


def test_final_warm_capture_recovery_keeps_existing_evidence_and_activates_flat_state(
    engine=None,
):
    factory, repo, sources, targets, _, seeds, service = prepared(engine)
    with factory() as db:
        before = {
            r.batch_id: r.payload_hash for r in db.scalars(select(ReferenceBatch)).all()
        }
        reconciliations = [
            (r.reconciliation_id, r.status)
            for r in db.scalars(select(ReferenceCaptureReconciliation)).all()
        ]
    plan = service.plan(
        sources,
        recording_start=NEW_START,
        expires_at=EXPIRY,
        now=START + timedelta(minutes=1),
    )
    result = service.apply(
        plan, expected_plan_hash=plan["plan_hash"], now=START + timedelta(minutes=2)
    )
    assert set(result) == set(targets)
    for sid, target in zip(sources, targets):
        _, cp = repo.load_checkpoint(target)
        assert cp.strategy_state == seeds[sid].checkpoint.strategy_state
        assert cp.computed_through == NOW - timedelta(minutes=1)
        assert (
            cp.reference_state.open_trade is None
            and cp.reference_state.recording_start == NEW_START
        )
    with factory() as db:
        assert {
            r.batch_id: r.payload_hash
            for r in db.scalars(
                select(ReferenceBatch).where(ReferenceBatch.batch_id.in_(before))
            ).all()
        } == before
        assert [
            (r.reconciliation_id, r.status)
            for r in db.scalars(select(ReferenceCaptureReconciliation)).all()
        ] == reconciliations
        assert not db.scalar(
            select(ReferenceBatch.batch_id)
            .where(ReferenceBatch.batch_key.like("original-conflict:%"))
            .limit(1)
        )


def test_original_typed_receipts_cannot_admit_capture_recovery():
    factory, _, sources, targets, original, _, service = prepared(captures=False)
    transfer = OriginalObservationTransfer(
        factory, verify_observation=proof, assert_fenced=lambda: None
    )
    plan = transfer.plan(targets, (original,))
    transfer.apply(
        plan, expected_plan_hash=plan["plan_hash"], now=START + timedelta(minutes=3)
    )
    with pytest.raises(RepositoryConflict, match="CONFLICT_RECOVERY_SCOPE_INVALID"):
        service.plan(
            sources,
            recording_start=NEW_START,
            expires_at=EXPIRY,
            now=START + timedelta(minutes=4),
        )


@pytest.mark.parametrize(
    "kind", ["untyped", "tampered", "provisional", "incomplete", "wrong_start"]
)
def test_unverified_or_incomplete_seed_cannot_create_plan(kind):
    _, _, sources, _, _, seeds, service = prepared()
    sid = sources[0]
    seed = seeds[sid]
    if kind == "untyped":
        seeds[sid] = {"fake": "seed"}
    elif kind == "tampered":
        seeds[sid] = replace(seed, seed_hash="0" * 64)
    else:
        proof_data = {**seed.proof}
        cp = seed.checkpoint
        if kind == "provisional":
            proof_data.update(stage="provisional_canonical", status="PENDING_WARMUP")
        elif kind == "incomplete":
            proof_data["interval_authority"] = {
                **proof_data["interval_authority"],
                "remaining_endpoints_before_start": ["2026-10-08T08:20:00+00:00"],
            }
        else:
            proof_data["recording_start"] = (
                NEW_START + timedelta(minutes=1)
            ).isoformat()
            cp = replace(
                cp,
                reference_state=replace(
                    cp.reference_state, recording_start=NEW_START + timedelta(minutes=1)
                ),
            )
        seeds[sid] = _result(
            seed.identity,
            cp,
            seed.schema,
            proof_data,
            seed.binding["original_source_binding"],
        )
    with pytest.raises(RepositoryConflict):
        service.plan(
            sources,
            recording_start=NEW_START,
            expires_at=EXPIRY,
            now=START + timedelta(minutes=1),
        )


def test_final_warm_recovery_rejects_a_single_route_even_if_others_disabled():
    from app.reference_trading.models import ReferenceStream

    factory, _, sources, targets, _, _, service = prepared()
    with factory.begin() as db:
        for target in targets[1:]:
            db.get(ReferenceStream, target).enabled = False
    with pytest.raises(RepositoryConflict, match="FINAL_WARM_SCOPE_INVALID"):
        service.plan(
            sources[:1],
            recording_start=NEW_START,
            expires_at=EXPIRY,
            now=START + timedelta(minutes=1),
        )


def test_final_warm_source_drift_rejects_apply_without_any_revision_change(engine=None):
    from app.reference_trading.models import ReferenceRevision, ReferenceStream

    factory, _, sources, _, _, seeds, service = prepared(engine)
    plan = service.plan(
        sources,
        recording_start=NEW_START,
        expires_at=EXPIRY,
        now=START + timedelta(minutes=1),
    )

    def snapshot():
        with factory() as db:
            return {
                model.__tablename__: sorted(
                    [
                        tuple(getattr(row, col.name) for col in model.__table__.columns)
                        for row in db.scalars(select(model)).all()
                    ],
                    key=repr,
                )
                for model in (
                    ReferenceStream,
                    ReferenceRevision,
                    ReferenceBatch,
                    ReferenceCaptureReconciliation,
                )
            }

    before = snapshot()
    sid = sources[0]
    seed = seeds[sid]
    seeds[sid] = _result(
        seed.identity,
        seed.checkpoint,
        seed.schema,
        {**seed.proof, "independent_source_revision": "changed-after-plan"},
        seed.binding["original_source_binding"],
    )
    with pytest.raises(RepositoryConflict):
        service.apply(
            plan, expected_plan_hash=plan["plan_hash"], now=START + timedelta(minutes=2)
        )
    assert snapshot() == before
