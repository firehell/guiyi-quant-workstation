/** 主力合约在某周期上的 bars 覆盖摘要 */
export interface DominantBarsCoveragePeriod {
  available: boolean
  start_time?: string | null
  end_time?: string | null
  row_count: number
  quality_status: string
}

/** 主力/可报价合约条目（含 coverage 与 quote_ready） */
export interface DominantContractItem {
  product: string
  product_name: string
  exchange?: string | null
  exchange_name?: string | null
  sector?: string | null
  category?: string | null
  is_active?: boolean
  continuous_contract: string
  actual_contract: string
  dominant_mapping_date: string
  bars_coverage: Record<string, DominantBarsCoveragePeriod>
  quote_ready: boolean
  default_period: string
}

/** 主力合约列表响应 */
export interface DominantContractListResponse {
  items: DominantContractItem[]
  default_quote_period: string
}

/** K线/Bar 数据 */
export interface BarData {
  time: string
  datetime?: string
  trading_day?: string
  symbol?: string
  contract?: string
  exchange?: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  openInterest?: number
  turnover?: number
  bar_status?: string
  quality_status?: string
  source_mode?: string
  revision?: number
  source_bar_count?: number
  expected_bar_count?: number
  quality_reasons?: string[]
  source_start_datetime?: string | null
  source_end_datetime?: string | null
}

/** K 线图买卖点 / 信号 marker */
export interface KlineMarker {
  id: string
  time: string
  label: string
  tooltip?: string
  color: string
  position: 'aboveBar' | 'belowBar' | 'inBar'
  shape: 'circle' | 'square' | 'arrowUp' | 'arrowDown'
}

/** 副图指标面板类型 */
export type IndicatorPanelType = 'macd' | 'atr' | 'volume_ratio' | 'signal_score'
/** 行情读取模式：浏览器只读 / 研究严格模式 */
export type MarketAccessMode = 'browser' | 'research'

/** 行情资产证据（文件 id / checksum / 区间） */
export interface MarketAssetEvidence {
  market_data_file_id: number
  data_version?: string | null
  provider: string
  data_role: string
  quality_status: string
  checksum?: string | null
  start_time: string
  end_time: string
}

/** 行情读取血缘（lineage_token、质量与合约绑定） */
export interface MarketReadLineage {
  access_mode: MarketAccessMode
  strict_research_ready: boolean
  profile_id?: string | null
  quality_policy?: string | null
  market_data_file_id?: number | null
  market_data_file_ids: number[]
  data_version?: string | null
  data_versions: string[]
  provider?: string | null
  data_role?: string | null
  quality_status?: string | null
  source_interval?: string | null
  source_intervals: string[]
  source_interval_basis?: string | null
  binding_snapshot?: Record<string, unknown> | null
  lineage_token: string
  source_mode: 'historical' | 'live'
  view_role: string
  continuous_contract?: string | null
  actual_contract?: string | null
  asset_evidence: MarketAssetEvidence[]
}
/** 主图指标 ID */
export type MainIndicatorId = 'ema_10' | 'ema_21' | 'ema_60' | 'htdy'

/** 主图指标定义（能力、默认可见性、风险提示） */
export interface MainIndicatorDefinition {
  id: MainIndicatorId
  name: string
  displayName: string
  pane: 'main'
  renderer: 'line' | 'markers' | 'band' | 'mixed'
  capability: 'standard_overlay' | 'observation_overlay'
  defaultVisible: boolean
  color: string
  parameters: Record<string, number | string | boolean>
  lookbackBars: number
  alertCapable: boolean
  available: boolean
  allowedDataModes?: Array<'historical'>
  allowedAccessModes?: Array<'browser' | 'research'>
  repaintingRisk?: 'none' | 'known'
  riskMessages?: string[]
  unstableTailBars?: number
  unavailableReason?: string
}

/** 当前 bar 上的主图指标瞬时值 */
export interface MainIndicatorValue {
  id: MainIndicatorId
  displayName: string
  value: number | null
  color: string
  ready?: boolean
  valid?: boolean
  reason?: string | null
}

/** 主图指标时序点 */
export interface MainIndicatorPoint {
  time: string
  value: number | null
  ready: boolean
  valid: boolean
  reason?: string | null
}

