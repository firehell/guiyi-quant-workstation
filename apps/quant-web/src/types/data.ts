/** 数据源配置 */
export interface DataSourceInfo {
  id: number
  name: string
  provider: string
  status: string
  priority: number
  remark?: string | null
}

/** 交易所元数据 */
export interface ExchangeInfo {
  id: number
  code: string
  name: string
  country: string
  timezone: string
  is_active: boolean
}

/** 品种（instrument）元数据 */
export interface InstrumentInfo {
  id: number
  symbol: string
  name: string
  exchange_code: string
  sector?: string | null
  category?: string | null
  is_active: boolean
}

/** 期货合约元数据 */
export interface ContractInfo {
  id: number
  contract_code: string
  instrument_symbol: string
  exchange_code: string
  name?: string | null
  contract_month?: string | null
  listed_date?: string | null
  expired_date?: string | null
  status: string
  raw_symbol?: string | null
  provider?: string | null
}

/** 数据下载任务 */
export interface DataDownloadTaskInfo {
  id: number
  task_no: string
  provider: string
  data_type: string
  instrument_symbol?: string | null
  contract_code?: string | null
  period?: string | null
  start_time: string
  end_time: string
  status: string
  progress: number | string
  error_message?: string | null
  result: Record<string, unknown>
  created_at: string
  started_at?: string | null
  finished_at?: string | null
}

/** 数据质量检查报告 */
export interface DataQualityReportInfo {
  id: number
  provider: string
  data_type: string
  instrument_symbol?: string | null
  contract_code?: string | null
  period?: string | null
  start_time: string
  end_time: string
  status: string
  missing_bars: number
  duplicated_bars: number
  abnormal_price_count: number
  abnormal_volume_count: number
  details: Record<string, unknown>
  created_at: string
}

/** 本地 Parquet 覆盖范围与质量角色 */
export interface CoverageInfo {
  id: number
  provider: string
  data_type: string
  instrument_symbol?: string | null
  contract_code?: string | null
  period?: string | null
  start_time: string
  end_time: string
  latest_bar_time?: string | null
  row_count?: number | null
  file_path: string
  quality_status: string
  data_version?: string | null
  data_role?: string | null
  view_role?: string | null
  continuous_contract?: string | null
  actual_contract?: string | null
}
