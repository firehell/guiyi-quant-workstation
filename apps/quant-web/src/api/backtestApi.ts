import request from './request'
import type { BacktestReport, BacktestTask, BacktestTaskCreateRequest, BacktestTrade } from '@/types/backtest'

export function createBacktestTask(data: BacktestTaskCreateRequest) {
  return request.post<any, BacktestTask>('/api/backtests/tasks', data)
}

export function listBacktestTasks() {
  return request.get<any, BacktestTask[]>('/api/backtests/tasks')
}

export function getBacktestTask(taskId: number | string) {
  return request.get<any, BacktestTask>(`/api/backtests/tasks/${taskId}`)
}

export function listBacktestReports() {
  return request.get<any, BacktestReport[]>('/api/backtests/reports')
}

export function getBacktestReport(reportId: number) {
  return request.get<any, BacktestReport>(`/api/backtests/reports/${reportId}`)
}

export function listBacktestReportTrades(reportId: number) {
  return request.get<any, BacktestTrade[]>(`/api/backtests/reports/${reportId}/trades`)
}
