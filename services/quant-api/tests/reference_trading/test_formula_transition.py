"""Formula retirement retains original evidence and never creates an exit fill."""

from dataclasses import replace
from datetime import datetime, UTC, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.reference_trading.models import (
    ReferenceStream,
    ReferenceRevision,
    ReferenceBatch,
    ReferenceActivationReceipt,
    ReferenceActionRow,
    ReferenceTradeRow,
)
from app.reference_trading.repository import ReferenceRepository, RepositoryConflict
from app.reference_trading.contracts import SeedChunk, manifest_sha256
from app.reference_trading.formula_transition import NewowFormulaTransition, SCHEMA
from guiyi_quant.reference_trading import (
    ReferenceState,
    ReferenceAction,
    ActionKind,
    reduce_reference,
)
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.strategy_checkpoint import (
    adapter_checkpoint_to_json,
    adapter_checkpoint_from_json,
    _wire,
    _canonical,
)
from guiyi_quant.reference_trading.checkpoint import checkpoint_to_json
from guiyi_quant.newow.product_adapters import (
    build_product_identity,
    seed_replay_state,
    replay_step,
)
from guiyi_quant.newow.product_contracts import ProductBar
from guiyi_quant.newow.product_identity import (
    reference_model_version,
    futures_adaptation_version,
)
from guiyi_quant.newow.fusion_reference import (
    build_fusion_stream_identity,
    FusionReferenceReplayState,
)
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.reference_trading import StreamIdentity

NOW = datetime(2026, 11, 7, 8, tzinfo=UTC)
BAR = NOW - timedelta(days=1)
START = NOW + timedelta(hours=1)


