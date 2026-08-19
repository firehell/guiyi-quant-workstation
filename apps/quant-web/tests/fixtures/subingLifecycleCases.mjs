// Generated once from the current backend lifecycle reducer and API mappers.
// Keep this test-only matrix literal: frontend tests must not recreate strategy formulas.
export const subingLifecycleCases = {
  "companionFormalLong5m": {
    "actual_contract": "AG2601",
    "calibration_id": "subing_intraday_v1",
    "calibration_state": "accepted",
    "companion": {
      "snapshot": {
        "bar_end": "2026-01-12T02:30:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "golden",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "15m",
        "trading_day": "2026-01-12",
        "volume": "300",
        "volume_ratio_prev": "3"
      },
      "status": "ready"
    },
    "dominant_mapping_date": "2026-01-12",
    "frequency": "5m",
    "lifecycle": {
      "anchor_bar_end": "2026-01-12T02:30:00Z",
      "availability": "ready",
      "bound_reference_pivot": null,
      "boundary_reset": null,
      "confirmation_source": "formal_v1",
      "confirmed_at": "2026-01-12T02:30:00Z",
      "crossed_trading_day": false,
      "current_risk_codes": [],
      "direction": "long",
      "entry_progress": null,
      "formal_v1_matched": true,
      "formula_version": "subing_lifecycle_v2",
      "hold_count": 0,
      "hold_required": 3,
      "last_confirmed_at": "2026-01-12T02:30:00Z",
      "last_confirmed_stage": "entry_confirmed",
      "latest_transition": {
        "from_stage": "idle",
        "reason_codes": [
          "FORMAL_V1_MATCHED"
        ],
        "to_stage": "entry_confirmed",
        "transition_at": "2026-01-12T02:30:00Z",
        "transition_id": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T02:30:00+00:00:2026-01-12T02:30:00+00:00:entry_confirmed"
      },
      "lower_tf_risk_count": 0,
      "observed_at": "2026-01-12T02:30:00Z",
      "open_interest_delta": null,
      "opportunity_key": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T02:30:00+00:00",
      "policy_id": "subing_lifecycle_v2_research_v1",
      "rebreak_reference_price": null,
      "research_only": true,
      "retest_at": null,
      "retest_rebreak_count": 0,
      "risk_progress": null,
      "stage": "entry_confirmed",
      "trigger_kind": null,
      "trigger_timeframe": null,
      "triggered_at": null,
      "unavailable_reason": null,
      "volume_ratio_prev": null
    },
    "live_observation": "unavailable",
    "live_reason": "live_unavailable",
    "macd_policy_id": "web_macd_legacy_v1",
    "primary": {
      "snapshot": {
        "bar_end": "2026-01-12T02:30:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "300",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "5m",
        "trading_day": "2026-01-12",
        "volume": "300",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "primary_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "fail"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "fail"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "pass"
        }
      ],
      "direction": "none",
      "error_code": null,
      "lower_tf_confirmation": false,
      "resolution": null,
      "status": "not_matched",
      "trigger_timeframe": "5m"
    },
    "product_name": "白银",
    "resolved_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_THRESHOLD",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "pass"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "pass"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE5_THRESHOLD",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "MACD_POLICY_EQUIVALENCE",
          "state": "pass"
        }
      ],
      "direction": "long",
      "error_code": null,
      "lower_tf_confirmation": false,
      "resolution": null,
      "status": "matched",
      "trigger_timeframe": "15m"
    },
    "segment_start_trading_day": "2026-01-12",
    "signal_macd_policy_id": "subing_macd_sma_window_scale2_v1",
    "source_mode": "canonical",
    "symbol": "ag"
  },
  "dailyUnavailable": {
    "actual_contract": "AG2601",
    "calibration_id": "subing_intraday_v1",
    "calibration_state": "accepted",
    "companion": null,
    "dominant_mapping_date": "2026-01-12",
    "frequency": "1d",
    "lifecycle": {
      "anchor_bar_end": null,
      "availability": "unavailable",
      "bound_reference_pivot": null,
      "boundary_reset": null,
      "confirmation_source": null,
      "confirmed_at": null,
      "crossed_trading_day": false,
      "current_risk_codes": [],
      "direction": "none",
      "entry_progress": null,
      "formal_v1_matched": false,
      "formula_version": "subing_lifecycle_v2",
      "hold_count": 0,
      "hold_required": 3,
      "last_confirmed_at": null,
      "last_confirmed_stage": "idle",
      "latest_transition": null,
      "lower_tf_risk_count": 0,
      "observed_at": "2026-01-12T07:00:00Z",
      "open_interest_delta": null,
      "opportunity_key": null,
      "policy_id": "subing_lifecycle_v2_research_v1",
      "rebreak_reference_price": null,
      "research_only": true,
      "retest_at": null,
      "retest_rebreak_count": 0,
      "risk_progress": null,
      "stage": "idle",
      "trigger_kind": null,
      "trigger_timeframe": null,
      "triggered_at": null,
      "unavailable_reason": "SUBING_LIFECYCLE_INTRADAY_ONLY",
      "volume_ratio_prev": null
    },
    "live_observation": "not_applicable",
    "live_reason": "daily_historical_only",
    "macd_policy_id": "web_macd_legacy_v1",
    "primary": {
      "snapshot": {
        "bar_end": "2026-01-12T07:00:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "1d",
        "trading_day": "2026-01-12",
        "volume": "100",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "primary_signal": {
      "conditions": [
        {
          "code": "INTRADAY_CALIBRATION_SCOPE",
          "state": "pending"
        }
      ],
      "direction": "none",
      "error_code": "SUBING_DAILY_RESEARCH_PENDING",
      "lower_tf_confirmation": false,
      "resolution": null,
      "status": "research_pending",
      "trigger_timeframe": "1d"
    },
    "product_name": "白银",
    "resolved_signal": null,
    "segment_start_trading_day": "2026-01-12",
    "signal_macd_policy_id": "subing_macd_sma_window_scale2_v1",
    "source_mode": "canonical",
    "symbol": "ag"
  },
  "dualFormalLong5m": {
    "actual_contract": "AG2601",
    "calibration_id": "subing_intraday_v1",
    "calibration_state": "accepted",
    "companion": {
      "snapshot": {
        "bar_end": "2026-01-12T02:30:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "golden",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "15m",
        "trading_day": "2026-01-12",
        "volume": "300",
        "volume_ratio_prev": "3"
      },
      "status": "ready"
    },
    "dominant_mapping_date": "2026-01-12",
    "frequency": "5m",
    "lifecycle": {
      "anchor_bar_end": "2026-01-12T02:30:00Z",
      "availability": "ready",
      "bound_reference_pivot": null,
      "boundary_reset": null,
      "confirmation_source": "formal_v1",
      "confirmed_at": "2026-01-12T02:30:00Z",
      "crossed_trading_day": false,
      "current_risk_codes": [],
      "direction": "long",
      "entry_progress": null,
      "formal_v1_matched": true,
      "formula_version": "subing_lifecycle_v2",
      "hold_count": 0,
      "hold_required": 3,
      "last_confirmed_at": "2026-01-12T02:30:00Z",
      "last_confirmed_stage": "entry_confirmed",
      "latest_transition": {
        "from_stage": "idle",
        "reason_codes": [
          "FORMAL_V1_MATCHED"
        ],
        "to_stage": "entry_confirmed",
        "transition_at": "2026-01-12T02:30:00Z",
        "transition_id": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T02:30:00+00:00:2026-01-12T02:30:00+00:00:entry_confirmed"
      },
      "lower_tf_risk_count": 0,
      "observed_at": "2026-01-12T02:30:00Z",
      "open_interest_delta": null,
      "opportunity_key": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T02:30:00+00:00",
      "policy_id": "subing_lifecycle_v2_research_v1",
      "rebreak_reference_price": null,
      "research_only": true,
      "retest_at": null,
      "retest_rebreak_count": 0,
      "risk_progress": null,
      "stage": "entry_confirmed",
      "trigger_kind": null,
      "trigger_timeframe": null,
      "triggered_at": null,
      "unavailable_reason": null,
      "volume_ratio_prev": null
    },
    "live_observation": "unavailable",
    "live_reason": "live_unavailable",
    "macd_policy_id": "web_macd_legacy_v1",
    "primary": {
      "snapshot": {
        "bar_end": "2026-01-12T02:30:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "golden",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "5m",
        "trading_day": "2026-01-12",
        "volume": "300",
        "volume_ratio_prev": "3"
      },
      "status": "ready"
    },
    "primary_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_THRESHOLD",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "pass"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "pass"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE5_THRESHOLD",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "MACD_POLICY_EQUIVALENCE",
          "state": "pass"
        }
      ],
      "direction": "long",
      "error_code": null,
      "lower_tf_confirmation": false,
      "resolution": null,
      "status": "matched",
      "trigger_timeframe": "5m"
    },
    "product_name": "白银",
    "resolved_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_THRESHOLD",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "pass"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "pass"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE5_THRESHOLD",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "MACD_POLICY_EQUIVALENCE",
          "state": "pass"
        }
      ],
      "direction": "long",
      "error_code": null,
      "lower_tf_confirmation": true,
      "resolution": "higher_timeframe_wins",
      "status": "matched",
      "trigger_timeframe": "15m"
    },
    "segment_start_trading_day": "2026-01-12",
    "signal_macd_policy_id": "subing_macd_sma_window_scale2_v1",
    "source_mode": "canonical",
    "symbol": "ag"
  },
  "dualFormalShort15m": {
    "actual_contract": "AG2601",
    "calibration_id": "subing_intraday_v1",
    "calibration_state": "accepted",
    "companion": {
      "snapshot": {
        "bar_end": "2026-01-12T02:30:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "101",
        "macd_cross": "dead",
        "macd_cross_level": "-0.15",
        "macd_dea": "-0.1",
        "macd_dif": "-0.2",
        "macd_histogram": "-0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "below",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "-1",
        "slope_10_raw": "-0.01",
        "slope_5_bps_per_bar": "-2",
        "slope_5_raw": "-0.02",
        "timeframe": "5m",
        "trading_day": "2026-01-12",
        "volume": "300",
        "volume_ratio_prev": "3"
      },
      "status": "ready"
    },
    "dominant_mapping_date": "2026-01-12",
    "frequency": "15m",
    "lifecycle": {
      "anchor_bar_end": "2026-01-12T02:30:00Z",
      "availability": "ready",
      "bound_reference_pivot": null,
      "boundary_reset": null,
      "confirmation_source": "formal_v1",
      "confirmed_at": "2026-01-12T02:30:00Z",
      "crossed_trading_day": false,
      "current_risk_codes": [],
      "direction": "short",
      "entry_progress": null,
      "formal_v1_matched": true,
      "formula_version": "subing_lifecycle_v2",
      "hold_count": 0,
      "hold_required": 3,
      "last_confirmed_at": "2026-01-12T02:30:00Z",
      "last_confirmed_stage": "entry_confirmed",
      "latest_transition": {
        "from_stage": "idle",
        "reason_codes": [
          "FORMAL_V1_MATCHED"
        ],
        "to_stage": "entry_confirmed",
        "transition_at": "2026-01-12T02:30:00Z",
        "transition_id": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:short:2026-01-12T02:30:00+00:00:2026-01-12T02:30:00+00:00:entry_confirmed"
      },
      "lower_tf_risk_count": 0,
      "observed_at": "2026-01-12T02:30:00Z",
      "open_interest_delta": null,
      "opportunity_key": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:short:2026-01-12T02:30:00+00:00",
      "policy_id": "subing_lifecycle_v2_research_v1",
      "rebreak_reference_price": null,
      "research_only": true,
      "retest_at": null,
      "retest_rebreak_count": 0,
      "risk_progress": null,
      "stage": "entry_confirmed",
      "trigger_kind": null,
      "trigger_timeframe": null,
      "triggered_at": null,
      "unavailable_reason": null,
      "volume_ratio_prev": null
    },
    "live_observation": "unavailable",
    "live_reason": "live_unavailable",
    "macd_policy_id": "web_macd_legacy_v1",
    "primary": {
      "snapshot": {
        "bar_end": "2026-01-12T02:30:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "101",
        "macd_cross": "dead",
        "macd_cross_level": "-0.15",
        "macd_dea": "-0.1",
        "macd_dif": "-0.2",
        "macd_histogram": "-0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "below",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "-1",
        "slope_10_raw": "-0.01",
        "slope_5_bps_per_bar": "-2",
        "slope_5_raw": "-0.02",
        "timeframe": "15m",
        "trading_day": "2026-01-12",
        "volume": "300",
        "volume_ratio_prev": "3"
      },
      "status": "ready"
    },
    "primary_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_THRESHOLD",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "pass"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "pass"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE5_THRESHOLD",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "MACD_POLICY_EQUIVALENCE",
          "state": "pass"
        }
      ],
      "direction": "short",
      "error_code": null,
      "lower_tf_confirmation": false,
      "resolution": null,
      "status": "matched",
      "trigger_timeframe": "15m"
    },
    "product_name": "白银",
    "resolved_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_THRESHOLD",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "pass"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "pass"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE5_THRESHOLD",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "MACD_POLICY_EQUIVALENCE",
          "state": "pass"
        }
      ],
      "direction": "short",
      "error_code": null,
      "lower_tf_confirmation": true,
      "resolution": "higher_timeframe_wins",
      "status": "matched",
      "trigger_timeframe": "15m"
    },
    "segment_start_trading_day": "2026-01-12",
    "signal_macd_policy_id": "subing_macd_sma_window_scale2_v1",
    "source_mode": "canonical",
    "symbol": "ag"
  },
  "formalDirectLong": {
    "actual_contract": "AG2601",
    "calibration_id": "subing_intraday_v1",
    "calibration_state": "accepted",
    "companion": {
      "snapshot": {
        "bar_end": "2026-01-12T02:00:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "300",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "15m",
        "trading_day": "2026-01-12",
        "volume": "300",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "dominant_mapping_date": "2026-01-12",
    "frequency": "5m",
    "lifecycle": {
      "anchor_bar_end": "2026-01-12T02:00:00Z",
      "availability": "ready",
      "bound_reference_pivot": null,
      "boundary_reset": null,
      "confirmation_source": "formal_v1",
      "confirmed_at": "2026-01-12T02:00:00Z",
      "crossed_trading_day": false,
      "current_risk_codes": [],
      "direction": "long",
      "entry_progress": null,
      "formal_v1_matched": true,
      "formula_version": "subing_lifecycle_v2",
      "hold_count": 0,
      "hold_required": 3,
      "last_confirmed_at": "2026-01-12T02:00:00Z",
      "last_confirmed_stage": "entry_confirmed",
      "latest_transition": {
        "from_stage": "idle",
        "reason_codes": [
          "FORMAL_V1_MATCHED"
        ],
        "to_stage": "entry_confirmed",
        "transition_at": "2026-01-12T02:00:00Z",
        "transition_id": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T02:00:00+00:00:2026-01-12T02:00:00+00:00:entry_confirmed"
      },
      "lower_tf_risk_count": 0,
      "observed_at": "2026-01-12T02:00:00Z",
      "open_interest_delta": null,
      "opportunity_key": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T02:00:00+00:00",
      "policy_id": "subing_lifecycle_v2_research_v1",
      "rebreak_reference_price": null,
      "research_only": true,
      "retest_at": null,
      "retest_rebreak_count": 0,
      "risk_progress": null,
      "stage": "entry_confirmed",
      "trigger_kind": null,
      "trigger_timeframe": null,
      "triggered_at": null,
      "unavailable_reason": null,
      "volume_ratio_prev": null
    },
    "live_observation": "unavailable",
    "live_reason": "live_unavailable",
    "macd_policy_id": "web_macd_legacy_v1",
    "primary": {
      "snapshot": {
        "bar_end": "2026-01-12T02:00:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "golden",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "5m",
        "trading_day": "2026-01-12",
        "volume": "300",
        "volume_ratio_prev": "3"
      },
      "status": "ready"
    },
    "primary_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_THRESHOLD",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "pass"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "pass"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE5_THRESHOLD",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "MACD_POLICY_EQUIVALENCE",
          "state": "pass"
        }
      ],
      "direction": "long",
      "error_code": null,
      "lower_tf_confirmation": false,
      "resolution": null,
      "status": "matched",
      "trigger_timeframe": "5m"
    },
    "product_name": "白银",
    "resolved_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_THRESHOLD",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "pass"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "pass"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE5_THRESHOLD",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "MACD_POLICY_EQUIVALENCE",
          "state": "pass"
        }
      ],
      "direction": "long",
      "error_code": null,
      "lower_tf_confirmation": false,
      "resolution": null,
      "status": "matched",
      "trigger_timeframe": "5m"
    },
    "segment_start_trading_day": "2026-01-12",
    "signal_macd_policy_id": "subing_macd_sma_window_scale2_v1",
    "source_mode": "canonical",
    "symbol": "ag"
  },
  "longMomentumHold": {
    "actual_contract": "AG2601",
    "calibration_id": "subing_intraday_v1",
    "calibration_state": "accepted",
    "companion": {
      "snapshot": {
        "bar_end": "2026-01-12T02:00:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "15m",
        "trading_day": "2026-01-12",
        "volume": "100",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "dominant_mapping_date": "2026-01-12",
    "frequency": "5m",
    "lifecycle": {
      "anchor_bar_end": "2026-01-12T02:00:00Z",
      "availability": "ready",
      "bound_reference_pivot": null,
      "boundary_reset": null,
      "confirmation_source": null,
      "confirmed_at": null,
      "crossed_trading_day": false,
      "current_risk_codes": [],
      "direction": "long",
      "entry_progress": "hold_confirming",
      "formal_v1_matched": false,
      "formula_version": "subing_lifecycle_v2",
      "hold_count": 1,
      "hold_required": 3,
      "last_confirmed_at": "2026-01-12T02:05:00Z",
      "last_confirmed_stage": "setup_armed",
      "latest_transition": {
        "from_stage": "idle",
        "reason_codes": [
          "DIRECTION_CONTEXT_ALIGNED"
        ],
        "to_stage": "setup_armed",
        "transition_at": "2026-01-12T02:00:00Z",
        "transition_id": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T02:00:00+00:00:2026-01-12T02:00:00+00:00:setup_armed"
      },
      "lower_tf_risk_count": 0,
      "observed_at": "2026-01-12T02:05:00Z",
      "open_interest_delta": "0",
      "opportunity_key": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T02:00:00+00:00",
      "policy_id": "subing_lifecycle_v2_research_v1",
      "rebreak_reference_price": null,
      "research_only": true,
      "retest_at": null,
      "retest_rebreak_count": 0,
      "risk_progress": null,
      "stage": "setup_armed",
      "trigger_kind": "macd_cross",
      "trigger_timeframe": "5m",
      "triggered_at": "2026-01-12T02:05:00Z",
      "unavailable_reason": null,
      "volume_ratio_prev": "1"
    },
    "live_observation": "unavailable",
    "live_reason": "live_unavailable",
    "macd_policy_id": "web_macd_legacy_v1",
    "primary": {
      "snapshot": {
        "bar_end": "2026-01-12T02:05:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "golden",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "5m",
        "trading_day": "2026-01-12",
        "volume": "100",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "primary_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "pass"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "fail"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "pass"
        }
      ],
      "direction": "none",
      "error_code": null,
      "lower_tf_confirmation": false,
      "resolution": null,
      "status": "not_matched",
      "trigger_timeframe": "5m"
    },
    "product_name": "白银",
    "resolved_signal": null,
    "segment_start_trading_day": "2026-01-12",
    "signal_macd_policy_id": "subing_macd_sma_window_scale2_v1",
    "source_mode": "canonical",
    "symbol": "ag"
  },
  "longSetup": {
    "actual_contract": "AG2601",
    "calibration_id": "subing_intraday_v1",
    "calibration_state": "accepted",
    "companion": {
      "snapshot": {
        "bar_end": "2026-01-12T01:30:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "15m",
        "trading_day": "2026-01-12",
        "volume": "100",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "dominant_mapping_date": "2026-01-12",
    "frequency": "5m",
    "lifecycle": {
      "anchor_bar_end": "2026-01-12T01:30:00Z",
      "availability": "ready",
      "bound_reference_pivot": null,
      "boundary_reset": null,
      "confirmation_source": null,
      "confirmed_at": null,
      "crossed_trading_day": false,
      "current_risk_codes": [],
      "direction": "long",
      "entry_progress": "waiting_trigger",
      "formal_v1_matched": false,
      "formula_version": "subing_lifecycle_v2",
      "hold_count": 0,
      "hold_required": 3,
      "last_confirmed_at": "2026-01-12T01:30:00Z",
      "last_confirmed_stage": "setup_armed",
      "latest_transition": {
        "from_stage": "idle",
        "reason_codes": [
          "DIRECTION_CONTEXT_ALIGNED"
        ],
        "to_stage": "setup_armed",
        "transition_at": "2026-01-12T01:30:00Z",
        "transition_id": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T01:30:00+00:00:2026-01-12T01:30:00+00:00:setup_armed"
      },
      "lower_tf_risk_count": 0,
      "observed_at": "2026-01-12T01:30:00Z",
      "open_interest_delta": null,
      "opportunity_key": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T01:30:00+00:00",
      "policy_id": "subing_lifecycle_v2_research_v1",
      "rebreak_reference_price": null,
      "research_only": true,
      "retest_at": null,
      "retest_rebreak_count": 0,
      "risk_progress": null,
      "stage": "setup_armed",
      "trigger_kind": null,
      "trigger_timeframe": null,
      "triggered_at": null,
      "unavailable_reason": null,
      "volume_ratio_prev": null
    },
    "live_observation": "unavailable",
    "live_reason": "live_unavailable",
    "macd_policy_id": "web_macd_legacy_v1",
    "primary": {
      "snapshot": {
        "bar_end": "2026-01-12T01:30:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "5m",
        "trading_day": "2026-01-12",
        "volume": "100",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "primary_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "fail"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "fail"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "pass"
        }
      ],
      "direction": "none",
      "error_code": null,
      "lower_tf_confirmation": false,
      "resolution": null,
      "status": "not_matched",
      "trigger_timeframe": "5m"
    },
    "product_name": "白银",
    "resolved_signal": null,
    "segment_start_trading_day": "2026-01-12",
    "signal_macd_policy_id": "subing_macd_sma_window_scale2_v1",
    "source_mode": "canonical",
    "symbol": "ag"
  },
  "noFormalLong15m": {
    "actual_contract": "AG2601",
    "calibration_id": "subing_intraday_v1",
    "calibration_state": "accepted",
    "companion": {
      "snapshot": {
        "bar_end": "2026-01-12T02:30:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "300",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "5m",
        "trading_day": "2026-01-12",
        "volume": "300",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "dominant_mapping_date": "2026-01-12",
    "frequency": "15m",
    "lifecycle": {
      "anchor_bar_end": "2026-01-12T02:30:00Z",
      "availability": "ready",
      "bound_reference_pivot": null,
      "boundary_reset": null,
      "confirmation_source": null,
      "confirmed_at": null,
      "crossed_trading_day": false,
      "current_risk_codes": [],
      "direction": "long",
      "entry_progress": "waiting_trigger",
      "formal_v1_matched": false,
      "formula_version": "subing_lifecycle_v2",
      "hold_count": 0,
      "hold_required": 3,
      "last_confirmed_at": "2026-01-12T02:30:00Z",
      "last_confirmed_stage": "setup_armed",
      "latest_transition": {
        "from_stage": "idle",
        "reason_codes": [
          "DIRECTION_CONTEXT_ALIGNED"
        ],
        "to_stage": "setup_armed",
        "transition_at": "2026-01-12T02:30:00Z",
        "transition_id": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T02:30:00+00:00:2026-01-12T02:30:00+00:00:setup_armed"
      },
      "lower_tf_risk_count": 0,
      "observed_at": "2026-01-12T02:30:00Z",
      "open_interest_delta": null,
      "opportunity_key": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T02:30:00+00:00",
      "policy_id": "subing_lifecycle_v2_research_v1",
      "rebreak_reference_price": null,
      "research_only": true,
      "retest_at": null,
      "retest_rebreak_count": 0,
      "risk_progress": null,
      "stage": "setup_armed",
      "trigger_kind": null,
      "trigger_timeframe": null,
      "triggered_at": null,
      "unavailable_reason": null,
      "volume_ratio_prev": null
    },
    "live_observation": "unavailable",
    "live_reason": "live_unavailable",
    "macd_policy_id": "web_macd_legacy_v1",
    "primary": {
      "snapshot": {
        "bar_end": "2026-01-12T02:30:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "300",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "15m",
        "trading_day": "2026-01-12",
        "volume": "300",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "primary_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "fail"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "fail"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "pass"
        }
      ],
      "direction": "none",
      "error_code": null,
      "lower_tf_confirmation": false,
      "resolution": null,
      "status": "not_matched",
      "trigger_timeframe": "15m"
    },
    "product_name": "白银",
    "resolved_signal": null,
    "segment_start_trading_day": "2026-01-12",
    "signal_macd_policy_id": "subing_macd_sma_window_scale2_v1",
    "source_mode": "canonical",
    "symbol": "ag"
  },
  "oppositeContextClosed": {
    "actual_contract": "AG2601",
    "calibration_id": "subing_intraday_v1",
    "calibration_state": "accepted",
    "companion": {
      "snapshot": {
        "bar_end": "2026-01-12T02:15:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "15m",
        "trading_day": "2026-01-12",
        "volume": "100",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "dominant_mapping_date": "2026-01-12",
    "frequency": "5m",
    "lifecycle": {
      "anchor_bar_end": "2026-01-12T02:15:00Z",
      "availability": "ready",
      "bound_reference_pivot": null,
      "boundary_reset": null,
      "confirmation_source": "formal_v1",
      "confirmed_at": "2026-01-12T02:00:00Z",
      "crossed_trading_day": false,
      "current_risk_codes": [],
      "direction": "short",
      "entry_progress": null,
      "formal_v1_matched": false,
      "formula_version": "subing_lifecycle_v2",
      "hold_count": 0,
      "hold_required": 3,
      "last_confirmed_at": "2026-01-12T02:15:00Z",
      "last_confirmed_stage": "closed",
      "latest_transition": {
        "from_stage": "entry_confirmed",
        "reason_codes": [
          "OPPOSITE_DIRECTION_CONTEXT_CONFIRMED"
        ],
        "to_stage": "closed",
        "transition_at": "2026-01-12T02:15:00Z",
        "transition_id": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:short:2026-01-12T02:00:00+00:00:2026-01-12T02:15:00+00:00:closed"
      },
      "lower_tf_risk_count": 0,
      "observed_at": "2026-01-12T02:15:00Z",
      "open_interest_delta": null,
      "opportunity_key": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:short:2026-01-12T02:00:00+00:00",
      "policy_id": "subing_lifecycle_v2_research_v1",
      "rebreak_reference_price": null,
      "research_only": true,
      "retest_at": null,
      "retest_rebreak_count": 0,
      "risk_progress": null,
      "stage": "closed",
      "trigger_kind": null,
      "trigger_timeframe": null,
      "triggered_at": null,
      "unavailable_reason": null,
      "volume_ratio_prev": null
    },
    "live_observation": "unavailable",
    "live_reason": "live_unavailable",
    "macd_policy_id": "web_macd_legacy_v1",
    "primary": {
      "snapshot": {
        "bar_end": "2026-01-12T02:15:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "5m",
        "trading_day": "2026-01-12",
        "volume": "100",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "primary_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "fail"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "fail"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "pass"
        }
      ],
      "direction": "none",
      "error_code": null,
      "lower_tf_confirmation": false,
      "resolution": null,
      "status": "not_matched",
      "trigger_timeframe": "5m"
    },
    "product_name": "白银",
    "resolved_signal": null,
    "segment_start_trading_day": "2026-01-12",
    "signal_macd_policy_id": "subing_macd_sma_window_scale2_v1",
    "source_mode": "canonical",
    "symbol": "ag"
  },
  "pivotBreakHold": {
    "actual_contract": "AG2601",
    "calibration_id": "subing_intraday_v1",
    "calibration_state": "accepted",
    "companion": {
      "snapshot": {
        "bar_end": "2026-01-12T01:30:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "15m",
        "trading_day": "2026-01-12",
        "volume": "100",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "dominant_mapping_date": "2026-01-12",
    "frequency": "5m",
    "lifecycle": {
      "anchor_bar_end": "2026-01-12T01:30:00Z",
      "availability": "ready",
      "bound_reference_pivot": {
        "confirmed_at": "2026-01-12T01:50:00Z",
        "contract": "AG2601",
        "kind": "high",
        "pivot_id": "AG2601:2026-01-12:5m:high:2026-01-12T01:40:00+00:00",
        "pivot_time": "2026-01-12T01:40:00Z",
        "price": "110",
        "segment_start_trading_day": "2026-01-12",
        "timeframe": "5m"
      },
      "boundary_reset": null,
      "confirmation_source": null,
      "confirmed_at": null,
      "crossed_trading_day": false,
      "current_risk_codes": [],
      "direction": "long",
      "entry_progress": "hold_confirming",
      "formal_v1_matched": false,
      "formula_version": "subing_lifecycle_v2",
      "hold_count": 1,
      "hold_required": 3,
      "last_confirmed_at": "2026-01-12T01:55:00Z",
      "last_confirmed_stage": "setup_armed",
      "latest_transition": {
        "from_stage": "idle",
        "reason_codes": [
          "DIRECTION_CONTEXT_ALIGNED"
        ],
        "to_stage": "setup_armed",
        "transition_at": "2026-01-12T01:30:00Z",
        "transition_id": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T01:30:00+00:00:2026-01-12T01:30:00+00:00:setup_armed"
      },
      "lower_tf_risk_count": 0,
      "observed_at": "2026-01-12T01:55:00Z",
      "open_interest_delta": "18",
      "opportunity_key": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T01:30:00+00:00",
      "policy_id": "subing_lifecycle_v2_research_v1",
      "rebreak_reference_price": "115",
      "research_only": true,
      "retest_at": null,
      "retest_rebreak_count": 0,
      "risk_progress": null,
      "stage": "setup_armed",
      "trigger_kind": "pivot_break",
      "trigger_timeframe": "5m",
      "triggered_at": "2026-01-12T01:55:00Z",
      "unavailable_reason": null,
      "volume_ratio_prev": "3"
    },
    "live_observation": "unavailable",
    "live_reason": "live_unavailable",
    "macd_policy_id": "web_macd_legacy_v1",
    "primary": {
      "snapshot": {
        "bar_end": "2026-01-12T01:55:00Z",
        "bar_source": "canonical",
        "close": "111",
        "contract": "AG2601",
        "ema21": "110",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "13.51351351351351351351351351",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.0111",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.0222",
        "timeframe": "5m",
        "trading_day": "2026-01-12",
        "volume": "300",
        "volume_ratio_prev": "3"
      },
      "status": "ready"
    },
    "primary_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "fail"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "pass"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "pass"
        }
      ],
      "direction": "none",
      "error_code": null,
      "lower_tf_confirmation": false,
      "resolution": null,
      "status": "not_matched",
      "trigger_timeframe": "5m"
    },
    "product_name": "白银",
    "resolved_signal": null,
    "segment_start_trading_day": "2026-01-12",
    "signal_macd_policy_id": "subing_macd_sma_window_scale2_v1",
    "source_mode": "canonical",
    "symbol": "ag"
  },
  "pivotRetest0": {
    "actual_contract": "AG2601",
    "calibration_id": "subing_intraday_v1",
    "calibration_state": "accepted",
    "companion": {
      "snapshot": {
        "bar_end": "2026-01-12T01:30:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "15m",
        "trading_day": "2026-01-12",
        "volume": "100",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "dominant_mapping_date": "2026-01-12",
    "frequency": "5m",
    "lifecycle": {
      "anchor_bar_end": "2026-01-12T01:30:00Z",
      "availability": "ready",
      "bound_reference_pivot": {
        "confirmed_at": "2026-01-12T01:50:00Z",
        "contract": "AG2601",
        "kind": "high",
        "pivot_id": "AG2601:2026-01-12:5m:high:2026-01-12T01:40:00+00:00",
        "pivot_time": "2026-01-12T01:40:00Z",
        "price": "110",
        "segment_start_trading_day": "2026-01-12",
        "timeframe": "5m"
      },
      "boundary_reset": null,
      "confirmation_source": null,
      "confirmed_at": null,
      "crossed_trading_day": false,
      "current_risk_codes": [],
      "direction": "long",
      "entry_progress": "retest_confirming",
      "formal_v1_matched": false,
      "formula_version": "subing_lifecycle_v2",
      "hold_count": 1,
      "hold_required": 3,
      "last_confirmed_at": "2026-01-12T02:00:00Z",
      "last_confirmed_stage": "setup_armed",
      "latest_transition": {
        "from_stage": "idle",
        "reason_codes": [
          "DIRECTION_CONTEXT_ALIGNED"
        ],
        "to_stage": "setup_armed",
        "transition_at": "2026-01-12T01:30:00Z",
        "transition_id": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T01:30:00+00:00:2026-01-12T01:30:00+00:00:setup_armed"
      },
      "lower_tf_risk_count": 0,
      "observed_at": "2026-01-12T02:00:00Z",
      "open_interest_delta": "18",
      "opportunity_key": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T01:30:00+00:00",
      "policy_id": "subing_lifecycle_v2_research_v1",
      "rebreak_reference_price": "115",
      "research_only": true,
      "retest_at": "2026-01-12T02:00:00Z",
      "retest_rebreak_count": 0,
      "risk_progress": null,
      "stage": "setup_armed",
      "trigger_kind": "pivot_break",
      "trigger_timeframe": "5m",
      "triggered_at": "2026-01-12T01:55:00Z",
      "unavailable_reason": null,
      "volume_ratio_prev": "3"
    },
    "live_observation": "unavailable",
    "live_reason": "live_unavailable",
    "macd_policy_id": "web_macd_legacy_v1",
    "primary": {
      "snapshot": {
        "bar_end": "2026-01-12T02:00:00Z",
        "bar_source": "canonical",
        "close": "111",
        "contract": "AG2601",
        "ema21": "110",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "13.51351351351351351351351351",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.0111",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.0222",
        "timeframe": "5m",
        "trading_day": "2026-01-12",
        "volume": "100",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "primary_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "fail"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "fail"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "pass"
        }
      ],
      "direction": "none",
      "error_code": null,
      "lower_tf_confirmation": false,
      "resolution": null,
      "status": "not_matched",
      "trigger_timeframe": "5m"
    },
    "product_name": "白银",
    "resolved_signal": null,
    "segment_start_trading_day": "2026-01-12",
    "signal_macd_policy_id": "subing_macd_sma_window_scale2_v1",
    "source_mode": "canonical",
    "symbol": "ag"
  },
  "pivotRetest1": {
    "actual_contract": "AG2601",
    "calibration_id": "subing_intraday_v1",
    "calibration_state": "accepted",
    "companion": {
      "snapshot": {
        "bar_end": "2026-01-12T01:30:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "15m",
        "trading_day": "2026-01-12",
        "volume": "100",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "dominant_mapping_date": "2026-01-12",
    "frequency": "5m",
    "lifecycle": {
      "anchor_bar_end": "2026-01-12T01:30:00Z",
      "availability": "ready",
      "bound_reference_pivot": {
        "confirmed_at": "2026-01-12T01:50:00Z",
        "contract": "AG2601",
        "kind": "high",
        "pivot_id": "AG2601:2026-01-12:5m:high:2026-01-12T01:40:00+00:00",
        "pivot_time": "2026-01-12T01:40:00Z",
        "price": "110",
        "segment_start_trading_day": "2026-01-12",
        "timeframe": "5m"
      },
      "boundary_reset": null,
      "confirmation_source": null,
      "confirmed_at": null,
      "crossed_trading_day": false,
      "current_risk_codes": [],
      "direction": "long",
      "entry_progress": "retest_confirming",
      "formal_v1_matched": false,
      "formula_version": "subing_lifecycle_v2",
      "hold_count": 1,
      "hold_required": 3,
      "last_confirmed_at": "2026-01-12T02:05:00Z",
      "last_confirmed_stage": "setup_armed",
      "latest_transition": {
        "from_stage": "idle",
        "reason_codes": [
          "DIRECTION_CONTEXT_ALIGNED"
        ],
        "to_stage": "setup_armed",
        "transition_at": "2026-01-12T01:30:00Z",
        "transition_id": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T01:30:00+00:00:2026-01-12T01:30:00+00:00:setup_armed"
      },
      "lower_tf_risk_count": 0,
      "observed_at": "2026-01-12T02:05:00Z",
      "open_interest_delta": "18",
      "opportunity_key": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T01:30:00+00:00",
      "policy_id": "subing_lifecycle_v2_research_v1",
      "rebreak_reference_price": "115",
      "research_only": true,
      "retest_at": "2026-01-12T02:00:00Z",
      "retest_rebreak_count": 1,
      "risk_progress": null,
      "stage": "setup_armed",
      "trigger_kind": "pivot_break",
      "trigger_timeframe": "5m",
      "triggered_at": "2026-01-12T01:55:00Z",
      "unavailable_reason": null,
      "volume_ratio_prev": "3"
    },
    "live_observation": "unavailable",
    "live_reason": "live_unavailable",
    "macd_policy_id": "web_macd_legacy_v1",
    "primary": {
      "snapshot": {
        "bar_end": "2026-01-12T02:05:00Z",
        "bar_source": "canonical",
        "close": "114",
        "contract": "AG2601",
        "ema21": "113",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "13.15789473684210526315789474",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.0114",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.0228",
        "timeframe": "5m",
        "trading_day": "2026-01-12",
        "volume": "100",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "primary_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "fail"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "fail"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "pass"
        }
      ],
      "direction": "none",
      "error_code": null,
      "lower_tf_confirmation": false,
      "resolution": null,
      "status": "not_matched",
      "trigger_timeframe": "5m"
    },
    "product_name": "白银",
    "resolved_signal": null,
    "segment_start_trading_day": "2026-01-12",
    "signal_macd_policy_id": "subing_macd_sma_window_scale2_v1",
    "source_mode": "canonical",
    "symbol": "ag"
  },
  "pivotRetestConfirmed": {
    "actual_contract": "AG2601",
    "calibration_id": "subing_intraday_v1",
    "calibration_state": "accepted",
    "companion": {
      "snapshot": {
        "bar_end": "2026-01-12T01:30:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.01",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.02",
        "timeframe": "15m",
        "trading_day": "2026-01-12",
        "volume": "100",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "dominant_mapping_date": "2026-01-12",
    "frequency": "5m",
    "lifecycle": {
      "anchor_bar_end": "2026-01-12T01:30:00Z",
      "availability": "ready",
      "bound_reference_pivot": {
        "confirmed_at": "2026-01-12T01:50:00Z",
        "contract": "AG2601",
        "kind": "high",
        "pivot_id": "AG2601:2026-01-12:5m:high:2026-01-12T01:40:00+00:00",
        "pivot_time": "2026-01-12T01:40:00Z",
        "price": "110",
        "segment_start_trading_day": "2026-01-12",
        "timeframe": "5m"
      },
      "boundary_reset": null,
      "confirmation_source": "pivot_retest_rebreak",
      "confirmed_at": "2026-01-12T02:10:00Z",
      "crossed_trading_day": false,
      "current_risk_codes": [],
      "direction": "long",
      "entry_progress": null,
      "formal_v1_matched": false,
      "formula_version": "subing_lifecycle_v2",
      "hold_count": 1,
      "hold_required": 3,
      "last_confirmed_at": "2026-01-12T02:10:00Z",
      "last_confirmed_stage": "entry_confirmed",
      "latest_transition": {
        "from_stage": "setup_armed",
        "reason_codes": [
          "PIVOT_RETEST_REBREAK_CONFIRMED"
        ],
        "to_stage": "entry_confirmed",
        "transition_at": "2026-01-12T02:10:00Z",
        "transition_id": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T01:30:00+00:00:2026-01-12T02:10:00+00:00:entry_confirmed"
      },
      "lower_tf_risk_count": 0,
      "observed_at": "2026-01-12T02:10:00Z",
      "open_interest_delta": "18",
      "opportunity_key": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T01:30:00+00:00",
      "policy_id": "subing_lifecycle_v2_research_v1",
      "rebreak_reference_price": "115",
      "research_only": true,
      "retest_at": "2026-01-12T02:00:00Z",
      "retest_rebreak_count": 2,
      "risk_progress": null,
      "stage": "entry_confirmed",
      "trigger_kind": "pivot_break",
      "trigger_timeframe": "5m",
      "triggered_at": "2026-01-12T01:55:00Z",
      "unavailable_reason": null,
      "volume_ratio_prev": "3"
    },
    "live_observation": "unavailable",
    "live_reason": "live_unavailable",
    "macd_policy_id": "web_macd_legacy_v1",
    "primary": {
      "snapshot": {
        "bar_end": "2026-01-12T02:10:00Z",
        "bar_source": "canonical",
        "close": "116",
        "contract": "AG2601",
        "ema21": "115",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "12.93103448275862068965517241",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "1",
        "slope_10_raw": "0.0116",
        "slope_5_bps_per_bar": "2",
        "slope_5_raw": "0.0232",
        "timeframe": "5m",
        "trading_day": "2026-01-12",
        "volume": "100",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "primary_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "fail"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "fail"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE5_DIRECTION",
          "state": "pass"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "pass"
        }
      ],
      "direction": "none",
      "error_code": null,
      "lower_tf_confirmation": false,
      "resolution": null,
      "status": "not_matched",
      "trigger_timeframe": "5m"
    },
    "product_name": "白银",
    "resolved_signal": null,
    "segment_start_trading_day": "2026-01-12",
    "signal_macd_policy_id": "subing_macd_sma_window_scale2_v1",
    "source_mode": "canonical",
    "symbol": "ag"
  },
  "shortExitRiskFirst": {
    "actual_contract": "AG2601",
    "calibration_id": "subing_intraday_v1",
    "calibration_state": "accepted",
    "companion": {
      "snapshot": {
        "bar_end": "2026-01-12T02:00:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "101",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "300",
        "price_side": "below",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "-1",
        "slope_10_raw": "-0.01",
        "slope_5_bps_per_bar": "-2",
        "slope_5_raw": "-0.02",
        "timeframe": "15m",
        "trading_day": "2026-01-12",
        "volume": "300",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "dominant_mapping_date": "2026-01-12",
    "frequency": "5m",
    "lifecycle": {
      "anchor_bar_end": "2026-01-12T02:00:00Z",
      "availability": "ready",
      "bound_reference_pivot": null,
      "boundary_reset": null,
      "confirmation_source": "formal_v1",
      "confirmed_at": "2026-01-12T02:00:00Z",
      "crossed_trading_day": false,
      "current_risk_codes": [
        "LOWER_TF_EMA21_BREACH"
      ],
      "direction": "short",
      "entry_progress": null,
      "formal_v1_matched": false,
      "formula_version": "subing_lifecycle_v2",
      "hold_count": 0,
      "hold_required": 3,
      "last_confirmed_at": "2026-01-12T02:10:00Z",
      "last_confirmed_stage": "exit_risk",
      "latest_transition": {
        "from_stage": "continuation",
        "reason_codes": [
          "LOWER_TF_EMA21_BREACH"
        ],
        "to_stage": "exit_risk",
        "transition_at": "2026-01-12T02:10:00Z",
        "transition_id": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:short:2026-01-12T02:00:00+00:00:2026-01-12T02:10:00+00:00:exit_risk"
      },
      "lower_tf_risk_count": 2,
      "observed_at": "2026-01-12T02:10:00Z",
      "open_interest_delta": null,
      "opportunity_key": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:short:2026-01-12T02:00:00+00:00",
      "policy_id": "subing_lifecycle_v2_research_v1",
      "rebreak_reference_price": null,
      "research_only": true,
      "retest_at": null,
      "retest_rebreak_count": 0,
      "risk_progress": null,
      "stage": "exit_risk",
      "trigger_kind": null,
      "trigger_timeframe": null,
      "triggered_at": null,
      "unavailable_reason": null,
      "volume_ratio_prev": null
    },
    "live_observation": "unavailable",
    "live_reason": "live_unavailable",
    "macd_policy_id": "web_macd_legacy_v1",
    "primary": {
      "snapshot": {
        "bar_end": "2026-01-12T02:10:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "-1",
        "slope_10_raw": "-0.01",
        "slope_5_bps_per_bar": "-2",
        "slope_5_raw": "-0.02",
        "timeframe": "5m",
        "trading_day": "2026-01-12",
        "volume": "100",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "primary_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_DIRECTION",
          "state": "fail"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "fail"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "fail"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "fail"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "fail"
        },
        {
          "code": "COMPANION_SLOPE5_DIRECTION",
          "state": "fail"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "fail"
        }
      ],
      "direction": "none",
      "error_code": null,
      "lower_tf_confirmation": false,
      "resolution": null,
      "status": "not_matched",
      "trigger_timeframe": "5m"
    },
    "product_name": "白银",
    "resolved_signal": null,
    "segment_start_trading_day": "2026-01-12",
    "signal_macd_policy_id": "subing_macd_sma_window_scale2_v1",
    "source_mode": "canonical",
    "symbol": "ag"
  },
  "shortExitRiskSecond": {
    "actual_contract": "AG2601",
    "calibration_id": "subing_intraday_v1",
    "calibration_state": "accepted",
    "companion": {
      "snapshot": {
        "bar_end": "2026-01-12T02:15:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "101",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "below",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "-1",
        "slope_10_raw": "-0.01",
        "slope_5_bps_per_bar": "-2",
        "slope_5_raw": "-0.02",
        "timeframe": "15m",
        "trading_day": "2026-01-12",
        "volume": "100",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "dominant_mapping_date": "2026-01-12",
    "frequency": "5m",
    "lifecycle": {
      "anchor_bar_end": "2026-01-12T02:15:00Z",
      "availability": "ready",
      "bound_reference_pivot": null,
      "boundary_reset": null,
      "confirmation_source": "formal_v1",
      "confirmed_at": "2026-01-12T02:00:00Z",
      "crossed_trading_day": false,
      "current_risk_codes": [
        "LOWER_TF_EMA21_BREACH"
      ],
      "direction": "short",
      "entry_progress": null,
      "formal_v1_matched": false,
      "formula_version": "subing_lifecycle_v2",
      "hold_count": 0,
      "hold_required": 3,
      "last_confirmed_at": "2026-01-12T02:25:00Z",
      "last_confirmed_stage": "exit_risk",
      "latest_transition": {
        "from_stage": "continuation",
        "reason_codes": [
          "LOWER_TF_EMA21_BREACH"
        ],
        "to_stage": "exit_risk",
        "transition_at": "2026-01-12T02:25:00Z",
        "transition_id": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:short:2026-01-12T02:00:00+00:00:2026-01-12T02:25:00+00:00:exit_risk"
      },
      "lower_tf_risk_count": 2,
      "observed_at": "2026-01-12T02:25:00Z",
      "open_interest_delta": null,
      "opportunity_key": "subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:short:2026-01-12T02:00:00+00:00",
      "policy_id": "subing_lifecycle_v2_research_v1",
      "rebreak_reference_price": null,
      "research_only": true,
      "retest_at": null,
      "retest_rebreak_count": 0,
      "risk_progress": null,
      "stage": "exit_risk",
      "trigger_kind": null,
      "trigger_timeframe": null,
      "triggered_at": null,
      "unavailable_reason": null,
      "volume_ratio_prev": null
    },
    "live_observation": "unavailable",
    "live_reason": "live_unavailable",
    "macd_policy_id": "web_macd_legacy_v1",
    "primary": {
      "snapshot": {
        "bar_end": "2026-01-12T02:25:00Z",
        "bar_source": "canonical",
        "close": "100",
        "contract": "AG2601",
        "ema21": "99",
        "macd_cross": "none",
        "macd_cross_level": "0.15",
        "macd_dea": "0.1",
        "macd_dif": "0.2",
        "macd_histogram": "0.2",
        "macd_zero_distance_abs": "0.15",
        "macd_zero_distance_bps": "15.0000",
        "previous_volume": "100",
        "price_side": "above",
        "segment_start_trading_day": "2026-01-12",
        "slope_10_bps_per_bar": "-1",
        "slope_10_raw": "-0.01",
        "slope_5_bps_per_bar": "-2",
        "slope_5_raw": "-0.02",
        "timeframe": "5m",
        "trading_day": "2026-01-12",
        "volume": "100",
        "volume_ratio_prev": "1"
      },
      "status": "ready"
    },
    "primary_signal": {
      "conditions": [
        {
          "code": "PRIMARY_PRICE_DIRECTION",
          "state": "pass"
        },
        {
          "code": "PRIMARY_SLOPE5_DIRECTION",
          "state": "fail"
        },
        {
          "code": "PRIMARY_SLOPE10_DIRECTION",
          "state": "fail"
        },
        {
          "code": "PRIMARY_MACD_CROSS",
          "state": "fail"
        },
        {
          "code": "PRIMARY_VOLUME_RATIO",
          "state": "fail"
        },
        {
          "code": "COMPANION_PRICE_DIRECTION",
          "state": "fail"
        },
        {
          "code": "COMPANION_SLOPE5_DIRECTION",
          "state": "fail"
        },
        {
          "code": "COMPANION_SLOPE10_DIRECTION",
          "state": "fail"
        }
      ],
      "direction": "none",
      "error_code": null,
      "lower_tf_confirmation": false,
      "resolution": null,
      "status": "not_matched",
      "trigger_timeframe": "5m"
    },
    "product_name": "白银",
    "resolved_signal": null,
    "segment_start_trading_day": "2026-01-12",
    "signal_macd_policy_id": "subing_macd_sma_window_scale2_v1",
    "source_mode": "canonical",
    "symbol": "ag"
  }
}

// Source-backed transport seam: this is the exact reducer/API delta from
// formalDirectLong when the ready 15m companion still ends at 01:45.
const olderCompanionAtBoundary = structuredClone(subingLifecycleCases.formalDirectLong)
olderCompanionAtBoundary.companion.snapshot.bar_end = '2026-01-12T01:45:00Z'
olderCompanionAtBoundary.companion.snapshot.previous_volume = '100'
olderCompanionAtBoundary.companion.snapshot.volume = '100'
olderCompanionAtBoundary.lifecycle.anchor_bar_end = '2026-01-12T01:45:00Z'
subingLifecycleCases.olderCompanionAtBoundary = olderCompanionAtBoundary

export function cloneSubingLifecycleCase(name) {
  const value = subingLifecycleCases[name]
  if (!value) throw new Error(`unknown SuBing lifecycle case: ${name}`)
  return structuredClone(value)
}

export function reidentifySubingResponse(response, contract) {
  const clone = structuredClone(response)
  const previous = clone.actual_contract
  clone.actual_contract = contract
  for (const result of [clone.primary, clone.companion]) {
    if (result?.snapshot) result.snapshot.contract = contract
  }
  const lifecycle = clone.lifecycle
  if (lifecycle?.opportunity_key) lifecycle.opportunity_key = lifecycle.opportunity_key.replaceAll(previous, contract)
  if (lifecycle?.latest_transition?.transition_id) {
    lifecycle.latest_transition.transition_id = lifecycle.latest_transition.transition_id.replaceAll(previous, contract)
  }
  if (lifecycle?.bound_reference_pivot) {
    lifecycle.bound_reference_pivot.contract = contract
    lifecycle.bound_reference_pivot.pivot_id = lifecycle.bound_reference_pivot.pivot_id.replaceAll(previous, contract)
  }
  return clone
}

export const lifecycleChartBars = Array.from({ length: 13 }, (_, index) => {
  const barEnd = new Date(Date.UTC(2026, 0, 12, 1, 30 + index * 5)).toISOString()
  return {
    bar_end: barEnd,
    trading_day: '2026-01-12',
    open: 99 + index,
    high: 102 + index,
    low: 98 + index,
    close: 100 + index,
    volume: 1_000 + index,
    turnover: 10_000 + index,
    open_interest: 2_000 + index,
  }
})
