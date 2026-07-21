import request from './request'
import type {
  ContractInfo,
  CoverageInfo,
  DataDownloadTaskInfo,
  DataQualityReportInfo,
  DataSourceInfo,
  ExchangeInfo,
  InstrumentInfo,
} from '@/types/data'

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

/** 获取数据下载任务列表 */
export function getDownloadTasks() {
  return request.get<any, DataDownloadTaskInfo[]>('/data/download-tasks')
}

/** 获取数据质量报告列表 */
export function getQualityReports() {
  return request.get<any, DataQualityReportInfo[]>('/data/quality-reports')
}

/** 获取数据覆盖度（coverage）列表 */
export function getCoverage() {
  return request.get<any, CoverageInfo[]>('/data/coverage')
}