def fixture(engine=None, *, current=False):
    engine = engine or create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repo = ReferenceRepository(factory)
    pairs = []
    sources = []
    for code in ["trend", "oscillation", "dual_fusion"] + (["main_rise"] if current else []):
        p = build_product_identity(
            "rb", "oscillation" if code == "dual_fusion" else code, "60m"
        )
        identity = (
            build_fusion_stream_identity("rb", "60m")
            if code == "dual_fusion"
            else StreamIdentity(
                "newow_" + code,
                p.formula_versions,
                p.profile_id,
                reference_model_version(p),
                futures_adaptation_version("60m"),
                "rb",
                "60m",
                "actual_dominant",
                "historical_replay",
                None,
            )
        )
        bar = NewowDailyBar(
            "rb",
            "RB2701",
            "owner",
            BAR.date(),
            BAR,
            Decimal(100),
            Decimal(102),
            Decimal(99),
            Decimal(101),
            100,
            None,
            "fixture",
            True,
            True,
        )
        state = (
            FusionReferenceReplayState()
            if code == "dual_fusion"
            else replay_step(
                p,
                seed_replay_state(),
                ProductBar(
                    bar,
                    "60m",
                    calculation_segment_id="calc",
                    source_bar_sha256="a" * 64,
                ),
            )[0]
        )
        cp = AdapterCheckpoint(
            state,
            BAR,
            "a" * 64,
            "RB2701",
            "owner",
            "calc",
            identity,
            ReferenceState.flat(identity),
        )
        stored = repo.ensure_stream(identity)
        manifest = {"reader": "verified-fixture"}
        if code == "dual_fusion":
            manifest["source_dependencies"] = list(sources)
        rev = repo.create_revision(
            identity.stream_id, stored.row_version, manifest_sha256(manifest)
        )
        content = adapter_checkpoint_to_json(
            cp,
            strategy_schema="newow_dual_fusion_reference_v1"
            if code == "dual_fusion"
            else "newow_product_replay_v1",
        )
        repo.stage_seed_chunk(
            rev, SeedChunk("seed", 0, 1, sha256(content.encode()).hexdigest(), content)
        )
        repo.seal_seed(
            rev,
            manifest,
            cp,
            "newow_dual_fusion_reference_v1"
            if code == "dual_fusion"
            else "newow_product_replay_v1",
        )
        repo.publish_revision(
            identity.stream_id, rev, stored.row_version, manifest_sha256(manifest)
        )
        sources.append(dict(stream_id=identity.stream_id, revision_id=rev, seq=1))
        if code == "trend" and not current:
            continue
        old = replace(
            identity,
            formula_versions=identity.formula_versions if current else ("legacy_formula_v1",),
            profile_id=identity.profile_id if current else "legacy",
            recording_mode="forward_observation",
            observation_policy_version="completed_observation_v1",
        )
        repo.ensure_stream(old)
        reference = ReferenceState.flat(old, recording_start=BAR - timedelta(days=1))
        action = ReferenceAction(
            old,
            "entry",
            "RB2701",
            "owner",
            "calc",
            BAR,
            BAR.date(),
            0,
            ActionKind.OPEN_LONG,
            Decimal(100),
        )
        if not current or code == "trend":
            reference = reduce_reference(reference, actions=(action,)).state
        cp = replace(cp, stream=old, reference_state=reference)
        # Retained legacy bytes: normal readers must continue to reject the oscillator.
        if code == "oscillation" and not current:
            from guiyi_quant.newow.oscillation_channel import OscillationState

            cp.strategy_state.oscillation_state = OscillationState()
        schema = (
            "newow_dual_fusion_reference_v1"
            if code == "dual_fusion"
            else "newow_product_replay_v1"
        )
        body = dict(
            schema_version="reference_strategy_checkpoint_v1",
            strategy_schema=schema,
            stream_id=old.stream_id,
            strategy_state=_wire(cp.strategy_state),
            reference_state=json.loads(checkpoint_to_json(reference)),
            computed_through=BAR.isoformat(),
            last_fingerprint="a" * 64,
            physical_contract="RB2701",
            owner_segment_id="owner",
            calculation_segment_id="calc",
        )
        # Obtain the real schema spelling from a valid envelope.
        body["schema_version"] = json.loads(content)["schema_version"]
        raw = _canonical(
            {**body, "checksum_sha256": sha256(_canonical(body).encode()).hexdigest()}
        )
        with factory.begin() as db:
            row = db.get(ReferenceStream, old.stream_id)
            rid = uuid4().hex
            bid = uuid4().hex
            db.add(
                ReferenceRevision(
                    stream_id=old.stream_id,
                    revision_id=rid,
                    status="active",
                    last_seq=1,
                    dependency_digest=manifest_sha256(manifest),
                )
            )
            db.flush()
            db.add(
                ReferenceBatch(
                    batch_id=bid,
                    stream_id=old.stream_id,
                    revision_id=rid,
                    batch_key="old",
                    payload_hash="a" * 64,
                    kind="calculation",
                    outcome="committed",
                    seq=1,
                    expected_seq=0,
                    post_state_hash=sha256(raw.encode()).hexdigest(),
                    checkpoint_text=raw,
                    strategy_schema=schema,
                    computed_through=BAR,
                    dependency_manifest=manifest,
                    source_evidence={
                        "presentation_v1": {
                            "version": "presentation_v1",
                            "points": [],
                            "first_day": None,
                            "last_day": None,
                        }
                    },
                    projected_action_pks=[],
                    diagnostics=[],
                    processed_at=BAR,
                )
            )
            db.flush()
            revision = db.get(ReferenceRevision, (old.stream_id, rid))
            revision.checkpoint_batch_id = bid
            row.enabled = True
            row.active_revision_id = rid
            row.latest_seq = 1
            row.activation_generation = 1
            row.recording_start = reference.recording_start
            row.activation_plan_hash = "b" * 64
            row.health = "READY"
            db.add(
                ReferenceActivationReceipt(
                    receipt_id=uuid4().hex,
                    stream_id=old.stream_id,
                    revision_id=rid,
                    generation=1,
                    plan_hash="b" * 64,
                    recording_start=reference.recording_start,
                    activated_at=reference.recording_start,
                    environment="fixture",
                    host="fixture",
                    budget={"max_units_per_round": 32},
                    recovery_policy="block",
                )
            )
            if reference.open_trade is None:
                pairs.append((old.stream_id, identity.stream_id))
                continue
            aid = uuid4().hex
            db.add(
                ReferenceActionRow(
                    action_pk=aid,
                    stream_id=old.stream_id,
                    origin_revision_id=rid,
                    batch_revision_id=rid,
                    source_action_id="entry",
                    recording_mode="forward_observation",
                    kind="OPEN_LONG",
                    sequence=0,
                    physical_contract="RB2701",
                    owner_segment_id="owner",
                    calculation_segment_id="calc",
                    bar_end=BAR,
                    trading_day=BAR.date(),
                    reference_price=Decimal(100),
                    reference_price_type="close",
                    batch_id=bid,
                    batch_seq=1,
                )
            )
            db.flush()
            t = reference.open_trade
            db.add(
                ReferenceTradeRow(
                    stream_id=old.stream_id,
                    revision_id=rid,
                    trade_id=t.reference_trade_id,
                    valid_from_seq=1,
                    entry_action_pk=aid,
                    side="LONG",
                    status="OPEN",
                    physical_contract="RB2701",
                    owner_segment_id="owner",
                    calculation_segment_id="calc",
                    entry_bar_end=BAR,
                    entry_trading_day=BAR.date(),
                    entry_reference_price=Decimal(100),
                    holding_bars=0,
                    effective_bar_end=BAR,
                )
            )
        pairs.append((old.stream_id, identity.stream_id))
    return factory, pairs


