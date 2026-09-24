"""Explicitly authorized interruption of an uncaptured forward interval."""

from __future__ import annotations

from datetime import date, datetime

from app.reference_trading.capture import ForwardCapture
from app.reference_trading.contracts import PreparedBatch
from app.reference_trading.presentation import envelope, presentation_point
from guiyi_quant.newow.product_adapters import seed_replay_state
from guiyi_quant.reference_trading import BoundaryReason, ReferenceBoundary, reduce_reference
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.htdy import HtdyForwardState
from guiyi_quant.reference_trading.subing_forward import seed_subing_forward


def capture_observation_gap(
    identity, *, revision_id: str, generation: int,
    previous_watermark: datetime | None, observed_at: datetime, reason: str,
    trading_day: date | None, endpoints: tuple[datetime, ...],
) -> ForwardCapture:
    if reason not in {"OBSERVATION_GAP", "FIRST_SEEN_NOT_PROVEN"}:
        raise ValueError("RECOVERY_REASON_INVALID")
    if previous_watermark is not None and observed_at <= previous_watermark:
        raise ValueError("RECOVERY_TIME_INVALID")
    if type(trading_day) is not date:
        raise ValueError("RECOVERY_TRADING_DAY_UNAVAILABLE")
    if not endpoints or any(
        item.tzinfo is None or item.utcoffset() is None or item > observed_at
        for item in endpoints
    ):
        raise ValueError("RECOVERY_ENDPOINTS_UNAVAILABLE")
    return ForwardCapture(
        identity.stream_id, revision_id, generation,
        f"observation-gap:{observed_at.isoformat()}", observed_at, observed_at,
        "observation_interruption", {"reason": reason,
                                     "trading_day": trading_day.isoformat()},
        {"previous_watermark": None if previous_watermark is None else previous_watermark.isoformat(),
         "recovery_policy": "interrupt_and_restart",
         "gap_endpoints": [item.isoformat() for item in endpoints]},
        "gap_recovery",
    )


def evaluate_observation_gap(token, checkpoint, evidence, *, dependency_manifest):
    capture = evidence.get("forward_capture_v1")
    if (
        not isinstance(capture, dict)
        or capture.get("eligibility") != "gap_recovery"
        or capture.get("source_kind") != "observation_interruption"
    ):
        raise ValueError("RECOVERY_CAPTURE_INVALID")
    proof = capture.get("source_proof")
    payload = capture.get("input_payload")
    stream = checkpoint.stream
    prior = checkpoint.reference_state
    if stream is None or prior is None or not isinstance(proof, dict) or not isinstance(payload, dict):
        raise ValueError("RECOVERY_CAPTURE_INVALID")
    if proof.get("recovery_policy") != "interrupt_and_restart" or payload.get("reason") not in {
        "OBSERVATION_GAP", "FIRST_SEEN_NOT_PROVEN",
    }:
        raise ValueError("RECOVERY_POLICY_INVALID")
    if not isinstance(proof.get("gap_endpoints"), list) or not proof["gap_endpoints"]:
        raise ValueError("RECOVERY_ENDPOINTS_UNAVAILABLE")
    observed = datetime.fromisoformat(capture["observed_at"])
    day = date.fromisoformat(payload["trading_day"])
    endpoints = tuple(datetime.fromisoformat(item) for item in proof["gap_endpoints"])
    if (
        observed.tzinfo is None or observed.utcoffset() is None
        or capture.get("bar_end") != observed.isoformat()
        or proof.get("previous_watermark") != (
            None if checkpoint.computed_through is None else checkpoint.computed_through.isoformat()
        )
        or checkpoint.computed_through is not None and observed <= checkpoint.computed_through
        or any(item.tzinfo is None or item > observed for item in endpoints)
    ):
        raise ValueError("RECOVERY_PROGRESS_CONFLICT")
    code = stream.strategy_code.replace("-", "_")
    if code.startswith("newow_"):
        strategy, schema = seed_replay_state(), "newow_product_replay_v1"
    elif code == "subing_reference":
        strategy, schema = seed_subing_forward(), "subing_forward_v1"
    elif code == "htdy":
        strategy = HtdyForwardState(
            stream.reference_model_version, stream.observation_policy_version,
        )
        schema = "htdy_first_seen_v1"
    else:
        raise ValueError("RECOVERY_STRATEGY_UNSUPPORTED")
    old = prior.open_trade
    boundaries = () if old is None else (ReferenceBoundary(
        stream, BoundaryReason.OBSERVATION_INTERRUPTED,
        old.physical_contract, old.owner_segment_id, old.calculation_segment_id,
        observed, day,
    ),)
    transition = reduce_reference(
        prior, boundaries=boundaries, completed_bar_end=observed,
        completed_trading_day=day,
    )
    next_checkpoint = AdapterCheckpoint(
        strategy, observed, "observation-gap:" + capture["hash"], None, None, None,
        stream, transition.state,
    )
    point = presentation_point(
        kind="boundary", trading_day=day,
        formula_versions=stream.formula_versions,
        value={"bar_end": observed, "observed_at": observed,
               "reason": "OBSERVATION_INTERRUPTED",
               "gap_code": payload["reason"]},
    )
    return PreparedBatch(
        stream.stream_id, token.revision_id,
        f"forward:{capture['source_key']}", token, dependency_manifest,
        (), (transition,), next_checkpoint, schema,
        {"forward_capture_v1": {
            "capture_id": evidence["capture_id"], "hash": capture["hash"],
            "generation": capture["generation"],
        }, "observation_gap_v1": {
            "observed_at": observed.isoformat(), "trading_day": day.isoformat(),
            "reason": payload["reason"],
        }, "presentation_v1": envelope([point])},
        observed,
    )
