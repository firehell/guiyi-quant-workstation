from copy import deepcopy

import pytest

from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.repository import RepositoryConflict
from app.reference_trading.source_revisions import build_revision_proof, validate_revision_proof


def inputs():
    raw = {"bar_end": "2026-10-23T07:00:00+00:00", "trading_day": "2026-10-23",
           "open": "4044", "high": "4048", "low": "4043", "close": "4048",
           "volume": "752", "turnover": "3000000", "open_interest": "89389"}
    evidence = {"source_kind": "completed_live", "bar_end": raw["bar_end"],
                "observed_at": "2026-10-23T07:00:03+00:00",
                "eligibility": "completed_observation",
                "input_payload": {"product": "b", "contract": "B2611", "bar": raw,
                                  "source_bar_sha256": manifest_sha256(raw)},
                "source_proof": {"frequency": "60m", "source_sha256": manifest_sha256(raw),
                                 "owner_segment_id": "b:B2611:owner", "calculation_segment_id": "b:B2611:owner"}}
    canonical = {**raw, "volume": "32860", "open_interest": "64595"}
    source = {"contract": "B2611", "frequency": "60m", "listed_date": "2025-11-17",
              "expired_date": "2026-11-30", "partitions": [{"content_sha256": "a" * 64,
              "quality_sha256": None, "coverage_end": raw["bar_end"]}]}
    return evidence, canonical, source


def test_same_identity_revision_retains_all_values_and_material_differences():
    evidence, canonical, source = inputs()
    old = deepcopy(evidence)
    proof = build_revision_proof(evidence, canonical, source, provider="rqdata")
    assert proof["differences"] == {
        "volume": {"observed": "752", "canonical": "32860"},
        "open_interest": {"observed": "89389", "canonical": "64595"}}
    assert proof["observed_bar"] == evidence["input_payload"]["bar"]
    assert proof["canonical_bar"] == canonical
    assert validate_revision_proof(proof) == proof
    assert evidence == old


@pytest.mark.parametrize("mutation", ["hash", "endpoint", "contract", "frequency", "owner", "quality", "negative", "nan", "unknown", "provider"])
def test_identity_quality_unknown_and_corruption_never_become_normal_revision(mutation):
    evidence, canonical, source = inputs()
    provider = "rqdata"
    if mutation == "hash":
        evidence["source_proof"]["source_sha256"] = "f" * 64
    if mutation == "endpoint":
        canonical["bar_end"] = "2026-10-23T06:00:00+00:00"
    if mutation == "contract":
        source["contract"] = "B2701"
    if mutation == "frequency":
        source["frequency"] = "1d"
    if mutation == "owner":
        evidence["source_proof"]["owner_segment_id"] = ""
    if mutation == "quality":
        source["partitions"][0].pop("quality_sha256")
    if mutation == "negative":
        canonical["volume"] = "-1"
    if mutation == "nan":
        canonical["close"] = "NaN"
    if mutation == "unknown":
        canonical["open_interest"] = None
    if mutation == "provider":
        provider = "unknown"
    with pytest.raises(RepositoryConflict):
        build_revision_proof(evidence, canonical, source, provider=provider)


def test_decimal_scale_only_is_not_a_source_revision():
    evidence, _, source = inputs()
    canonical = {**evidence["input_payload"]["bar"], "close": "4048.000000"}
    assert build_revision_proof(evidence, canonical, source, provider="rqdata") is None


def test_persisted_evidence_is_revalidated_instead_of_trusted_by_label():
    proof = build_revision_proof(*inputs(), provider="rqdata")
    proof["canonical_bar"]["close"] = "1"
    with pytest.raises(RepositoryConflict):
        validate_revision_proof(proof)


def stored_case(count=1):
    from datetime import datetime
    from app.reference_trading.capture import ForwardCapture
    from app.reference_trading.models import ReferenceActivationReceipt, ReferenceBatch, ReferenceStream
    from test_scheduled_reconciliation import _live_database

    factory, _, _, now = _live_database(count)
    with factory() as session, session.begin():
        row = session.query(ReferenceBatch).filter_by(kind="capture").order_by(ReferenceBatch.batch_id).first()
        wire = deepcopy(row.source_evidence["forward_capture_v1"])
        wire["input_payload"]["bar"]["turnover"] = "0"
        raw = wire["input_payload"]["bar"]
        wire["input_payload"]["source_bar_sha256"] = manifest_sha256(raw)
        wire["source_proof"]["source_sha256"] = manifest_sha256(raw)
        capture = ForwardCapture(row.stream_id, row.revision_id, wire["generation"],
                                 wire["source_key"], datetime.fromisoformat(wire["bar_end"]),
                                 datetime.fromisoformat(wire["observed_at"]), wire["source_kind"],
                                 wire["input_payload"], wire["source_proof"], wire["eligibility"])
        row.source_evidence = capture.evidence()
        row.payload_hash = capture.capture_hash
        cid, sid = row.batch_id, row.stream_id
        stream = session.get(ReferenceStream, sid)
        session.add(ReferenceActivationReceipt(receipt_id='fixture-source-revision-receipt',
            stream_id=sid, revision_id=row.revision_id, generation=wire['generation'],
            plan_hash='b'*64, recording_start=stream.recording_start,
            activated_at=stream.recording_start, environment='isolated', host='fixture',
            budget={'max_pending':32}, recovery_policy='block'))
        canonical = {**raw, "volume": str(int(raw["volume"]) + 10)}
        source = {"contract": wire["input_payload"]["contract"], "frequency": "60m",
                  "partitions": [{"content_sha256": "a" * 64, "quality_sha256": None,
                                  "coverage_end": raw["bar_end"]}]}
        proof = build_revision_proof(capture.evidence()["forward_capture_v1"], canonical, source, provider="rqdata")
    return factory, cid, sid, proof, now