/** 主图指标完整序列与计算元信息 */
export interface MainIndicatorSeries {
  id: MainIndicatorId
  indicator_code: string
  display_name: string
  indicator_version: string
  parameters: Record<string, number | string | boolean>
  parameters_hash: string
  seed_policy: string
  calculation_start?: string | null
  warmup_bars: number
  confirmed_only: boolean
  data_version?: string | null
  calculation_source: string
  repainting_risk: string
  points: MainIndicatorPoint[]
}

/** 图表叠加层（价线 / marker / 风险带） */
export interface ChartOverlay {
  id: string
  type: 'price_line' | 'signal_marker' | 'trade_marker' | 'risk_band'
  price?: number
  label: string
  color: string
  lineStyle?: 'solid' | 'dashed' | 'dotted'
}

/** 悬停 K 线时的上下文（指标与 marker） */
export interface HoverKlineContext {
  time: string
  bar: BarData
  ema21?: number | null
  mainIndicators?: MainIndicatorValue[]
  macd?: {
    dif?: number | null
    dea?: number | null
    histogram?: number | null
  } | null
  atr?: number | null
  marker?: KlineMarker | null
  cursorPrice?: number | null
}

/** 单合约单周期的 coverage 明细 */
export interface MarketCoveragePeriod {
  period: string
  provider: string
  data_type: string
  source_mode?: string | null
  view_role?: string | null
  continuous_contract?: string | null
  actual_contract?: string | null
  start_time: string
  end_time: string
  latest_bar_time?: string | null
  row_count: number
  quality_status: string
  data_version?: string | null
  data_role?: string | null
  file_path?: string | null
  profile_id?: string | null
  quality_policy?: string | null
  market_data_file_id?: number | null
  binding_snapshot?: Record<string, unknown> | null
}

/** 合约级 coverage（含多周期） */
export interface MarketCoverageContract {
  contract: string
  name?: string | null
  exchange?: string | null
  provider?: string | null
  status?: string | null
  view_role?: string | null
  continuous_contract?: string | null
  actual_contract?: string | null
  periods: MarketCoveragePeriod[]
}

/** 品种级 coverage（含多合约） */
export interface MarketCoverageInstrument {
  symbol: string
  name?: string | null
  exchange?: string | null
  sector?: string | null
  contracts: MarketCoverageContract[]
}

/** 扁平化 coverage 条目（工作台列表用） */
export interface MarketCoverageItem {
  symbol: string
  contract: string
  period: string
  provider: string
  data_type: string
  source_mode?: string | null
  view_role?: string | null
  continuous_contract?: string | null
  actual_contract?: string | null
  exchange?: string | null
  name?: string | null
  start_time: string
  end_time: string
  latest_bar_time?: string | null
  row_count: number
  quality_status: string
  data_version?: string | null
  data_role?: string | null
  file_path?: string | null
  profile_id?: string | null
  quality_policy?: string | null
  market_data_file_id?: number | null
  binding_snapshot?: Record<string, unknown> | null
}

/** 工作台默认选中的 symbol/contract/period */
export interface MarketWorkbenchSelection {
  symbol: string
  contract: string
  period: string
  provider?: string | null
  profile_id?: string | null
  start: string
  end: string
}

/** K 线工作台 coverage 聚合响应 */
export interface MarketWorkbenchCoverage {
  instruments: MarketCoverageInstrument[]
  items: MarketCoverageItem[]
  default_selection?: MarketWorkbenchSelection | null
}

/** 历史 bars 质量摘要 */
export interface MarketBarsQuality {
  status: string
  missing_bars: number
  duplicated_bars: number
  abnormal_price_count: number
  abnormal_volume_count: number
  report_count: number
  warning_reasons?: string[]
  cross_file_conflicts?: number
  conflict_details?: Array<{
    dedupe_key: string
    occurrence_count: number
    conflicting_fields: string[]
    value_ranges: Record<string, number[] | null>
    file_count: number
    assets?: MarketAssetEvidence[]
  }> | null
}

