from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.reference_trading.capture import ForwardCapture
from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.models import ReferenceBatch, ReferenceStream
from app.reference_trading.reconciliation import CanonicalEvidence
from app.reference_trading.scheduled_reconciliation import (
    CompletedCanonicalReader,
    ScheduledCanonicalReconciliation,
    capture_reconciliation_status,
)
from app.reference_trading.forward_inputs import ForwardInputUnavailable
from app.reference_trading.repository import RepositoryConflict
from test_newow_fusion_forward import _backlog_database


def _live_database(count):
    factory, stream, start, now = _backlog_database(count, frequency="60m")
    with factory() as session, session.begin():
        for row in session.query(ReferenceBatch).filter(
            ReferenceBatch.kind == "capture"
        ):
            wire = row.source_evidence["forward_capture_v1"]
            raw = wire["input_payload"]["bar"]
            raw["bar_end"] = (
                start + timedelta(hours=int(row.batch_key.split(":")[1]))
            ).isoformat()
            capture = ForwardCapture(
                row.stream_id,
                row.revision_id,
                1,
                row.batch_key,
                datetime.fromisoformat(raw["bar_end"]),
                now,
                "completed_live",
                {**wire["input_payload"], "source_bar_sha256": manifest_sha256(raw)},
                {
                    **wire["source_proof"],
                    "frequency": "60m",
                    "source_sha256": manifest_sha256(raw),
                },
                "completed_observation",
            )
            row.source_evidence = capture.evidence()
            row.payload_hash = capture.capture_hash
    return factory, stream, start, now


def test_pending_round_robin_exceeds_budget_and_later_canonical_matches():
    factory, _, start, now = _live_database(12)
    available = False

    def canonical(evidence):
        return CanonicalEvidence(
            "published" if available else "not-yet",
            evidence["source_proof"]["source_sha256"] if available else None,
        )

    from contextlib import nullcontext

    scheduler = ScheduledCanonicalReconciliation(
        factory, canonical, read_guard=nullcontext, limit=8, interval_seconds=1
    )
    rounds = [scheduler.tick(now=now + timedelta(seconds=i)) for i in range(3)]
    assert len({cid for report in rounds for cid, status in report.statuses}) == 24
    assert all(
        status == "pending" for report in rounds for _, status in report.statuses
    )
    available = True
    reports = [scheduler.tick(now=now + timedelta(seconds=i)) for i in range(3, 7)]
    assert (
        len(
            {
                cid
                for report in reports
                for cid, status in report.statuses
                if status == "matched"
            }
        )
        == 24
    )
    assert scheduler.tick(now=now + timedelta(seconds=8)).statuses == ()


def test_mismatch_blocks_source_and_generation_change_blocks_append():
    factory, _, start, now = _live_database(1)
    from contextlib import nullcontext

    scheduler = ScheduledCanonicalReconciliation(
        factory,
        lambda _: CanonicalEvidence("published", "f" * 64),
        read_guard=nullcontext,
        interval_seconds=1,
    )
    assert all(status == "mismatch" for _, status in scheduler.tick(now=now).statuses)
    with factory() as session:
        stream = session.query(ReferenceStream).first()
        with pytest.raises(
            ForwardInputUnavailable, match="REFERENCE_CANONICAL_MISMATCH"
        ):
            scheduler.assert_source_allowed(stream.stream_id)
    factory, _, start, now = _live_database(1)

    def changes_scope(evidence):
        with factory() as session, session.begin():
            for stream in session.query(ReferenceStream):
                stream.activation_generation += 1
        return CanonicalEvidence("published", evidence["source_proof"]["source_sha256"])

    scheduler = ScheduledCanonicalReconciliation(
        factory, changes_scope, read_guard=nullcontext, interval_seconds=1
    )
    result = scheduler.tick(now=now)
    assert result.statuses == ()
    assert result.errors


