from datetime import timedelta
from dataclasses import replace
from decimal import Decimal
import json
import pytest
from sqlalchemy import select
from app.market_data.live_market import _bar_from_payload
from app.reference_trading.capture import ForwardCapture
from app.reference_trading.contracts import PreparedBatch
from app.reference_trading.forward_inputs import _bar_wire
from app.reference_trading.inbox import ReferenceInboxRepository
from app.reference_trading.models import ReferenceBatch, ReferenceInboxDelivery
from app.reference_trading.presentation import envelope
from app.reference_trading.repository import ReferenceRepository
from guiyi_quant.reference_trading import CompletedReferenceBar, reduce_reference
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from test_forward_capture import _active
from test_activation import NOW
from test_inbox import event


def fixture(engine=None, *, frequency="1d"):
    from app.reference_trading.inbox_recovery import InboxRecovery

    factory, identity, revision, _ = _active(engine)
    if frequency != "1d":
        from hashlib import sha256
        from app.reference_trading.activation import ForwardActivation
        from app.reference_trading.contracts import SeedChunk, manifest_sha256
        from guiyi_quant.newow.product_adapters import seed_replay_state
        from guiyi_quant.reference_trading import ReferenceState

        identity = replace(identity, frequency=frequency)
        repo = ReferenceRepository(factory)
        stored = repo.ensure_stream(identity)
        manifest = {"source": "fixture"}
        revision = repo.create_revision(
            identity.stream_id, stored.row_version, manifest_sha256(manifest)
        )
        repo.stage_seed_chunk(
            revision, SeedChunk("seed", 0, 1, sha256(b"seed").hexdigest(), "seed")
        )
        repo.seal_seed(
            revision,
            manifest,
            AdapterCheckpoint(
                seed_replay_state(),
                stream=identity,
                reference_state=ReferenceState.flat(
                    identity, recording_start=NOW + timedelta(seconds=1)
                ),
            ),
            "newow_product_replay_v1",
        )
        activation = ForwardActivation(factory)
        act = activation.plan(
            identity.stream_id,
            revision,
            host="test",
            environment="isolated",
            recording_start=NOW + timedelta(seconds=1),
            expires_at=NOW + timedelta(minutes=1),
            budget={"max_pending": 32},
        )
        activation.apply(act, expected_plan_hash=act.plan_hash, now=NOW)
    inbox = ReferenceInboxRepository(factory)
    original = replace(event(), channel="live:bar:rb:" + frequency)
    receipt = inbox.ingest(original, ingested_at=NOW + timedelta(seconds=10))
    identifier = receipt.delivery_ids[0]
    inbox.mark_blocked(
        identifier, "REFERENCE_INBOX_NO_CALCULATION", at=NOW + timedelta(seconds=11)
    )
    raw = _bar_from_payload(json.dumps(original.data))
    capture = ForwardCapture(
        identity.stream_id,
        revision,
        1,
        "RB2610:" + raw.bar_end.isoformat(),
        raw.bar_end,
        original.confirmed_at,
        "completed_live",
        {"bar": _bar_wire(raw), "contract": "RB2610"},
        {
            "owner_segment_id": "owner",
            "calculation_segment_id": "calc",
            "inbox_delivery_id": identifier,
            "journal_stream_id": original.stream_id,
            "journal_envelope_sha256": __import__("hashlib")
            .sha256(original.to_json().encode())
            .hexdigest(),
            "raw_received_at": original.raw_received_at.isoformat(),
            "confirmed_at": original.confirmed_at.isoformat(),
            "ingested_at": (NOW + timedelta(seconds=10)).isoformat(),
        },
        "first_seen",
    )

    def evaluate(token, checkpoint, evidence):
        proof = evidence["forward_capture_v1"]
        transition = reduce_reference(
            checkpoint.reference_state,
            completed_bar=CompletedReferenceBar(
                "RB2610", "owner", "calc", raw.bar_end, raw.trading_day, Decimal("3500")
            ),
        )
        updated = AdapterCheckpoint(
            checkpoint.strategy_state,
            raw.bar_end,
            proof["hash"],
            "RB2610",
            "owner",
            "calc",
            identity,
            transition.state,
        )
        return PreparedBatch(
            identity.stream_id,
            revision,
            "forward:recovered:" + identifier,
            token,
            {"source": "fixture"},
            (),
            (transition,),
            updated,
            "newow_product_replay_v1",
            {
                "forward_capture_v1": {
                    "capture_id": evidence["capture_id"],
                    "hash": proof["hash"],
                    "generation": 1,
                },
                "presentation_v1": envelope([]),
            },
            original.confirmed_at,
        )

    from tempfile import TemporaryDirectory
    from pathlib import Path

    attempts = TemporaryDirectory(prefix="guiyi-inbox-recovery-test-")
    from app.reference_trading.inbox_recovery import digest

    recovery = InboxRecovery(
        factory,
        attempt_dir=Path(attempts.name).resolve(),
        verify_fence=lambda: {
            "owner": "parked",
            "token": "test",
            "attempt_namespace_sha256": digest(str(Path(attempts.name).resolve())),
        },
        verify_source=lambda plan: None,
        now=lambda: NOW + timedelta(seconds=20),
    )
    recovery._test_attempts = attempts
    plan = recovery.plan(
        identifier, capture=capture, expires_at=NOW + timedelta(minutes=1)
    )
    return factory, inbox, recovery, plan, evaluate


