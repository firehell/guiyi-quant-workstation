"""Independent receiving proof; calculation failures cannot erase accepted input."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.market_data.observation_stream import ObservationEnvelope, ObservationStream
from app.reference_trading.inbox import ReferenceInboxRepository
from app.reference_trading.models import (
    ReferenceActivationReceipt,
    ReferenceInboxDelivery,
    ReferenceInboxInput,
    ReferenceRevision,
    ReferenceStream,
)
from app.reference_trading.receiving_handover import (
    freeze_receiving_intent,
    seal_receiving_backlog,
)
from app.reference_trading.receiving_liveness import (
    ReceivingLivenessError,
    snapshot_receiving,
    prove_receiving_liveness,
    receiving_snapshot_identity,
)
from app.runtime_handover import _write
from guiyi_quant.reference_trading import StreamIdentity
from tests.reference_trading.test_receiving_handover import (
    setup,
    TARGET,
    SCHEMA,
    CAPACITY,
    DAY,
)

NOW = datetime(2026, 10, 27, 8, tzinfo=UTC)


def _setup(tmp_path, engine=None, real_redis=None):
    protocol, journal, _ = setup(tmp_path)
    for identifier, fields in journal.redis.rows[journal.key(DAY)]:
        event = ObservationEnvelope.from_json(fields["envelope"], stream_id=identifier)
        event = ObservationEnvelope(
            event.observation_id,
            event.trading_day,
            event.source_observed_at,
            "live:bar:rb:5m",
            {
                **event.data,
                "open": "100",
                "high": "101",
                "low": "99",
                "volume": "1",
                "turnover": None,
                "open_interest": None,
            },
            True,
            event.stream_id,
            event.raw_received_at,
            event.confirmed_at,
        )
        fields["envelope"] = event.to_json()
        journal.redis.hashes[journal.identity_key(DAY)][event.observation_id] = (
            json.dumps(
                {
                    "id": identifier,
                    "payload": event.to_json(),
                    "content": event.to_json(),
                }
            )
        )
    if real_redis is not None:
        for key, value in journal.redis.values.items():
            real_redis.set(key, value)
        for key, rows in journal.redis.rows.items():
            for identifier, fields in rows:
                real_redis.xadd(key, fields, id=identifier)
        for key, values in journal.redis.hashes.items():
            real_redis.hset(key, mapping=values)
        journal = ObservationStream(real_redis, kind="completed")
    intent = freeze_receiving_intent(
        protocol, journal, target=TARGET, schema_proof=SCHEMA
    )
    source = seal_receiving_backlog(
        protocol,
        journal,
        intent,
        target=TARGET,
        schema_proof=SCHEMA,
        progress=intent["baseline"],
        capacity=CAPACITY,
    )
    protocol.activate(journal, assert_owned=lambda: None)
    engine = engine or create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    identity = StreamIdentity(
        "subing_reference",
        ("test",),
        "test",
        "test",
        "test",
        "rb",
        "5m",
        "actual_dominant",
        "forward_observation",
        "test",
    )
    start = datetime.combine(DAY, datetime.min.time(), tzinfo=UTC)
    with factory() as session, session.begin():
        session.add(
            ReferenceStream(
                stream_id=identity.stream_id,
                identity_hash=identity.stream_id.removeprefix("reference-stream:"),
                strategy_code=identity.strategy_code,
                formula_versions=["test"],
                profile_id="test",
                reference_model_version="test",
                futures_adaptation_version="test",
                product="rb",
                frequency="5m",
                series_kind="actual_dominant",
                recording_mode="forward_observation",
                observation_policy_version="test",
                enabled=True,
                activation_generation=1,
                recording_start=start,
                activation_plan_hash="b" * 64,
            )
        )
        session.flush()
        session.add(
            ReferenceRevision(
                stream_id=identity.stream_id,
                revision_id="revision",
                status="active",
                last_seq=1,
                dependency_digest="c" * 64,
            )
        )
        session.flush()
        session.add(
            ReferenceActivationReceipt(
                receipt_id="receipt",
                stream_id=identity.stream_id,
                revision_id="revision",
                generation=1,
                plan_hash="b" * 64,
                recording_start=start,
                activated_at=start,
                environment="isolated",
                host="test",
                budget={},
                recovery_policy="block",
            )
        )
        session.get(ReferenceStream, identity.stream_id).active_revision_id = "revision"
    repo = ReferenceInboxRepository(factory)

    def capture(identifier, *, ack=True, status=None):
        row = journal.redis.xrange(
            journal.key(DAY), min=identifier, max=identifier, count=1
        )[0][1]
        receipt = repo.ingest(
            ObservationEnvelope.from_json(
                row.get("envelope", row.get(b"envelope")), stream_id=identifier
            )
        )
        if status:
            with factory() as session, session.begin():
                delivery = session.get(ReferenceInboxDelivery, receipt.delivery_ids[0])
                delivery.status, delivery.code = status, "CALCULATION_FAILED"
        if ack:
            if hasattr(journal.redis, "values"):
                journal.redis.values[journal.cursor_key("reference", DAY)] = identifier
            else:
                journal.ack(
                    "reference",
                    DAY,
                    expected_cursor=journal.cursor("reference", DAY),
                    next_id=identifier,
                )
        return receipt

    def sample(seconds=0, *, live=True, **kwargs):
        return snapshot_receiving(
            factory,
            protocol,
            journal,
            intent=intent,
            source_proof=source,
            target=TARGET,
            schema_proof=SCHEMA,
            sampled_at=NOW + timedelta(seconds=seconds),
            owner_cycle_at=(NOW + timedelta(seconds=seconds)).isoformat()
            if live
            else None,
            **kwargs,
        )

    return factory, protocol, journal, intent, source, capture, sample


def test_two_fresh_receiving_cycles_prove_real_prefix_progress_before_old_tail(
    tmp_path,
):
    factory, protocol, journal, intent, source, capture, sample = _setup(tmp_path)
    parked = sample(live=False)
    before_bytes = protocol.path.read_bytes()
    first = sample(0)
    capture("11-0", status="BLOCKED")
    second = sample(1)
    proof = prove_receiving_liveness(first, second, now=NOW + timedelta(seconds=1))
    assert proof["mode"] == "durable_receiving_backlog_liveness"
    assert proof["calculation_ready"] is False and proof["advanced_count"] == 1
    assert second["remaining_count"] == 1 and second["old_tail_reached"] is False
    assert (
        journal.cursor("reference", DAY) == "11-0"
        and protocol.path.read_bytes() == before_bytes
    )
    with factory() as session:
        assert session.scalar(select(ReferenceInboxDelivery.status)) == "BLOCKED"
    assert parked["owner_cycle_at"] is None


@pytest.mark.parametrize("status", ("PENDING", "WAITING_HISTORY", "BLOCKED"))
def test_all_calculation_statuses_are_separate_from_intake_integrity(tmp_path, status):
    factory, _, _, _, _, capture, sample = _setup(tmp_path)
    capture("11-0", status=status)
    assert sample()["acknowledged_count"] == 1
    with factory() as session:
        assert session.scalar(select(ReferenceInboxDelivery.status)) == status


def test_unknown_delivery_cannot_grant_receiving_liveness(tmp_path):
    factory, _, _, _, _, capture, sample = _setup(tmp_path)
    capture("11-0", status="UNKNOWN")
    with pytest.raises(
        ReceivingLivenessError, match="REFERENCE_RECEIVING_LIVENESS_UNPROVEN"
    ):
        sample()
    with factory() as session:
        assert session.scalar(select(ReferenceInboxDelivery.status)) == "UNKNOWN"


def test_db_commit_before_ack_is_retained_without_inventing_ack_progress(tmp_path):
    _, _, _, _, _, capture, sample = _setup(tmp_path)
    first = sample()
    capture("11-0", ack=False)
    second = sample(1)
    assert (
        second["acknowledged_count"] == 0
        and second["capacity"]["day_inputs"][DAY.isoformat()] == 1
    )
    with pytest.raises(ReceivingLivenessError):
        prove_receiving_liveness(first, second, now=NOW + timedelta(seconds=1))


@pytest.mark.parametrize(
    "drift",
    (
        "missing_input",
        "raw_hash",
        "missing_route",
        "routing_hash",
        "receipt",
        "source_middle",
        "source_identity",
        "source_suffix",
        "cursor_regression",
        "cursor_over_tail",
        "partition",
        "request_hash",
        "active_boundary",
        "intake",
        "authority",
    ),
)
def test_unknown_original_prefix_suffix_identity_or_intake_is_never_liveness(
    tmp_path, drift
):
    factory, protocol, journal, intent, source, capture, sample = _setup(tmp_path)
    receipt = capture("11-0")
    if drift in {
        "missing_input",
        "raw_hash",
        "missing_route",
        "routing_hash",
        "receipt",
    }:
        with factory() as session, session.begin():
            item = session.get(ReferenceInboxInput, receipt.input_id)
            row = session.get(ReferenceInboxDelivery, receipt.delivery_ids[0])
            if drift == "missing_input":
                session.delete(row)
                session.flush()
                session.delete(item)
            elif drift == "raw_hash":
                item.envelope_sha256 = "0" * 64
            elif drift == "routing_hash":
                item.routing_sha256 = "0" * 64
            elif drift == "receipt":
                session.get(ReferenceActivationReceipt, "receipt").plan_hash = "0" * 64
            else:
                session.delete(row)
    elif drift == "source_middle":
        journal.redis.rows[journal.key(DAY)][1][1]["envelope"] = journal.redis.rows[
            journal.key(DAY)
        ][1][1]["envelope"].replace('"close":"100"', '"close":"101"')
    elif drift == "source_identity":
        journal.redis.hashes[journal.identity_key(DAY)].pop("source-11")
    elif drift == "source_suffix":
        journal.redis.rows[journal.key(DAY)].pop()
    elif drift == "cursor_regression":
        journal.redis.values[journal.cursor_key("reference", DAY)] = "9-0"
    elif drift == "cursor_over_tail":
        journal.redis.values[journal.cursor_key("reference", DAY)] = "13-0"
    elif drift == "partition":
        journal.redis.rows["live:observations:completed:2026-10-28"] = []
    elif drift == "authority":
        SCHEMA["schema_sha256"] = "0" * 64
    else:
        value = protocol.read()
        if drift == "request_hash":
            value["requested_at"] = NOW.isoformat()
        elif drift == "active_boundary":
            value["boundaries"][DAY.isoformat()]["cursor"] = "0-0"
        else:
            value["intake_error"] = "UNKNOWN_COMMIT"
        _write(protocol.path, value)
    try:
        with pytest.raises(ReceivingLivenessError):
            sample()
    finally:
        SCHEMA["schema_sha256"] = "c" * 64


def test_caught_up_idle_is_based_on_current_frontiers_even_with_legacy_flag(tmp_path):
    _, _, _, _, _, capture, sample = _setup(tmp_path)
    capture("11-0")
    capture("12-0")
    first, second = sample(), sample(1)
    assert (
        prove_receiving_liveness(first, second, now=NOW + timedelta(seconds=1))["mode"]
        == "durable_receiving_caught_up_idle"
    )
    result = prove_receiving_liveness(
        first, second, closed_idle=True, now=NOW + timedelta(seconds=1)
    )
    assert (
        result["mode"] == "durable_receiving_caught_up_idle"
        and result["calculation_ready"] is False
    )


@pytest.mark.parametrize(
    "bad", ("same_cycle", "stale", "backward", "tamper", "different_target")
)
def test_two_distinct_fresh_rounds_and_same_frozen_attempt_are_mandatory(tmp_path, bad):
    _, _, _, _, _, capture, sample = _setup(tmp_path)
    first = sample()
    capture("11-0")
    second = sample(1)
    if bad == "same_cycle":
        second["owner_cycle_at"] = first["owner_cycle_at"]
    elif bad == "stale":
        second = sample(31)
    elif bad == "backward":
        first, second = second, first
    elif bad == "different_target":
        second["target_sha256"] = "0" * 64
    else:
        second["acknowledged_count"] = 7
    with pytest.raises(ReceivingLivenessError):
        prove_receiving_liveness(
            first, second, now=NOW + timedelta(seconds=31 if bad == "stale" else 1)
        )


def test_parked_snapshot_identity_ignores_only_read_time_and_owner_cycle(tmp_path):
    _, _, _, _, _, _, sample = _setup(tmp_path)
    first, second = sample(live=False), sample(1, live=False)
    assert first["snapshot_sha256"] != second["snapshot_sha256"]
    assert receiving_snapshot_identity(first) == receiving_snapshot_identity(second)


def test_budget_failure_does_not_mutate_protocol_ack_or_rows(tmp_path):
    _, protocol, journal, _, _, _, sample = _setup(tmp_path)
    before = protocol.path.read_bytes(), deepcopy(journal.redis.values)

    def expired():
        raise RuntimeError("deadline")

    with pytest.raises(ReceivingLivenessError):
        sample(check_budget=expired)
    assert (protocol.path.read_bytes(), journal.redis.values) == before


def _append(journal, identifier):
    from dataclasses import replace

    old_id, fields = journal.redis.xrevrange(journal.key(DAY), count=1)[0]
    if isinstance(old_id, bytes):
        old_id = old_id.decode()
    previous = ObservationEnvelope.from_json(
        fields.get("envelope", fields.get(b"envelope")), stream_id=old_id
    )
    end = datetime.fromisoformat(previous.data["bar_end"]) + timedelta(minutes=1)
    original = replace(
        previous,
        observation_id="source-" + identifier,
        stream_id=identifier,
        data={**previous.data, "bar_end": end.isoformat()},
        source_observed_at=end + timedelta(seconds=1),
        raw_received_at=end + timedelta(seconds=1),
        confirmed_at=end + timedelta(seconds=2),
    )
    raw = original.to_json()
    record = json.dumps({"id": identifier, "payload": raw, "content": raw})
    if hasattr(journal.redis, "rows"):
        journal.redis.rows[journal.key(DAY)].append((identifier, {"envelope": raw}))
        journal.redis.hashes[journal.identity_key(DAY)][original.observation_id] = (
            record
        )
    else:
        journal.redis.xadd(journal.key(DAY), {"envelope": raw}, id=identifier)
        journal.redis.hset(journal.identity_key(DAY), original.observation_id, record)


def test_new_append_without_ack_does_not_invalidate_old_frozen_suffix(tmp_path):
    _, _, journal, _, source, capture, sample = _setup(tmp_path)
    capture("11-0")
    _append(journal, "13-0")
    result = sample()
    assert result["source_count"] == source["count"] == 2
    assert result["acknowledged_count"] == result["remaining_count"] == 1


def test_ack_beyond_old_tail_verifies_the_entire_new_prefix(tmp_path):
    _, _, journal, _, _, capture, sample = _setup(tmp_path)
    first = sample()
    capture("11-0")
    capture("12-0")
    _append(journal, "13-0")
    capture("13-0")
    second = sample(1)
    assert second["acknowledged_count"] == 3 and second["source_count"] == 2
    assert second["old_tail_reached"] and second["remaining_count"] == 0
    assert (
        prove_receiving_liveness(first, second, now=NOW + timedelta(seconds=1))[
            "advanced_count"
        ]
        == 3
    )


@pytest.mark.parametrize(
    "drift", ("missing_middle", "wrong_new_hash", "wrong_new_identity")
)
def test_new_ack_prefix_cannot_hide_unknown_intermediate_or_changed_original(
    tmp_path, drift
):
    factory, _, journal, _, _, capture, sample = _setup(tmp_path)
    capture("11-0")
    capture("12-0")
    _append(journal, "13-0")
    intermediate = capture("13-0")
    _append(journal, "14-0")
    capture("14-0")
    if drift == "wrong_new_identity":
        journal.redis.hashes[journal.identity_key(DAY)].pop("source-13-0")
    else:
        with factory() as session, session.begin():
            item = session.get(ReferenceInboxInput, intermediate.input_id)
            if drift == "wrong_new_hash":
                item.envelope_sha256 = "0" * 64
            else:
                session.delete(
                    session.get(ReferenceInboxDelivery, intermediate.delivery_ids[0])
                )
                session.flush()
                session.delete(item)
    with pytest.raises(ReceivingLivenessError):
        sample()


def test_ack_prefix_validation_is_streamed_through_multiple_fixed_chunks(
    tmp_path, monkeypatch
):
    from app.reference_trading import receiving_liveness as module

    _, _, journal, _, _, capture, sample = _setup(tmp_path)
    capture("11-0")
    capture("12-0")
    for index in range(13, 271):
        _append(journal, f"{index}-0")
        capture(f"{index}-0")
    sizes = []
    original = module._prefix

    def observed(session, events, *args, **kwargs):
        sizes.append(len(events))
        return original(session, events, *args, **kwargs)

    monkeypatch.setattr(module, "_prefix", observed)
    result = sample()
    assert result["acknowledged_count"] == sum(sizes) == 260
    assert sizes == [128, 128, 4]


def test_cursor_advancing_during_readback_is_not_claimed_as_verified_earlier_prefix(
    tmp_path,
):
    _, _, journal, _, _, capture, sample = _setup(tmp_path)
    capture("11-0")
    capture("12-0", ack=False)
    _append(journal, "13-0")
    capture("13-0", ack=False)
    calls = []

    def budget():
        calls.append(1)
        if len(calls) == 3:
            journal.redis.values[journal.cursor_key("reference", DAY)] = "13-0"

    result = sample(check_budget=budget)
    assert result["days"][DAY.isoformat()]["ack"] == "11-0"
    assert (
        result["acknowledged_count"] == 1 and journal.cursor("reference", DAY) == "13-0"
    )


from tests.alembic.conftest import isolated_postgres_engine  # noqa: E402,F401
from tests.test_runtime_schema_compatibility import installed_inbox_database  # noqa: E402,F401


@pytest.fixture
def isolated_journal_redis():
    import os
    import redis

    raw_port = os.getenv("GUIYI_TEST_REDIS_PORT", "")
    if not raw_port:
        pytest.skip("GUIYI_TEST_REDIS_PORT must name this run's disposable Redis")
    assert raw_port.isdigit() and 0 < int(raw_port) <= 65535 and int(raw_port) != 6379
    client = redis.Redis(host="127.0.0.1", port=int(raw_port), db=15, socket_timeout=5)
    try:
        client.ping()
    except redis.RedisError:
        pytest.fail("the configured disposable Redis is unavailable")
    assert client.dbsize() == 0, "dedicated journal fixture DB must be empty"
    journal = ObservationStream(client, kind="completed")
    keys = (
        journal.key(DAY),
        journal.identity_key(DAY),
        journal.cursor_key("reference", DAY),
        journal.registration_key("reference"),
    )
    try:
        yield client
    finally:
        client.delete(*keys)
        client.close()


@pytest.mark.isolated_postgresql
def test_postgresql_and_real_redis_prefix_proof_is_readonly_and_survives_new_feed_input(
    installed_inbox_database,  # noqa: F811
    isolated_journal_redis,
    tmp_path,
):
    from sqlalchemy import event

    factory, protocol, journal, _, _, capture, sample = _setup(
        tmp_path, installed_inbox_database, isolated_journal_redis
    )
    first = sample()
    capture("11-0", status="BLOCKED")
    capture("12-0")
    _append(journal, "13-0")
    capture("13-0")
    statements = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.upper())

    event.listen(installed_inbox_database, "before_cursor_execute", observe)
    before = (
        protocol.path.read_bytes(),
        journal.cursor("reference", DAY),
        journal.tail(DAY),
    )
    try:
        second = sample(1)
    finally:
        event.remove(installed_inbox_database, "before_cursor_execute", observe)
    assert (
        protocol.path.read_bytes(),
        journal.cursor("reference", DAY),
        journal.tail(DAY),
    ) == before
    assert second["acknowledged_count"] == 3 and second["source_count"] == 2
    assert (
        prove_receiving_liveness(first, second, now=NOW + timedelta(seconds=1))[
            "advanced_count"
        ]
        == 3
    )
    assert any("REPEATABLE READ, READ ONLY" in statement for statement in statements)
    assert not any(
        "FOR UPDATE" in statement
        or statement.lstrip().startswith(
            ("INSERT", "UPDATE", "DELETE", "ALTER", "DROP")
        )
        for statement in statements
    )
    with factory() as session:
        assert "BLOCKED" in session.scalars(select(ReferenceInboxDelivery.status)).all()
    idle = sample(2)
    assert (
        prove_receiving_liveness(second, idle, now=NOW + timedelta(seconds=2))["mode"]
        == "durable_receiving_caught_up_idle"
    )
    _append(journal, "14-0")
    pending = sample(3)
    from app.reference_trading.receiving_liveness import verify_receiving_nonregression

    assert verify_receiving_nonregression(
        idle, pending, now=NOW + timedelta(seconds=3)
    ) == {"advanced_count": 0, "caught_up_idle": False}
    with pytest.raises(ReceivingLivenessError):
        prove_receiving_liveness(
            idle, pending, closed_idle=True, now=NOW + timedelta(seconds=3)
        )


def test_caught_up_fresh_cycles_prove_idle_even_during_trading(tmp_path):
    _, _, _, _, _, capture, sample = _setup(tmp_path)
    capture("11-0")
    capture("12-0")
    before, after = sample(), sample(1)
    result = prove_receiving_liveness(before, after, now=NOW + timedelta(seconds=1))
    assert result["mode"] == "durable_receiving_caught_up_idle"
    assert after["days"][DAY.isoformat()]["current_tail"] == "12-0"
    assert after["days"][DAY.isoformat()]["final_tail"] == "12-0"
    assert result["calculation_ready"] is False


def test_new_unacked_tail_never_counts_as_idle_even_when_closed(tmp_path):
    _, _, journal, _, _, capture, sample = _setup(tmp_path)
    capture("11-0")
    capture("12-0")
    first = sample()
    _append(journal, "13-0")
    second = sample(1)
    with pytest.raises(ReceivingLivenessError):
        prove_receiving_liveness(
            first, second, closed_idle=True, now=NOW + timedelta(seconds=1)
        )


def test_nonregression_distinguishes_valid_wait_from_liveness(tmp_path):
    from app.reference_trading.receiving_liveness import verify_receiving_nonregression

    _, _, _, _, _, _, sample = _setup(tmp_path)
    before, after = sample(), sample(1)
    assert verify_receiving_nonregression(
        before, after, now=NOW + timedelta(seconds=1)
    ) == {
        "advanced_count": 0,
        "caught_up_idle": False,
    }
    with pytest.raises(ReceivingLivenessError):
        prove_receiving_liveness(before, after, now=NOW + timedelta(seconds=1))


def test_static_context_stays_bound_while_verified_ack_progresses(tmp_path):
    from app.reference_trading.receiving_liveness import receiving_context_identity

    _, _, _, _, _, capture, sample = _setup(tmp_path)
    first = sample()
    capture("11-0")
    second = sample(1)
    assert receiving_context_identity(first) == receiving_context_identity(second)
    assert receiving_snapshot_identity(first) != receiving_snapshot_identity(second)


@pytest.mark.parametrize("field", ("current_tail", "final_tail"))
def test_resigned_invalid_frontier_is_never_idle_authority(tmp_path, field):
    from app.reference_trading.inbox import _digest

    _, _, _, _, _, capture, sample = _setup(tmp_path)
    capture("11-0")
    capture("12-0")
    before, after = sample(), sample(1)
    after["days"][DAY.isoformat()][field] = "11-0"
    after["snapshot_sha256"] = _digest(
        {k: v for k, v in after.items() if k != "snapshot_sha256"}
    )
    with pytest.raises(ReceivingLivenessError):
        prove_receiving_liveness(before, after, now=NOW + timedelta(seconds=1))


def test_expired_continuity_is_not_a_liveness_proof(tmp_path):
    from app.reference_trading.receiving_liveness import (
        receiving_sample_is_fresh,
        verify_receiving_continuity,
    )

    _, _, _, _, _, capture, sample = _setup(tmp_path)
    first = sample()
    capture("11-0")
    second = sample(31)
    now = NOW + timedelta(seconds=31)
    assert not receiving_sample_is_fresh(first, now=now)
    assert receiving_sample_is_fresh(second, now=now)
    assert verify_receiving_continuity(first, second)["advanced_count"] == 1
    with pytest.raises(ReceivingLivenessError):
        prove_receiving_liveness(first, second, now=now)


@pytest.mark.parametrize(
    "field", ("protocol_sha256", "ack_inputs_sha256", "ack_routes_sha256")
)
def test_expiry_never_allows_a_resigned_context_or_prefix_change(tmp_path, field):
    from app.reference_trading.inbox import _digest
    from app.reference_trading.receiving_liveness import verify_receiving_continuity

    _, _, _, _, _, capture, sample = _setup(tmp_path)
    capture("11-0")
    first, second = sample(), sample(31)
    if field == "protocol_sha256":
        second[field] = "0" * 64
    else:
        second["days"][DAY.isoformat()][field] = "0" * 64
    second["snapshot_sha256"] = _digest(
        {k: v for k, v in second.items() if k != "snapshot_sha256"}
    )
    with pytest.raises(ReceivingLivenessError):
        verify_receiving_continuity(first, second)


def test_freshness_checks_clock_and_integrity_before_returning_expired(tmp_path):
    from app.reference_trading.receiving_liveness import receiving_sample_is_fresh

    _, _, _, _, _, _, sample = _setup(tmp_path)
    first = sample()
    with pytest.raises(ReceivingLivenessError):
        receiving_sample_is_fresh(first, now=NOW - timedelta(seconds=1))
    first["acknowledged_count"] = 1
    with pytest.raises(ReceivingLivenessError):
        receiving_sample_is_fresh(first, now=NOW + timedelta(seconds=31))
