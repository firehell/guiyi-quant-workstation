/** C6-07A Market/Runtime observation — display-only, no runtime start / RQData. */

export type ObservationFieldStatus = 'available' | 'unavailable' | 'warning'

export type MarketDataMode = 'historical' | 'live'

export interface ObservationField<T = string> {
  status: ObservationFieldStatus
  value: T | null
  reason?: string | null
}

export interface MarketRuntimeObservationContext {
  data_mode: ObservationField<MarketDataMode>
  source_badge: ObservationField
  actual_contract: ObservationField
  latest_live_1m: ObservationField
  confirmed_count: ObservationField<number>
  partial_count: ObservationField<number>
  checkpoint_status: ObservationField
  checkpoint_lag_seconds: ObservationField<number>
  latency_ms: ObservationField<number>
  runtime_health_status: ObservationField
  archived_trading_day: ObservationField
  active_data_version: ObservationField
  quality_status: ObservationField
  profile_id: ObservationField
}

export interface MarketRuntimeObservationInput {
  data_mode?: MarketDataMode | null
  /** Conflicting mode hint from another source — triggers mix warning when differs. */
  conflicting_data_mode?: MarketDataMode | null
  actual_contract?: string | null
  latest_live_1m?: string | null
  confirmed_count?: number | null
  partial_count?: number | null
  /** Chart/display uses confirmed-only bars; must not equal confirmed+partial silently. */
  chart_row_count?: number | null
  checkpoint_status?: string | null
  checkpoint_lag_seconds?: number | null
  latency_ms?: number | null
  runtime_health_status?: string | null
  archived_trading_day?: string | null
  active_data_version?: string | null
  quality_status?: string | null
  profile_id?: string | null
  target_blocked_reasons?: string[] | null
  readiness_status?: string | null
}
