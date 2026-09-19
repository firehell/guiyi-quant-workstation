"""Shared pure contracts for future unified reference-trading adapters."""

from .adapters import StrategyAdapter
from .contracts import (
    ActionKind, BoundaryReason, RecordingMode, ReferenceAction, ReferenceBoundary,
    ReferenceMark, ReferenceState, ReferenceTrade, ReferenceTransition, Side, StreamIdentity, TradeStatus,
)
from .reducer import reduce_reference

__all__ = [
    "ActionKind", "BoundaryReason", "RecordingMode", "ReferenceAction", "ReferenceBoundary",
    "ReferenceMark", "ReferenceState", "ReferenceTrade", "ReferenceTransition", "Side", "StrategyAdapter",
    "StreamIdentity", "TradeStatus", "reduce_reference",
]
