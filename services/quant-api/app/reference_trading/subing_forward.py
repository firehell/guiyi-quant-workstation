"""Project one captured completed SuBing input through the shared reducer."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json

from app.reference_trading.contracts import PreparedBatch, SourceAction
from app.reference_trading.presentation import envelope, presentation_point
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.subing_forward import (
    SubingForwardState, advance_subing_forward,
)


def evaluate_subing_capture(token, checkpoint, evidence, *, dependency_manifest):
    capture = evidence.get("forward_capture_v1")
    if not isinstance(capture, dict):
        raise ValueError("SUBING_CAPTURE_CORRUPT")
    payload, proof = capture.get("input_payload"), capture.get("source_proof")
    if not isinstance(payload, dict) or not isinstance(proof, dict):
        raise ValueError("SUBING_CAPTURE_CORRUPT")
    bar = payload.get("bar")
    if not isinstance(bar, dict):
        raise ValueError("SUBING_CAPTURE_BAR_INVALID")
    if sha256(json.dumps(bar, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != proof.get("source_sha256"):
        raise ValueError("SUBING_CAPTURE_SOURCE_CONFLICT")
    stream = checkpoint.stream
    reference = checkpoint.reference_state
    if stream is None or reference is None or not isinstance(checkpoint.strategy_state, SubingForwardState):
        raise ValueError("SUBING_CHECKPOINT_INVALID")
    end = datetime.fromisoformat(bar["bar_end"])
    observed = datetime.fromisoformat(capture["observed_at"])
    if (
        end.isoformat() != capture.get("bar_end")
        or end.tzinfo is None or observed.tzinfo is None
        or observed < end
        or proof.get("previous_watermark") != (
            None if checkpoint.computed_through is None else checkpoint.computed_through.isoformat()
        )
        or proof.get("expected_endpoints") != [end.isoformat()]
    ):
        raise ValueError("SUBING_CAPTURE_PROGRESS_CONFLICT")
    day = date.fromisoformat(bar["trading_day"])
    warmup = None
    needs_warmup = (checkpoint.strategy_state.processed_count == 0
        or checkpoint.physical_contract != payload["contract"]
        or checkpoint.owner_segment_id != proof["owner_segment_id"]
        or checkpoint.calculation_segment_id != proof["calculation_segment_id"])
    if stream.observation_policy_version == "subing_physical_prefix_forward_v2" and (needs_warmup or "warmup_checkpoint" in payload):
        from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_from_json
        seeded = adapter_checkpoint_from_json(payload.get("warmup_checkpoint", ""),
            expected_stream=stream, expected_strategy_schema="subing_forward_v1")
        if (not isinstance(seeded.strategy_state, SubingForwardState)
                or seeded.reference_state.open_trade is not None
                or seeded.physical_contract != payload["contract"]
                or seeded.owner_segment_id != proof["owner_segment_id"]
                or seeded.calculation_segment_id != proof["calculation_segment_id"]
                or seeded.computed_through is not None and seeded.computed_through >= end):
            raise ValueError("SUBING_WARMUP_IDENTITY_INVALID")
        warmup = seeded.strategy_state.kernel_state
    strategy, actions, transition, display = advance_subing_forward(
        checkpoint.strategy_state, reference,
        physical_contract=payload["contract"],
        owner_segment_id=proof["owner_segment_id"],
        calculation_segment_id=proof["calculation_segment_id"],
        bar_end=end, trading_day=day, close=Decimal(bar["close"]), warmup_kernel=warmup,
        rollover_at=None if proof.get("owner_started_at") is None else datetime.fromisoformat(proof["owner_started_at"]),
    )
    next_checkpoint = AdapterCheckpoint(
        strategy, end, capture["hash"], payload["contract"],
        proof["owner_segment_id"], proof["calculation_segment_id"],
        stream, transition.state,
    )
    point = presentation_point(
        kind="signal" if display["direction"] else "indicator",
        value={**display, "observed_at": observed, "first_seen": True},
        trading_day=day, formula_versions=stream.formula_versions,
    )
    return PreparedBatch(
        stream.stream_id, token.revision_id, f"forward:{capture['source_key']}",
        token, dependency_manifest,
        tuple(SourceAction(action, observed) for action in actions),
        (transition,), next_checkpoint, "subing_forward_v1",
        {"forward_capture_v1": {
            "capture_id": evidence["capture_id"], "hash": capture["hash"],
            "generation": capture["generation"],
        }, "presentation_v1": envelope([point])},
        observed,
    )


def subing_warmup_checkpoint(identity, contract, owner_id, calculation_id, bars):
    """Warm only indicators from an authority-validated strict-before prefix."""
    from guiyi_quant.indicators.subing_ths import SubingThs15mKernel
    from guiyi_quant.reference_trading import ReferenceState
    from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_to_json
    kernel = SubingThs15mKernel()
    state = kernel.initial_state()
    last = None
    for bar in bars:
        if last is not None and bar.bar_end <= last:
            raise ValueError("SUBING_WARMUP_ORDER_INVALID")
        state, _ = kernel.step(state, float(bar.close), bar_end=bar.bar_end.isoformat())
        last = bar.bar_end
    checkpoint = AdapterCheckpoint(SubingForwardState(state, state.macd.fast.count, contract, calculation_id),
        last, None if last is None else sha256(json.dumps([str(state), last.isoformat()]).encode()).hexdigest(),
        contract, owner_id, calculation_id, identity, ReferenceState.flat(identity, recording_start=last or datetime.min.replace(tzinfo=UTC)))
    return adapter_checkpoint_to_json(checkpoint, strategy_schema="subing_forward_v1")
