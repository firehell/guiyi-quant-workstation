"""Shared pure contracts for future unified reference-trading adapters."""

from .adapters import StrategyAdapter
from .checkpoint import checkpoint_from_json, checkpoint_to_json
from .contracts import (
    ActionKind, BoundaryReason, CompletedReferenceBar, RecordingMode, ReferenceAction, ReferenceBoundary,
    ReferenceMark, ReferenceState, ReferenceTrade, ReferenceTransition, Side, StreamIdentity, TradeStatus,
)
from .reducer import reduce_reference

__all__ = [
    "ActionKind", "BoundaryReason", "CompletedReferenceBar", "RecordingMode", "ReferenceAction", "ReferenceBoundary",
    "ReferenceMark", "ReferenceState", "ReferenceTrade", "ReferenceTransition", "Side", "StrategyAdapter",
    "StreamIdentity", "TradeStatus", "reduce_reference",
    "checkpoint_from_json", "checkpoint_to_json",
]
