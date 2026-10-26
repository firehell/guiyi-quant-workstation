from datetime import UTC, datetime, timedelta
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.market_data.live_market import LIVE_BAR_CHANNEL_PREFIX
from app.market_data.observation_stream import ObservationEnvelope
from app.reference_trading.inbox import ReferenceInboxRepository
from app.reference_trading.models import ReferenceStream, ReferenceRevision, ReferenceActivationReceipt, ReferenceInboxDelivery, ReferenceInboxInput
from app.reference_trading.operational_readiness import build_receiving_wait_proof, reference_waiting_history_mode

from guiyi_quant.reference_trading import StreamIdentity

NOW = datetime.now(UTC)
IDENTITY = StreamIdentity(strategy_code="subing_reference", formula_versions=("test",), profile_id="test",
    reference_model_version="test", futures_adaptation_version="test", product="rb", frequency="5m",
    series_kind="actual_dominant", recording_mode="forward_observation", observation_policy_version="test")
STREAM = IDENTITY.stream_id
ALLOWED = "SOURCE_BUSY"


def setup_wait(*, status="WAITING_HISTORY", code=ALLOWED, engine=None):
    engine = engine or create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    start = NOW - timedelta(hours=1)
    with factory() as session, session.begin():
        session.add(ReferenceStream(stream_id=STREAM, identity_hash=STREAM.removeprefix("reference-stream:"), strategy_code="subing_reference",
            formula_versions=["test"], profile_id="test", reference_model_version="test", futures_adaptation_version="test",
            product="rb", frequency="5m", series_kind="actual_dominant", recording_mode="forward_observation",
            observation_policy_version="test", enabled=True, active_revision_id=None, activation_generation=1,
            recording_start=start, activation_plan_hash="b" * 64))
        session.flush()
        session.add(ReferenceRevision(stream_id=STREAM, revision_id="revision", status="active", last_seq=0, dependency_digest="c" * 64))
        session.flush()
        session.add(ReferenceActivationReceipt(receipt_id="receipt", stream_id=STREAM, revision_id="revision", generation=1,
            plan_hash="b" * 64, recording_start=start, activated_at=start, environment="isolated", host="test",
            budget={}, recovery_policy="test"))
        session.flush()
        session.get(ReferenceStream, STREAM).active_revision_id = "revision"
    repo = ReferenceInboxRepository(factory)
    receipt = repo.ingest(event())
    delivery = receipt.delivery_ids[0]
    with factory() as session, session.begin():
        row = session.get(ReferenceInboxDelivery, delivery)
        row.status, row.code = status, code
    return factory, repo, delivery


def event(identifier="10-0"):
    end = NOW - timedelta(minutes=1)
    return ObservationEnvelope("observation-" + identifier, end.date(), end + timedelta(seconds=2),
        f"{LIVE_BAR_CHANNEL_PREFIX}:rb:5m", {"bar_end": end.isoformat(), "trading_day": end.date().isoformat(),
        "contract": "RB2701", "open": "100", "high": "101", "low": "99", "close": "100", "volume": "1",
        "turnover": None, "open_interest": None}, True, identifier, end + timedelta(seconds=1), end + timedelta(seconds=3))


def state(proof):
    return {"phase": "active", "at": NOW.isoformat(), "ready": False, "proof": {"cursor_validated": True,
        "reference_runtime": {"stage": "receiving_cycle", "ready": False, "blocked_count": proof["waiting_count"]},
        "receiving": {"protocol_version": 2, "intake_error": None, "waiting_history_proof": proof}}}


def mode_authority(monkeypatch, factory):
    from app.reference_trading import operational_readiness as module
    protocol = {"schema_version": 1, "protocol_version": 2, "status": "active", "binding": "stable", "boundaries": {}}
    monkeypatch.setattr(module, "_session_factory", lambda: factory)
    monkeypatch.setattr(module, "_receiving_protocol", lambda: SimpleNamespace(binding="stable", read=lambda: dict(protocol)))
    monkeypatch.setattr(module, "_schema_ready", lambda session_factory: True)
    monkeypatch.setattr(module, "_now", lambda: NOW)
    return protocol


