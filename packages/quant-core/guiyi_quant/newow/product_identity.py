"""Stable product identities, separate from all legacy kernel marker IDs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .product_contracts import ProductIdentity, StrategyAction


REFERENCE_MODEL_VERSION = "newow_marker_reference_zero_cost_v3"
FUTURES_ADAPTATION_VERSION = "newow_futures_quality_segment_v3"
FUTURES_INPUT_POLICY_VERSION = "newow_futures_quality_observation_v2"


def utc_timestamp(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("NEWOW_PRODUCT_NAIVE_TIMESTAMP")
    return value.astimezone(UTC)


def _text(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("NEWOW_PRODUCT_EMPTY_IDENTITY")
    return value


def _digest(fields: dict[str, object]) -> str:
    payload = json.dumps(
        fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_segment_id(product: str, contract: str, owner_start: datetime) -> str:
    """Use the true owner start supplied upstream, never a clipped query start."""
    if _text(product) != product.lower() or _text(contract) != contract.upper():
        raise ValueError("NEWOW_PRODUCT_INVALID_PHYSICAL_IDENTITY")
    return f"{product}:{contract}:{utc_timestamp(owner_start).isoformat()}"


def build_calculation_segment_id(owner_segment_id: str, last_gap_at: datetime) -> str:
    """A price gap resets calculation without changing the physical owner."""
    return f"{_text(owner_segment_id)}|price-gap:{utc_timestamp(last_gap_at).isoformat()}"


def _event_fields(
    identity: ProductIdentity,
    contract: str,
    segment_id: str,
    bar_end: datetime,
    action: str,
    sequence: int | None,
) -> dict[str, object]:
    if _text(contract) != contract.upper():
        raise ValueError("NEWOW_PRODUCT_INVALID_CONTRACT")
    if sequence is not None and (type(sequence) is not int or sequence < 0):
        raise ValueError("NEWOW_PRODUCT_INVALID_SEQUENCE")
    return {
        "product": identity.product,
        "strategy": identity.strategy,
        "frequency": identity.frequency,
        "formula_versions": identity.formula_versions,
        "contract": contract,
        "segment_id": _text(segment_id),
        "bar_end": utc_timestamp(bar_end).isoformat(),
        "action": _text(action),
        "sequence": sequence,
    }


def build_signal_id(
    identity: ProductIdentity,
    contract: str,
    segment_id: str,
    bar_end: datetime,
    action: str,
    sequence: int,
    calculation_segment_id: str | None = None,
) -> str:
    if action not in ("BUILD", "CLEAR") or sequence is None:
        raise ValueError("NEWOW_PRODUCT_INVALID_ACTION")
    fields = _event_fields(identity, contract, segment_id, bar_end, action, sequence)
    if calculation_segment_id is not None and calculation_segment_id != segment_id:
        fields["calculation_segment_id"] = _text(calculation_segment_id)
    return _digest(fields)


def build_hint_id(
    identity: ProductIdentity,
    contract: str,
    segment_id: str,
    bar_end: datetime,
    kind: str,
    sequence: int | None,
    calculation_segment_id: str | None = None,
) -> str:
    # A namespace in action prevents a hint from ever colliding with a main action.
    fields = _event_fields(
        identity, contract, segment_id, bar_end, f"HINT:{_text(kind)}", sequence
    )
    if calculation_segment_id is not None and calculation_segment_id != segment_id:
        fields["calculation_segment_id"] = _text(calculation_segment_id)
    return _digest(fields)


def build_reference_trade_id(entry: StrategyAction) -> str:
    if entry.kind != "BUILD" or entry.trade_eligibility != "ELIGIBLE":
        raise ValueError("NEWOW_PRODUCT_NO_ELIGIBLE_ENTRY")
    return _digest(
        {
            "entry_signal_id": entry.signal_id,
            "reference_model_version": REFERENCE_MODEL_VERSION,
            "futures_adaptation_version": FUTURES_ADAPTATION_VERSION,
        }
    )
