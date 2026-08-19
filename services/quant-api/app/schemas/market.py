"""Market API 响应模型（Pydantic）。

与 Canonical K 线、主力映射及 Catalog 覆盖查询的 HTTP 契约对齐；字段类型与
MarketDataService 输出一致（价格/量使用 Decimal）。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class MarketBarOut(BaseModel):
    """单根 Canonical K 线。"""

    bar_end: datetime
    trading_day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal | None
    open_interest: Decimal | None


class CoverageOut(BaseModel):
    """本次查询结果在时间轴上的实际覆盖区间。"""

    start: datetime
    end: datetime


class ContractSegmentOut(BaseModel):
    """actual_dominant 查询时解析出的合约分段（按交易日切换主力）。"""

    contract: str
    start_trading_day: date
    end_trading_day: date


class MarketPageMetaOut(BaseModel):
    """历史游标分页边界。"""

    has_more_before: bool
    next_before: datetime | None


class MarketBarsPageResponse(BaseModel):
    """``/bars/page`` 历史游标分页响应。"""

    request: dict[str, object]
    bars: list[MarketBarOut]
    canonical_coverage: CoverageOut | None
    page: MarketPageMetaOut
    resolved_contract_segments: list[ContractSegmentOut]


class MarketReadStateResponse(BaseModel):
    """Market Web 的统一历史/Live 展示状态。"""

    symbol: str
    series_kind: str
    frequency: str
    operational: bool
    phase: str
    trading_day: date | None
    live_eligible: bool
    live_available: bool
    live_contract: str | None
    canonical_end: datetime | None
    after_market: dict[str, object]


class DominantContractOut(BaseModel):
    """单品种最新主力合约摘要。"""

    product: str
    product_name: str
    sector: str
    exchange: str
    actual_contract: str
    dominant_mapping_date: date


class DominantContractListResponse(BaseModel):
    """``/dominants`` 列表响应。"""

    items: list[DominantContractOut]


class ProductResearchResponse(BaseModel):
    """``/research/product`` 单品种只读研究快照。"""

    symbol: str
    product_name: str
    sector: str
    exchange: str
    series_kind: str
    contract: str | None
    as_of: date
    current_dominant: str
    dominant_mapping_date: date
    daily_trend: str
    weekly_trend: str
    position20: Decimal | None
    distance_to_20d_high: Decimal | None
    distance_to_20d_low: Decimal | None
    volume_ratio20: Decimal | None
    oi_change_1d: Decimal | None
    turnover_change_5d: Decimal | None
    atr14_percentile252: Decimal | None
    recent_daily: list[MarketBarOut]


class SubingFactorSnapshotOut(BaseModel):
    """SuBing 单周期 confirmed-bar Factor 快照。"""

    timeframe: str
    bar_end: datetime
    trading_day: date
    contract: str
    segment_start_trading_day: date
    bar_source: str
    close: Decimal
    ema21: Decimal
    price_side: str
    slope_5_raw: Decimal
    slope_10_raw: Decimal
    slope_5_bps_per_bar: Decimal
    slope_10_bps_per_bar: Decimal
    macd_dif: Decimal
    macd_dea: Decimal
    macd_histogram: Decimal
    macd_cross: str
    macd_cross_level: Decimal
    macd_zero_distance_abs: Decimal
    macd_zero_distance_bps: Decimal
    volume: Decimal
    previous_volume: Decimal
    volume_ratio_prev: Decimal | None


class SubingFactorResultOut(BaseModel):
    """SuBing Factor 可用性与可选快照。"""

    status: str
    snapshot: SubingFactorSnapshotOut | None


class SubingConditionOut(BaseModel):
    """SuBing executable Signal 单项条件，不包含 zero-band。"""

    code: str
    state: str


class SubingSignalOut(BaseModel):
    """SuBing 入场方向 Signal 的只读评估或同 boundary 解析结果。"""

    status: str
    direction: str
    trigger_timeframe: str | None
    lower_tf_confirmation: bool
    resolution: str | None
    conditions: list[SubingConditionOut]
    error_code: str | None


class SubingLifecyclePivotOut(BaseModel):
    """SuBing research lifecycle 绑定的已确认 Pivot。"""

    pivot_id: str
    kind: str
    timeframe: str
    pivot_time: datetime
    confirmed_at: datetime
    price: Decimal
    contract: str
    segment_start_trading_day: date


class SubingLifecycleTransitionOut(BaseModel):
    """SuBing research lifecycle 的最近一次状态转换。"""

    transition_id: str
    transition_at: datetime
    from_stage: str
    to_stage: str
    reason_codes: list[str]


class SubingLifecycleSnapshotOut(BaseModel):
    """SuBing Lifecycle V2 的只读 research-only 当前快照。"""

    formula_version: str
    policy_id: str
    research_only: bool
    observed_at: datetime | None
    anchor_bar_end: datetime | None
    availability: str
    unavailable_reason: str | None
    direction: str
    stage: str
    opportunity_key: str | None
    entry_progress: str | None
    trigger_kind: str | None
    trigger_timeframe: str | None
    triggered_at: datetime | None
    confirmation_source: str | None
    confirmed_at: datetime | None
    hold_count: int
    hold_required: int
    bound_reference_pivot: SubingLifecyclePivotOut | None
    rebreak_reference_price: Decimal | None
    retest_at: datetime | None
    retest_rebreak_count: int
    volume_ratio_prev: Decimal | None
    open_interest_delta: Decimal | None
    current_risk_codes: list[str]
    risk_progress: str | None
    lower_tf_risk_count: int
    last_confirmed_stage: str
    last_confirmed_at: datetime | None
    latest_transition: SubingLifecycleTransitionOut | None
    crossed_trading_day: bool
    boundary_reset: str | None
    formal_v1_matched: bool


class SubingResearchResponse(BaseModel):
    """``/research/subing`` current-rank1 只读研究快照。"""

    symbol: str
    product_name: str
    frequency: str
    actual_contract: str
    dominant_mapping_date: date
    segment_start_trading_day: date
    source_mode: str
    live_observation: str
    live_reason: str | None
    macd_policy_id: str
    signal_macd_policy_id: str
    calibration_state: str
    calibration_id: str | None
    primary: SubingFactorResultOut
    companion: SubingFactorResultOut | None
    primary_signal: SubingSignalOut
    resolved_signal: SubingSignalOut | None
    lifecycle: SubingLifecycleSnapshotOut


class MarketRadarSummaryOut(BaseModel):
    """Radar 第一屏需要的聚合计数，不包含综合分数。"""

    up_count: int
    down_count: int
    volume_expansion_count: int
    oi_increase_count: int
    high_volatility_count: int


class MarketRadarItemOut(BaseModel):
    """单个参与 Radar 的 actual-dominant 日线研究事实。"""

    symbol: str
    product_name: str
    sector: str
    price_change_1d: Decimal | None
    price_change_5d: Decimal | None
    volume_ratio20: Decimal | None
    oi_change_1d: Decimal | None
    atr14_percentile252: Decimal | None
    position20: Decimal | None
    turnover: Decimal | None
    reason_codes: list[str]


class MarketRadarSectorOut(BaseModel):
    """复用 active taxonomy 的板块汇总。"""

    sector: str
    total_count: int
    participant_count: int
    up_count: int
    down_count: int
    median_price_change_1d: Decimal | None
    attention_count: int


class MarketRadarResponse(BaseModel):
    """``/research/radar`` 全 active universe 的 freshness-aware 只读快照。"""

    status: str
    expected_as_of: date
    active_count: int
    participant_count: int
    stale: list[str]
    unavailable: list[str]
    summary: MarketRadarSummaryOut
    items: list[MarketRadarItemOut]
    attention: list[MarketRadarItemOut]
    sector_summary: list[MarketRadarSectorOut]