def test_recovery_calculation_and_append_only_resolution_are_atomic_and_idempotent():
    from app.reference_trading.models import ReferenceInboxRecoveryResult

    factory, inbox, recovery, plan, evaluate = fixture()
    result = recovery.apply(plan, expected_plan_hash=plan.plan_hash, evaluator=evaluate)
    assert recovery.readback(plan) == result
    assert (
        recovery.apply(plan, expected_plan_hash=plan.plan_hash, evaluator=evaluate)
        == result
    )
    with factory() as db:
        original = db.get(ReferenceInboxDelivery, plan.delivery_id)
        assert original.status == "BLOCKED" and original.calculation_batch_id is None
        resolution = db.scalar(select(ReferenceInboxRecoveryResult))
        assert resolution.delivery_id == original.delivery_id
        calculation = db.get(ReferenceBatch, resolution.calculation_batch_id)
        assert calculation.kind == "calculation" and calculation.outcome == "committed"
    assert inbox.next_heads() == ()
    health = inbox.health()
    assert health["blocked_count"] == 0 and health["historical_blocked_count"] == 1
    assert (
        health["recovered_calculation_count"] == 1
        and health["unfinished_deliveries"] == 0
    )


def test_failed_calculation_never_resolves_or_skips_original():
    from app.reference_trading.models import ReferenceInboxRecoveryResult

    factory, inbox, recovery, plan, evaluate = fixture()

    def fail(stage):
        if stage == "after_actions":
            raise RuntimeError("injected")

    with pytest.raises(Exception, match="UNKNOWN"):
        recovery.apply(
            plan,
            expected_plan_hash=plan.plan_hash,
            evaluator=evaluate,
            fault_injector=fail,
        )
    with factory() as db:
        assert db.scalar(select(ReferenceInboxRecoveryResult)) is None
    assert inbox.next_heads()[0].delivery_id == plan.delivery_id


def test_recovery_rejects_fence_or_frozen_original_drift_and_wrong_plan_hash():
    factory, inbox, recovery, plan, evaluate = fixture()
    with pytest.raises(ValueError, match="PLAN_HASH"):
        recovery.apply(plan, expected_plan_hash="0" * 64, evaluator=evaluate)
    recovery.verify_fence = lambda: {"owner": "active"}
    with pytest.raises(ValueError, match="FENCE"):
        recovery.apply(plan, expected_plan_hash=plan.plan_hash, evaluator=evaluate)


def test_later_delivery_cannot_bypass_earlier_unresolved_head():
    factory, inbox, recovery, plan, evaluate = fixture()
    later = event("20-0", end=event().confirmed_at + timedelta(seconds=2))
    receipt = inbox.ingest(later)
    capture = replace(
        plan.capture,
        bar_end=later.confirmed_at,
        observed_at=later.confirmed_at,
        source_proof={
            **plan.capture.source_proof,
            "inbox_delivery_id": receipt.delivery_ids[0],
        },
    )
    with pytest.raises(ValueError, match="ORDER"):
        recovery.plan(
            receipt.delivery_ids[0], capture=capture, expires_at=plan.expires_at
        )


