from dataclasses import dataclass, fields
from math import isfinite


@dataclass(frozen=True, slots=True)
class NewowTrendProfile:
    profile_id: str
    frequency: str
    trend_band_formula: str
    escape_formula: str
    cup_handle_formula: str
    typical_price_close_weight: float
    trend_weight_period: int
    trend_signal_period: int
    var4_lookback: int
    var4_smoothing_n: int
    var4_smoothing_m: int
    ma120_period: int
    ma120_slope_window: int
    ma120_flat_threshold: float
    cup_reversal_atr: float
    cup_min_leg_bars: int
    cup_history_limit: int
    cup_max_confirmed_pivots: int
    cup_max_candidate_checks_per_step: int
    cup_atr_period: int
    cup_pretrend_min_bars: int
    cup_pretrend_max_bars: int
    cup_pretrend_min_return: float
    cup_pretrend_min_move_atr: float
    cup_min_bars: int
    cup_max_bars: int
    cup_depth_min_pct: float
    cup_depth_preferred_max_pct: float
    cup_depth_hard_max_pct: float
    cup_depth_min_atr: float
    cup_rim_gap_max_pct: float
    cup_rim_gap_max_atr: float
    cup_bottom_zone_ratio: float
    cup_bottom_span_ready_min: int
    cup_leg_ratio_soft_min: float
    cup_leg_ratio_soft_max: float
    cup_leg_ratio_hard_min: float
    cup_leg_ratio_hard_max: float
    cup_midline_crossings_soft_max: int
    cup_midline_crossings_hard_max: int
    cup_handle_min_bars: int
    cup_handle_max_bars: int
    cup_handle_depth_max_pct: float
    cup_handle_retrace_max_ratio: float
    cup_handle_upper_half_ratio: float
    cup_handle_right_volume_max_ratio: float
    cup_handle_baseline_volume_max_ratio: float
    cup_breakout_buffer_atr: float
    cup_breakout_volume20_min_ratio: float
    cup_breakout_handle_volume_min_ratio: float
    cup_forming_min_body_score: int
    cup_ready_min_score: int
    cup_breakout_min_score: int
    cup_ready_expiry_bars: int
    cup_post_breakout_archive_bars: int
    cup_recent_terminal_ids_limit: int

    def __post_init__(self) -> None:
        integer_values = tuple(
            getattr(self, field.name) for field in fields(self) if field.type is int
        )
        values = tuple(
            value
            for field in fields(self)
            if isinstance(value := getattr(self, field.name), (float, int))
        )
        if (
            any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in integer_values
            )
            or not all(isfinite(value) for value in values)
        ):
            raise ValueError("NEWOW_PROFILE_INVALID")
        positive_integers = (
            self.cup_atr_period,
            self.cup_pretrend_min_bars,
            self.cup_pretrend_max_bars,
            self.cup_min_bars,
            self.cup_max_bars,
            self.cup_bottom_span_ready_min,
            self.cup_handle_min_bars,
            self.cup_handle_max_bars,
            self.cup_ready_expiry_bars,
            self.cup_post_breakout_archive_bars,
            self.cup_recent_terminal_ids_limit,
            self.cup_min_leg_bars,
            self.cup_history_limit,
            self.cup_max_confirmed_pivots,
            self.cup_max_candidate_checks_per_step,
        )
        if (
            any(value <= 0 for value in positive_integers)
            or self.cup_pretrend_min_bars > self.cup_pretrend_max_bars
            or self.cup_min_bars > self.cup_max_bars
            or self.cup_handle_min_bars > self.cup_handle_max_bars
            or self.cup_reversal_atr <= 0
            or self.cup_pretrend_min_return <= 0
            or self.cup_pretrend_min_move_atr <= 0
            or not (
                0
                < self.cup_depth_min_pct
                <= self.cup_depth_preferred_max_pct
                <= self.cup_depth_hard_max_pct
                <= 1
            )
            or self.cup_depth_min_atr <= 0
            or self.cup_rim_gap_max_pct <= 0
            or self.cup_rim_gap_max_atr <= 0
            or not 0 < self.cup_bottom_zone_ratio < 1
            or not (
                0
                < self.cup_leg_ratio_hard_min
                <= self.cup_leg_ratio_soft_min
                <= self.cup_leg_ratio_soft_max
                <= self.cup_leg_ratio_hard_max
            )
            or self.cup_midline_crossings_soft_max < 0
            or self.cup_midline_crossings_soft_max
            > self.cup_midline_crossings_hard_max
            or not 0 < self.cup_handle_depth_max_pct < 1
            or not 0 < self.cup_handle_retrace_max_ratio <= 1
            or not 0 < self.cup_handle_upper_half_ratio <= 1
            or not 0 < self.cup_handle_right_volume_max_ratio <= 1
            or not 0 < self.cup_handle_baseline_volume_max_ratio <= 1
            or self.cup_breakout_buffer_atr < 0
            or self.cup_breakout_volume20_min_ratio <= 0
            or self.cup_breakout_handle_volume_min_ratio <= 0
            or not 0 <= self.cup_forming_min_body_score <= 60
            or not 0 <= self.cup_ready_min_score <= 94
            or not 0 <= self.cup_breakout_min_score <= 100
        ):
            raise ValueError("NEWOW_PROFILE_INVALID")