def test_transition_atomic_append_and_idempotent(transition_engine):
    factory, pairs = fixture(transition_engine)
    service = NewowFormulaTransition(factory, assert_fenced=lambda: None)
    with factory() as db:
        originals = {
            b.batch_id: b.checkpoint_text for b in db.scalars(select(ReferenceBatch))
        }
    plan = service.plan(pairs, recording_start=START, expires_at=START, now=NOW)
    assert service.status(plan) is None
    result = service.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    assert result["status"] == "COMMITTED" and service.status(plan) == result
    assert (
        service.apply(
            plan, expected_plan_hash=plan["plan_hash"], now=START + timedelta(days=1)
        )
        == result
    )
    with factory() as db:
        assert all(
            db.get(ReferenceBatch, k).checkpoint_text == v for k, v in originals.items()
        )
        retired = list(
            db.scalars(
                select(ReferenceTradeRow).where(
                    ReferenceTradeRow.status == "OBSERVATION_INTERRUPTED"
                )
            )
        )
        assert len(retired) == 2 and all(
            t.exit_action_pk is None
            and t.exit_reference_price is None
            and t.reference_return is None
            for t in retired
        )
        assert len(list(db.scalars(select(ReferenceActionRow)))) == 2
        for item in plan["items"]:
            old = db.get(ReferenceStream, item["old"]["stream"]["stream_id"])
            assert not old.enabled
            batch = db.get(
                ReferenceBatch,
                db.get(
                    ReferenceRevision, (old.stream_id, old.active_revision_id)
                ).checkpoint_batch_id,
            )
            from app.reference_trading.repository import _identity_from_row

            cp = adapter_checkpoint_from_json(
                batch.checkpoint_text,
                expected_stream=_identity_from_row(old),
                expected_strategy_schema=SCHEMA,
            )
            assert cp.reference_state.open_trade is None
            new = db.get(ReferenceStream, item["bootstrap"]["target_stream_id"])
            assert new.enabled
            assert new.health == "FORMULA_WARMING"


def test_transition_rejects_drift_before_writes(transition_engine):
    factory, pairs = fixture(transition_engine)
    service = NewowFormulaTransition(factory, assert_fenced=lambda: None)
    plan = service.plan(pairs, recording_start=START, expires_at=START, now=NOW)
    with factory.begin() as db:
        db.get(ReferenceStream, pairs[0][0]).row_version += 1
    with pytest.raises(RepositoryConflict, match="PREIMAGE_DRIFT"):
        service.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    assert service.status(plan) is None
    with factory() as db:
        assert all(db.get(ReferenceStream, p[0]).enabled for p in pairs)


