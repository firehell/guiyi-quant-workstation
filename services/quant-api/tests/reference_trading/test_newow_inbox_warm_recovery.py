from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.reference_trading.activation import ForwardActivation
from app.reference_trading.contracts import SeedChunk, manifest_sha256
from app.reference_trading.forward_authority import ForwardMarketAuthority
from app.reference_trading.inbox import ReferenceInboxRepository
from app.reference_trading.inbox_recovery import digest, original_digest
from app.reference_trading.models import ReferenceInboxDelivery, ReferenceInboxInput
from app.reference_trading.newow_inbox_warm_recovery import NewowOscillationInboxWarmRecovery, POLICY
from app.reference_trading.repository import ReferenceRepository
from guiyi_quant.newow.product_adapters import seed_replay_state
from guiyi_quant.reference_trading import ReferenceState, StreamIdentity
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading.test_newow_worker_recovery import forward_postgresql  # noqa: F401
from test_activation import NOW
from test_inbox import event
from test_newow_fusion_forward import sources


@pytest.fixture
def scenario(forward_postgresql, tmp_path):  # noqa: F811
    Base.metadata.create_all(forward_postgresql)
    factory = sessionmaker(forward_postgresql, expire_on_commit=False)
    repo = ReferenceRepository(factory)
    _, dependencies = sources("60m")
    wire = dependencies[1]["identity"]
    identity = StreamIdentity(**{**wire, "formula_versions": tuple(wire["formula_versions"])})
    prefix_at = NOW + timedelta(seconds=2)
    start = NOW + timedelta(seconds=4)
    end = NOW + timedelta(seconds=6)
    day = end.date()
    market = SimpleNamespace(
        dominant_segment_for_day=lambda *_: SimpleNamespace(
            contract="RB2610", symbol="rb", start_trading_day=day,
        ),
        session_windows=lambda **_: [SimpleNamespace(start=NOW - timedelta(hours=1))],
        expected_contract_replay_endpoints=lambda **kw: tuple(
            (t, day) for t in market.ends if kw["after"] < t <= kw["cutoff"]
        ),
        ends=(prefix_at, end),
    )
    owner, calculation = ForwardMarketAuthority(market).owner_segments(identity, "RB2610", day, NOW)
    stream = repo.ensure_stream(identity)
    manifest = {"source": "isolated"}
    revision = repo.create_revision(identity.stream_id, stream.row_version, manifest_sha256(manifest))
    repo.stage_seed_chunk(revision, SeedChunk("seed", 0, 1, sha256(b"seed").hexdigest(), "seed"))
    repo.seal_seed(
        revision, manifest, AdapterCheckpoint(
            seed_replay_state(), NOW, sha256(b"seed").hexdigest(), "RB2610", owner, calculation,
            identity, ReferenceState.flat(identity, recording_start=start),
        ), "newow_product_replay_v1",
    )
    activation = ForwardActivation(factory)
    plan = activation.plan(
        identity.stream_id, revision, host="isolated", environment="isolated",
        recording_start=start, expires_at=start + timedelta(minutes=1), budget={"max_pending": 32},
    )
    activation.apply(plan, expected_plan_hash=plan.plan_hash, now=NOW)
    inbox = ReferenceInboxRepository(factory)
    prefix = replace(event("10-0", end=prefix_at), channel="live:bar:rb:60m")
    head = replace(event("20-0", end=end), channel="live:bar:rb:60m")
    assert inbox.ingest(prefix).delivery_ids == ()
    delivery_id, = inbox.ingest(head).delivery_ids
    inbox.mark_blocked(delivery_id, "OBSERVATION_GAP")
    attempts = tmp_path.resolve() / "attempts"
    recovery = NewowOscillationInboxWarmRecovery(
        factory, attempt_dir=attempts,
        verify_fence=lambda: {"attempt_namespace_sha256": digest(str(attempts)), "host": "isolated"},
        market_factory=lambda _: market,
    )
    return recovery, repo, inbox, factory, market, delivery_id, start, end


@pytest.mark.isolated_postgresql
def test_warm_recovery_commits_only_the_formal_head_and_preserves_original(scenario):
    recovery, repo, inbox, factory, _, delivery_id, _, end = scenario
    draft = recovery.prepare(delivery_id)
    assert len(draft.capture.source_proof[POLICY]["originals"]) == 1
    assert draft.warmed.reference_state == draft.original.reference_state
    plan = recovery.plan(delivery_id, expires_at=recovery.inbox.now() + timedelta(minutes=1))
    result = recovery.apply(plan, expected_plan_hash=plan.plan_hash, commit_guard=lambda *_: None)
    assert recovery.readback(plan) == result
    assert recovery.apply(plan, expected_plan_hash=plan.plan_hash, commit_guard=lambda *_: None) == result
    token, checkpoint = repo.load_checkpoint(draft.token.stream_id)
    assert token.seq == draft.token.seq + 1 and token.revision_id == draft.token.revision_id
    assert checkpoint.computed_through == end
    with factory() as session:
        delivery = session.get(ReferenceInboxDelivery, delivery_id)
        original = session.get(ReferenceInboxInput, delivery.input_id)
        assert original_digest(delivery, original) == plan.original_sha256
        assert session.scalars(select(ReferenceInboxDelivery.delivery_id)).all() == [delivery_id]
    assert inbox.next_heads() == ()


@pytest.mark.isolated_postgresql
def test_warm_recovery_rejects_source_drift_and_preserves_head_on_commit_failure(scenario):
    recovery, repo, _, _, market, delivery_id, start, end = scenario
    plan = recovery.plan(delivery_id, expires_at=recovery.inbox.now() + timedelta(minutes=1))
    ends = market.ends
    market.ends = (start, end)
    with pytest.raises(ValueError, match="NEWOW_INBOX_WARM_ENDPOINTS_INVALID"):
        recovery.apply(plan, expected_plan_hash=plan.plan_hash, commit_guard=lambda *_: None)
    assert recovery.readback(plan) is None
    market.ends = ends

    def reject_commit(*_):
        raise RuntimeError("ISOLATED_COMMIT_GUARD_FAILURE")

    with pytest.raises(ValueError, match="REFERENCE_INBOX_RECOVERY_OUTCOME_UNKNOWN"):
        recovery.apply(plan, expected_plan_hash=plan.plan_hash, commit_guard=reject_commit)
    assert recovery.readback(plan) is None
    assert repo.load_checkpoint(plan.capture.stream_id)[0] == plan.checkpoint