def test_wait_proof_is_exact_readonly_and_contains_counts_and_hashes_only():
    factory, _, _ = setup_wait()
    proof = build_receiving_wait_proof(factory, ((STREAM, ALLOWED),))
    assert proof["waiting_count"] == 1 and proof["pending_count"] == 0
    assert set(proof) == {"schema_version", "kind", "waiting_count", "pending_count", "blocked_pairs_sha256", "heads_sha256"}
    assert STREAM not in str(proof)
    with factory() as session:
        assert session.scalar(select(ReferenceInboxDelivery.status)) == "WAITING_HISTORY"


@pytest.mark.parametrize("pairs", ((("wrong-stream", ALLOWED),), ((STREAM, "SUBING_PHYSICAL_PREFIX_UNAVAILABLE"),), (),
                                   ((STREAM, ALLOWED), (STREAM, ALLOWED))))
def test_wrong_blocked_head_or_reason_is_not_accepted_by_count(pairs):
    factory, _, _ = setup_wait()
    assert build_receiving_wait_proof(factory, pairs) is None


@pytest.mark.parametrize("field", ("revision", "generation", "receipt_hash", "raw_hash", "routing_hash"))
def test_frozen_identity_or_original_content_drift_blocks_proof(field):
    factory, _, delivery = setup_wait()
    with factory() as session, session.begin():
        row = session.get(ReferenceInboxDelivery, delivery)
        if field == "revision":
            session.get(ReferenceStream, STREAM).active_revision_id = "wrong"
        elif field == "generation":
            row.generation += 1
        elif field == "receipt_hash":
            session.get(ReferenceActivationReceipt, "receipt").plan_hash = "d" * 64
        elif field == "raw_hash":
            session.get(ReferenceInboxInput, row.input_id).envelope_sha256 = "e" * 64
        else:
            session.get(ReferenceInboxInput, row.input_id).routing_sha256 = "f" * 64
    assert build_receiving_wait_proof(factory, ((STREAM, ALLOWED),)) is None


@pytest.mark.parametrize("status,code", (("BLOCKED", "QUALITY_FAILED"), ("UNKNOWN", "COMMIT_UNKNOWN"),
    ("WAITING_HISTORY", "LIVE_SOURCE_UNAVAILABLE"), ("WAITING_HISTORY", "OBSERVATION_GAP"),
    ("WAITING_HISTORY", "NONPOSITIVE_CLOSE"), ("PENDING", "NEWOW_FUSION_SOURCE_PENDING")))
def test_unsafe_or_unproved_wait_is_never_operational(status, code):
    factory, _, _ = setup_wait(status=status, code=code)
    assert build_receiving_wait_proof(factory, ((STREAM, code),) if status == "WAITING_HISTORY" else ()) is None


def test_global_blocked_or_unknown_tail_blocks_even_when_head_waits():
    factory, repo, _ = setup_wait()
    later = repo.ingest(event("11-0")).delivery_ids[0]
    with factory() as session, session.begin():
        session.get(ReferenceInboxDelivery, later).status = "UNKNOWN"
    assert build_receiving_wait_proof(factory, ((STREAM, ALLOWED),)) is None


@pytest.mark.parametrize("status,code,expected", (("WAITING_HISTORY", ALLOWED, "durable_receiving_waiting_history"),
                                                ("PENDING", None, "durable_receiving_backlog")))
def test_only_independently_verified_v2_receiving_mode_is_accepted(monkeypatch, status, code, expected):
    factory, _, _ = setup_wait(status=status, code=code)
    pairs = ((STREAM, code),) if status == "WAITING_HISTORY" else ()
    proof = build_receiving_wait_proof(factory, pairs)
    mode_authority(monkeypatch, factory)
    assert reference_waiting_history_mode(state(proof)) == expected
    assert state(proof)["proof"]["reference_runtime"]["ready"] is False


