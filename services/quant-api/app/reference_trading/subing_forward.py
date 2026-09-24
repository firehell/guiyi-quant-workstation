"""Project one captured completed SuBing input through the shared reducer."""

from __future__ import annotations

from datetime import date, datetime
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
    strategy, actions, transition, display = advance_subing_forward(
        checkpoint.strategy_state, reference,
        physical_contract=payload["contract"],
        owner_segment_id=proof["owner_segment_id"],
        calculation_segment_id=proof["calculation_segment_id"],
        bar_end=end, trading_day=day, close=Decimal(bar["close"]),
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
