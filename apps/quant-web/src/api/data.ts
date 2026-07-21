import request from './request'
import type {
  ContractInfo,
  CoverageInfo,
  CoveragePage,
  DataCenterSummary,
  DataDownloadTaskInfo,
  DataDownloadTaskPage,
  DataProfileInfo,
  DataQualityReportInfo,
  DataQualityReportPage,
  DataSourceInfo,
  ExchangeInfo,
  InstrumentInfo,
} from '@/types/data'

export type CoverageQuery = {
  paged?: boolean
  limit?: number
  offset?: number
  symbol?: string
  contract?: string
  period?: string
  quality?: string
  provider?: string
  binding_status?: string
  include_paths?: boolean
}

export type TaskQuery = {
  paged?: boolean
  limit?: number
  offset?: number
  symbol?: string
  contract?: string
  period?: string
  provider?: string
  status?: string
}

export type QualityQuery = {
  paged?: boolean
  limit?: number
  offset?: number
  symbol?: string
  contract?: string
  period?: string
  quality?: string
  provider?: string
}

/** 首屏有界摘要：计数，不拉全表 */
export function getDataCenterSummary() {
  return request.get<any, DataCenterSummary>('/data/summary')
}

/** 获取数据源列表 */
export function getDataSources() {
  return request.get<any, DataSourceInfo[]>('/data/sources')
}

/** 获取交易所列表 */
export function getExchanges() {
  return request.get<any, ExchangeInfo[]>('/data/exchanges')
}

/** 获取品种/标的列表 */
export function getInstruments() {
  return request.get<any, InstrumentInfo[]>('/data/instruments')
}

/** 获取合约列表 */
export function getContracts() {
  return request.get<any, ContractInfo[]>('/data/contracts')
}

/** 获取数据下载任务（默认兼容全量；Web V1 使用 paged=true） */
export function getDownloadTasks(params?: TaskQuery) {
  return request.get<any, DataDownloadTaskInfo[] | DataDownloadTaskPage>('/data/download-tasks', {
    params,
  })
}

/** 获取数据质量报告 */
export function getQualityReports(params?: QualityQuery) {
  return request.get<any, DataQualityReportInfo[] | DataQualityReportPage>('/data/quality-reports', {
    params,
  })
}

/** 获取 coverage；默认不返回物理路径 */
export function getCoverage(params?: CoverageQuery) {
  return request.get<any, CoverageInfo[] | CoveragePage>('/data/coverage', { params })
}

/** 只读 Profile 列表（无 apply/switch） */
export function getDataProfiles() {
  return request.get<any, DataProfileInfo[]>('/data/profiles')
}