def test_stale_head_proof_and_protocol_or_schema_error_never_pass(monkeypatch):
    factory, repo, _ = setup_wait()
    proof = build_receiving_wait_proof(factory, ((STREAM, ALLOWED),))
    protocol = mode_authority(monkeypatch, factory)
    owner = state(proof)
    protocol["intake_error"] = "REFERENCE_INBOX_COMMIT_UNKNOWN"
    assert reference_waiting_history_mode(owner) is None
    protocol.pop("intake_error")
    from app.reference_trading import operational_readiness as module
    monkeypatch.setattr(module, "_schema_ready", lambda session_factory: False)
    assert reference_waiting_history_mode(owner) is None
    monkeypatch.setattr(module, "_schema_ready", lambda session_factory: True)
    older = repo.ingest(event("9-0")).delivery_ids[0]
    repo.mark_waiting(older, ALLOWED)
    assert reference_waiting_history_mode(owner) is None


@pytest.mark.parametrize("change", ("legacy", "stage", "count", "cursor", "stale", "intake", "requested"))
def test_legacy_or_invalid_owner_report_keeps_existing_gate(monkeypatch, change):
    factory, _, _ = setup_wait()
    proof = build_receiving_wait_proof(factory, ((STREAM, ALLOWED),))
    protocol = mode_authority(monkeypatch, factory)
    owner = deepcopy(state(proof))
    if change == "legacy":
        owner["proof"]["receiving"]["protocol_version"] = 1
    elif change == "stage":
        owner["proof"]["reference_runtime"]["stage"] = "scan"
    elif change == "count":
        owner["proof"]["reference_runtime"]["blocked_count"] += 1
    elif change == "cursor":
        owner["proof"]["cursor_validated"] = False
    elif change == "stale":
        owner["at"] = (NOW - timedelta(seconds=31)).isoformat()
    elif change == "intake":
        owner["proof"]["receiving"]["intake_error"] = "ERROR"
    else:
        protocol["status"] = "requested"
    assert reference_waiting_history_mode(owner) is None


def test_zero_waiting_empty_proof_is_not_a_hidden_database_failure(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    proof = build_receiving_wait_proof(factory, ())
    assert proof["waiting_count"] == proof["pending_count"] == 0
    mode_authority(monkeypatch, factory)
    assert reference_waiting_history_mode(state(proof)) == "durable_receiving"
    def unavailable():
        raise RuntimeError("private database connection error")
    assert build_receiving_wait_proof(unavailable, ()) is None
    engine.dispose()


def test_owner_binding_drift_and_slow_schema_proof_fail_closed(monkeypatch):
    factory, _, _ = setup_wait()
    proof = build_receiving_wait_proof(factory, ((STREAM, ALLOWED),))
    protocol = mode_authority(monkeypatch, factory)
    owner = state(proof)
    protocol["binding"] = "different-data-authority"
    assert reference_waiting_history_mode(owner) is None
    protocol["binding"] = "stable"
    from app.reference_trading import operational_readiness as module
    calls = iter((NOW, NOW + timedelta(seconds=31)))
    monkeypatch.setattr(module, "_now", lambda: next(calls))
    assert reference_waiting_history_mode(owner) is None


from tests.alembic.conftest import isolated_postgres_engine  # noqa: E402,F401
from tests.test_runtime_schema_compatibility import installed_inbox_database  # noqa: E402,F401


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize("status,code,mode", (("WAITING_HISTORY", ALLOWED, "durable_receiving_waiting_history"),
                                            ("PENDING", None, "durable_receiving_backlog")))
def test_postgresql_proof_and_fresh_schema_gate_are_readonly_repeatable(installed_inbox_database, tmp_path, monkeypatch, status, code, mode):  # noqa: F811
    import json
    from sqlalchemy import event as sql_event
    from app.reference_trading import operational_readiness as module
    from app.reference_trading.inbox_protocol import ReceivingProtocol
    from app.runtime_handover import _write
    factory, _, _ = setup_wait(engine=installed_inbox_database, status=status, code=code)
    protocol = ReceivingProtocol(tmp_path / "receiving.json", binding="isolated-stable")
    _write(protocol.path, {"schema_version": 1, "protocol_version": 2, "status": "active",
                           "binding": protocol.binding, "boundaries": {}})
    monkeypatch.setattr(module, "_session_factory", lambda: factory)
    monkeypatch.setattr(module, "_receiving_protocol", lambda: protocol)
    monkeypatch.setattr(module, "_now", lambda: NOW)
    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.upper())
    sql_event.listen(installed_inbox_database, "before_cursor_execute", capture)
    try:
        proof = build_receiving_wait_proof(factory, ((STREAM, code),) if status == "WAITING_HISTORY" else ())
        assert proof is not None
        assert reference_waiting_history_mode(state(proof)) == mode
        assert any("REPEATABLE READ, READ ONLY" in statement for statement in statements)
        assert not any("FOR UPDATE" in statement or statement.lstrip().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"))
                       for statement in statements)
        assert json.loads(protocol.path.read_text())["status"] == "active"
    finally:
        sql_event.remove(installed_inbox_database, "before_cursor_execute", capture)