/** 当前 bars 请求对应的 coverage 片段 */
export interface MarketBarsCoverage {
  symbol: string
  contract: string
  period: string
  provider?: string | null
  data_type?: string | null
  source_mode?: string | null
  view_role?: string | null
  continuous_contract?: string | null
  actual_contract?: string | null
  start_time?: string | null
  end_time?: string | null
  latest_bar_time?: string | null
  row_count: number
  quality_status: string
  data_version?: string | null
  data_role?: string | null
  file_path?: string | null
  profile_id?: string | null
  quality_policy?: string | null
  market_data_file_id?: number | null
  binding_snapshot?: Record<string, unknown> | null
}

/** 历史 / 研究模式 bars 响应 */
export interface MarketBarsResponse {
  bars: BarData[]
  quality: MarketBarsQuality
  coverage?: MarketBarsCoverage | null
  request: {
    symbol: string
    contract: string
    period: string
    start?: string | null
    end?: string | null
    provider?: string | null
    data_role?: string | null
    profile_id?: string | null
    access_mode?: MarketAccessMode
    expected_market_data_file_id?: number | null
    expected_lineage_token?: string | null
    limit: number
  }
  lineage: MarketReadLineage
  strict_research_ready: boolean
  message?: string | null
  data_identity?: CanonicalDataIdentity
}

export interface CanonicalDataIdentity {
  dataset_kind: 'continuous' | 'actual_dominant'
  frequency: string
  source_datasets: Array<Record<string, string>>
  manifest_digests: string[]
  source_data_versions: string[]
  requested_window: [string, string]
  derived_frequency?: string | null
}

/** 通用指标点（含 ready/valid） */
export interface MarketIndicatorPoint {
  time?: string | null
  value?: number | null
  ready: boolean
  valid: boolean
  reason?: string | null
}

/** 批量主图指标响应 */
export interface MarketIndicatorsResponse {
  request: {
    symbol: string
    contract: string
    period: string
    indicator_codes: string[]
    display_start?: string | null
    display_end?: string | null
    display_bar_count: number
    provider?: string | null
    data_role?: string | null
    profile_id?: string | null
    access_mode: MarketAccessMode
    expected_market_data_file_id?: number | null
    expected_lineage_token?: string | null
    quote_mode: boolean
    allow_continuous: boolean
    read_limit: number
  }
  warmup: {
    requested_display_bar_count: number
    max_warmup_bars: number
    read_limit: number
    source_bar_count: number
    display_bar_count: number
  }
  indicators: MainIndicatorSeries[]
  lineage: MarketReadLineage
  strict_research_ready: boolean
  message?: string | null
  data_identity?: CanonicalDataIdentity
}

/** MACD 专用指标响应（DIF/DEA/柱） */
export interface MarketMacdIndicatorResponse {
  policy: string
  indicator_code: string
  indicator_version: string
  parameters: Record<string, unknown>
  basis: Record<string, unknown>
  dif: MarketIndicatorPoint[]
  dea: MarketIndicatorPoint[]
  histogram: MarketIndicatorPoint[]
  source_bar_count: number
  ready_count: number
  coverage?: MarketBarsCoverage | null
  request: MarketBarsResponse['request']
  lineage: MarketReadLineage
  strict_research_ready: boolean
  message?: string | null
  data_identity?: CanonicalDataIdentity
}

/** 拉取 market bars 的请求参数 */
export interface MarketBarsRequestParams {
  dataset_kind?: 'continuous' | 'actual_dominant'
  symbol: string
  contract: string | null
  period: string
  start?: string
  end?: string
  provider?: string | null
  data_role?: string | null
  access_mode?: MarketAccessMode
  expected_lineage_token?: string | null
  quote_mode?: boolean
  allow_continuous?: boolean
  tail?: boolean
  limit?: number
}

/** 合约信息 */
export interface SymbolInfo {
  symbol: string
  name: string
  exchange: string
  productType: 'futures' | 'options' | 'stock'
  multiplier: number
  marginRatio: number
  tickSize: number
  tradingHours: string
}

/** 行情快照 */
export interface QuoteSnapshot {
  symbol: string
  lastPrice: number
  bidPrice: number
  askPrice: number
  bidVolume: number
  askVolume: number
  volume: number
  openInterest: number
  turnover: number
  preClose: number
  preSettle: number
  timestamp: string
}
