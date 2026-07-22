import request from './request'
import type {
  BacktestReport,
  BacktestOrder,
  BacktestTask,
  BacktestTaskCreateRequest,
  BacktestTrade,
  BacktestTradeExportFormat,
  BacktestTradesPage,
  BacktestTradesQuery,
} from '@/types/backtest'
import type { BacktestValidationContext, BacktestValidationContextObservation } from '@/types/backtestValidation'

/** 创建通用回测任务 */
export function createBacktestTask(data: BacktestTaskCreateRequest) {
  return request.post<any, BacktestTask>('/api/backtests/tasks', data)
}

/** 列出全部回测任务 */
export function listBacktestTasks() {
  return request.get<any, BacktestTask[]>('/api/backtests/tasks')
}

/** 按任务 ID 获取回测任务详情 */
export function getBacktestTask(taskId: number | string) {
  return request.get<any, BacktestTask>(`/api/backtests/tasks/${taskId}`)
}

/** 列出全部回测报告 */
export function listBacktestReports() {
  return request.get<any, BacktestReport[]>('/api/backtests/reports')
}

/** 按报告 ID 获取回测报告 */
export function getBacktestReport(reportId: number) {
  return request.get<any, BacktestReport>(`/api/backtests/reports/${reportId}`)
}

/** 获取报告的校验上下文（指标/口径核对用） */
export function getBacktestValidationContext(reportId: number) {
  return request.get<any, BacktestValidationContext>(`/api/backtests/reports/${reportId}/validation-context`)
}

/** Web 展示使用的只读观察包装；无效证据返回 available=false，不制造预期 HTTP console error。 */
export function getBacktestValidationContextObservation(reportId: number) {
  return request.get<any, BacktestValidationContextObservation>(
    `/api/backtests/reports/${reportId}/validation-context/observation`,
  )
}

/** 分页查询报告成交明细 */
export function listBacktestReportTrades(reportId: number, query: BacktestTradesQuery = {}) {
  return request.get<any, BacktestTradesPage>(`/api/backtests/reports/${reportId}/trades`, {
    params: cleanQueryParams(query),
  })
}

/**
 * 拉取报告全部成交明细（自动翻页聚合）。
 * 默认每页 1000 条，直到 items 为空或已凑齐 total。
 */
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

/** 导出报告成交明细（返回 Blob，由调用方触发下载） */
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

/** 列出报告委托/订单明细 */
export function listBacktestReportOrders(reportId: number) {
  return request.get<any, BacktestOrder[]>(`/api/backtests/reports/${reportId}/orders`)
}

/** 创建 JM V1-B 日线 EMA21 + MACD + 成交量 快捷回测任务 */
export function createJmV1bDailyEma21Task() {
  return request.post<any, BacktestTask>('/api/backtests/v1b/jm/daily-ema21-macd-volume/tasks')
}

/** 创建 JM V1-B 日线 Score 2/4 快捷回测任务 */
export function createJmV1bDailyScore2of4Task() {
  return request.post<any, BacktestTask>('/api/backtests/v1b/jm/daily-score2of4/tasks')
}

/** 创建 JM V1-B 日线趋势交叉 Score2 快捷回测任务 */
export function createJmV1bDailyTrendCrossScore2Task() {
  return request.post<any, BacktestTask>('/api/backtests/v1b/jm/daily-trend-cross-score2/tasks')
}

/** 创建 JM V1-B 入场周期（15m / 5m）快捷回测任务 */
export function createJmV1bEntryTask(entryInterval: '15m' | '5m') {
  return request.post<any, BacktestTask>(`/api/backtests/v1b/jm/${entryInterval}/tasks`)
}

/**
 * 将 Axios/未知错误转成可读中文提示。
 * 对 404、Alembic schema 未对齐等情况给出定向排查文案。
 */
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

/** 从未知错误对象中安全取出 HTTP response */
function responseFromError(err: unknown) {
  if (typeof err !== 'object' || err === null || !('response' in err)) return null
  return (err as { response?: { status?: number; data?: unknown } }).response || null
}

/** 解析 FastAPI 风格 detail / message / error 字段 */
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

/**
 * 判断是否为回测相关表/列缺失导致的 migration 不一致。
 * 通过已知 schema 关键字或 “column/relation does not exist” 文案识别。
 */
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

/** 去掉 undefined / null / 空字符串，避免污染 query string */
function cleanQueryParams(query: object) {
  return Object.fromEntries(
    Object.entries(query).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  )
}
