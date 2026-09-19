"""Historical SuBing reference response; monetary values are decimal strings."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, NonNegativeInt, model_validator


class ReferenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubingReferenceSignalOut(ReferenceOut):
    signal_id: str
    bar_end: str
    trading_day: str
    physical_contract: str
    segment_id: str
    calculation_segment_id: str | None = None
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
    dif: str | None = None
    dea: str | None = None
    macd: str | None = None
    ema21: str | None = None


class SubingReferenceTradeOut(ReferenceOut):
    reference_trade_id: str
    side: Literal["LONG", "SHORT"]
    physical_contract: str
    segment_id: str
    calculation_segment_id: str | None = None
    entry_signal_id: str
    entry_bar_end: str
    entry_trading_day: str
    entry_reference_price: str
    exit_signal_id: str | None
    exit_bar_end: str | None
    exit_trading_day: str | None
    exit_reference_price: str | None
    status: Literal["OPEN", "CLOSED", "ROLLOVER_INTERRUPTED", "DATA_INTERRUPTED"]
    holding_bars: NonNegativeInt
    reference_return_pct: str | None
    mark_bar_end: str | None
    mark_reference_price: str | None
    mark_change_pct: str | None
    interrupted_at: str | None
    interruption_reason: Literal["PRICE_UNAVAILABLE", "NONPOSITIVE_CLOSE"] | None = None
    interruption_trading_day: str | None = None
    initial: bool

    @model_validator(mode="after")
    def validate_status_fields(self) -> "SubingReferenceTradeOut":
        exit_fields = (
            self.exit_signal_id, self.exit_bar_end, self.exit_trading_day,
            self.exit_reference_price, self.reference_return_pct,
        )
        mark_fields = (self.mark_bar_end, self.mark_reference_price, self.mark_change_pct)
        if self.status == "CLOSED":
            valid = all(value is not None for value in exit_fields) and all(
                value is None for value in (*mark_fields, self.interrupted_at,
                                             self.interruption_reason,
                                             self.interruption_trading_day)
            )
        elif self.status == "OPEN":
            valid = all(value is None for value in (*exit_fields, self.interrupted_at,
                                                     self.interruption_reason,
                                                     self.interruption_trading_day))
        elif self.status == "DATA_INTERRUPTED":
            valid = (
                self.interrupted_at is not None
                and self.interruption_reason is not None
                and self.interruption_trading_day is not None
                and all(value is None for value in (*exit_fields, *mark_fields))
            )
        else:
            valid = (
                self.interrupted_at is not None
                and self.interruption_reason is None
                and self.interruption_trading_day is None
                and all(value is None for value in (*exit_fields, *mark_fields))
            )
        if not valid:
            raise ValueError("SUBING_REFERENCE_TRADE_STATE_INVALID")
        return self


class SubingReferenceSummaryOut(ReferenceOut):
    closed_count: NonNegativeInt
    win_count: NonNegativeInt
    loss_count: NonNegativeInt
    flat_count: NonNegativeInt
    open_count: NonNegativeInt
    interrupted_count: NonNegativeInt
    rollover_interrupted_count: NonNegativeInt | None = None
    data_interrupted_count: NonNegativeInt | None = None
    initial_count: NonNegativeInt
    win_rate_pct: str | None
    mean_return_pct: str | None
    sum_return_percentage_points: str


class SubingReferenceIndicatorOut(ReferenceOut):
    bar_end: str
    physical_contract: str
    segment_id: str
    calculation_segment_id: str | None = None
    dif: str | None
    dea: str | None
    macd: str | None
    ema21: str | None


class SubingCoverageIntervalOut(ReferenceOut):
    since: str
    through: str
    status: Literal[
        "WARMING", "INDICATOR_READY_CROSS_UNEVALUABLE", "CROSS_EVALUATED",
        "PRICE_UNAVAILABLE", "NONPOSITIVE_CLOSE",
    ]
    physical_contract: str
    segment_id: str
    calculation_segment_id: str | None


class SubingQualityInterruptionOut(ReferenceOut):
    bar_end: str
    trading_day: str
    physical_contract: str
    segment_id: str
    classification: Literal["PRICE_UNAVAILABLE", "NONPOSITIVE_CLOSE"]
    classification_version: Literal[
        "rqdata-d1-zero-ohl-v1", "rqdata-d1-nonpositive-close-v1"
    ]
    request_sha256: str
    response_sha256: str


class SubingQualityChartBarOut(ReferenceOut):
    bar_end: str
    trading_day: str
    open: str
    high: str
    low: str
    close: str
    volume: str
    turnover: str | None
    open_interest: str | None
    physical_contract: str
    segment_id: str
    calculation_segment_id: str


class SubingReferenceResponse(ReferenceOut):
    symbol: str
    frequency: Literal["15m", "30m", "60m", "1d"]
    series_kind: Literal["actual_dominant"]
    formula_version: Literal["subing_ths_15m_v3", "subing_ths_30m_v1", "subing_ths_60m_v1", "subing_ths_1d_v1"]
    reference_model_version: Literal[
        "subing_reference_reverse_close_v1",
        "subing_reference_reverse_close_quality_segment_v2",
    ]
    as_of: str
    performance_since: str
    performance_through: str
    reference_cutoff: str
    input_snapshot_hash: str
    executable: Literal[False]
    auto_order: Literal[False]
    source: Literal["historical_replay"]
    research_status: Literal[
        "ready", "warming", "WARMING",
        "INDICATOR_READY_CROSS_UNEVALUABLE", "CROSS_EVALUATED",
    ]
    summary: SubingReferenceSummaryOut
    signals: list[SubingReferenceSignalOut]
    indicators: list[SubingReferenceIndicatorOut]
    items: list[SubingReferenceTradeOut]
    next_before: str | None
    quality_policy_version: Literal["subing-d1-quality-segment-v1"] | None = None
    coverage_intervals: list[SubingCoverageIntervalOut] | None = None
    quality_interruptions: list[SubingQualityInterruptionOut] | None = None
    quality_chart_bars: list[SubingQualityChartBarOut] | None = None