def test_exact_physical_canonical_pending_match_mismatch_and_owner_conflict():
    from test_newow_fusion_forward import sources

    case, deps = sources("60m")
    evidence = deps[0]["capture"]
    from decimal import Decimal

    raw = evidence["input_payload"]["bar"]
    bar = SimpleNamespace(
        **{
            key: datetime.fromisoformat(value)
            if key == "bar_end"
            else date.fromisoformat(value)
            if key == "trading_day"
            else None
            if value is None
            else Decimal(value)
            for key, value in raw.items()
        },
        turnover=None,
    )
    landed = False

    class Market:
        def contract_source_evidence(self, **kwargs):
            assert kwargs["contract"] == evidence["input_payload"]["contract"]
            return {
                "partitions": [
                    {
                        "coverage_end": (
                            bar.bar_end if landed else bar.bar_end - timedelta(hours=1)
                        ).isoformat()
                    }
                ]
            }

        def query_page_inclusive(self, query):
            assert query.contract == evidence["input_payload"]["contract"]
            assert query.before == bar.bar_end
            return SimpleNamespace(bars=(bar,))

    def owner(*_):
        return (
            evidence["source_proof"]["owner_segment_id"],
            evidence["source_proof"]["calculation_segment_id"],
        )

    reader = CompletedCanonicalReader(Market(), owner)
    assert reader(evidence).source_sha256 is None
    landed = True
    assert reader(evidence).source_sha256 == evidence["source_proof"]["source_sha256"]
    bar.close += Decimal("1")
    assert reader(evidence).source_sha256 != evidence["source_proof"]["source_sha256"]
    with pytest.raises(RepositoryConflict, match="RECONCILIATION_OWNER_CONFLICT"):
        CompletedCanonicalReader(Market(), lambda *_: ("wrong", "wrong"))(evidence)


def test_dual_status_uses_both_real_base_evidences_and_rejects_wrong_capture_link():
    from contextlib import nullcontext

    factory, stream, start, now = _live_database(1)
    with factory() as session, session.begin():
        rows = (
            session.query(ReferenceBatch).filter(ReferenceBatch.kind == "capture").all()
        )
        sources = [
            {
                "capture_id": row.batch_id,
                "stream_id": row.stream_id,
                "revision_id": row.revision_id,
                "capture": row.source_evidence["forward_capture_v1"],
            }
            for row in rows
        ]
        session.add(
            ReferenceBatch(
                batch_id="dual",
                stream_id=stream.stream_id,
                revision_id="fusion",
                batch_key="capture:dual",
                payload_hash="0" * 64,
                kind="capture",
                outcome="consumed",
                expected_seq=1,
                dependency_manifest={},
                source_evidence={
                    "forward_capture_v1": {
                        "source_kind": "completed_fusion_sources",
                        "input_payload": {"sources": sources},
                    }
                },
                projected_action_pks=[],
                diagnostics=[],
                processed_at=now,
            )
        )
    with factory() as session:
        assert capture_reconciliation_status(session, "dual") == "pending"
    scheduler = ScheduledCanonicalReconciliation(
        factory,
        lambda e: CanonicalEvidence("canonical", e["source_proof"]["source_sha256"]),
        read_guard=nullcontext,
    )
    scheduler.tick(now=now)
    with factory() as session:
        assert capture_reconciliation_status(session, "dual") == "matched"
    with factory() as session, session.begin():
        from app.reference_trading.models import ReferenceCaptureReconciliation

        base_id = sources[0]["capture_id"]
        session.add(
            ReferenceCaptureReconciliation(
                reconciliation_id="changed",
                capture_batch_id=base_id,
                source_revision="canonical-revised",
                status="mismatch",
                captured_sha256="0" * 64,
                canonical_sha256="f" * 64,
                checked_at=now,
            )
        )
    with factory() as session:
        assert capture_reconciliation_status(session, "dual") == "mismatch"
    with factory() as session, session.begin():
        row = session.get(ReferenceBatch, "dual")
        import copy

        changed = copy.deepcopy(row.source_evidence)
        changed["forward_capture_v1"]["input_payload"]["sources"][0]["capture"][
            "hash"
        ] = "f" * 64
        row.source_evidence = changed
    with (
        factory() as session,
        pytest.raises(RepositoryConflict, match="RECONCILIATION_DEPENDENCY_CONFLICT"),
    ):
        capture_reconciliation_status(session, "dual")
