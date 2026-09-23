"""Project one durably captured Newow completed observation."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json

from app.reference_trading.contracts import PreparedBatch, SourceAction
from app.reference_trading.inputs import HistoricalInputBar
from app.reference_trading.presentation import envelope, presentation_point
from app.reference_trading.service import NewowHistoricalPayload, _newow_step
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_adapters import (
    ProductReplayState, build_product_identity, replay_step, seed_replay_state,
)
from guiyi_quant.newow.product_contracts import ProductBar, ProductFrequency, ProductStrategy
from guiyi_quant.newow.product_identity import InputQualityPolicy
from guiyi_quant.reference_trading import (
    BoundaryReason, CompletedReferenceBar, ReferenceBoundary, reduce_reference,
)
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint, strategy_input_fingerprint


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("NEWOW_CAPTURE_CORRUPT")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("NEWOW_CAPTURE_TIME_INVALID")
    return parsed


def _whole_number(value: object) -> int:
    """Parquet Decimal scale must not change a valid integral market quantity."""
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("NEWOW_CAPTURE_BAR_INVALID") from exc
    if not parsed.is_finite() or parsed != parsed.to_integral_value():
        raise ValueError("NEWOW_CAPTURE_BAR_INVALID")
    return int(parsed)


def evaluate_newow_capture(token, checkpoint, evidence, *, dependency_manifest):
    capture = evidence.get("forward_capture_v1")
    if not isinstance(capture, dict) or capture.get("eligibility") != "completed_observation":
        raise ValueError("NEWOW_CAPTURE_INELIGIBLE")
    payload, proof = capture.get("input_payload"), capture.get("source_proof")
    if not isinstance(payload, dict) or not isinstance(proof, dict):
        raise ValueError("NEWOW_CAPTURE_CORRUPT")
    raw = payload.get("bar")
    if not isinstance(raw, dict) or set(raw) not in ({
        "bar_end", "trading_day", "open", "high", "low", "close",
        "volume", "open_interest",
    }, {
        "bar_end", "trading_day", "open", "high", "low", "close",
        "volume", "turnover", "open_interest",
    }):
        raise ValueError("NEWOW_CAPTURE_BAR_INVALID")
    if sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != proof.get("source_sha256"):
        raise ValueError("NEWOW_CAPTURE_SOURCE_CONFLICT")
    stream = checkpoint.stream
    prior = checkpoint.reference_state
    if stream is None or prior is None or not isinstance(checkpoint.strategy_state, ProductReplayState):
        raise ValueError("NEWOW_CHECKPOINT_INVALID")
    code = stream.strategy_code.replace("-", "_")
    if not code.startswith("newow_"):
        raise ValueError("NEWOW_CAPTURE_IDENTITY_CONFLICT")
    frequency = ProductFrequency(stream.frequency)
    strategy = ProductStrategy(code.removeprefix("newow_"))
    identity = build_product_identity(
        stream.product, strategy, frequency,
        input_quality_policy=InputQualityPolicy(payload["input_quality_policy"]),
    )
    if (
        identity.formula_versions != stream.formula_versions
        or identity.profile_id != stream.profile_id
        or payload.get("product") != stream.product
        or proof.get("frequency") != stream.frequency
    ):
        raise ValueError("NEWOW_CAPTURE_IDENTITY_CONFLICT")
    end = _timestamp(raw.get("bar_end"))
    observed = _timestamp(capture.get("observed_at"))
    if (
        end != _timestamp(capture.get("bar_end")) or end > observed
        or checkpoint.computed_through is not None and end <= checkpoint.computed_through
        or proof.get("previous_watermark") != (
            None if checkpoint.computed_through is None else checkpoint.computed_through.isoformat()
        )
        or proof.get("expected_endpoints") != [end.isoformat()]
        or capture.get("source_kind") not in {"completed_live", "canonical_completed"}
        or frequency is ProductFrequency.HOURLY and capture.get("source_kind") != "completed_live"
        or frequency in {ProductFrequency.DAILY, ProductFrequency.WEEKLY}
        and capture.get("source_kind") != "canonical_completed"
    ):
        raise ValueError("NEWOW_CAPTURE_PROGRESS_CONFLICT")
    day = date.fromisoformat(raw["trading_day"])
    contract = payload["contract"]
    owner = proof["owner_segment_id"]
    calculation = proof["calculation_segment_id"]
    source_sha = payload["source_bar_sha256"]
    if (
        not isinstance(source_sha, str) or len(source_sha) != 64
        or any(char not in "0123456789abcdef" for char in source_sha)
        or not isinstance(payload.get("source_identity"), str)
        or not payload["source_identity"]
    ):
        raise ValueError("NEWOW_CAPTURE_SOURCE_CONFLICT")
    if capture["source_kind"] == "completed_live" and source_sha != proof["source_sha256"]:
        raise ValueError("NEWOW_CAPTURE_SOURCE_CONFLICT")
    product_bar = ProductBar(
        NewowDailyBar(
            stream.product, contract, owner, day, end,
            Decimal(raw["open"]), Decimal(raw["high"]),
            Decimal(raw["low"]), Decimal(raw["close"]), _whole_number(raw["volume"]),
            None if raw["open_interest"] is None else _whole_number(raw["open_interest"]),
            payload["source_identity"], True, True,
        ), frequency, calculation_segment_id=calculation,
        source_bar_sha256=source_sha,
    )
    fingerprint = strategy_input_fingerprint({
        "source_bar_sha256": source_sha, "bar": raw,
        "physical_contract": contract, "owner_segment_id": owner,
        "calculation_segment_id": calculation,
        "input_quality_policy": identity.input_quality_policy,
        "source_identity": payload["source_identity"],
    })
    rollover = checkpoint.physical_contract is not None and (
        checkpoint.physical_contract != contract
        or checkpoint.owner_segment_id != owner
        or checkpoint.calculation_segment_id != calculation
    )
    points: list[dict[str, object]] = []
    if rollover:
        old = prior.open_trade
        boundary = () if old is None else (ReferenceBoundary(
            stream, BoundaryReason.ROLLOVER, old.physical_contract,
            old.owner_segment_id, old.calculation_segment_id, end, day,
        ),)
        transition = reduce_reference(
            prior, boundaries=boundary,
            completed_bar=CompletedReferenceBar(contract, owner, calculation, end, day, product_bar.bar.close),
        )
        next_state, _frame, _diagnostics = replay_step(identity, seed_replay_state(), product_bar)
        points.append(presentation_point(
            kind="boundary", trading_day=day, formula_versions=stream.formula_versions,
            value={"bar_end": end, "reason": "ROLLOVER", "observed_at": observed,
                   "physical_contract": old.physical_contract if old else checkpoint.physical_contract,
                   "owner_segment_id": checkpoint.owner_segment_id,
                   "calculation_segment_id": checkpoint.calculation_segment_id},
        ))
        sources: tuple[SourceAction, ...] = ()
        next_checkpoint = AdapterCheckpoint(
            next_state, end, fingerprint, contract, owner, calculation, stream, transition.state,
        )
    else:
        item = HistoricalInputBar(
            end, day, contract, owner, calculation, product_bar.bar.close,
            fingerprint, NewowHistoricalPayload(identity, product_bar, False),
        )
        next_checkpoint, raw_sources, transition = _newow_step(
            stream, checkpoint, item, points,
        )
        sources = tuple(SourceAction(source.action, observed) for source in raw_sources)
        for point in points:
            value = point.get("value")
            if isinstance(value, dict):
                value["observed_at"] = observed.isoformat()
    return PreparedBatch(
        stream.stream_id, token.revision_id, f"forward:{capture['source_key']}",
        token, dependency_manifest, sources, (transition,), next_checkpoint,
        "newow_product_replay_v1",
        {"forward_capture_v1": {
            "capture_id": evidence["capture_id"], "hash": capture["hash"],
            "generation": capture["generation"],
        }, "presentation_v1": envelope(points)},
        observed,
    )
