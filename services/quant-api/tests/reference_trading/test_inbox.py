"""Inbox durability and transaction contracts (SQLite does not prove PG locks)."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.market_data.live_market import LIVE_BAR_CHANNEL_PREFIX
from app.market_data.observation_stream import ObservationEnvelope
from app.reference_trading.inbox import (
    InboxCommitUnknown,
    InboxConflict,
    ReferenceInboxRepository,
    complete_inbox_delivery,
)
from app.reference_trading.models import (
    ReferenceBatch,
    ReferenceInboxDelivery,
    ReferenceInboxInput,
)
from tests.reference_trading.test_activation import NOW
from tests.reference_trading.test_forward_capture import _active


def event(identifier="10-0", *, close="3500", eligible=True, end=None):
    end = end or NOW + timedelta(seconds=2)
    return ObservationEnvelope(
        "observation-" + identifier,
        end.date(),
        end + timedelta(milliseconds=2),
        f"{LIVE_BAR_CHANNEL_PREFIX}:rb:1d",
        {
            "bar_end": end.isoformat(),
            "trading_day": end.date().isoformat(),
            "contract": "RB2610",
            "close": close,
            "open": "3500",
            "high": "3510",
            "low": "3490",
            "volume": "100",
            "turnover": None,
            "open_interest": None,
        },
        eligible,
        identifier,
        end + timedelta(milliseconds=1),
        end + timedelta(milliseconds=3),
    )


def setup(**kwargs):
    factory, identity, revision, activation = _active()
    return (
        factory,
        identity,
        revision,
        activation,
        ReferenceInboxRepository(factory, **kwargs),
    )


def test_ingest_is_immutable_idempotent_and_freezes_targets_before_ack():
    factory, identity, revision, activation, repo = setup()
    original = event()
    first = repo.ingest(original, ingested_at=NOW + timedelta(seconds=5))
    assert not first.duplicate and len(first.delivery_ids) == 1
    head = repo.pending_head(identity.stream_id)
    assert head.delivery_id == first.delivery_ids[0]
    assert head.revision_id == revision and head.generation == 1
    assert head.envelope.to_json() == original.to_json()
    assert head.envelope.stream_id == original.stream_id
    assert head.ingested_at == NOW + timedelta(seconds=5)
    activation.disable(
        identity.stream_id, expected_generation=1, now=NOW + timedelta(seconds=6)
    )
    duplicate = repo.ingest(original)
    assert duplicate.duplicate and duplicate.delivery_ids == first.delivery_ids
    with pytest.raises(InboxConflict, match="REFERENCE_INBOX_CONTENT_CONFLICT"):
        repo.ingest(event(close="3501"))
    with factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(ReferenceInboxInput)) == 1
        )
        assert (
            session.scalar(select(func.count()).select_from(ReferenceInboxDelivery))
            == 1
        )
    with pytest.raises(InboxConflict, match="REFERENCE_INBOX_ACTIVATION_DRIFT"):
        repo.validate_delivery(head.delivery_id)


def test_numeric_journal_order_waiting_head_blocks_later_input():
    _, identity, _, _, repo = setup()
    repo.ingest(event("100-0"))
    repo.ingest(event("9-12"))
    repo.ingest(event("9-2"))
    first = repo.pending_head(identity.stream_id)
    assert first.envelope.stream_id == "9-2"
    repo.mark_waiting(first.delivery_id, "SOURCE_BUSY")
    assert repo.pending_head(identity.stream_id).delivery_id == first.delivery_id
    assert repo.next_heads()[0].status == "WAITING_HISTORY"
    repo.mark_blocked(first.delivery_id, "OWNER_MISMATCH")
    assert repo.next_heads()[0].status == "BLOCKED"
    assert (
        repo.next_heads(after_stream_id=identity.stream_id)[0].delivery_id
        == first.delivery_id
    )
    with pytest.raises(ValueError, match="REFERENCE_INBOX_HEAD_BUDGET_INVALID"):
        repo.next_heads(limit=33)


@pytest.mark.parametrize(
    "eligible,offset,targets", [(False, 2, 0), (True, 0, 0), (True, 1, 1)]
)
def test_old_and_ineligible_completed_envelopes_are_retained_without_routing(
    eligible, offset, targets
):
    factory, _, _, _, repo = setup()
    receipt = repo.ingest(event(eligible=eligible, end=NOW + timedelta(seconds=offset)))
    assert len(receipt.delivery_ids) == targets
    with factory() as session:
        assert session.get(ReferenceInboxInput, receipt.input_id) is not None


def test_capacity_fails_closed_without_partial_receipt_or_delivery():
    factory, identity, _, _, repo = setup(daily_limit=1)
    first = repo.ingest(event("1-0"))
    assert repo.ingest(event("1-0")).duplicate
    with pytest.raises(InboxConflict, match="REFERENCE_INBOX_DAILY_CAPACITY_EXCEEDED"):
        repo.ingest(event("2-0"))
    with factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(ReferenceInboxInput)) == 1
        )
    tiny = ReferenceInboxRepository(factory, unfinished_bytes_limit=1)
    with pytest.raises(
        InboxConflict, match="REFERENCE_INBOX_UNFINISHED_CAPACITY_EXCEEDED"
    ):
        tiny.ingest(event("3-0"))
    assert repo.pending_head(identity.stream_id).delivery_id == first.delivery_ids[0]


def calculation(session, identity, revision, identifier, evidence):
    row = ReferenceBatch(
        batch_id=identifier,
        stream_id=identity.stream_id,
        revision_id=revision,
        batch_key=identifier,
        payload_hash="a" * 64,
        kind="calculation",
        outcome="committed",
        seq=99,
        expected_seq=98,
        dependency_manifest={},
        source_evidence=evidence,
        projected_action_pks=[],
        diagnostics=[],
        processed_at=NOW + timedelta(seconds=9),
    )
    session.add(row)
    session.flush()
    return row


def test_completion_and_calculation_share_one_atomic_transaction():
    factory, identity, revision, _, repo = setup()
    receipt = repo.ingest(event())
    evidence = {
        "forward_capture_v1": {
            "source_proof": {"inbox_delivery_id": receipt.delivery_ids[0]}
        }
    }
    with pytest.raises(RuntimeError, match="rollback"):
        with factory() as session, session.begin():
            calculation(session, identity, revision, "calc-rollback", evidence)
            complete_inbox_delivery(
                session,
                identity.stream_id,
                revision,
                evidence,
                calculation_batch_id="calc-rollback",
                calculated_at=NOW + timedelta(seconds=9),
            )
            raise RuntimeError("rollback")
    assert repo.pending_head(identity.stream_id).status == "PENDING"
    with factory() as session:
        assert session.get(ReferenceBatch, "calc-rollback") is None
    with factory() as session, session.begin():
        calculation(session, identity, revision, "calc-ok", evidence)
        assert complete_inbox_delivery(
            session,
            identity.stream_id,
            revision,
            evidence,
            calculation_batch_id="calc-ok",
            calculated_at=NOW + timedelta(seconds=9),
        )
    assert repo.pending_head(identity.stream_id) is None
    assert repo.health()["unfinished_deliveries"] == 0
    with factory() as session, session.begin():
        assert complete_inbox_delivery(
            session,
            identity.stream_id,
            revision,
            evidence,
            calculation_batch_id="calc-ok",
            calculated_at=NOW + timedelta(seconds=9),
        )
        with pytest.raises(InboxConflict, match="REFERENCE_INBOX_COMPLETION_CONFLICT"):
            complete_inbox_delivery(
                session,
                identity.stream_id,
                revision,
                evidence,
                calculation_batch_id="other",
                calculated_at=NOW + timedelta(seconds=9),
            )


def test_later_delivery_cannot_complete_before_earliest_head():
    factory, identity, revision, _, repo = setup()
    repo.ingest(event("1-0"))
    later = repo.ingest(event("2-0"))
    evidence = {
        "forward_capture_v1": {
            "source_proof": {"inbox_delivery_id": later.delivery_ids[0]}
        }
    }
    with factory() as session, session.begin():
        calculation(session, identity, revision, "calc-later", evidence)
        with pytest.raises(InboxConflict, match="REFERENCE_INBOX_ORDER_CONFLICT"):
            complete_inbox_delivery(
                session,
                identity.stream_id,
                revision,
                evidence,
                calculation_batch_id="calc-later",
                calculated_at=NOW + timedelta(seconds=9),
            )


def test_commit_success_response_lost_is_proven_by_readback_without_reingest():
    calls = []

    def fault(stage):
        calls.append(stage)
        if stage == "after_commit":
            raise OperationalError("redacted", {}, Exception("lost response"))

    factory, _, _, _, repo = setup(fault_injector=fault)
    receipt = repo.ingest(event())
    assert receipt.duplicate and calls == ["before_commit", "after_commit"]
    with factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(ReferenceInboxInput)) == 1
        )
    assert repo.ingest(event()).duplicate


def test_uncertain_rollback_without_receipt_is_unknown_and_does_not_retry():
    calls = []

    def fault(stage):
        calls.append(stage)
        raise OperationalError("redacted", {}, Exception("connection gone"))

    factory, _, _, _, repo = setup(fault_injector=fault)
    with pytest.raises(InboxCommitUnknown, match="REFERENCE_INBOX_COMMIT_UNKNOWN"):
        repo.ingest(event())
    assert calls == ["before_commit"]
    with factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(ReferenceInboxInput)) == 0
        )


def legacy_capture(
    factory, identity, revision, original, *, consumed=False, exact_proof=True
):
    from hashlib import sha256
    import json
    from app.market_data.live_market import _bar_from_payload
    from app.reference_trading.forward_inputs import _bar_wire
    from app.reference_trading.capture import ForwardCapture
    from app.reference_trading.repository import ReferenceRepository

    proof = {
        "journal_stream_id": original.stream_id,
        "journal_envelope_sha256": sha256(original.to_json().encode()).hexdigest(),
        "raw_received_at": original.raw_received_at.isoformat(),
        "confirmed_at": original.confirmed_at.isoformat(),
    }
    if not exact_proof:
        proof.pop("journal_envelope_sha256")
    capture = ForwardCapture(
        identity.stream_id,
        revision,
        1,
        original.data["contract"] + ":" + original.data["bar_end"],
        NOW + timedelta(seconds=2),
        original.confirmed_at,
        "completed_live",
        {
            "bar": _bar_wire(_bar_from_payload(json.dumps(original.data))),
            "contract": original.data["contract"],
        },
        proof,
        "completed_live",
    )
    capture_id = ReferenceRepository(factory).capture_forward(capture)
    if consumed:
        with factory() as session, session.begin():
            evidence = {
                "forward_capture_v1": {
                    **capture.evidence()["forward_capture_v1"],
                    "capture_id": capture_id,
                }
            }
            calculation(session, identity, revision, "legacy-calc", evidence)
            row = session.get(ReferenceBatch, capture_id)
            row.consumed_by_batch_id, row.outcome = "legacy-calc", "consumed"
    return capture_id


def test_ingest_reconciles_exact_legacy_completed_capture_without_recomputing():
    factory, identity, revision, _, repo = setup()
    original = event()
    legacy_capture(factory, identity, revision, original, consumed=True)
    receipt = repo.ingest(original)
    assert repo.pending_head(identity.stream_id) is None
    with factory() as session:
        row = session.get(ReferenceInboxDelivery, receipt.delivery_ids[0])
        assert row.status == "COMPLETED" and row.calculation_batch_id == "legacy-calc"
        assert row.calculated_at == (NOW + timedelta(seconds=9)).replace(tzinfo=None)


def test_pending_legacy_capture_binds_without_mutating_original_capture_hash():
    factory, identity, revision, _, repo = setup()
    original = event()
    capture_id = legacy_capture(factory, identity, revision, original)
    receipt = repo.ingest(original)
    with factory() as session, session.begin():
        capture = session.get(ReferenceBatch, capture_id)
        before = capture.payload_hash
        evidence = {
            "forward_capture_v1": {
                **capture.source_evidence["forward_capture_v1"],
                "capture_id": capture_id,
            }
        }
        calculation(session, identity, revision, "legacy-calc", evidence)
        capture.consumed_by_batch_id, capture.outcome = "legacy-calc", "consumed"
        assert complete_inbox_delivery(
            session,
            identity.stream_id,
            revision,
            capture_row=capture,
            calculation_batch_id="legacy-calc",
            calculated_at=NOW + timedelta(seconds=9),
        )
        assert (
            capture.payload_hash == before
            and "inbox_delivery_id"
            not in capture.source_evidence["forward_capture_v1"]["source_proof"]
        )
    assert repo.validate_delivery(receipt.delivery_ids[0]).status == "COMPLETED"


def test_unproven_legacy_capture_blocks_instead_of_skipping_or_replaying():
    factory, identity, revision, _, repo = setup()
    legacy_capture(
        factory, identity, revision, event(), consumed=True, exact_proof=False
    )
    repo.ingest(event())
    head = repo.pending_head(identity.stream_id)
    assert (
        head.status == "BLOCKED"
        and head.code == "REFERENCE_INBOX_LEGACY_EVIDENCE_INCOMPLETE"
    )


@pytest.fixture
def inbox_postgresql(isolated_postgres_engine):  # noqa: F811
    from uuid import uuid4
    from app.db.base import Base

    schema = "reference_inbox_" + uuid4().hex
    with isolated_postgres_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = isolated_postgres_engine.execution_options(
        schema_translate_map={None: schema}
    )
    try:
        # Apply the real inbox migration, not only ORM metadata: triggers and
        # constraints must be verified against PostgreSQL itself.
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from tests.alembic.test_reference_forward_migration import _migration

        Base.metadata.create_all(
            scoped,
            tables=[
                table
                for table in Base.metadata.sorted_tables
                if not table.name.startswith("reference_inbox_")
            ],
        )
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            migration = _migration("20261026_0053_reference_inbox.py")
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
        yield scoped
    finally:
        with isolated_postgres_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


from tests.alembic.conftest import isolated_postgres_engine  # noqa: E402,F401


def test_migration_has_single_parent_and_guarded_downgrade():
    from tests.alembic.test_reference_forward_migration import _migration

    migration = _migration("20261026_0053_reference_inbox.py")
    assert (
        migration.revision == "20261026_0053"
        and migration.down_revision == "20261015_0052"
    )


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize("same_event", [True, False])
def test_postgresql_concurrent_ingest_serializes_daily_capacity(
    inbox_postgresql, same_event
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    factory, _, _, _ = _active(inbox_postgresql)
    repo = ReferenceInboxRepository(factory, daily_limit=1)
    barrier = Barrier(2)

    def ingest(identifier):
        barrier.wait()
        try:
            return repo.ingest(event(identifier))
        except InboxConflict as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(ingest, "1-0"),
            pool.submit(ingest, "1-0" if same_event else "2-0"),
        ]
        results = [future.result(timeout=15) for future in futures]
    with factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(ReferenceInboxInput)) == 1
        )
        assert (
            session.scalar(select(func.count()).select_from(ReferenceInboxDelivery))
            == 1
        )
    if same_event:
        assert sorted(result.duplicate for result in results) == [False, True]
        assert results[0].delivery_ids == results[1].delivery_ids
    else:
        assert (
            len(
                [
                    result
                    for result in results
                    if result == "REFERENCE_INBOX_DAILY_CAPACITY_EXCEEDED"
                ]
            )
            == 1
        )


@pytest.mark.isolated_postgresql
def test_postgresql_real_schema_enforces_immutable_receipt_and_frozen_route(
    inbox_postgresql,
):
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy import text

    factory, _, _, _ = _active(inbox_postgresql)
    repo = ReferenceInboxRepository(factory)
    receipt = repo.ingest(event())
    schema = inbox_postgresql.get_execution_options()["schema_translate_map"][None]
    for statement in (
        f'UPDATE "{schema}".reference_inbox_inputs SET envelope_sha256 = :value',
        f'DELETE FROM "{schema}".reference_inbox_inputs WHERE input_id = :value',
        f'UPDATE "{schema}".reference_inbox_deliveries SET generation = 2 WHERE delivery_id <> :value',
        f'DELETE FROM "{schema}".reference_inbox_deliveries WHERE delivery_id <> :value',
    ):
        with pytest.raises(DBAPIError, match="REFERENCE_INBOX_IMMUTABLE"):
            with inbox_postgresql.begin() as connection:
                connection.execute(text(statement), {"value": receipt.input_id})
    repo.mark_waiting(receipt.delivery_ids[0], "SOURCE_BUSY")
    assert repo.health()["waiting_history_count"] == 1


def test_retained_originals_are_hashed_ordered_unique_cutoff_and_eligible():
    from dataclasses import replace

    factory, identity, _, _, repo = setup()
    prior = event("20-0", end=NOW + timedelta(seconds=1))
    repo.ingest(event("10-0", end=NOW + timedelta(seconds=2)))
    repo.ingest(prior)
    target = repo.pending_head(identity.stream_id)
    # Original numeric journal order chooses 10-0 as head, retained replay
    # orders physical bars and never includes later/ineligible/other inputs.
    repo.ingest(event("30-0", end=NOW + timedelta(seconds=3)))
    repo.ingest(replace(prior, stream_id="21-0", observation_id="exact-duplicate"))
    repo.ingest(event("22-0", eligible=False, end=NOW + timedelta(milliseconds=1500)))
    late = event("24-0", close="3509", end=NOW + timedelta(seconds=1))
    repo.ingest(replace(late, confirmed_at=NOW + timedelta(seconds=9)))
    unrelated = event("23-0", end=NOW + timedelta(milliseconds=1600))
    repo.ingest(
        replace(
            unrelated,
            channel=f"{LIVE_BAR_CHANNEL_PREFIX}:cu:1d",
            data={**unrelated.data, "contract": "CU2610"},
        )
    )
    retained = repo.retained_observations(target.delivery_id)
    assert [item.stream_id for item in retained] == ["20-0", "10-0"]
    assert retained[0].to_json() == prior.to_json()
    with factory() as session, session.begin():
        row = session.scalar(
            select(ReferenceInboxInput).where(ReferenceInboxInput.journal_id == "20-0")
        )
        row.envelope_sha256 = "0" * 64  # SQLite fixture; real PG prevents this UPDATE.
    with pytest.raises(InboxConflict, match="REFERENCE_INBOX_CONTENT_CONFLICT"):
        repo.retained_observations(target.delivery_id)


def test_retained_conflicting_original_bar_cannot_be_merged_into_replay():
    _, _, _, _, repo = setup()
    first = repo.ingest(event("1-0"))
    repo.ingest(event("2-0", close="3501"))
    with pytest.raises(
        InboxConflict, match="REFERENCE_INBOX_RETAINED_CONTENT_CONFLICT"
    ):
        repo.retained_observations(first.delivery_ids[0])


def test_fair_head_cursor_reaches_streams_after_first_32_waiting_heads():
    from app.reference_trading.models import (
        ReferenceActivationReceipt,
        ReferenceRevision,
        ReferenceStream,
    )

    factory, identity, revision, _, repo = setup()
    with factory() as session, session.begin():
        original = session.get(ReferenceStream, identity.stream_id)
        receipt = session.scalar(
            select(ReferenceActivationReceipt).where(
                ReferenceActivationReceipt.stream_id == identity.stream_id
            )
        )
        for index in range(32):
            stream_id, revision_id = f"route-{index:03d}", f"revision-{index:03d}"
            stream_data = {
                column.name: getattr(original, column.name)
                for column in original.__table__.columns
            }
            stream_data.update(
                stream_id=stream_id,
                identity_hash=f"hash-{index}",
                active_revision_id=None,
            )
            clone = ReferenceStream(**stream_data)
            session.add(clone)
            session.flush()
            session.add(
                ReferenceRevision(
                    stream_id=stream_id,
                    revision_id=revision_id,
                    status="active",
                    dependency_digest="a" * 64,
                )
            )
            session.flush()
            clone.active_revision_id = revision_id
            receipt_data = {
                column.name: getattr(receipt, column.name)
                for column in receipt.__table__.columns
            }
            receipt_data.update(
                receipt_id=f"receipt-{index}",
                stream_id=stream_id,
                revision_id=revision_id,
            )
            session.add(ReferenceActivationReceipt(**receipt_data))
    repo.ingest(event())
    first_round = repo.next_heads()
    assert len(first_round) == 32
    for item in first_round:
        repo.mark_waiting(item.delivery_id, "SOURCE_BUSY")
    second_round = repo.next_heads(after_stream_id=first_round[-1].stream_id)
    assert len({item.stream_id for item in first_round + second_round}) == 33


@pytest.mark.isolated_postgresql
def test_postgresql_concurrent_different_day_ingestion_respects_global_byte_capacity(
    inbox_postgresql,
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.reference_trading.inbox import _envelope

    factory, _, _, _ = _active(inbox_postgresql)
    first = event("1-0")
    second = event("2-0", end=NOW + timedelta(days=1, seconds=2))
    repo = ReferenceInboxRepository(
        factory, unfinished_bytes_limit=max(_envelope(first)[5], _envelope(second)[5])
    )
    barrier = Barrier(2)

    def ingest(original):
        barrier.wait()
        try:
            return repo.ingest(original)
        except InboxConflict as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(ingest, original) for original in (first, second)]
        results = [future.result(timeout=15) for future in futures]
    assert results.count("REFERENCE_INBOX_UNFINISHED_CAPACITY_EXCEEDED") == 1
    assert repo.health()["unfinished_inputs"] == 1


def test_dependency_wait_stays_pending_and_cannot_skip_head_or_reset_history_wait():
    _, identity, _, _, repo = setup()
    first, later = repo.ingest(event("1-0")), repo.ingest(event("2-0"))
    with pytest.raises(InboxConflict, match="REFERENCE_INBOX_ORDER_CONFLICT"):
        repo.mark_dependency_wait(
            later.delivery_ids[0], "REFERENCE_FUSION_SOURCE_NOT_READY"
        )
    repo.mark_dependency_wait(
        first.delivery_ids[0], "REFERENCE_FUSION_SOURCE_NOT_READY"
    )
    assert repo.pending_head(identity.stream_id).status == "PENDING"
    assert repo.health()["dependency_wait_count"] == 1
    assert repo.health()["by_code"] == (
        {"status": "PENDING", "code": "REFERENCE_FUSION_SOURCE_NOT_READY", "count": 1},
    )
    repo.mark_waiting(first.delivery_ids[0], "SOURCE_BUSY")
    with pytest.raises(InboxConflict, match="REFERENCE_INBOX_STATE_CONFLICT"):
        repo.mark_dependency_wait(
            first.delivery_ids[0], "REFERENCE_FUSION_SOURCE_NOT_READY"
        )
