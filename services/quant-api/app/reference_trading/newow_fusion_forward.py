"""Fuse only committed, aligned completed forward captures of both base streams."""

from __future__ import annotations

from app.reference_trading.recording_scope import LIVE_FREQUENCIES

from datetime import date
from decimal import Decimal
from hashlib import sha256
import json

from app.reference_trading.capture import ForwardCapture
from app.reference_trading.contracts import PreparedBatch, manifest_sha256
from app.reference_trading.inputs import HistoricalInputBar
from app.reference_trading.newow_fusion import (
    FusionHistoricalPayload,
    advance_fusion_step,
    decode_source_action,
    fusion_input_policy,
)
from app.reference_trading.newow_forward import _timestamp, _whole_number
from app.reference_trading.presentation import (
    _wire,
    envelope,
    presentation_point,
    require_envelope,
)
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_contracts import ProductBar, ProductFrequency
from guiyi_quant.newow.product_identity import (
    REFERENCE_MODEL_VERSION,
    futures_adaptation_version,
)
from guiyi_quant.reference_trading import (
    BoundaryReason,
    RecordingMode,
    ReferenceBoundary,
    StreamIdentity,
)


def _validated_sources(stream, dependencies):
    if not isinstance(dependencies, list) or len(dependencies) != 2:
        raise ValueError("REFERENCE_FUSION_SOURCE_NOT_READY")
    actions, captures = [], []
    policy = fusion_input_policy(stream)
    for strategy, dependency in zip(("trend", "oscillation"), dependencies):
        product_identity = build_product_identity(
            stream.product, strategy, stream.frequency, input_quality_policy=policy
        )
        expected = StreamIdentity(
            f"newow_{strategy}",
            product_identity.formula_versions,
            product_identity.profile_id,
            REFERENCE_MODEL_VERSION,
            futures_adaptation_version(stream.frequency, policy),
            stream.product,
            stream.frequency,
            "actual_dominant",
            RecordingMode.FORWARD_OBSERVATION,
            stream.observation_policy_version,
        )
        if (
            dependency.get("identity") != _wire(expected)
            or dependency.get("stream_id") != expected.stream_id
            or type(dependency.get("seq")) is not int
            or dependency["seq"] < 1
            or any(
                not dependency.get(key)
                for key in ("revision_id", "capture_id", "batch_id")
            )
        ):
            raise ValueError("REFERENCE_FUSION_SOURCE_IDENTITY_CONFLICT")
        capture = dependency.get("capture")
        if not isinstance(capture, dict):
            raise ValueError("REFERENCE_FUSION_SOURCE_NOT_READY")
        payload, proof = capture.get("input_payload"), capture.get("source_proof")
        if not isinstance(payload, dict) or not isinstance(proof, dict):
            raise ValueError("REFERENCE_FUSION_SOURCE_INPUT_CONFLICT")
        end, observed = (
            _timestamp(capture.get("bar_end")),
            _timestamp(capture.get("observed_at")),
        )
        source = (
            "completed_live" if stream.frequency in LIVE_FREQUENCIES else "canonical_completed"
        )
        if (
            capture.get("eligibility") != "completed_observation"
            or capture.get("source_kind") != source
            or end > observed
            or proof.get("frequency") != stream.frequency
            or proof.get("expected_endpoints") != [end.isoformat()]
            or payload.get("product") != stream.product
            or payload.get("input_quality_policy") != policy.value
        ):
            raise ValueError("REFERENCE_FUSION_SOURCE_INPUT_CONFLICT")
        reconstructed = ForwardCapture(
            expected.stream_id,
            dependency["revision_id"],
            capture["generation"],
            capture["source_key"],
            end,
            observed,
            source,
            payload,
            proof,
            capture["eligibility"],
        )
        if reconstructed.capture_hash != capture.get("hash"):
            raise ValueError("REFERENCE_FUSION_SOURCE_HASH_CONFLICT")
        raw = payload.get("bar")
        if (
            not isinstance(raw, dict)
            or raw.get("bar_end") != end.isoformat()
            or sha256(
                json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            != proof.get("source_sha256")
            or source == "completed_live"
            and payload.get("source_bar_sha256") != proof.get("source_sha256")
        ):
            raise ValueError("REFERENCE_FUSION_SOURCE_HASH_CONFLICT")
        source_actions = dependency.get("actions")
        if not isinstance(source_actions, list) or not all(
            isinstance(wire, dict) for wire in source_actions
        ):
            raise ValueError("REFERENCE_FUSION_SOURCE_INPUT_CONFLICT")
        for wire in source_actions:
            # observed_at is delivery metadata, outside StrategyAction's frozen identity.
            action = decode_source_action(
                {k: v for k, v in wire.items() if k != "observed_at"}, product_identity
            )
            if (
                action.bar_end != end
                or action.trading_day.isoformat() != raw["trading_day"]
                or (
                    action.physical_contract,
                    action.segment_id,
                    action.calculation_segment_id,
                )
                != (
                    payload["contract"],
                    proof["owner_segment_id"],
                    proof["calculation_segment_id"],
                )
            ):
                raise ValueError("REFERENCE_FUSION_SOURCE_INPUT_CONFLICT")
            actions.append(action)
        captures.append(capture)
    first, second = captures
    if (
        first["bar_end"] != second["bar_end"]
        or first["source_kind"] != second["source_kind"]
        or first["input_payload"] != second["input_payload"]
        or first["source_proof"] != second["source_proof"]
    ):
        raise ValueError("REFERENCE_FUSION_SOURCE_INPUT_CONFLICT")
    return first, tuple(actions), max(_timestamp(c["observed_at"]) for c in captures)


def build_fusion_capture(
    identity, *, revision_id, generation, after, now, dependencies
):
    if (
        identity.strategy_code != "newow_dual_fusion"
        or identity.recording_mode is not RecordingMode.FORWARD_OBSERVATION
    ):
        raise ValueError("REFERENCE_FUSION_STREAM_IDENTITY_CONFLICT")
    base, _actions, observed = _validated_sources(identity, dependencies)
    end = _timestamp(base["bar_end"])
    if after is not None and end <= after or observed > now:
        raise ValueError("REFERENCE_FUSION_PROGRESS_CONFLICT")
    return ForwardCapture(
        identity.stream_id,
        revision_id,
        generation,
        base["source_key"],
        end,
        observed,
        "completed_fusion_sources",
        {"sources": dependencies},
        {
            "previous_watermark": None if after is None else after.isoformat(),
            "dependency_sha256": manifest_sha256(dependencies),
        },
        "completed_fusion",
    )


def evaluate_fusion_capture(token, checkpoint, evidence, *, dependency_manifest):
    capture = evidence.get("forward_capture_v1")
    stream = checkpoint.stream
    if (
        not isinstance(capture, dict)
        or capture.get("source_kind") != "completed_fusion_sources"
        or capture.get("eligibility") != "completed_fusion"
        or stream is None
    ):
        raise ValueError("REFERENCE_FUSION_CAPTURE_INVALID")
    dependencies = capture["input_payload"].get("sources")
    base, actions, observed = _validated_sources(stream, dependencies)
    end = _timestamp(base["bar_end"])
    if (
        capture["source_proof"].get("dependency_sha256")
        != manifest_sha256(dependencies)
        or capture["bar_end"] != base["bar_end"]
        or _timestamp(capture["observed_at"]) != observed
        or checkpoint.computed_through is not None
        and end <= checkpoint.computed_through
        or capture["source_proof"].get("previous_watermark")
        != (
            None
            if checkpoint.computed_through is None
            else checkpoint.computed_through.isoformat()
        )
    ):
        raise ValueError("REFERENCE_FUSION_PROGRESS_CONFLICT")
    payload, proof = base["input_payload"], base["source_proof"]
    raw = payload["bar"]
    contract, owner, calculation = (
        payload["contract"],
        proof["owner_segment_id"],
        proof["calculation_segment_id"],
    )
    day = date.fromisoformat(raw["trading_day"])
    bar = ProductBar(
        NewowDailyBar(
            stream.product,
            contract,
            owner,
            day,
            end,
            Decimal(raw["open"]),
            Decimal(raw["high"]),
            Decimal(raw["low"]),
            Decimal(raw["close"]),
            _whole_number(raw["volume"]),
            None
            if raw["open_interest"] is None
            else _whole_number(raw["open_interest"]),
            payload["source_identity"],
            True,
            True,
        ),
        ProductFrequency(stream.frequency),
        calculation_segment_id=calculation,
        source_bar_sha256=payload["source_bar_sha256"],
    )
    boundaries = ()
    prior = checkpoint.reference_state
    if prior is not None and prior.open_trade is not None:
        old = prior.open_trade
        if (
            old.physical_contract,
            old.owner_segment_id,
            old.calculation_segment_id,
        ) != (contract, owner, calculation):
            boundaries = (
                ReferenceBoundary(
                    stream,
                    (
                        BoundaryReason.ROLLOVER
                        if (old.physical_contract, old.owner_segment_id)
                        != (contract, owner)
                        else BoundaryReason.DATA_INTERRUPTED
                    ),
                    old.physical_contract,
                    old.owner_segment_id,
                    old.calculation_segment_id,
                    end,
                    day,
                ),
            )
    item = HistoricalInputBar(
        end,
        day,
        contract,
        owner,
        calculation,
        bar.bar.close,
        capture["source_proof"]["dependency_sha256"],
        FusionHistoricalPayload(bar, actions),
        boundaries=boundaries,
    )
    points = []
    next_checkpoint, sources, transition = advance_fusion_step(
        stream, checkpoint, item, points, observed_at=observed
    )
    for point in points:
        point["value"]["observed_at"] = observed.isoformat()
        if point["kind"] == "indicator":
            point["value"]["availability"] = {
                "status": "ready"
                if all(
                    str(d.get("availability")).lower() == "ready" for d in dependencies
                )
                else "warming",
                "reason_code": None
                if all(
                    str(d.get("availability")).lower() == "ready" for d in dependencies
                )
                else "SOURCE_WARMING",
            }
    points.append(
        presentation_point(
            kind="availability",
            trading_day=day,
            formula_versions=stream.formula_versions,
            value={
                "bar_end": end,
                "observed_at": observed,
                "physical_contract": contract,
                "segment_id": owner,
                "calculation_segment_id": calculation,
                "status": "READY"
                if all(
                    str(d.get("availability")).lower() == "ready" for d in dependencies
                )
                else "WARMING",
                "main_state": "HOLD"
                if next_checkpoint.reference_state.open_trade
                else "FLAT",
            },
        )
    )
    return PreparedBatch(
        stream.stream_id,
        token.revision_id,
        f"forward:{capture['source_key']}",
        token,
        dependency_manifest,
        sources,
        (transition,),
        next_checkpoint,
        "newow_dual_fusion_reference_v1",
        {
            "forward_capture_v1": {
                "capture_id": evidence["capture_id"],
                "hash": capture["hash"],
                "generation": capture["generation"],
            },
            "presentation_v1": envelope(points),
        },
        observed,
    )


class SavedForwardFusionSources:
    """Bounded database read of consumed captures; historical actions are excluded."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def __call__(self, identity, *, revision_id, generation, after, now):
        from sqlalchemy import select
        from app.reference_trading.models import ReferenceBatch, ReferenceStream
        from app.reference_trading.repository import _identity_from_row, _aware
        from app.reference_trading.forward_inputs import ForwardInputUnavailable

        dependencies = []
        with self._session_factory() as session:
            for strategy in ("trend", "oscillation"):
                streams = session.scalars(
                    select(ReferenceStream).where(
                        ReferenceStream.strategy_code == f"newow_{strategy}",
                        ReferenceStream.product == identity.product,
                        ReferenceStream.frequency == identity.frequency,
                        ReferenceStream.recording_mode == "forward_observation",
                        ReferenceStream.enabled.is_(True),
                    )
                ).all()
                if len(streams) != 1:
                    raise ForwardInputUnavailable("REFERENCE_FUSION_SOURCE_NOT_READY")
                stream = streams[0]
                from sqlalchemy.orm import aliased

                committed = aliased(ReferenceBatch)
                query = (
                    select(ReferenceBatch, committed)
                    .join(
                        committed,
                        committed.batch_id == ReferenceBatch.consumed_by_batch_id,
                    )
                    .where(
                        ReferenceBatch.stream_id == stream.stream_id,
                        ReferenceBatch.revision_id == stream.active_revision_id,
                        ReferenceBatch.kind == "capture",
                        ReferenceBatch.outcome == "consumed",
                        committed.computed_through.is_not(None),
                        committed.computed_through <= now,
                        ReferenceBatch.observed_at <= now,
                    )
                )
                if after is not None:
                    query = query.where(committed.computed_through > after)
                pair = session.execute(
                    query.order_by(
                        committed.computed_through,
                        committed.seq,
                        ReferenceBatch.batch_id,
                    ).limit(1)
                ).first()
                if pair is None:
                    dependencies.append(None)
                    continue
                row, calculation = pair
                base = row.source_evidence["forward_capture_v1"]
                if (
                    calculation is None
                    or calculation.kind != "calculation"
                    or calculation.outcome != "committed"
                    or calculation.stream_id != stream.stream_id
                    or calculation.revision_id != stream.active_revision_id
                    or _aware(calculation.computed_through)
                    != _timestamp(base["bar_end"])
                    or base["generation"] != stream.activation_generation
                    or calculation.source_evidence.get("forward_capture_v1")
                    != {
                        "capture_id": row.batch_id,
                        "hash": base["hash"],
                        "generation": base["generation"],
                    }
                ):
                    raise ForwardInputUnavailable("REFERENCE_FUSION_SOURCE_NOT_READY")
                points = require_envelope(
                    calculation.source_evidence.get("presentation_v1")
                )
                available = [
                    p["value"].get("status")
                    for p in points
                    if p.get("kind") == "availability"
                ]
                dependencies.append(
                    {
                        "identity": _wire(_identity_from_row(stream)),
                        "stream_id": stream.stream_id,
                        "revision_id": stream.active_revision_id,
                        "capture_id": row.batch_id,
                        "batch_id": calculation.batch_id,
                        "seq": calculation.seq,
                        "capture": base,
                        "actions": [
                            p["value"] for p in points if p.get("kind") == "action"
                        ],
                        "availability": available[-1] if available else "WARMING",
                    }
                )
        gaps = [
            dependency
            for dependency in dependencies
            if dependency is not None
            and dependency["capture"].get("eligibility") == "gap_recovery"
        ]
        if gaps:
            # A single interrupted source invalidates the fusion's observed entry.
            # Propagate the earliest durable boundary; later boundaries advance on
            # their own cursor rather than being discarded or merged into a Bar.
            from app.reference_trading.recovery import capture_observation_gap

            for dependency in gaps:
                base = dependency["capture"]
                strategy = dependency["identity"]["strategy_code"].removeprefix(
                    "newow_"
                )
                if strategy not in {"trend", "oscillation"}:
                    raise ValueError("REFERENCE_FUSION_SOURCE_IDENTITY_CONFLICT")
                product = build_product_identity(
                    identity.product,
                    strategy,
                    identity.frequency,
                    input_quality_policy=fusion_input_policy(identity),
                )
                expected = StreamIdentity(
                    f"newow_{strategy}",
                    product.formula_versions,
                    product.profile_id,
                    REFERENCE_MODEL_VERSION,
                    identity.futures_adaptation_version,
                    identity.product,
                    identity.frequency,
                    identity.series_kind,
                    RecordingMode.FORWARD_OBSERVATION,
                    identity.observation_policy_version,
                )
                if (
                    dependency["identity"] != _wire(expected)
                    or dependency["stream_id"] != expected.stream_id
                ):
                    raise ValueError("REFERENCE_FUSION_SOURCE_IDENTITY_CONFLICT")
                captured = ForwardCapture(
                    dependency["stream_id"],
                    dependency["revision_id"],
                    base["generation"],
                    base["source_key"],
                    _timestamp(base["bar_end"]),
                    _timestamp(base["observed_at"]),
                    base["source_kind"],
                    base["input_payload"],
                    base["source_proof"],
                    base["eligibility"],
                )
                if (
                    captured.capture_hash != base["hash"]
                    or base["source_kind"] != "observation_interruption"
                ):
                    raise ValueError("REFERENCE_FUSION_SOURCE_HASH_CONFLICT")
            selected = min(
                gaps,
                key=lambda dependency: _timestamp(dependency["capture"]["bar_end"]),
            )
            base = selected["capture"]
            gap = capture_observation_gap(
                identity,
                revision_id=revision_id,
                generation=generation,
                previous_watermark=after,
                observed_at=_timestamp(base["observed_at"]),
                reason=base["input_payload"]["reason"],
                trading_day=date.fromisoformat(base["input_payload"]["trading_day"]),
                endpoints=tuple(
                    _timestamp(end) for end in base["source_proof"]["gap_endpoints"]
                ),
            )
            from dataclasses import replace

            return replace(
                gap,
                source_proof={
                    **gap.source_proof,
                    "fusion_source_dependencies": [
                        dependency
                        for dependency in gaps
                        if dependency["capture"]["bar_end"] == base["bar_end"]
                    ],
                },
            )
        if any(dependency is None for dependency in dependencies):
            return None
        if (
            dependencies[0]["capture"]["bar_end"]
            != dependencies[1]["capture"]["bar_end"]
        ):
            raise ForwardInputUnavailable("REFERENCE_FUSION_DEPENDENCY_LAG")
        return build_fusion_capture(
            identity,
            revision_id=revision_id,
            generation=generation,
            after=after,
            now=now,
            dependencies=dependencies,
        )
