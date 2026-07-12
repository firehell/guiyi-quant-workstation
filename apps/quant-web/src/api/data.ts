import request from './request'
import type {
  ContractInfo,
  CoverageInfo,
  DataDownloadTaskInfo,
  DataProfileInfo,
  DataQualityReportInfo,
  DataSourceInfo,
  ExchangeInfo,
  InstrumentInfo,
} from '@/types/data'

export function getDataSources() {
  return request.get<any, DataSourceInfo[]>('/data/sources')
}

export function getExchanges() {
  return request.get<any, ExchangeInfo[]>('/data/exchanges')
}

export function getInstruments() {
  return request.get<any, InstrumentInfo[]>('/data/instruments')
}

export function getContracts() {
  return request.get<any, ContractInfo[]>('/data/contracts')
}

export function getDownloadTasks() {
  return request.get<any, DataDownloadTaskInfo[]>('/data/download-tasks')
}

export function getQualityReports() {
  return request.get<any, DataQualityReportInfo[]>('/data/quality-reports')
}

export function getCoverage() {
  return request.get<any, CoverageInfo[]>('/data/coverage')
}

export function getDataProfiles() {
  return request.get<any, DataProfileInfo[]>('/data/profiles')
}
