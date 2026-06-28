import request from './request'
import type {
  BacktestDrawdownPoint,
  BacktestEquityPoint,
  BacktestReport,
  BacktestOrder,
  BacktestTask,
  BacktestTaskCreateRequest,
  BacktestTrade,
  BacktestTradeExportFormat,
  BacktestTradesPage,
  BacktestTradesQuery,
} from '@/types/backtest'

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

export function listBacktestReportTrades(reportId: number, query: BacktestTradesQuery = {}) {
  return request.get<any, BacktestTradesPage>(`/api/backtests/reports/${reportId}/trades`, {
    params: cleanQueryParams(query),
  })
}

export async function fetchAllBacktestReportTrades(reportId: number, query: BacktestTradesQuery = {}) {
  const limit = query.limit && query.limit > 0 ? query.limit : 1000
  let offset = query.offset && query.offset > 0 ? query.offset : 0
  const items: BacktestTrade[] = []

  while (true) {
    const page = await listBacktestReportTrades(reportId, { ...query, limit, offset })
    items.push(...page.items)

    if (page.items.length === 0 || items.length >= page.total) break
    offset += page.limit || limit
  }

  return items
}

export function exportBacktestReportTrades(
  reportId: number,
  format: BacktestTradeExportFormat,
  query: BacktestTradesQuery = {},
) {
  return request.get<any, Blob>(`/api/backtests/reports/${reportId}/trades/export`, {
    params: cleanQueryParams({ ...query, format }),
    responseType: 'blob',
  })
}

export function listBacktestReportOrders(reportId: number) {
  return request.get<any, BacktestOrder[]>(`/api/backtests/reports/${reportId}/orders`)
}

export function getBacktestReportEquityCurve(reportId: number) {
  return request.get<any, BacktestEquityPoint[]>(`/api/backtests/reports/${reportId}/equity-curve`)
}

export function getBacktestReportDrawdownCurve(reportId: number) {
  return request.get<any, BacktestDrawdownPoint[]>(`/api/backtests/reports/${reportId}/drawdown-curve`)
}

export function describeBacktestApiError(err: unknown, fallback: string) {
  const response = responseFromError(err)
  const detail = responseDetail(response?.data)
  const status = response?.status
  const message = [detail, err instanceof Error ? err.message : ''].filter(Boolean).join(' ')

  if (status === 404) return `${fallback}：未找到对应的回测任务或报告，请确认 report_id 是否来自当前 Web 连接的后端数据库。`
  if (isMigrationMismatch(message)) {
    return `${fallback}：后端数据库 schema 未对齐，请先确认本地 Alembic migration 已升级到 head。`
  }
  if (detail) return `${fallback}：${detail}`
  if (err instanceof Error) return `${fallback}：${err.message}`
  return fallback
}

function responseFromError(err: unknown) {
  if (typeof err !== 'object' || err === null || !('response' in err)) return null
  return (err as { response?: { status?: number; data?: unknown } }).response || null
}

function responseDetail(data: unknown) {
  if (typeof data === 'string') return data
  if (typeof data !== 'object' || data === null) return ''
  const detail = (data as { detail?: unknown; message?: unknown; error?: unknown }).detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (typeof item === 'object' && item !== null && 'msg' in item) return String((item as { msg?: unknown }).msg || '')
        return ''
      })
      .filter(Boolean)
      .join('；')
  }
  const message = (data as { message?: unknown; error?: unknown }).message || (data as { error?: unknown }).error
  return typeof message === 'string' ? message : ''
}

function isMigrationMismatch(message: string) {
  const normalized = message.toLowerCase()
  const hasKnownBacktestSchemaToken = [
    'engine_type',
    'backtest_orders',
    'backtest_equity_curve',
    'backtest_drawdown_curve',
    'undefinedtable',
    'undefinedcolumn',
  ].some((token) => normalized.includes(token))
  const hasMissingDbObjectText =
    normalized.includes('does not exist') && (normalized.includes('column') || normalized.includes('relation'))
  return hasKnownBacktestSchemaToken || hasMissingDbObjectText
}

function cleanQueryParams(query: object) {
  return Object.fromEntries(
    Object.entries(query).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  )
}
