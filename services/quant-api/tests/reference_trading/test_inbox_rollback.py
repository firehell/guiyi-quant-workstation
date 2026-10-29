"""Explicit one-shot rollback continuation; real kernel and isolated transactions."""

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.reference_trading.composition import build_forward_reference_worker
from app.reference_trading.htdy_activation import (
    htdy_identity,
    plan_htdy_activation,
    apply_htdy_activation,
)
from app.reference_trading.inbox import ReferenceInboxRepository
from app.reference_trading.inbox_recovery import InboxRecovery, digest
from app.reference_trading.repository import ReferenceRepository
from app.reference_trading.models import (
    ReferenceInboxDelivery as D,
    ReferenceBatch as B,
    ReferenceInboxRecoveryResult as R,
)
from tests.reference_trading.test_htdy_60m_forward import Read, original


def prepared(tmp_path, engine=None, product="al"):
    factory = sessionmaker(
        engine or create_engine("sqlite+pysqlite:///:memory:"), expire_on_commit=False
    )
    with factory() as db:
        Base.metadata.create_all(db.get_bind())

    class Market(Read):
        def bars_until(self, query, *, trading_day, end, limit):
            w = super().bars_until(query, trading_day=trading_day, end=end, limit=limit)
            return replace(
                w,
                symbol=product,
                contract=product.upper() + "2610",
                bar_contracts=(product.upper() + "2610",) * 32,
            )

    market = Market()
    end = market.bars[-1].bar_end
    now = end - timedelta(minutes=2)
    activation = plan_htdy_activation(
        operational=(product,),
        recording_start=end - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=1),
        now=now,
        host="isolated",
        environment="isolated",
    )
    apply_htdy_activation(
        factory,
        activation,
        expected_plan_hash=activation["plan_hash"],
        operational=(product,),
        now=now,
    )
    repo = ReferenceRepository(factory)
    repo.inbox_enabled = True
    inbox = ReferenceInboxRepository(factory)
    event = original(market)
    event = replace(
        event,
        channel=f"live:bar:{product}:60m",
        data={**event.data, "contract": product.upper() + "2610"},
    )
    did = inbox.ingest(event).delivery_ids[0]
    inbox.mark_blocked(did, "HTDY_WINDOW_UNAVAILABLE")
    worker = build_forward_reference_worker(
        repository=repo,
        market_read=market,
        newow_reader=None,
        owner_segments=lambda *_: ("owner", "calc"),
        expected_endpoints=lambda *a: (a[-1],),
        newow_capability_ready=lambda *_: False,
        enabled=True,
    )
    sid = htdy_identity(product).stream_id
    worker.source_envelope = event
    worker.source_observed_at = event.confirmed_at
    cap = worker._read_input(sid, "live_event", end)
    cap = replace(
        cap,
        source_proof={
            **cap.source_proof,
            "inbox_delivery_id": did,
            "journal_stream_id": event.stream_id,
            "journal_envelope_sha256": sha256(event.to_json().encode()).hexdigest(),
            "raw_received_at": event.raw_received_at.isoformat(),
            "confirmed_at": event.confirmed_at.isoformat(),
        },
    )
    attempts = tmp_path.resolve() / "attempts"
    recovery = InboxRecovery(
        factory,
        attempt_dir=attempts,
        verify_fence=lambda: {
            "stopped": True,
            "attempt_namespace_sha256": digest(str(attempts)),
        },
        verify_source=lambda p: None,
        now=lambda: event.confirmed_at + timedelta(seconds=20),
        verify_rollback=lambda: {"old_transactions_ended": True},
    )
    parent = recovery.plan(
        did, capture=cap, expires_at=event.confirmed_at + timedelta(minutes=1)
    )
    recovery._claim(parent)
    capture_id = repo.capture_forward(cap)
    return (
        factory,
        repo,
        inbox,
        recovery,
        parent,
        capture_id,
        worker._service_for(sid)._evaluator,
    )


