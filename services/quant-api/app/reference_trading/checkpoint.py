"""Pure persisted checkpoint watermarks shared by Reference adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.reference_trading.inputs import HistoricalInputBar
    from guiyi_quant.reference_trading import ReferenceState
    from guiyi_quant.reference_trading.adapters import AdapterCheckpoint


def checkpoint_watermark(
    checkpoint: AdapterCheckpoint[object],
    item: HistoricalInputBar,
    reference_state: ReferenceState,
):
    candidates = tuple(
        value
        for value in (
            checkpoint.computed_through,
            item.bar_end,
            reference_state.computed_through,
            None
            if reference_state.last_event_key is None
            else reference_state.last_event_key[0],
        )
        if value is not None
    )
    return max(candidates)