def test_existing_mismatch_gets_append_only_revision_evidence_and_unblocks_exact_capture():
    from app.reference_trading.reconciliation import CanonicalEvidence, ForwardReconciler
    from app.reference_trading.models import ReferenceBatch, ReferenceCaptureReconciliation, ReferenceStream
    from app.reference_trading.scheduled_reconciliation import capture_reconciliation_status
    from app.reference_trading.transaction_guards import assert_source_allowed

    factory, cid, sid, proof, now = stored_case()
    strict = ForwardReconciler(factory, lambda _: CanonicalEvidence(proof["source_revision"], proof["canonical_sha256"]))
    assert strict.reconcile(cid, now=now) == "mismatch"
    with factory() as session:
        before = session.get(ReferenceStream, sid).latest_seq
        original = deepcopy(session.get(ReferenceBatch, cid).source_evidence)
    revised = ForwardReconciler(factory, lambda _: CanonicalEvidence(proof["source_revision"], proof["canonical_sha256"], revision_proof=proof))
    assert revised.reconcile(cid, now=now) == "source_revised"
    assert revised.reconcile(cid, now=now) == "source_revised"
    with factory() as session:
        assert session.query(ReferenceCaptureReconciliation).one().status == "mismatch"
        assert session.query(ReferenceBatch).filter(ReferenceBatch.batch_key.like("source-revision:%")).count() == 1
        assert session.get(ReferenceBatch, cid).source_evidence == original
        assert session.get(ReferenceStream, sid).latest_seq == before
        assert capture_reconciliation_status(session, cid) == "source_revised"
        assert_source_allowed(session, sid)


def test_explaining_one_mismatch_never_waives_another_or_forged_receipt():
    from app.reference_trading.reconciliation import CanonicalEvidence, ForwardReconciler
    from app.reference_trading.models import ReferenceBatch
    from app.reference_trading.transaction_guards import assert_source_allowed
    from app.reference_trading.forward_inputs import ForwardInputUnavailable

    factory, cid, sid, proof, now = stored_case(2)
    revised = ForwardReconciler(factory, lambda _: CanonicalEvidence(proof["source_revision"], proof["canonical_sha256"], revision_proof=proof))
    assert revised.reconcile(cid, now=now) == "source_revised"
    with factory() as session:
        other = session.query(ReferenceBatch).filter_by(stream_id=sid, kind="capture").filter(ReferenceBatch.batch_id != cid).one().batch_id
    assert ForwardReconciler(factory, lambda _: CanonicalEvidence("canonical:unexplained", "f" * 64)).reconcile(other, now=now) == "mismatch"
    with factory() as session:
        with pytest.raises(ForwardInputUnavailable, match="REFERENCE_CANONICAL_MISMATCH"):
            assert_source_allowed(session, sid)


def test_native_reader_opts_into_revision_only_after_exact_physical_read():
    from datetime import date, datetime
    from decimal import Decimal
    from types import SimpleNamespace
    from app.reference_trading.scheduled_reconciliation import CompletedCanonicalReader

    evidence, canonical, source = inputs()
    bar = SimpleNamespace(**{key: datetime.fromisoformat(value) if key == "bar_end"
                              else date.fromisoformat(value) if key == "trading_day"
                              else None if value is None else Decimal(value)
                              for key, value in canonical.items()})
    market = SimpleNamespace(contract_source_evidence=lambda **_: source,
                             query_page_inclusive=lambda _: SimpleNamespace(bars=(bar,)),
                             catalog=SimpleNamespace(contract_fact=lambda *_: SimpleNamespace(provider="rqdata")))
    def owner(*_):
        return evidence["source_proof"]["owner_segment_id"], evidence["source_proof"]["calculation_segment_id"]
    result = CompletedCanonicalReader(market, owner, source_revision_policy=True)(evidence)
    assert result.revision_proof["differences"]["volume"]["canonical"] == "32860"
    evidence["input_payload"]["bar"]["close"] = "1"
    with pytest.raises(RepositoryConflict):
        CompletedCanonicalReader(market, owner, source_revision_policy=True)(evidence)


