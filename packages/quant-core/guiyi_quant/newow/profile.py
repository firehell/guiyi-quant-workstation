from dataclasses import dataclass


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
)