def test_proven_rollback_continues_existing_capture_once_without_rewriting_original(
    tmp_path,
):
    factory, repo, inbox, r, parent, capture_id, evaluate = prepared(tmp_path)
    claim = (r.attempt_dir / (parent.delivery_id + ".json")).read_bytes()
    continuation = r.plan_rollback_continuation(
        parent, capture_id=capture_id, expires_at=parent.expires_at
    )
    result = r.apply_rollback_continuation(
        continuation, expected_plan_hash=continuation.plan_hash, evaluator=evaluate
    )
    assert r.readback(continuation) == result
    assert (
        r.apply_rollback_continuation(
            continuation, expected_plan_hash=continuation.plan_hash, evaluator=evaluate
        )
        == result
    )
    assert (r.attempt_dir / (parent.delivery_id + ".json")).read_bytes() == claim
    with factory() as db:
        assert db.get(D, parent.delivery_id).status == "BLOCKED"
        assert db.get(B, capture_id).consumed_by_batch_id == result[0]
        assert db.scalar(select(func.count()).select_from(R)) == 1
    assert inbox.health()["blocked_count"] == 0


def test_failed_continuation_consumes_marker_and_cannot_retry_or_replan(tmp_path):
    factory, repo, inbox, r, parent, cid, evaluate = prepared(tmp_path)
    p = r.plan_rollback_continuation(
        parent, capture_id=cid, expires_at=parent.expires_at
    )
    before = repo.load_checkpoint(parent.capture.stream_id)[0]

    def fail(stage):
        if stage == "after_actions":
            raise RuntimeError("injected")

    with pytest.raises(ValueError, match="OUTCOME_UNKNOWN"):
        r.apply_rollback_continuation(
            p, expected_plan_hash=p.plan_hash, evaluator=evaluate, fault_injector=fail
        )
    assert repo.load_checkpoint(parent.capture.stream_id)[0] == before
    assert r.readback(p) is None
    with pytest.raises(ValueError, match="ATTEMPT_CONSUMED"):
        r.apply_rollback_continuation(
            p, expected_plan_hash=p.plan_hash, evaluator=evaluate
        )
    with pytest.raises(ValueError, match="ATTEMPT_CONSUMED"):
        r.plan_rollback_continuation(
            parent, capture_id=cid, expires_at=parent.expires_at
        )
    with pytest.raises(ValueError, match="ATTEMPT_CONSUMED"):
        r.apply(parent, expected_plan_hash=parent.plan_hash, evaluator=evaluate)


@pytest.mark.parametrize("drift", ["capture", "claim", "rollback", "fence", "source"])
def test_continuation_rechecks_every_preimage_before_consuming_marker(tmp_path, drift):
    factory, repo, inbox, r, parent, cid, evaluate = prepared(tmp_path)
    p = r.plan_rollback_continuation(
        parent, capture_id=cid, expires_at=parent.expires_at
    )
    if drift == "capture":
        with factory() as db, db.begin():
            db.get(B, cid).payload_hash = "0" * 64
    elif drift == "claim":
        path = r.attempt_dir / (parent.delivery_id + ".json")
        raw = json.loads(path.read_bytes())
        raw["plan_hash"] = "0" * 64
        path.write_text(json.dumps(raw))
    elif drift == "rollback":
        r.verify_rollback = lambda: {"old_transactions_ended": False}
    elif drift == "fence":
        r.verify_fence = lambda: {"stopped": False}
    else:

        def unavailable(_):
            raise ValueError("SOURCE_CHANGED")

        r.verify_source = unavailable
    with pytest.raises(ValueError):
        r.apply_rollback_continuation(
            p, expected_plan_hash=p.plan_hash, evaluator=evaluate
        )
    assert not (
        r.attempt_dir / (parent.delivery_id + ".rollback-continuation.json")
    ).exists()
    assert r.readback(p) is None