def test_forged_resolution_never_grants_queue_or_health_progress():
    from app.reference_trading.models import ReferenceInboxRecoveryResult

    factory, inbox, recovery, plan, evaluate = fixture()
    recovery.apply(plan, expected_plan_hash=plan.plan_hash, evaluator=evaluate)
    # SQLite only: production trigger forbids this mutation itself.
    with factory() as db, db.begin():
        row = db.scalar(select(ReferenceInboxRecoveryResult))
        row.proof_sha256 = "0" * 64
    with pytest.raises(ValueError, match="RECOVERY"):
        inbox.next_heads()


def test_fence_loss_during_projection_rolls_back_calculation_and_resolution():
    from app.reference_trading.models import ReferenceInboxRecoveryResult

    factory, inbox, recovery, plan, evaluate = fixture()

    def lose(stage):
        if stage == "after_actions":
            recovery.verify_fence = lambda: {"owner": "lost"}

    with pytest.raises(ValueError, match="UNKNOWN"):
        recovery.apply(
            plan,
            expected_plan_hash=plan.plan_hash,
            evaluator=evaluate,
            fault_injector=lose,
        )
    with factory() as db:
        assert db.scalar(select(ReferenceInboxRecoveryResult)) is None
    assert inbox.next_heads()[0].delivery_id == plan.delivery_id


def test_unknown_attempt_is_consumed_and_cannot_retry_or_replan():
    factory, inbox, recovery, plan, evaluate = fixture()

    def fail(stage):
        if stage == "after_actions":
            raise RuntimeError("injected")

    with pytest.raises(ValueError, match="UNKNOWN"):
        recovery.apply(
            plan,
            expected_plan_hash=plan.plan_hash,
            evaluator=evaluate,
            fault_injector=fail,
        )
    with pytest.raises(ValueError, match="ATTEMPT_CONSUMED"):
        recovery.apply(plan, expected_plan_hash=plan.plan_hash, evaluator=evaluate)
    with pytest.raises(ValueError, match="ATTEMPT_CONSUMED"):
        recovery.plan(
            plan.delivery_id, capture=plan.capture, expires_at=plan.expires_at
        )


def test_normal_later_disable_preserves_verified_historical_recovery():
    from app.reference_trading.activation import ForwardActivation

    factory, inbox, recovery, plan, evaluate = fixture()
    recovery.apply(plan, expected_plan_hash=plan.plan_hash, evaluator=evaluate)
    ForwardActivation(factory).disable(
        plan.capture.stream_id, expected_generation=1, now=NOW + timedelta(seconds=30)
    )
    assert inbox.next_heads() == ()
    assert recovery.readback(plan) is not None
    assert inbox.health()["recovered_calculation_count"] == 1


