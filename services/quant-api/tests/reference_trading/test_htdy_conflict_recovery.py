from app.reference_trading.htdy_conflict_recovery import HtdyConflictRecovery


from datetime import UTC, datetime, timedelta
from dataclasses import replace
from hashlib import sha256
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.reference_trading.htdy_activation import (
    plan_htdy_activation,
    apply_htdy_activation,
    htdy_identity,
)
from app.reference_trading.htdy_conflict_recovery import retired_delivery_ids, KEY
from app.reference_trading.models import (
    ReferenceBatch,
    ReferenceRevision,
    ReferenceStream,
)
from app.reference_trading.repository import RepositoryConflict
from guiyi_quant.reference_trading.strategy_checkpoint import (
    adapter_checkpoint_from_json,
    adapter_checkpoint_to_json,
)

NOW = datetime(2026, 10, 30, 8, tzinfo=UTC)


@pytest.fixture
def setup(engine=None):
    engine = (
        engine if engine is not None else create_engine("sqlite+pysqlite:///:memory:")
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    # Real accepted identities, exact production-sized conflict scope.
    products = (
        "a ag al ao ap au b bb bc br bu c cf cj cs cu eb ec eg fb fg fu hc "
        "i ic if ih im j jd jm l lc lh lu m ma ni nr oi p pb pf pg pk pp ps rb"
    ).split()
    assert len(products) == 48
    plan = plan_htdy_activation(
        operational=products,
        recording_start=NOW - timedelta(days=4),
        expires_at=NOW - timedelta(days=4, seconds=10),
        now=NOW - timedelta(days=5),
        host="fixture",
        environment="fixture",
    )
    apply_htdy_activation(
        factory,
        plan,
        expected_plan_hash=plan["plan_hash"],
        operational=set(products),
        now=NOW - timedelta(days=5),
    )
    from tests.reference_trading.test_htdy_conflict_source import (
        fixture as source_fixture,
    )
    from app.reference_trading.capture import ForwardCapture
    from copy import deepcopy

    source, source_identity, source_binding, cap = source_fixture()
    source_proof = source(source_identity, source_binding, {})
    with factory() as session, session.begin():
        for stream in session.scalars(select(ReferenceStream)):
            identity = htdy_identity(stream.product)
            revision = session.get(
                ReferenceRevision, (stream.stream_id, stream.active_revision_id)
            )
            batch = session.get(ReferenceBatch, revision.checkpoint_batch_id)
            cp = adapter_checkpoint_from_json(
                json.dumps(source_binding["checkpoint"]),
                expected_stream=source_identity,
                expected_strategy_schema="htdy_first_seen_v1",
            )
            cp = replace(
                cp,
                stream=identity,
                reference_state=replace(cp.reference_state, stream=identity),
            )
            content = adapter_checkpoint_to_json(
                cp, strategy_schema="htdy_first_seen_v1"
            )
            batch.checkpoint_text, batch.post_state_hash = (
                content,
                sha256(content.encode()).hexdigest(),
            )
            capture = ForwardCapture(
                identity.stream_id,
                revision.revision_id,
                1,
                cap.source_key,
                cap.bar_end,
                cap.observed_at,
                cap.source_kind,
                cap.input_payload,
                cap.source_proof,
                cap.eligibility,
            )
            session.add(
                ReferenceBatch(
                    batch_id="capture-" + stream.product,
                    stream_id=stream.stream_id,
                    revision_id=revision.revision_id,
                    batch_key="capture-original",
                    payload_hash=capture.capture_hash,
                    kind="capture",
                    outcome="pending",
                    expected_seq=1,
                    dependency_manifest={},
                    source_evidence=capture.evidence(),
                    projected_action_pks=[],
                    diagnostics=[],
                    observed_at=cap.observed_at,
                    processed_at=cap.observed_at,
                )
            )
    ids = [htdy_identity(p).stream_id for p in products]

    def proof(identity, binding, manifest):
        result = deepcopy(source_proof)
        result["checkpoint_sha256"] = binding["checkpoint_sha256"]
        result["capture_sha256"] = binding["captures"][0]["payload_hash"]
        return result

    recovery = HtdyConflictRecovery(
        factory, verify_source=proof, assert_fenced=lambda: None, clock=lambda: NOW
    )
    return factory, recovery, ids


def test_atomic_flat_future_restart_preserves_old_batches(setup):
    factory, recovery, ids = setup
    plan = recovery.plan(
        ids,
        recording_start=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(minutes=1),
        now=NOW,
    )
    with factory() as session:
        originals = {
            b.batch_id: (b.checkpoint_text, b.payload_hash)
            for b in session.scalars(select(ReferenceBatch))
        }
    result = recovery.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    assert len(result) == 48
    assert recovery.readback(plan) == result
    assert (
        recovery.apply(
            plan, expected_plan_hash=plan["plan_hash"], now=NOW + timedelta(days=4)
        )
        == result
    )
    with factory() as session:
        assert retired_delivery_ids(session) == ()
        for bid, original in originals.items():
            b = session.get(ReferenceBatch, bid)
            assert (b.checkpoint_text, b.payload_hash) == original
        boundaries = [
            b
            for b in session.scalars(select(ReferenceBatch))
            if KEY in b.source_evidence
        ]
        assert len(boundaries) == 48
        for sid, rid in result.items():
            r = session.get(ReferenceRevision, (sid, rid))
            cp = adapter_checkpoint_from_json(
                session.get(ReferenceBatch, r.checkpoint_batch_id).checkpoint_text,
                expected_stream=htdy_identity(
                    session.get(ReferenceStream, sid).product
                ),
                expected_strategy_schema="htdy_first_seen_v1",
            )
            assert (
                cp.strategy_state.window == () and cp.reference_state.open_trade is None
            )
            assert cp.computed_through is None


def test_source_drift_rolls_back_all48(setup):
    factory, recovery, ids = setup
    plan = recovery.plan(
        ids,
        recording_start=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(minutes=1),
        now=NOW,
    )
    proof = recovery.verify_source
    recovery.verify_source = lambda *args: {**proof(*args), "changed": True}
    with pytest.raises(RepositoryConflict, match="PREIMAGE_DRIFT"):
        recovery.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    with factory() as session:
        assert all(
            r.status == "active" for r in session.scalars(select(ReferenceRevision))
        )


def test_scope_and_empty_source_fail_closed(setup):
    _, recovery, ids = setup
    with pytest.raises(RepositoryConflict, match="SCOPE_INVALID"):
        recovery.plan(
            ids[:47],
            recording_start=NOW + timedelta(hours=1),
            expires_at=NOW + timedelta(minutes=1),
            now=NOW,
        )
    recovery.verify_source = lambda *args: {}
    with pytest.raises(RepositoryConflict, match="SOURCE_UNVERIFIED"):
        recovery.plan(
            ids,
            recording_start=NOW + timedelta(hours=1),
            expires_at=NOW + timedelta(minutes=1),
            now=NOW,
        )


def _inbox(factory):
    from tests.reference_trading.test_inbox import event
    from app.reference_trading.inbox import ReferenceInboxRepository

    inbox = ReferenceInboxRepository(factory)
    item = replace(event(end=NOW - timedelta(minutes=30)), channel="live:bar:rb:60m")
    receipt = inbox.ingest(item, ingested_at=NOW)
    return receipt.delivery_ids[0]


def test_retired_delivery_keeps_original_status_and_hash_and_unblocks_new_generation(
    setup,
):
    from app.reference_trading.models import ReferenceInboxDelivery
    from app.reference_trading.inbox_recovery import verified_resolution_ids

    factory, recovery, ids = setup
    delivery_id = _inbox(factory)
    plan = recovery.plan(
        ids,
        recording_start=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(minutes=1),
        now=NOW,
    )
    recovery.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    with factory() as session:
        assert retired_delivery_ids(session) == (delivery_id,)
        assert delivery_id in verified_resolution_ids(session)
        row = session.get(ReferenceInboxDelivery, delivery_id)
        assert row.status == "PENDING" and row.calculation_batch_id is None
    with factory() as session, session.begin():
        session.get(ReferenceInboxDelivery, delivery_id).code = "TAMPER"
    with (
        factory() as session,
        pytest.raises(RepositoryConflict, match="RETIREMENT_INVALID"),
    ):
        retired_delivery_ids(session)


def test_unknown_inbox_cannot_be_retired(setup):
    from app.reference_trading.models import ReferenceInboxDelivery

    factory, recovery, ids = setup
    identifier = _inbox(factory)
    with factory() as session, session.begin():
        row = session.get(ReferenceInboxDelivery, identifier)
        row.status, row.unknown_at = "UNKNOWN", NOW
    with pytest.raises(RepositoryConflict, match="UNKNOWN_DELIVERY"):
        recovery.plan(
            ids,
            recording_start=NOW + timedelta(hours=1),
            expires_at=NOW + timedelta(minutes=1),
            now=NOW,
        )


@pytest.mark.parametrize("mutation", [None, "entry_price", "holding", "old_valid_to"])
def test_open_trade_is_interrupted_without_close_price_or_new_action(setup, mutation):
    from decimal import Decimal
    from app.reference_trading.models import ReferenceActionRow, ReferenceTradeRow
    from guiyi_quant.reference_trading import (
        ReferenceAction,
        ActionKind,
        reduce_reference,
    )

    factory, recovery, ids = setup
    identity = htdy_identity("rb")
    with factory() as session, session.begin():
        stream = session.get(ReferenceStream, identity.stream_id)
        revision = session.get(
            ReferenceRevision, (identity.stream_id, stream.active_revision_id)
        )
        batch = session.get(ReferenceBatch, revision.checkpoint_batch_id)
        cp = adapter_checkpoint_from_json(
            batch.checkpoint_text,
            expected_stream=identity,
            expected_strategy_schema="htdy_first_seen_v1",
        )
        end = datetime(2026, 10, 28, 6, tzinfo=UTC)
        action = ReferenceAction(
            identity,
            "original-build",
            "RB2610",
            "owner",
            "calc",
            end,
            end.date(),
            0,
            ActionKind.OPEN_LONG,
            Decimal("3500"),
        )
        transition = reduce_reference(cp.reference_state, actions=(action,))
        trade = transition.state.open_trade
        session.add(
            ReferenceActionRow(
                action_pk="original-action",
                stream_id=identity.stream_id,
                origin_revision_id=revision.revision_id,
                batch_revision_id=revision.revision_id,
                source_action_id=action.source_action_id,
                recording_mode="forward_observation",
                kind="OPEN_LONG",
                sequence=0,
                physical_contract=action.physical_contract,
                owner_segment_id="owner",
                calculation_segment_id="calc",
                bar_end=end,
                trading_day=end.date(),
                observed_at=end,
                reference_price=Decimal("3500"),
                reference_price_type="strategy_reference",
                batch_id=batch.batch_id,
                batch_seq=1,
            )
        )
        session.flush()
        session.add(
            ReferenceTradeRow(
                stream_id=identity.stream_id,
                revision_id=revision.revision_id,
                trade_id=trade.reference_trade_id,
                valid_from_seq=1,
                entry_action_pk="original-action",
                side="LONG",
                status="OPEN",
                physical_contract=action.physical_contract,
                owner_segment_id="owner",
                calculation_segment_id="calc",
                entry_bar_end=end,
                entry_trading_day=end.date(),
                entry_reference_price=Decimal("3500"),
                holding_bars=0,
                effective_bar_end=end,
                observed_at=end,
            )
        )
        content = adapter_checkpoint_to_json(
            replace(cp, reference_state=transition.state, physical_contract="RB2610"),
            strategy_schema="htdy_first_seen_v1",
        )
        batch.checkpoint_text, batch.post_state_hash = (
            content,
            sha256(content.encode()).hexdigest(),
        )
        old_revision = revision.revision_id
    plan = recovery.plan(
        ids,
        recording_start=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(minutes=1),
        now=NOW,
    )
    recovery.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    with factory() as session:
        rows = session.scalars(
            select(ReferenceTradeRow)
            .where(ReferenceTradeRow.revision_id == old_revision)
            .order_by(ReferenceTradeRow.valid_from_seq)
        ).all()
        assert [r.status for r in rows] == ["OPEN", "DATA_INTERRUPTED"]
        assert rows[0].valid_to_seq == rows[1].valid_from_seq
        assert rows[1].exit_reference_price is None and rows[1].reference_return is None
        assert len(session.scalars(select(ReferenceActionRow)).all()) == 1
    if mutation is not None:
        with factory() as session, session.begin():
            rows = session.scalars(
                select(ReferenceTradeRow)
                .where(ReferenceTradeRow.revision_id == old_revision)
                .order_by(ReferenceTradeRow.valid_from_seq)
            ).all()
            if mutation == "entry_price":
                rows[1].entry_reference_price += Decimal("1")
            elif mutation == "holding":
                rows[1].holding_bars += 1
            else:
                rows[0].valid_to_seq += 1
        with (
            factory() as session,
            pytest.raises(RepositoryConflict, match="RETIREMENT_INVALID"),
        ):
            retired_delivery_ids(session)


@pytest.mark.parametrize(
    "mutation", ["seed", "checkpoint", "receipt", "boundary", "capture"]
)
def test_typed_retirement_rejects_tampered_commit_evidence(setup, mutation):
    from app.reference_trading.models import ReferenceActivationReceipt

    factory, recovery, ids = setup
    _inbox(factory)
    plan = recovery.plan(
        ids,
        recording_start=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(minutes=1),
        now=NOW,
    )
    recovery.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    with factory() as session, session.begin():
        b = next(
            b
            for b in session.scalars(select(ReferenceBatch))
            if KEY in b.source_evidence and b.source_evidence[KEY]["retired_deliveries"]
        )
        p = b.source_evidence[KEY]
        if mutation == "seed":
            session.get(ReferenceBatch, p["new_seed_batch_id"]).checkpoint_text = "{}"
        elif mutation == "checkpoint":
            session.get(
                ReferenceBatch, p["old_checkpoint_batch_id"]
            ).checkpoint_text = "{}"
        elif mutation == "receipt":
            session.get(ReferenceActivationReceipt, p["new_receipt_id"]).plan_hash = (
                "c" * 64
            )
        else:
            b.payload_hash = "d" * 64
    with (
        factory() as session,
        pytest.raises(RepositoryConflict, match="RETIREMENT_INVALID"),
    ):
        retired_delivery_ids(session)


def test_final_fence_loss_rolls_back_and_slow_source_cannot_cross_expiry(setup):
    factory, recovery, ids = setup
    plan = recovery.plan(
        ids,
        recording_start=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(minutes=1),
        now=NOW,
    )
    calls = 0

    def fence():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RepositoryConflict("FENCE_LOST")

    recovery.assert_fenced = fence
    with pytest.raises(RepositoryConflict, match="FENCE_LOST"):
        recovery.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    assert recovery.readback(plan) is None
    recovery.assert_fenced = lambda: None
    proof = recovery.verify_source
    clock = [NOW]

    def source(*args):
        clock[0] += timedelta(seconds=2)
        return proof(*args)

    recovery.clock = lambda: clock[0]
    recovery.verify_source = source
    with pytest.raises(RepositoryConflict, match="WINDOW_INVALID"):
        recovery.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    assert recovery.readback(plan) is None


def test_verifiers_are_required():
    import pytest

    with pytest.raises(ValueError, match="VERIFIER_REQUIRED"):
        HtdyConflictRecovery(None, verify_source=None, assert_fenced=lambda: None)


@pytest.mark.parametrize(
    "mutation", ["placeholder", "policy", "checkpoint", "capture", "source", "conflict"]
)
def test_nonempty_but_untyped_source_proof_is_rejected(setup, mutation):
    _, recovery, ids = setup
    original = recovery.verify_source

    def bad(*args):
        proof = original(*args)
        if mutation == "placeholder":
            return {
                "conflicts": [{"bar_end": "x", "old_sha256": "a", "new_sha256": "b"}],
                "boundary_end": NOW.isoformat(),
                "boundary_trading_day": "2026-10-30",
            }
        if mutation == "policy":
            proof["policy"] = "placeholder"
        elif mutation == "checkpoint":
            proof["checkpoint_sha256"] = "f" * 64
        elif mutation == "capture":
            proof["capture_sha256"] = "f" * 64
        elif mutation == "source":
            proof["sources"] = []
        else:
            proof["conflicts"][0]["contract"] = "FOREIGN"
        return proof

    recovery.verify_source = bad
    with pytest.raises(RepositoryConflict, match="SOURCE_UNVERIFIED"):
        recovery.plan(
            ids,
            recording_start=NOW + timedelta(hours=1),
            expires_at=NOW + timedelta(minutes=1),
            now=NOW,
        )


@pytest.mark.parametrize(
    "mutation", ["future_bar", "late_confirmation", "late_ingestion", "wrong_receipt"]
)
def test_retired_delivery_must_precede_boundary_and_match_old_receipt(setup, mutation):
    from tests.reference_trading.test_inbox import event
    from app.reference_trading.inbox import (
        ReferenceInboxRepository,
        _route_identity,
        _digest,
    )
    from app.reference_trading.models import (
        ReferenceInboxDelivery,
        ReferenceInboxInput,
        ReferenceActivationReceipt,
    )

    factory, recovery, ids = setup
    start = NOW + timedelta(hours=1)
    original = replace(
        event(end=NOW - timedelta(minutes=30)), channel="live:bar:rb:60m"
    )
    ingested = NOW
    if mutation == "future_bar":
        original = replace(
            event(end=start + timedelta(minutes=1)), channel="live:bar:rb:60m"
        )
        ingested = start + timedelta(minutes=2)
    elif mutation == "late_confirmation":
        original = replace(original, confirmed_at=start + timedelta(seconds=1))
        ingested = start + timedelta(seconds=2)
    elif mutation == "late_ingestion":
        ingested = start + timedelta(seconds=1)
    receipt = ReferenceInboxRepository(factory).ingest(original, ingested_at=ingested)
    if mutation == "wrong_receipt":
        with factory() as session, session.begin():
            row = session.get(ReferenceInboxDelivery, receipt.delivery_ids[0])
            row.activation_receipt_id = session.scalar(
                select(ReferenceActivationReceipt.receipt_id).where(
                    ReferenceActivationReceipt.stream_id != row.stream_id
                )
            )
            item = session.get(ReferenceInboxInput, row.input_id)
            routes = session.scalars(
                select(ReferenceInboxDelivery)
                .where(ReferenceInboxDelivery.input_id == item.input_id)
                .order_by(ReferenceInboxDelivery.stream_id)
            ).all()
            item.routing_sha256 = _digest([_route_identity(r) for r in routes])
    with pytest.raises(RepositoryConflict, match="DELIVERY_BOUNDARY_INVALID"):
        recovery.plan(
            ids, recording_start=start, expires_at=NOW + timedelta(minutes=1), now=NOW
        )


def test_control_boundary_has_saved_presentation_but_no_inbox_calculation(setup):
    from app.reference_trading.inbox import ReferenceInboxRepository
    from app.reference_trading.models import ReferenceInboxRecoveryResult
    from app.reference_trading.query import HistoricalReferenceQuery
    from app.reference_trading.contracts import SnapshotIdentity

    factory, recovery, ids = setup
    _inbox(factory)
    before = ReferenceInboxRepository(factory).health()
    plan = recovery.plan(
        ids,
        recording_start=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(minutes=1),
        now=NOW,
    )
    recovery.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    after = ReferenceInboxRepository(factory).health()
    assert before["completed_count"] == after["completed_count"] == 0
    assert before["last_calculated_at"] is after["last_calculated_at"] is None
    with factory() as session:
        assert session.scalars(select(ReferenceInboxRecoveryResult)).all() == []
        for batch in session.scalars(
            select(ReferenceBatch).where(ReferenceBatch.kind == "calculation")
        ):
            assert batch.outcome == "committed" and batch.observed_at is None
            assert "forward_capture_v1" not in batch.source_evidence
            HistoricalReferenceQuery._assert_presentations(
                session, SnapshotIdentity(batch.stream_id, batch.revision_id, batch.seq)
            )


def test_retirement_survives_real_successor_commit_with_dependency_advance(setup):
    from app.reference_trading.capture import ForwardCapture
    from app.reference_trading.contracts import PreparedBatch, prove_dependency_append
    from app.reference_trading.repository import ReferenceRepository
    from app.reference_trading.inbox_recovery import verified_resolution_ids
    from guiyi_quant.reference_trading import reduce_reference

    factory, recovery, ids = setup
    delivery_id = _inbox(factory)
    start = NOW + timedelta(hours=1)
    plan = recovery.plan(
        ids, recording_start=start, expires_at=NOW + timedelta(minutes=1), now=NOW
    )
    result = recovery.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    identity = htdy_identity("rb")
    repo = ReferenceRepository(factory)
    state = repo.read_state(identity.stream_id, result[identity.stream_id])
    with factory() as session:
        revision = session.get(
            ReferenceRevision, (identity.stream_id, state.revision_id)
        )
        batch = session.get(ReferenceBatch, revision.checkpoint_batch_id)
        cp = adapter_checkpoint_from_json(
            batch.checkpoint_text,
            expected_stream=identity,
            expected_strategy_schema="htdy_first_seen_v1",
        )
    end = start + timedelta(hours=1)
    capture = ForwardCapture(
        identity.stream_id,
        state.revision_id,
        2,
        "natural-new-endpoint",
        end,
        end + timedelta(seconds=1),
        "completed_live",
        {"bar_end": end.isoformat()},
        {},
        "first_seen",
    )
    capture_id = repo.capture_forward(capture)
    transition = reduce_reference(
        cp.reference_state, completed_bar_end=end, completed_trading_day=end.date()
    )
    manifest = {**state.dependency_manifest, "new_partition": ["future-natural-input"]}
    checkpoint = replace(
        cp,
        computed_through=end,
        last_fingerprint=capture.capture_hash,
        physical_contract="RB2610",
        owner_segment_id="owner",
        calculation_segment_id="calc",
        reference_state=transition.state,
    )
    evidence = capture.evidence()
    evidence["forward_capture_v1"]["capture_id"] = capture_id
    prepared = PreparedBatch(
        identity.stream_id,
        state.revision_id,
        "natural-future",
        state.checkpoint,
        manifest,
        (),
        (transition,),
        checkpoint,
        "htdy_first_seen_v1",
        evidence,
        input_observed_at=capture.observed_at,
        dependency_advance=prove_dependency_append(
            state.dependency_manifest,
            manifest,
            appended_ranges=("future-natural-input",),
        ),
    )
    assert repo.commit_batch(state.checkpoint, prepared).seq == 2
    assert (
        repo.read_state(identity.stream_id).dependency_digest != state.dependency_digest
    )
    with factory() as session:
        assert delivery_id in verified_resolution_ids(session)


def test_disable_before_boundary_is_not_a_valid_retirement(setup):
    from app.reference_trading.models import ReferenceActivationReceipt

    factory, recovery, ids = setup
    _inbox(factory)
    plan = recovery.plan(
        ids,
        recording_start=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(minutes=1),
        now=NOW,
    )
    recovery.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    with factory() as session, session.begin():
        old = session.scalar(
            select(ReferenceActivationReceipt).where(
                ReferenceActivationReceipt.disabled_at.is_not(None)
            )
        )
        old.disabled_at = NOW - timedelta(seconds=1)
    with (
        factory() as session,
        pytest.raises(RepositoryConflict, match="RETIREMENT_INVALID"),
    ):
        retired_delivery_ids(session)
