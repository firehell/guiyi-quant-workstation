"""Historical SuBing reference response; monetary values are decimal strings."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, NonNegativeInt


class ReferenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubingReferenceSignalOut(ReferenceOut):
    signal_id: str
    bar_end: str
    trading_day: str
    physical_contract: str
    segment_id: str
    direction: Literal["buy", "sell"]
    reference_price: str
    action: Literal[
        "OPEN_LONG",
        "OPEN_SHORT",
        "REVERSE_TO_LONG",
        "REVERSE_TO_SHORT",
        "SAME_DIRECTION",
    ]
    entry_trade_id: str | None
    closed_trade_id: str | None
    closed_return_pct: str | None


class SubingReferenceTradeOut(ReferenceOut):
    reference_trade_id: str
    side: Literal["LONG", "SHORT"]
    physical_contract: str
    segment_id: str
    entry_signal_id: str
    entry_bar_end: str
    entry_trading_day: str
    entry_reference_price: str
    exit_signal_id: str | None
    exit_bar_end: str | None
    exit_trading_day: str | None
    exit_reference_price: str | None
    status: Literal["OPEN", "CLOSED", "ROLLOVER_INTERRUPTED"]
    holding_bars: NonNegativeInt
    reference_return_pct: str | None
    mark_bar_end: str | None
    mark_reference_price: str | None
    mark_change_pct: str | None
    interrupted_at: str | None
    initial: bool


class SubingReferenceSummaryOut(ReferenceOut):
    closed_count: NonNegativeInt
    win_count: NonNegativeInt
    loss_count: NonNegativeInt
    flat_count: NonNegativeInt
    open_count: NonNegativeInt
    interrupted_count: NonNegativeInt
    initial_count: NonNegativeInt
    win_rate_pct: str | None
    mean_return_pct: str | None
    sum_return_percentage_points: str


class SubingReferenceResponse(ReferenceOut):
    symbol: str
    frequency: Literal["15m"]
    series_kind: Literal["actual_dominant"]
    formula_version: Literal["subing_ths_15m_v3"]
    reference_model_version: Literal["subing_reference_reverse_close_v1"]
    as_of: str
    performance_since: str
    performance_through: str
    reference_cutoff: str
    input_snapshot_hash: str
    executable: Literal[False]
    auto_order: Literal[False]
    source: Literal["historical_replay"]
    summary: SubingReferenceSummaryOut
    signals: list[SubingReferenceSignalOut]
    items: list[SubingReferenceTradeOut]
    next_before: str | None
