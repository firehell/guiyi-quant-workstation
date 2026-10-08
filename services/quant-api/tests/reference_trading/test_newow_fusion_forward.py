from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json

import pytest

from app.reference_trading.contracts import CheckpointToken
from app.reference_trading.newow_fusion_forward import (
    build_fusion_capture,
    evaluate_fusion_capture,
)
from app.reference_trading.presentation import _wire
from guiyi_quant.newow.fusion_reference import (
    FusionReferenceReplayState,
    build_fusion_stream_identity,
)
from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.reference_trading import RecordingMode, ReferenceState
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from test_newow_forward import _capture


def sources(frequency="1d"):
    from newow.product_fixtures import ProductCases
    from guiyi_quant.newow.product_identity import (
        REFERENCE_MODEL_VERSION,
        futures_adaptation_version,
    )
    from guiyi_quant.reference_trading import StreamIdentity

    case = ProductCases().closed(frequency=frequency)
    bars = case.bars
    dependencies = []
    for strategy in ("trend", "oscillation"):
        identity = build_product_identity("rb", strategy, frequency)
        stream = StreamIdentity(
            f"newow_{strategy}",
            identity.formula_versions,
            identity.profile_id,
            REFERENCE_MODEL_VERSION,
            futures_adaptation_version(frequency),
            "rb",
            frequency,
            "actual_dominant",
            RecordingMode.FORWARD_OBSERVATION,
            "completed_observation_v1",
        )
        capture = _capture(stream, bars[0])
        if frequency == "60m":
            capture = replace(capture, source_kind="completed_live")
        action = replace(case.entry, identity=identity)
        dependencies.append(
            {
                "identity": _wire(stream),
                "stream_id": stream.stream_id,
                "revision_id": "revision",
                "capture_id": strategy + "-capture",
                "batch_id": strategy + "-calculation",
                "seq": 2,
                "capture": capture.evidence()["forward_capture_v1"],
                "actions": [_wire(action)] if strategy == "trend" else [],
                "availability": "READY",
            }
        )
    return case, dependencies


@pytest.mark.parametrize("frequency", ("1d", "1w", "60m"))
def test_fusion_forward_requires_two_aligned_completed_sources(frequency):
    case, dependencies = sources(frequency)
    stream = build_fusion_stream_identity(
        "rb",
        frequency,
        recording_mode="forward_observation",
        observation_policy_version="completed_observation_v1",
    )
    capture = build_fusion_capture(
        stream,
        revision_id="fusion-revision",
        generation=1,
        after=None,
        now=case.bars[0].bar.bar_end + timedelta(minutes=1),
        dependencies=dependencies,
    )
    checkpoint = AdapterCheckpoint(
        FusionReferenceReplayState(),
        stream=stream,
        reference_state=ReferenceState.flat(
            stream, recording_start=case.bars[0].bar.bar_end
        ),
    )
    token = CheckpointToken(
        stream.stream_id, "fusion-revision", 1, 1, sha256(b"seed").hexdigest()
    )
    prepared = evaluate_fusion_capture(
        token,
        checkpoint,
        {**capture.evidence(), "capture_id": "fusion-capture"},
        dependency_manifest={"source": "fixture"},
    )
    assert prepared.checkpoint.computed_through == case.bars[0].bar.bar_end
    assert prepared.checkpoint.reference_state.open_trade is not None
    assert prepared.source_actions[0].observed_at == capture.observed_at
    assert prepared.strategy_schema == "newow_dual_fusion_reference_v1"


@pytest.mark.parametrize(
    "field", ("owner_segment_id", "source_sha256", "calculation_segment_id")
)
def test_fusion_rejects_conflicting_base_proof(field):
    case, dependencies = sources()
    dependencies[1]["capture"]["source_proof"][field] = "conflict"
    stream = build_fusion_stream_identity(
        "rb",
        "1d",
        recording_mode="forward_observation",
        observation_policy_version="completed_observation_v1",
    )
    with pytest.raises(ValueError, match="FUSION"):
        build_fusion_capture(
            stream,
            revision_id="revision",
            generation=1,
            after=None,
            now=case.bars[0].bar.bar_end + timedelta(minutes=1),
            dependencies=dependencies,
        )


