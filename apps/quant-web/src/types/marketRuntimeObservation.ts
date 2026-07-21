/** C6-07A 行情/运行时观测 — 仅展示用，不启动 runtime / RQData */

/** 观测字段可用性状态 */
export type ObservationFieldStatus = 'available' | 'unavailable' | 'warning'

/** 行情数据模式：历史回放或 Live 流 */
export type MarketDataMode = 'historical' | 'live'

/** 带状态与原因的观测展示字段 */
export interface ObservationField<T = string> {
  status: ObservationFieldStatus
  value: T | null
  reason?: string | null
}

/** K 线工作台运行时观测上下文（数据源、checkpoint、质量等） */
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

/** 组装运行时观测上下文的原始输入 */
export interface MarketRuntimeObservationInput {
  data_mode?: MarketDataMode | null
  /** 来自其它来源的模式冲突提示，与当前模式不一致时触发 mix 警告 */
  conflicting_data_mode?: MarketDataMode | null
  actual_contract?: string | null
  latest_live_1m?: string | null
  confirmed_count?: number | null
  partial_count?: number | null
  /** 图表仅使用 confirmed bar；不得静默等于 confirmed + partial */
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