NEWOW_TREND_D1_V1 = NewowTrendProfile(
    profile_id="newow_trend_d1_v1",
    frequency="1d",
    trend_band_formula="newow_trend_band_cleanroom_v1",
    escape_formula="newow_escape_d123_v1",
    cup_handle_formula="newow_cup_handle_v1",
    typical_price_close_weight=3.0,
    trend_weight_period=20,
    trend_signal_period=5,
    var4_lookback=9,
    var4_smoothing_n=3,
    var4_smoothing_m=1,
    ma120_period=120,
    ma120_slope_window=10,
    ma120_flat_threshold=0.0005,
    cup_reversal_atr=1.25,
    cup_min_leg_bars=3,
    cup_history_limit=220,
    cup_max_confirmed_pivots=32,
    cup_max_candidate_checks_per_step=256,
    cup_atr_period=14,
    cup_pretrend_min_bars=20,
    cup_pretrend_max_bars=60,
    cup_pretrend_min_return=0.10,
    cup_pretrend_min_move_atr=4.0,
    cup_min_bars=25,
    cup_max_bars=90,
    cup_depth_min_pct=0.10,
    cup_depth_preferred_max_pct=0.35,
    cup_depth_hard_max_pct=0.50,
    cup_depth_min_atr=3.0,
    cup_rim_gap_max_pct=0.05,
    cup_rim_gap_max_atr=1.50,
    cup_bottom_zone_ratio=0.25,
    cup_bottom_span_ready_min=3,
    cup_leg_ratio_soft_min=0.50,
    cup_leg_ratio_soft_max=2.00,
    cup_leg_ratio_hard_min=1 / 3,
    cup_leg_ratio_hard_max=3.00,
    cup_midline_crossings_soft_max=3,
    cup_midline_crossings_hard_max=5,
    cup_handle_min_bars=5,
    cup_handle_max_bars=15,
    cup_handle_depth_max_pct=0.15,
    cup_handle_retrace_max_ratio=1 / 3,
    cup_handle_upper_half_ratio=0.50,
    cup_handle_right_volume_max_ratio=0.80,
    cup_handle_baseline_volume_max_ratio=0.90,
    cup_breakout_buffer_atr=0.10,
    cup_breakout_volume20_min_ratio=1.20,
    cup_breakout_handle_volume_min_ratio=1.50,
    cup_forming_min_body_score=45,
    cup_ready_min_score=80,
    cup_breakout_min_score=85,
    cup_ready_expiry_bars=20,
    cup_post_breakout_archive_bars=20,
    cup_recent_terminal_ids_limit=32,
)