def test_saved_forward_sources_wait_for_both_durable_calculations_and_reject_broken_link():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.base import Base
    from app.reference_trading.activation import ForwardActivation
    from app.reference_trading.contracts import SeedChunk, manifest_sha256
    from app.reference_trading.forward_service import ForwardReferenceService
    from app.reference_trading.newow_forward import evaluate_newow_capture
    from app.reference_trading.newow_fusion_forward import SavedForwardFusionSources
    from app.reference_trading.forward_inputs import ForwardInputUnavailable
    from app.reference_trading.models import ReferenceBatch
    from app.reference_trading.repository import ReferenceRepository
    from guiyi_quant.newow.product_adapters import seed_replay_state
    from guiyi_quant.reference_trading import StreamIdentity

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repo = ReferenceRepository(factory)
    case, dependencies = sources()
    start = case.bars[0].bar.bar_end
    now = start + timedelta(minutes=1)
    fusion = build_fusion_stream_identity(
        "rb",
        "1d",
        recording_mode="forward_observation",
        observation_policy_version="completed_observation_v1",
    )
    loader = SavedForwardFusionSources(factory)
    captured_ids = []
    for dep in dependencies:
        identity_wire = dict(dep["identity"])
        identity_wire["formula_versions"] = tuple(identity_wire["formula_versions"])
        stream = StreamIdentity(**identity_wire)
        stored = repo.ensure_stream(stream)
        manifest = {"source": "fixture"}
        revision = repo.create_revision(
            stream.stream_id, stored.row_version, manifest_sha256(manifest)
        )
        checkpoint = AdapterCheckpoint(
            seed_replay_state(),
            stream=stream,
            reference_state=ReferenceState.flat(stream, recording_start=start),
        )
        repo.stage_seed_chunk(
            revision, SeedChunk("seed", 0, 1, sha256(b"seed").hexdigest(), "seed")
        )
        repo.seal_seed(revision, manifest, checkpoint, "newow_product_replay_v1")
        activation = ForwardActivation(factory)
        plan = activation.plan(
            stream.stream_id,
            revision,
            host="test",
            environment="isolated",
            recording_start=start,
            expires_at=now,
            budget={"max_pending": 32},
        )
        activation.apply(
            plan, expected_plan_hash=plan.plan_hash, now=start - timedelta(seconds=1)
        )
        base_capture = _capture(stream, case.bars[0])
        base_capture = replace(base_capture, revision_id=revision)
        captured_ids.append(repo.capture_forward(base_capture))
        service = ForwardReferenceService(
            repo,
            lambda token, cp, evidence: evaluate_newow_capture(
                token, cp, evidence, dependency_manifest=manifest
            ),
        )
        if len(captured_ids) == 2:
            # Pending source input is insufficient even though both streams exist.
            assert (
                loader(fusion, revision_id="fusion", generation=1, after=None, now=now)
                is None
            )
        service.process_pending(stream.stream_id)
    capture = loader(fusion, revision_id="fusion", generation=1, after=None, now=now)
    assert capture.bar_end == start
    assert (
        loader(fusion, revision_id="fusion", generation=1, after=start, now=now) is None
    )
    with factory() as session, session.begin():
        consumed = session.get(ReferenceBatch, captured_ids[0])
        committed = session.get(ReferenceBatch, consumed.consumed_by_batch_id)
        committed.source_evidence = {
            **committed.source_evidence,
            "forward_capture_v1": {"hash": "wrong"},
        }
    with pytest.raises(
        ForwardInputUnavailable, match="REFERENCE_FUSION_SOURCE_NOT_READY"
    ):
        loader(fusion, revision_id="fusion", generation=1, after=None, now=now)


