"""Stable product identities, separate from all legacy kernel marker IDs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .product_contracts import ProductIdentity, StrategyAction


REFERENCE_MODEL_VERSION = "newow_marker_reference_zero_cost_v1"
FUTURES_ADAPTATION_VERSION = "newow_futures_segment_interrupt_v1"


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
) -> str:
    if action not in ("BUILD", "CLEAR") or sequence is None:
        raise ValueError("NEWOW_PRODUCT_INVALID_ACTION")
    return _digest(
        _event_fields(identity, contract, segment_id, bar_end, action, sequence)
    )


def build_hint_id(
    identity: ProductIdentity,
    contract: str,
    segment_id: str,
    bar_end: datetime,
    kind: str,
    sequence: int | None,
) -> str:
    # A namespace in action prevents a hint from ever colliding with a main action.
    return _digest(
        _event_fields(
            identity, contract, segment_id, bar_end, f"HINT:{_text(kind)}", sequence
        )
    )


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