def test_scope_recursion_and_namespace_cannot_expand_continuation(tmp_path):
    *_, r, parent, cid, evaluate = prepared(tmp_path, product="rb")
    with pytest.raises(ValueError, match="SCOPE"):
        r.plan_rollback_continuation(
            parent, capture_id=cid, expires_at=parent.expires_at
        )
    factory, repo, inbox, r, parent, cid, evaluate = prepared(tmp_path / "al")
    p = r.plan_rollback_continuation(
        parent, capture_id=cid, expires_at=parent.expires_at
    )
    with pytest.raises(ValueError, match="RECURSION"):
        r.plan_rollback_continuation(p, capture_id=cid, expires_at=parent.expires_at)
    other = InboxRecovery(
        factory,
        attempt_dir=tmp_path.resolve() / "other",
        verify_fence=r.verify_fence,
        verify_source=r.verify_source,
        verify_rollback=r.verify_rollback,
        now=r.now,
    )
    with pytest.raises(ValueError, match="NAMESPACE"):
        other.plan_rollback_continuation(
            parent, capture_id=cid, expires_at=parent.expires_at
        )
    with pytest.raises(ValueError, match="DEDICATED"):
        r.apply(p, expected_plan_hash=p.plan_hash, evaluator=evaluate)


def test_corrupt_continuation_link_cannot_release_health_or_ordering(tmp_path):
    factory, repo, inbox, r, parent, cid, evaluate = prepared(tmp_path)
    p = r.plan_rollback_continuation(
        parent, capture_id=cid, expires_at=parent.expires_at
    )
    r.apply_rollback_continuation(p, expected_plan_hash=p.plan_hash, evaluator=evaluate)
    with factory() as db, db.begin():
        row = db.get(R, parent.delivery_id)
        proof = dict(row.proof)
        link = dict(proof["rollback_continuation"])
        link["capture_id"] = "other"
        proof["rollback_continuation"] = link
        row.proof = proof
        row.proof_sha256 = digest(proof)
        row.plan_hash = digest(proof)
    with pytest.raises(ValueError):
        inbox.health()


def test_direct_service_cannot_bypass_continuation_claim(tmp_path):
    from app.reference_trading.forward_service import ForwardReferenceService

    factory, repo, inbox, r, parent, cid, evaluate = prepared(tmp_path)
    p = r.plan_rollback_continuation(
        parent, capture_id=cid, expires_at=parent.expires_at
    )
    with pytest.raises(Exception):
        ForwardReferenceService(repo, evaluate).process_pending(
            parent.capture.stream_id, inbox_recovery=(r, p)
        )
    assert r.readback(p) is None


def test_source_callback_uses_original_market_facts_without_worker_reentry(tmp_path):
    from contextlib import contextmanager
    from app.reference_trading.htdy_recovery_source import HtdyRecoverySource

    factory, repo, inbox, r, parent, cid, evaluate = prepared(tmp_path)

    class Market(Read):
        def bars_until(self, query, *, trading_day, end, limit):
            w = super().bars_until(query, trading_day=trading_day, end=end, limit=limit)
            return replace(
                w, symbol="al", contract="AL2610", bar_contracts=("AL2610",) * 32
            )

    market = Market()

    @contextmanager
    def facts():
        yield market, lambda *_: ("owner", "calc")

    source = HtdyRecoverySource(factory, facts)
    source(parent)
    assert market.checks >= 1


def test_live_old_transaction_or_expired_plan_never_grants_continuation(tmp_path):
    factory, repo, inbox, r, parent, cid, evaluate = prepared(tmp_path)
    r.verify_rollback = lambda: {"old_transactions_ended": False}
    with pytest.raises(ValueError, match="NOT_PROVEN"):
        r.plan_rollback_continuation(
            parent, capture_id=cid, expires_at=parent.expires_at
        )
    r.verify_rollback = lambda: {"old_transactions_ended": True}
    p = r.plan_rollback_continuation(
        parent, capture_id=cid, expires_at=parent.expires_at
    )
    r.now = lambda: parent.expires_at + timedelta(seconds=1)
    with pytest.raises(ValueError, match="EXPIRED"):
        r.apply_rollback_continuation(
            p, expected_plan_hash=p.plan_hash, evaluator=evaluate
        )
    assert not (
        r.attempt_dir / (parent.delivery_id + ".rollback-continuation.json")
    ).exists()