def test_retired_history_and_original_snapshot_remain_readable(
    monkeypatch, transition_engine
):
    from app.reference_trading.query import HistoricalReferenceQuery

    factory, pairs = fixture(transition_engine)
    query = HistoricalReferenceQuery(factory)
    # A token issued by the old release before the formula identity changed.
    with monkeypatch.context() as patch:
        patch.setattr(query, "_registered", lambda _: True)
        old = query.trades(pairs[0][0], since=BAR.date(), through=NOW.date())
    service = NewowFormulaTransition(factory, assert_fenced=lambda: None)
    plan = service.plan(pairs, recording_start=START, expires_at=START, now=NOW)
    service.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    latest = query.trades(pairs[0][0], since=BAR.date(), through=NOW.date())
    previous = query.trades(
        pairs[0][0],
        since=BAR.date(),
        through=NOW.date(),
        snapshot_token=old["snapshot"],
    )
    assert latest["items"][0]["status"] == "OBSERVATION_INTERRUPTED"
    assert previous["items"][0]["status"] == "OPEN"
    assert latest["coverage"]["formula_boundary_at"] == NOW.isoformat()
    assert (
        datetime.fromisoformat(latest["coverage"]["computed_through"]).replace(
            tzinfo=UTC
        )
        == BAR
    )


def test_failure_after_first_group_member_rolls_back_both(
    monkeypatch, transition_engine
):
    import app.reference_trading.formula_transition as module

    factory, pairs = fixture(transition_engine)
    service = NewowFormulaTransition(factory, assert_fenced=lambda: None)
    plan = service.plan(pairs, recording_start=START, expires_at=START, now=NOW)
    original = module.NewowForwardBootstrap.apply
    calls = []

    def fail_second(self, *args, **kwargs):
        calls.append(True)
        if len(calls) == 2:
            raise RepositoryConflict("INJECTED_SECOND_ACTIVATION_FAILURE")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(module.NewowForwardBootstrap, "apply", fail_second)
    with pytest.raises(RepositoryConflict, match="INJECTED_SECOND"):
        service.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    assert service.status(plan) is None
    with factory() as db:
        assert all(db.get(ReferenceStream, p[0]).enabled for p in pairs)
        assert all(
            db.get(ReferenceStream, p["bootstrap"]["target_stream_id"]) is None
            for p in plan["items"]
        )


@pytest.fixture(params=["sqlite", "postgresql"])
def transition_engine(request):
    if request.param == "sqlite":
        engine = create_engine("sqlite+pysqlite:///:memory:")
        try:
            yield engine
        finally:
            engine.dispose()
        return
    import os
    from app.db.migration_test_guard import (
        require_isolated_migration_database_url,
        probe_database_identity,
    )

    if not os.environ.get("GUIYI_ISOLATED_MIGRATION_DATABASE_URL"):
        pytest.skip("isolated PostgreSQL URL required")
    url = require_isolated_migration_database_url(
        os.environ, identity_probe=probe_database_identity
    )
    admin = create_engine(url)
    schema = "formula_transition_" + uuid4().hex
    with admin.begin() as db:
        db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = create_engine(url, connect_args={"options": "-csearch_path=" + schema})
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as db:
            db.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def test_warming_health_only_follows_verified_ready_projection():
    from app.reference_trading.formula_transition import finish_formula_warmup
    from types import SimpleNamespace

    prepared = SimpleNamespace(
        source_evidence={
            "presentation_v1": {
                "points": [{"kind": "availability", "value": {"status": "READY"}}]
            }
        }
    )
    for original in ["FORMULA_WARMING", "RECOVERY_PENDING", "BLOCKED", "READY"]:
        row = SimpleNamespace(health=original)
        finish_formula_warmup(row, prepared)
        assert row.health == ("READY" if original == "FORMULA_WARMING" else original)
    row = SimpleNamespace(health="FORMULA_WARMING")
    prepared.source_evidence["presentation_v1"]["points"][-1]["value"]["status"] = (
        "WARMING"
    )
    finish_formula_warmup(row, prepared)
    assert row.health == "FORMULA_WARMING"


