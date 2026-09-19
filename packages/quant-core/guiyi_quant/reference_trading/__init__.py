"""Shared pure contracts for future unified reference-trading adapters."""

from .adapters import AdapterCheckpoint, CompletedStrategyInput, StrategyAdapter, advance_checked
from .checkpoint import checkpoint_from_json, checkpoint_to_json
from .contracts import (
    ActionKind, BoundaryReason, CompletedReferenceBar, RecordingMode, ReferenceAction, ReferenceBoundary,
    ReferenceMark, ReferenceState, ReferenceTrade, ReferenceTransition, ReturnPolicy, Side, StreamIdentity, TradeStatus,
)
from .reducer import reduce_reference

__all__ = [
    "ActionKind", "BoundaryReason", "CompletedReferenceBar", "RecordingMode", "ReferenceAction", "ReferenceBoundary",
    "AdapterCheckpoint", "CompletedStrategyInput", "ReferenceMark", "ReferenceState", "ReferenceTrade",
    "ReferenceTransition", "ReturnPolicy", "Side", "StrategyAdapter", "advance_checked",
    "StreamIdentity", "TradeStatus", "reduce_reference",
    "checkpoint_from_json", "checkpoint_to_json",
]
