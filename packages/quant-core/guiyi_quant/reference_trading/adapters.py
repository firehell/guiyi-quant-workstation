"""The only P1 adapter seam; strategy implementations arrive in P2."""

from __future__ import annotations

from typing import Protocol

from .contracts import ReferenceState, ReferenceTransition, StreamIdentity


class StrategyAdapter(Protocol):
    """Pure strategy state advance contract, deliberately without application DTOs."""

    stream: StreamIdentity

    def seed(self) -> object: ...

    def advance(self, state: object, input_batch: object) -> tuple[object, ReferenceTransition]: ...