def test_scheduler_can_append_revision_classification_to_a_preexisting_mismatch():
    from contextlib import nullcontext
    from app.reference_trading.reconciliation import CanonicalEvidence, ForwardReconciler
    from app.reference_trading.scheduled_reconciliation import ScheduledCanonicalReconciliation

    factory, cid, _, proof, now = stored_case()
    assert ForwardReconciler(factory, lambda _: CanonicalEvidence(proof["source_revision"], proof["canonical_sha256"])).reconcile(cid, now=now) == "mismatch"
    def reader(wire):
        return CanonicalEvidence(proof["source_revision"], proof["canonical_sha256"], revision_proof=proof) if wire == proof["capture"] else CanonicalEvidence("unpublished", None)
    scheduler = ScheduledCanonicalReconciliation(factory, reader, read_guard=nullcontext, interval_seconds=1)
    assert (cid, "source_revised") in scheduler.tick(now=now).statuses


def test_old_generation_classification_requires_the_original_activation_lineage():
    from datetime import timedelta
    from app.reference_trading.models import ReferenceActivationReceipt, ReferenceBatch, ReferenceStream
    from app.reference_trading.scheduled_reconciliation import ScheduledCanonicalReconciliation

    factory, cid, sid, _, now = stored_case()
    with factory() as session, session.begin():
        stream = session.get(ReferenceStream, sid)
        stream.activation_generation = 2
        capture = session.get(ReferenceBatch, cid)
        session.delete(session.get(ReferenceActivationReceipt, 'fixture-source-revision-receipt'))
        session.flush()
        receipt = ReferenceActivationReceipt(receipt_id="original-receipt", stream_id=sid,
            revision_id=capture.revision_id, generation=1, plan_hash="a" * 64,
            recording_start=stream.recording_start, activated_at=now - timedelta(days=1),
            disabled_at=now + timedelta(seconds=1), environment="isolated", host="test",
            budget={}, recovery_policy="block")
        session.add(receipt)
        session.add(ReferenceActivationReceipt(receipt_id="successor-receipt", stream_id=sid,
            revision_id=capture.revision_id, generation=2, plan_hash="b" * 64,
            recording_start=stream.recording_start, activated_at=now + timedelta(seconds=1),
            environment="isolated", host="test", budget={}, recovery_policy="block"))
    with factory() as session:
        ScheduledCanonicalReconciliation._scope_guard(session, session.get(ReferenceBatch, cid))
    with factory() as session, session.begin():
        session.get(ReferenceActivationReceipt, "original-receipt").revision_id = "wrong-revision"
    with factory() as session:
        with pytest.raises(RepositoryConflict, match="RECONCILIATION_SCOPE_CONFLICT"):
            ScheduledCanonicalReconciliation._scope_guard(session, session.get(ReferenceBatch, cid))


def test_native_bounded_successor_closes_undisabled_original_receipt():
    from datetime import timedelta
    from types import SimpleNamespace
    from sqlalchemy import select
    from app.reference_trading.bounded_recovery import BoundedForwardRecovery
    from app.reference_trading.models import ReferenceActivationReceipt, ReferenceStream
    from app.reference_trading.source_revisions import activation_window_valid
    from tests.reference_trading.test_newow_worker_recovery import _setup

    factory, _, identity, revision, start, observed, _ = _setup(frequency="60m")
    service = BoundedForwardRecovery(factory, verify_gap=lambda *_: (start + timedelta(seconds=1),))
    plan = service.plan(identity.stream_id, endpoints=(start + timedelta(seconds=1),),
        trading_day=start.date(), observed_at=observed,
        expires_at=observed + timedelta(minutes=5), journal_proof={"cursor": "0-0"})
    service.apply(plan, expected_plan_hash=plan.plan_hash, now=observed)
    with factory() as session:
        receipts = session.scalars(select(ReferenceActivationReceipt)).all()
        old = next(row for row in receipts if row.generation == 1)
        assert old.disabled_at is None
        stream = session.get(ReferenceStream, identity.stream_id)
        capture = SimpleNamespace(stream_id=identity.stream_id, revision_id=revision,
            source_evidence={"forward_capture_v1": {"generation": 1}},
            processed_at=observed - timedelta(microseconds=1))
        assert activation_window_valid(capture, stream, receipts)
        capture.processed_at = observed
        assert not activation_window_valid(capture, stream, receipts)
        capture.processed_at = observed + timedelta(seconds=1)
        assert not activation_window_valid(capture, stream, receipts)