def test_no_checkpoint_advance_or_extra_pending_capture_is_tolerated(tmp_path):
    from app.reference_trading.models import ReferenceRevision

    factory, repo, inbox, r, parent, cid, evaluate = prepared(tmp_path)
    with factory() as db, db.begin():
        db.get(
            ReferenceRevision, (parent.capture.stream_id, parent.capture.revision_id)
        ).last_seq += 1
    with pytest.raises(ValueError, match="CHECKPOINT"):
        r.plan_rollback_continuation(
            parent, capture_id=cid, expires_at=parent.expires_at
        )


def test_successful_commit_with_lost_response_is_only_read_back(tmp_path, monkeypatch):
    from app.reference_trading.forward_service import ForwardReferenceService

    factory, repo, inbox, r, parent, cid, evaluate = prepared(tmp_path)
    p = r.plan_rollback_continuation(
        parent, capture_id=cid, expires_at=parent.expires_at
    )
    original_process = ForwardReferenceService.process_pending
    calls = []

    def lost(self, *args, **kwargs):
        result = original_process(self, *args, **kwargs)
        calls.append(result)
        raise ConnectionError("injected lost response")

    monkeypatch.setattr(ForwardReferenceService, "process_pending", lost)
    result = r.apply_rollback_continuation(
        p, expected_plan_hash=p.plan_hash, evaluator=evaluate
    )
    assert result[1] == calls[0].seq and r.readback(p) == result and len(calls) == 1
    assert (
        r.apply_rollback_continuation(
            p, expected_plan_hash=p.plan_hash, evaluator=evaluate
        )
        == result
    )
    assert len(calls) == 1


def test_rollback_proof_drift_inside_evaluation_rolls_back_atomic_commit(tmp_path):
    factory, repo, inbox, r, parent, cid, evaluate = prepared(tmp_path)
    p = r.plan_rollback_continuation(
        parent, capture_id=cid, expires_at=parent.expires_at
    )
    before = repo.load_checkpoint(parent.capture.stream_id)[0]

    def changed(*args):
        result = evaluate(*args)
        r.verify_rollback = lambda: {"old_transactions_ended": False}
        return result

    with pytest.raises(ValueError, match="OUTCOME_UNKNOWN"):
        r.apply_rollback_continuation(
            p, expected_plan_hash=p.plan_hash, evaluator=changed
        )
    assert repo.load_checkpoint(parent.capture.stream_id)[0] == before
    assert r.readback(p) is None


@pytest.mark.parametrize(
    "field,value",
    [("parent_claim", None), ("parent_proof", []), ("parent_claim", {"at": 7})],
)
def test_malformed_link_fails_with_fixed_validation_error(tmp_path, field, value):
    from app.reference_trading.inbox_rollback import verify_link

    factory, repo, inbox, r, parent, cid, evaluate = prepared(tmp_path)
    p = r.plan_rollback_continuation(
        parent, capture_id=cid, expires_at=parent.expires_at
    )
    proof = p.proof()
    link = dict(proof["rollback_continuation"])
    link[field] = value
    proof["rollback_continuation"] = link
    with pytest.raises(ValueError):
        verify_link(proof, cid)


def test_attempt_parent_directory_cannot_be_replaced_by_symlink(tmp_path):
    factory, repo, inbox, r, parent, cid, evaluate = prepared(tmp_path)
    p = r.plan_rollback_continuation(
        parent, capture_id=cid, expires_at=parent.expires_at
    )
    original = r.attempt_dir
    moved = original.with_name("moved")
    original.rename(moved)
    original.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError):
        r.apply_rollback_continuation(
            p, expected_plan_hash=p.plan_hash, evaluator=evaluate
        )
    assert r.readback(p) is None
    assert not (moved / (parent.delivery_id + ".rollback-continuation.json")).exists()