def test_fusion_forward_same_bar_clear_then_build_and_checkpoint_restart():
    from guiyi_quant.reference_trading import ActionKind, StreamIdentity
    from guiyi_quant.reference_trading.strategy_checkpoint import (
        adapter_checkpoint_to_json,
        adapter_checkpoint_from_json,
    )

    case, dependencies = sources()
    stream = build_fusion_stream_identity(
        "rb",
        "1d",
        recording_mode="forward_observation",
        observation_policy_version="completed_observation_v1",
    )
    checkpoint = AdapterCheckpoint(
        FusionReferenceReplayState(),
        stream=stream,
        reference_state=ReferenceState.flat(
            stream, recording_start=case.bars[0].bar.bar_end
        ),
    )
    token = CheckpointToken(
        stream.stream_id, "fusion", 1, 1, sha256(b"seed").hexdigest()
    )
    first_capture = build_fusion_capture(
        stream,
        revision_id="fusion",
        generation=1,
        after=None,
        now=case.bars[0].bar.bar_end + timedelta(minutes=1),
        dependencies=dependencies,
    )
    first = evaluate_fusion_capture(
        token,
        checkpoint,
        {**first_capture.evidence(), "capture_id": "first"},
        dependency_manifest={"source": "fixture"},
    )
    restored = adapter_checkpoint_from_json(
        adapter_checkpoint_to_json(
            first.checkpoint, strategy_schema=first.strategy_schema
        ),
        expected_stream=stream,
        expected_strategy_schema=first.strategy_schema,
    )
    second_bar = case.bars[1]
    for dep in dependencies:
        wire = dict(dep["identity"])
        wire["formula_versions"] = tuple(wire["formula_versions"])
        base_stream = StreamIdentity(**wire)
        capture = _capture(base_stream, second_bar)
        capture = replace(
            capture,
            source_proof={
                **capture.source_proof,
                "previous_watermark": case.bars[0].bar.bar_end.isoformat(),
            },
        )
        dep["capture"] = capture.evidence()["forward_capture_v1"]
        product_identity = build_product_identity(
            "rb", base_stream.strategy_code.removeprefix("newow_"), "1d"
        )
        action = (
            replace(case.exit, identity=product_identity)
            if product_identity.strategy.value == "trend"
            else replace(
                case.entry,
                identity=product_identity,
                bar_end=second_bar.bar.bar_end,
                trading_day=second_bar.bar.trading_day,
                reference_price=second_bar.bar.close,
            )
        )
        dep["actions"] = [_wire(action)]
        dep["seq"] = 3
    second_capture = build_fusion_capture(
        stream,
        revision_id="fusion",
        generation=1,
        after=first.checkpoint.computed_through,
        now=second_bar.bar.bar_end + timedelta(minutes=1),
        dependencies=dependencies,
    )
    second = evaluate_fusion_capture(
        token,
        restored,
        {**second_capture.evidence(), "capture_id": "second"},
        dependency_manifest={"source": "fixture"},
    )
    assert [action.action.kind for action in second.source_actions] == [
        ActionKind.CLOSE,
        ActionKind.OPEN_LONG,
    ]
    assert (
        second.checkpoint.reference_state.open_trade.entry_bar_end
        == second_bar.bar.bar_end
    )