def _exercise_one_gap_bridge(engine=None):
    from hashlib import sha256
    from app.reference_trading.bounded_recovery import BoundedForwardRecovery
    from app.reference_trading.forward_service import ForwardReferenceService
    from app.reference_trading.recovery import evaluate_observation_gap
    from app.reference_trading.models import ReferenceInboxRecoveryResult

    factory, inbox, recovery, first, evaluate = fixture(engine, frequency="60m")
    recovery.apply(first, expected_plan_hash=first.plan_hash, evaluator=evaluate)
    original = replace(
        event("20-0", end=NOW + timedelta(seconds=12)), channel="live:bar:rb:60m"
    )
    identifier = inbox.ingest(original).delivery_ids[0]
    inbox.mark_blocked(identifier, "OBSERVATION_GAP", at=NOW + timedelta(seconds=13))
    missing = (NOW + timedelta(seconds=6),)
    bounded = BoundedForwardRecovery(factory, verify_gap=lambda *a: missing)
    gap = bounded.plan(
        first.capture.stream_id,
        endpoints=missing,
        trading_day=original.trading_day,
        observed_at=NOW + timedelta(seconds=20),
        expires_at=NOW + timedelta(seconds=50),
        journal_proof={"kind": "SERVICE_OUTAGE", "sealed_source": "isolated"},
    )
    bounded.apply(
        gap, expected_plan_hash=gap.plan_hash, now=NOW + timedelta(seconds=20)
    )
    repo = ReferenceRepository(factory)
    ForwardReferenceService(
        repo,
        lambda token, cp, evidence: evaluate_observation_gap(
            token, cp, evidence, dependency_manifest={"source": "fixture"}
        ),
    ).process_pending(first.capture.stream_id)
    raw = _bar_from_payload(json.dumps(original.data))
    capture = replace(
        first.capture,
        generation=2,
        source_key="RB2610:" + raw.bar_end.isoformat(),
        bar_end=raw.bar_end,
        observed_at=original.confirmed_at,
        input_payload={"bar": _bar_wire(raw), "contract": "RB2610"},
        source_proof={
            **first.capture.source_proof,
            "inbox_delivery_id": identifier,
            "journal_stream_id": original.stream_id,
            "journal_envelope_sha256": sha256(original.to_json().encode()).hexdigest(),
            "raw_received_at": original.raw_received_at.isoformat(),
            "confirmed_at": original.confirmed_at.isoformat(),
        },
    )

    def evaluate_later(token, cp, evidence):
        proof = evidence["forward_capture_v1"]
        transition = reduce_reference(
            cp.reference_state,
            completed_bar=CompletedReferenceBar(
                "RB2610", "owner", "calc", raw.bar_end, raw.trading_day, Decimal("3500")
            ),
        )
        updated = AdapterCheckpoint(
            cp.strategy_state,
            raw.bar_end,
            proof["hash"],
            "RB2610",
            "owner",
            "calc",
            cp.stream,
            transition.state,
        )
        return PreparedBatch(
            capture.stream_id,
            capture.revision_id,
            "forward:bridge",
            token,
            {"source": "fixture"},
            (),
            (transition,),
            updated,
            "newow_product_replay_v1",
            {
                "forward_capture_v1": {
                    "capture_id": evidence["capture_id"],
                    "hash": proof["hash"],
                    "generation": 2,
                },
                "presentation_v1": envelope([]),
            },
            original.confirmed_at,
        )

    plan = recovery.plan(
        identifier, capture=capture, expires_at=NOW + timedelta(minutes=1)
    )
    recovery.apply(plan, expected_plan_hash=plan.plan_hash, evaluator=evaluate_later)
    with factory() as db:
        old = db.get(ReferenceInboxDelivery, identifier)
        assert old.generation == 1 and old.status == "BLOCKED"
        result = db.get(ReferenceInboxRecoveryResult, identifier)
        assert result.target_generation == 2
    assert inbox.next_heads() == ()
    return factory, inbox, recovery, plan


def test_resolution_snapshot_uses_constant_number_of_set_queries():
    from hashlib import sha256
    from sqlalchemy import event as sql_event
    from app.reference_trading.inbox_recovery import verified_resolution_ids

    factory, inbox, recovery, first, evaluate = fixture()
    recovery.apply(first, expected_plan_hash=first.plan_hash, evaluator=evaluate)
    for index in range(32):
        original = event(
            f"{20 + index}-0", end=NOW + timedelta(seconds=3, milliseconds=100 * index)
        )
        identifier = inbox.ingest(original).delivery_ids[0]
        inbox.mark_blocked(
            identifier, "REFERENCE_INBOX_NO_CALCULATION", at=NOW + timedelta(seconds=19)
        )
        raw = _bar_from_payload(json.dumps(original.data))
        capture = replace(
            first.capture,
            source_key="RB2610:" + raw.bar_end.isoformat(),
            bar_end=raw.bar_end,
            observed_at=original.confirmed_at,
            input_payload={"bar": _bar_wire(raw), "contract": "RB2610"},
            source_proof={
                **first.capture.source_proof,
                "inbox_delivery_id": identifier,
                "journal_stream_id": original.stream_id,
                "journal_envelope_sha256": sha256(
                    original.to_json().encode()
                ).hexdigest(),
                "raw_received_at": original.raw_received_at.isoformat(),
                "confirmed_at": original.confirmed_at.isoformat(),
                "ingested_at": (NOW + timedelta(seconds=19)).isoformat(),
            },
        )

        def advance(token, cp, evidence):
            proof = evidence["forward_capture_v1"]
            change = reduce_reference(
                cp.reference_state,
                completed_bar=CompletedReferenceBar(
                    "RB2610",
                    "owner",
                    "calc",
                    raw.bar_end,
                    raw.trading_day,
                    Decimal("3500"),
                ),
            )
            checkpoint = AdapterCheckpoint(
                cp.strategy_state,
                raw.bar_end,
                proof["hash"],
                "RB2610",
                "owner",
                "calc",
                cp.stream,
                change.state,
            )
            return PreparedBatch(
                capture.stream_id,
                capture.revision_id,
                "forward:scale:" + identifier,
                token,
                {"source": "fixture"},
                (),
                (change,),
                checkpoint,
                "newow_product_replay_v1",
                {
                    "forward_capture_v1": {
                        "capture_id": evidence["capture_id"],
                        "hash": proof["hash"],
                        "generation": 1,
                    },
                    "presentation_v1": envelope([]),
                },
                original.confirmed_at,
            )

        plan = recovery.plan(
            identifier, capture=capture, expires_at=NOW + timedelta(minutes=1)
        )
        recovery.apply(plan, expected_plan_hash=plan.plan_hash, evaluator=advance)
    with factory() as db:
        engine = db.get_bind()
    queries = []

    def count(*args):
        queries.append(1)

    sql_event.listen(engine, "before_cursor_execute", count)
    try:
        with factory() as db:
            assert len(verified_resolution_ids(db)) == 33
    finally:
        sql_event.remove(engine, "before_cursor_execute", count)
    assert len(queries) <= 6