def test_lost_acknowledgement_status_proves_commit_without_second_activation(
    transition_engine,
):
    factory, pairs = fixture(transition_engine)
    service = NewowFormulaTransition(factory, assert_fenced=lambda: None)
    plan = service.plan(pairs, recording_start=START, expires_at=START, now=NOW)
    service.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    # Simulate a client losing the reply. A new process uses only original plan.
    reopened = NewowFormulaTransition(factory, assert_fenced=lambda: None)
    assert reopened.status(plan)["status"] == "COMMITTED"
    with factory() as db:
        assert len(list(db.scalars(select(ReferenceActivationReceipt)))) == 4
        for item in plan["items"]:
            source = db.get(ReferenceStream, item["bootstrap"]["target_stream_id"])
            batch = db.scalar(
                select(ReferenceBatch).where(
                    ReferenceBatch.stream_id == source.stream_id,
                    ReferenceBatch.kind == "seed_seal",
                )
            )
            from app.reference_trading.repository import _identity_from_row

            cp = adapter_checkpoint_from_json(
                batch.checkpoint_text,
                expected_stream=_identity_from_row(source),
                expected_strategy_schema=batch.strategy_schema,
            )
            assert cp.reference_state.open_trade is None


def test_retirement_reader_rejects_rehashed_owner_mismatch(transition_engine):
    from guiyi_quant.reference_trading.strategy_checkpoint import (
        retirement_reference_from_json,
    )
    from app.reference_trading.repository import _identity_from_row

    factory, pairs = fixture(transition_engine)
    with factory() as db:
        stream = db.get(ReferenceStream, pairs[0][0])
        revision = db.get(
            ReferenceRevision, (stream.stream_id, stream.active_revision_id)
        )
        batch = db.get(ReferenceBatch, revision.checkpoint_batch_id)
        raw = json.loads(batch.checkpoint_text)
        raw.pop("checksum_sha256")
        raw["physical_contract"] = "RB9999"
        raw["checksum_sha256"] = sha256(_canonical(raw).encode()).hexdigest()
        with pytest.raises(ValueError, match="open trade owner"):
            retirement_reference_from_json(
                _canonical(raw),
                expected_stream=_identity_from_row(stream),
                expected_strategy_schema=batch.strategy_schema,
            )