@pytest.mark.parametrize("field,value", (("product", "cu"), ("frequency", "60m"), ("profile_id", "different"),
    ("identity_hash", "0" * 64), ("formula_versions", ["different"]), ("reference_model_version", "different"),
    ("futures_adaptation_version", "different"), ("strategy_code", "different"), ("series_kind", "different"),
    ("observation_policy_version", "different")))
def test_current_stream_identity_drift_rejects_same_revision_generation_receipt(field, value):
    factory, _, _ = setup_wait()
    initial = build_receiving_wait_proof(factory, ((STREAM, ALLOWED),))
    assert initial is not None
    with factory() as session, session.begin():
        setattr(session.get(ReferenceStream, STREAM), field, value)
    assert build_receiving_wait_proof(factory, ((STREAM, ALLOWED),)) is None


def test_verified_original_channel_must_match_current_stream_identity():
    from dataclasses import replace
    from app.reference_trading.inbox import _envelope
    factory, _, delivery_id = setup_wait()
    original = event()
    wrong = replace(original, channel=f"{LIVE_BAR_CHANNEL_PREFIX}:cu:5m",
                    data={**original.data, "contract": "CU2701"})
    product, frequency, end, canonical, digest, size, order = _envelope(wrong)
    with factory() as session, session.begin():
        delivery = session.get(ReferenceInboxDelivery, delivery_id)
        item = session.get(ReferenceInboxInput, delivery.input_id)
        item.product, item.frequency, item.canonical_envelope = product, frequency, canonical
        item.envelope_sha256, item.payload_bytes = digest, size
    assert build_receiving_wait_proof(factory, ((STREAM, ALLOWED),)) is None


@pytest.mark.parametrize("change", ("missing_count", "missing_hash", "bool_count", "negative", "overflow", "total_overflow",
                                   "bad_hash", "uppercase_hash", "extra", "kind", "schema", "none"))
def test_shared_pure_shape_validator_rejects_incomplete_or_unbounded_proof(change):
    from app.reference_trading.operational_readiness import valid_receiving_wait_proof, MAX_HEADS
    factory, _, _ = setup_wait()
    proof = build_receiving_wait_proof(factory, ((STREAM, ALLOWED),))
    assert valid_receiving_wait_proof(proof) is True
    if change == "missing_count":
        proof.pop("pending_count")
    elif change == "missing_hash":
        proof.pop("heads_sha256")
    elif change == "bool_count":
        proof["waiting_count"] = True
    elif change == "negative":
        proof["pending_count"] = -1
    elif change == "overflow":
        proof["waiting_count"] = MAX_HEADS + 1
    elif change == "total_overflow":
        proof["waiting_count"], proof["pending_count"] = MAX_HEADS, 1
    elif change == "bad_hash":
        proof["heads_sha256"] = "invalid"
    elif change == "uppercase_hash":
        proof["heads_sha256"] = "A" * 64
    elif change == "extra":
        proof["unverified"] = True
    elif change == "kind":
        proof["kind"] = "legacy"
    elif change == "schema":
        proof["schema_version"] = True
    else:
        proof = None
    assert valid_receiving_wait_proof(proof) is False