def test_recovery_hash_accepts_finite_runtime_budget_numbers_only():
    from app.reference_trading.inbox_recovery import digest

    assert len(digest({"max_stream_seconds": 5.0})) == 64
    with pytest.raises(ValueError):
        digest({"budget": float("nan")})
    with pytest.raises(ValueError):
        digest({"budget": float("inf")})


def test_broken_gap_calculation_never_resolves_cross_generation_original():
    factory, inbox, recovery, plan = (
        _exercise_one_gap_bridge()
    )
    with factory() as db, db.begin():
        caps = db.scalars(
            select(ReferenceBatch).where(ReferenceBatch.kind == "capture")
        ).all()
        gap = next(
            r
            for r in caps
            if r.source_evidence["forward_capture_v1"].get("eligibility")
            == "gap_recovery"
        )
        gap.consumed_by_batch_id = None
        gap.outcome = "pending"
    with pytest.raises(ValueError, match="RECOVERY"):
        inbox.next_heads()
    with pytest.raises(ValueError, match="RECOVERY"):
        inbox.health()
    with pytest.raises(ValueError, match="RECOVERY"):
        recovery.readback(plan)


def test_disabled_bridge_receipt_retains_valid_historical_resolution():
    from app.reference_trading.activation import ForwardActivation

    factory, inbox, recovery, plan = (
        _exercise_one_gap_bridge()
    )
    ForwardActivation(factory).disable(
        plan.capture.stream_id, expected_generation=2, now=NOW + timedelta(seconds=30)
    )
    assert inbox.next_heads() == () and recovery.readback(plan) is not None


def test_one_proven_gap_bridges_frozen_old_generation_without_rewriting_routes():
    _exercise_one_gap_bridge()


def test_recovery_preserves_native_same_transaction_source_guard():
    factory, inbox, recovery, plan, evaluate = fixture()
    calls = []
    def guard(session, stream_id):
        assert session.in_transaction()
        assert stream_id == plan.capture.stream_id
        calls.append(stream_id)
    recovery.apply(plan, expected_plan_hash=plan.plan_hash, evaluator=evaluate,
                   commit_guard=guard)
    assert calls == [plan.capture.stream_id]
    assert recovery.readback(plan) is not None


def test_verified_recovery_releases_capacity_without_rewriting_blocked():
    from app.reference_trading.models import ReferenceInboxInput
    factory, inbox, recovery, plan, evaluate = fixture()
    recovery.apply(plan, expected_plan_hash=plan.plan_hash, evaluator=evaluate)
    with factory() as session:
        size = session.get(ReferenceInboxInput, plan.input_id).payload_bytes
    assert inbox.health()['unfinished_bytes'] == 0
    inbox._unfinished_bytes_limit = size + 32
    second = inbox.ingest(event('20-0', end=NOW + timedelta(seconds=12)))
    assert len(second.delivery_ids) == 1