def _backlog_database(count, *, gap_offsets=(), frequency="1d"):
    """Actual stored capture/calculation pairs with delayed identical first-seen."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.base import Base
    from app.reference_trading.models import (
        ReferenceBatch,
        ReferenceRevision,
        ReferenceStream,
    )
    from guiyi_quant.reference_trading import StreamIdentity
    from app.reference_trading.capture import ForwardCapture
    from app.reference_trading.presentation import envelope

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    case, deps = sources(frequency)
    start = case.bars[0].bar.bar_end
    observed = start + timedelta(days=600)
    fusion = build_fusion_stream_identity(
        "rb",
        "1d",
        recording_mode="forward_observation",
        observation_policy_version="completed_observation_v1",
    )
    with factory() as session, session.begin():
        for strategy, dep in enumerate(deps):
            wire = dep["identity"]
            row = ReferenceStream(
                stream_id=dep["stream_id"],
                identity_hash=str(strategy) * 64,
                **wire,
                enabled=True,
                active_revision_id=f"revision-{strategy}",
                latest_seq=count + 1,
                row_version=1,
                health="READY",
                activation_generation=1,
                recording_start=start,
            )
            session.add(row)
            session.add(
                ReferenceRevision(
                    stream_id=row.stream_id,
                    revision_id=row.active_revision_id,
                    status="active",
                    dependency_digest="0" * 64,
                    last_seq=count + 1,
                )
            )
            for i in range(count):
                end = start + timedelta(days=i)
                raw_capture = dep["capture"]
                payload = {
                    **raw_capture["input_payload"],
                    "bar": {
                        **raw_capture["input_payload"]["bar"],
                        "bar_end": end.isoformat(),
                        "trading_day": end.date().isoformat(),
                    },
                }
                proof = {
                    **raw_capture["source_proof"],
                    "expected_endpoints": [end.isoformat()],
                    "source_sha256": sha256(
                        json.dumps(
                            payload["bar"], sort_keys=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest(),
                }
                capture = ForwardCapture(
                    row.stream_id,
                    row.active_revision_id,
                    1,
                    f"bar:{i}",
                    end,
                    observed,
                    "canonical_completed",
                    payload,
                    proof,
                    "completed_observation",
                )
                if (strategy, i) in gap_offsets:
                    from app.reference_trading.recovery import capture_observation_gap

                    # Recovery Bar is observation boundary, separate from source Bar endpoints.
                    capture = capture_observation_gap(
                        StreamIdentity(
                            **{
                                **wire,
                                "formula_versions": tuple(wire["formula_versions"]),
                            }
                        ),
                        revision_id=row.active_revision_id,
                        generation=1,
                        previous_watermark=None,
                        observed_at=end,
                        reason="OBSERVATION_GAP",
                        trading_day=end.date(),
                        endpoints=(end,),
                    )
                cap_id, calc_id = f"cap-{strategy}-{i:04d}", f"calc-{strategy}-{i:04d}"
                common = dict(
                    stream_id=row.stream_id,
                    revision_id=row.active_revision_id,
                    payload_hash=capture.capture_hash,
                    expected_seq=i + 1,
                    dependency_manifest={},
                    projected_action_pks=[],
                    diagnostics=[],
                    processed_at=observed,
                )
                session.add(
                    ReferenceBatch(
                        batch_id=cap_id,
                        batch_key=f"capture:{i}",
                        kind="capture",
                        outcome="consumed",
                        source_evidence=capture.evidence(),
                        observed_at=capture.observed_at,
                        consumed_by_batch_id=calc_id,
                        **common,
                    )
                )
                session.add(
                    ReferenceBatch(
                        batch_id=calc_id,
                        batch_key=f"forward:{i}",
                        kind="calculation",
                        outcome="committed",
                        seq=i + 2,
                        computed_through=capture.bar_end,
                        source_evidence={
                            "forward_capture_v1": {
                                "capture_id": cap_id,
                                "hash": capture.capture_hash,
                                "generation": 1,
                            },
                            "presentation_v1": envelope([]),
                        },
                        **common,
                    )
                )
    return factory, fusion, start, observed


@pytest.mark.parametrize("count", (257, 512))
def test_delayed_same_observed_backlog_advances_by_true_bar_cursor_after_restart(count):
    from app.reference_trading.newow_fusion_forward import SavedForwardFusionSources

    factory, stream, start, now = _backlog_database(count)
    loader = SavedForwardFusionSources(factory)
    # Simulate persisted watermarks before/after the former 256 row ceiling.
    for i in (254, 255, 256, count - 1):
        loader = SavedForwardFusionSources(factory)
        capture = loader(
            stream,
            revision_id="fusion",
            generation=1,
            after=start + timedelta(days=i - 1),
            now=now,
        )
        assert capture.bar_end == start + timedelta(days=i)


@pytest.mark.parametrize("gap_offsets", (((0, 1),), ((0, 1), (1, 1)), ((0, 1), (1, 2))))
def test_single_and_two_source_interruption_propagate_without_skipping(gap_offsets):
    from app.reference_trading.newow_fusion_forward import SavedForwardFusionSources

    factory, stream, start, now = _backlog_database(4, gap_offsets=gap_offsets)
    capture = SavedForwardFusionSources(factory)(
        stream, revision_id="fusion", generation=1, after=start, now=now
    )
    assert capture.eligibility == "gap_recovery"
    assert capture.bar_end == start + timedelta(days=1)


@pytest.mark.parametrize("gap_offsets", (((0, 1),), ((0, 1), (1, 1)), ((0, 1), (1, 2))))
def test_fusion_gap_interrupts_old_open_restores_fusion_checkpoint_and_resumes_common_bar(
    gap_offsets,
):
    from decimal import Decimal
    from app.reference_trading.newow_fusion_forward import SavedForwardFusionSources
    from app.reference_trading.recovery import evaluate_observation_gap
    from guiyi_quant.reference_trading import (
        ActionKind,
        ReferenceAction,
        reduce_reference,
    )
    from guiyi_quant.reference_trading.strategy_checkpoint import (
        adapter_checkpoint_to_json,
        adapter_checkpoint_from_json,
    )

    factory, stream, start, now = _backlog_database(4, gap_offsets=gap_offsets)
    old_entry = ReferenceAction(
        stream,
        "old-entry",
        "RB2610",
        "old-owner",
        "old-calc",
        start,
        start.date(),
        0,
        ActionKind.OPEN_LONG,
        Decimal("100"),
    )
    prior = reduce_reference(
        ReferenceState.flat(stream, recording_start=start), actions=(old_entry,)
    ).state
    checkpoint = AdapterCheckpoint(
        FusionReferenceReplayState(),
        computed_through=start,
        stream=stream,
        reference_state=prior,
    )
    token = CheckpointToken(
        stream.stream_id, "fusion", 1, 1, sha256(b"seed").hexdigest()
    )
    boundary_count = 2 if len({offset for _strategy, offset in gap_offsets}) == 2 else 1
    for boundary in range(boundary_count):
        capture = SavedForwardFusionSources(factory)(
            stream,
            revision_id="fusion",
            generation=1,
            after=checkpoint.computed_through,
            now=now,
        )
        prepared = evaluate_observation_gap(
            token,
            checkpoint,
            {**capture.evidence(), "capture_id": f"gap-{boundary}"},
            dependency_manifest={"source": "fixture"},
        )
        assert isinstance(
            prepared.checkpoint.strategy_state, FusionReferenceReplayState
        )
        assert prepared.strategy_schema == "newow_dual_fusion_reference_v1"
        if boundary == 0:
            assert (
                prepared.transitions[0].changed_trades[0].status.value
                == "OBSERVATION_INTERRUPTED"
            )
        checkpoint = adapter_checkpoint_from_json(
            adapter_checkpoint_to_json(
                prepared.checkpoint, strategy_schema=prepared.strategy_schema
            ),
            expected_stream=stream,
            expected_strategy_schema=prepared.strategy_schema,
        )
        assert checkpoint.reference_state.open_trade is None
    next_capture = SavedForwardFusionSources(factory)(
        stream,
        revision_id="fusion",
        generation=1,
        after=checkpoint.computed_through,
        now=now,
    )
    assert next_capture.eligibility == "completed_fusion"
    completed = evaluate_fusion_capture(
        token,
        checkpoint,
        {**next_capture.evidence(), "capture_id": "next-common"},
        dependency_manifest={"source": "fixture"},
    )
    assert completed.checkpoint.computed_through == start + timedelta(
        days=boundary_count + 1
    )
    assert completed.checkpoint.reference_state.open_trade is None
