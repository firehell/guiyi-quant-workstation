"""Pure HTDY first-seen capture evaluator; transport is intentionally absent."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json

from app.alerts.evaluators import HtdyOriginalEvaluator
from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import MarketReadWindow
from app.reference_trading.contracts import PreparedBatch, SourceAction
from app.reference_trading.presentation import envelope, presentation_point
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.contracts import (
    BoundaryReason, CompletedReferenceBar, ReferenceBoundary,
)
from guiyi_quant.reference_trading.htdy import (
    CONTEXT_BARS, HtdyBarFact, HtdyForwardState, project_first_seen,
)
from guiyi_quant.reference_trading.reducer import reduce_reference


def _instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("HTDY_CAPTURE_CORRUPT")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("HTDY_CAPTURE_CORRUPT")
    return result


def evaluate_htdy_capture(token, checkpoint, evidence, *, dependency_manifest):
    capture = evidence.get("forward_capture_v1")
    if not isinstance(capture, dict) or capture.get("eligibility") != "first_seen":
        raise ValueError("HTDY_CAPTURE_INELIGIBLE")
    payload, proof = capture.get("input_payload"), capture.get("source_proof")
    if not isinstance(payload, dict) or not isinstance(proof, dict):
        raise ValueError("HTDY_CAPTURE_CORRUPT")
    bars_raw = payload.get("bars")
    contracts = payload.get("bar_contracts")
    if (
        not isinstance(bars_raw, list) or len(bars_raw) != CONTEXT_BARS
        or not isinstance(contracts, list) or len(contracts) != CONTEXT_BARS
        or not all(isinstance(item, dict) for item in bars_raw)
    ):
        raise ValueError("HTDY_CAPTURE_WINDOW_INVALID")
    bars = tuple(CanonicalBar(
        bar_end=_instant(item["bar_end"]), trading_day=date.fromisoformat(item["trading_day"]),
        open=Decimal(item["open"]), high=Decimal(item["high"]),
        low=Decimal(item["low"]), close=Decimal(item["close"]),
        volume=Decimal(item["volume"]),
        turnover=None if item["turnover"] is None else Decimal(item["turnover"]),
        open_interest=None if item["open_interest"] is None else Decimal(item["open_interest"]),
    ) for item in bars_raw)
    if sha256(json.dumps(
        bars_raw, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest() != proof.get("window_sha256"):
        raise ValueError("HTDY_CAPTURE_WINDOW_CONFLICT")
    if any(bar.volume != int(bar.volume) for bar in bars):
        raise ValueError("HTDY_CAPTURE_VOLUME_INVALID")
    if not isinstance(checkpoint.strategy_state, HtdyForwardState):
        raise ValueError("HTDY_CHECKPOINT_INVALID")
    stream = checkpoint.stream
    prior = checkpoint.reference_state
    if stream is None or prior is None:
        raise ValueError("HTDY_CHECKPOINT_INVALID")
    current = bars[-1]
    if (
        current.bar_end != _instant(capture["bar_end"])
        or current.bar_end >= _instant(capture["observed_at"])
        or contracts[-1] != payload.get("contract")
        or proof.get("event_bar_end") != current.bar_end.isoformat()
        or checkpoint.computed_through is not None and current.bar_end <= checkpoint.computed_through
    ):
        raise ValueError("HTDY_CAPTURE_IDENTITY_CONFLICT")
    new_window = tuple(HtdyBarFact(
        bar.bar_end, bar.trading_day, contracts[index], bar.open, bar.high,
        bar.low, bar.close, int(bar.volume),
    ) for index, bar in enumerate(bars))
    old_window = checkpoint.strategy_state.window
    owner_changed = checkpoint.physical_contract is not None and (
        checkpoint.physical_contract != payload["contract"]
        or checkpoint.calculation_segment_id != proof["calculation_segment_id"]
    )
    if old_window and not owner_changed and old_window[1:] != new_window[:-1]:
        raise ValueError("OBSERVATION_GAP")
    window = MarketReadWindow(
        symbol=stream.product.upper(), series_kind="actual_dominant",
        frequency=stream.frequency, trading_day=current.trading_day,
        contract=payload["contract"], cutoff=current.bar_end,
        bars=bars, bar_contracts=tuple(contracts),
    )
    if owner_changed:
        old_trade = prior.open_trade
        boundary = () if old_trade is None else (ReferenceBoundary(
            stream, BoundaryReason.ROLLOVER, old_trade.physical_contract,
            old_trade.owner_segment_id, old_trade.calculation_segment_id,
            current.bar_end, current.trading_day,
        ),)
        transition = reduce_reference(
            prior, boundaries=boundary,
            completed_bar=CompletedReferenceBar(
                window.contract, proof["owner_segment_id"],
                proof["calculation_segment_id"], current.bar_end,
                current.trading_day, current.close,
            ),
        )
        observations = ()
        actions = ()
    else:
        found = HtdyOriginalEvaluator().evaluate_first_seen(window)
        observations = () if not found else found[0].observation_types
        actions, transition = project_first_seen(
            prior, observations=observations, physical_contract=window.contract,
            owner_segment_id=proof["owner_segment_id"],
            calculation_segment_id=proof["calculation_segment_id"],
            bar_end=current.bar_end, trading_day=current.trading_day, close=current.close,
        )
    next_checkpoint = AdapterCheckpoint(
        HtdyForwardState(
            stream.reference_model_version, stream.observation_policy_version, new_window,
        ), current.bar_end, capture["hash"], window.contract,
        proof["owner_segment_id"], proof["calculation_segment_id"],
        stream, transition.state,
    )
    point = presentation_point(
        kind="signal", value={
            "bar_end": current.bar_end, "observed_at": _instant(capture["observed_at"]),
            "observation_types": observations, "physical_contract": window.contract,
            "first_seen": True, "rollover_interrupted": owner_changed,
        }, trading_day=current.trading_day, formula_versions=stream.formula_versions,
    )
    return PreparedBatch(
        stream.stream_id, token.revision_id,
        f"forward:{capture['source_key']}", token, dependency_manifest,
        tuple(SourceAction(action, _instant(capture["observed_at"])) for action in actions),
        (transition,), next_checkpoint, "htdy_first_seen_v1",
        {"forward_capture_v1": {
            "capture_id": evidence["capture_id"], "hash": capture["hash"],
            "generation": capture["generation"],
        }, "presentation_v1": envelope([point])},
        _instant(capture["observed_at"]),
    )
