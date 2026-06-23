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

export function getDataSources() {
  return request.get<any, DataSourceInfo[]>('/api/v1/data/sources')
}

export function getExchanges() {
  return request.get<any, ExchangeInfo[]>('/api/v1/data/exchanges')
}

export function getInstruments() {
  return request.get<any, InstrumentInfo[]>('/api/v1/data/instruments')
}

export function getContracts() {
  return request.get<any, ContractInfo[]>('/api/v1/data/contracts')
}

export function getDownloadTasks() {
  return request.get<any, DataDownloadTaskInfo[]>('/api/v1/data/download-tasks')
}

export function getQualityReports() {
  return request.get<any, DataQualityReportInfo[]>('/api/v1/data/quality-reports')
}

export function getCoverage() {
  return request.get<any, CoverageInfo[]>('/api/v1/data/coverage')
}