def test_h1_boundary_uses_cold_seed_and_preserves_retired_history(transition_engine):
    from app.reference_trading.newow_h1_boundary import NewowH1Boundary
    from app.reference_trading.models import ReferenceInboxDelivery, ReferenceInboxInput
    from app.reference_trading.inbox import _head_query

    factory, pairs = fixture(transition_engine, current=True)
    old_ids = [old for old, _ in pairs]
    service = NewowH1Boundary(factory, assert_fenced=lambda: None)
    with factory.begin() as db:
        old = db.get(ReferenceStream, old_ids[0])
        receipt = db.scalar(select(ReferenceActivationReceipt).where(
            ReferenceActivationReceipt.stream_id == old.stream_id
        ))
        db.add(ReferenceInboxInput(
            input_id="i", trading_day=BAR.date(), journal_id="1-0", journal_ms=1,
            journal_sequence=0, observation_id="o", product="rb", frequency="60m", canonical_envelope="{}",
            envelope_sha256="1"*64, routing_sha256="2"*64, payload_bytes=2,
            target_count=1, bar_end=BAR, source_observed_at=BAR,
            confirmed_at=BAR, ingested_at=BAR,
        ))
        db.flush()
        db.add(ReferenceInboxDelivery(
            delivery_id="d", input_id="i", stream_id=old.stream_id,
            revision_id=old.active_revision_id, generation=old.activation_generation,
            activation_receipt_id=receipt.receipt_id,
            activation_plan_hash=old.activation_plan_hash, recording_start=old.recording_start,
            status="BLOCKED", code="OBSERVATION_GAP", created_at=BAR, updated_at=BAR,
        ))
    plan = service.plan(old_ids, recording_start=START, expires_at=START, now=NOW)
    with factory() as db:
        before = {b.batch_id:b.checkpoint_text for b in db.scalars(select(ReferenceBatch))}
    assert service.status(plan) is None
    result = service.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    assert result == service.status(plan)
    assert result == service.apply(plan, expected_plan_hash=plan["plan_hash"], now=START)
    with factory() as db:
        assert all(db.get(ReferenceBatch, bid).checkpoint_text == raw for bid,raw in before.items())
        assert db.get(ReferenceInboxDelivery, "d").status == "BLOCKED"
        assert db.scalar(_head_query(old_ids[0])).delivery_id == "d"
        assert all(not db.get(ReferenceStream, sid).enabled for sid in old_ids)
        for item in plan["items"]:
            sid = item["bootstrap"]["target_stream_id"]
            assert db.get(ReferenceStream, sid).health == "FORMULA_WARMING"
            assert db.scalar(_head_query(sid)) is None
            _, cp = ReferenceRepository(factory).load_checkpoint(sid)
            assert cp.computed_through is None and cp.reference_state.open_trade is None
        interrupted = db.scalars(select(ReferenceTradeRow).where(
            ReferenceTradeRow.status == "OBSERVATION_INTERRUPTED"
        )).all()
        assert len(interrupted) == 1 and all(
            row.exit_action_pk is None and row.exit_reference_price is None
            and row.reference_return is None for row in interrupted
        )

    from app.reference_trading.composition import build_forward_reference_worker
    from app.reference_trading.inbox import ReferenceInboxRepository
    from app.reference_trading.newow_fusion_forward import SavedForwardFusionSources
    from tests.reference_trading.test_inbox import event

    def expected_endpoints(_, contract, day, after, cutoff):
        return tuple(e for e in (START, START + timedelta(hours=1)) if after < e <= cutoff)

    repo = ReferenceRepository(factory)
    worker = build_forward_reference_worker(
        repository=repo, market_read=None, newow_reader=None,
        owner_segments=lambda *args: ("owner", "calc"), expected_endpoints=expected_endpoints,
        newow_capability_ready=lambda _: True, fusion_sources=SavedForwardFusionSources(factory),
        enabled=True, now=lambda: START + timedelta(hours=2),
    )
    inbox = ReferenceInboxRepository(factory)
    targets = [item["bootstrap"]["target_stream_id"] for item in plan["items"]]
    with factory() as db:
        targets.sort(key=lambda sid: db.get(ReferenceStream, sid).strategy_code == "newow_dual_fusion")
    for index, end in enumerate((START, START + timedelta(hours=1)), start=10):
        original = replace(event(str(index) + "-0", end=end), channel="live:bar:rb:60m")
        ingested = original.confirmed_at + timedelta(seconds=1)
        assert len(inbox.ingest(original, ingested_at=ingested).delivery_ids) == 4
        worker.source_envelope = original
        worker.source_observed_at = original.confirmed_at
        worker.raw_received_at = original.raw_received_at
        worker.inbox_ingested_at = ingested
        for target in targets:
            head = inbox.pending_head(target)
            worker.process_inbox_delivery(target, end, delivery_id=head.delivery_id)
            assert inbox.pending_head(target) is None
            checkpoint = repo.load_checkpoint(target)[1]
            assert checkpoint.computed_through == end and checkpoint.reference_state.open_trade is None
    assert service.status(plan) == result


def test_h1_boundary_rolls_back_all_four_on_activate_failure(monkeypatch, transition_engine):
    from app.reference_trading.newow_h1_boundary import NewowH1Boundary

    factory, pairs = fixture(transition_engine, current=True)
    ids = [old for old, _ in pairs]
    service = NewowH1Boundary(factory, assert_fenced=lambda: None)
    plan = service.plan(ids, recording_start=START, expires_at=START, now=NOW)
    activate = service._activate_target
    calls = []
    def fail_second(*args, **kwargs):
        calls.append(True)
        if len(calls) == 2:
            raise RepositoryConflict("INJECTED_SECOND_ACTIVATION_FAILURE")
        return activate(*args, **kwargs)

    monkeypatch.setattr(service, "_activate_target", fail_second)
    with pytest.raises(RepositoryConflict, match="INJECTED_SECOND"):
        service.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    assert service.status(plan) is None
    with factory() as db:
        assert all(db.get(ReferenceStream, sid).enabled for sid in ids)
        assert all(db.get(ReferenceStream, item["bootstrap"]["target_stream_id"]) is None
                   for item in plan["items"])
