import request from './request'
import type { BacktestReport, BacktestTrade } from '@/types/backtest'
import type {
  BacktestMarketBarsQueryDebug,
  BacktestMarketBarsResult,
  BarData,
  DataProfileSummary,
  DominantContractListResponse,
  LiveMarketBarsResponse,
  MarketMacdIndicatorResponse,
  MarketBarsRequestParams,
  MarketBarsResponse,
  MarketIndicatorsResponse,
  MarketWorkbenchCoverage,
  SymbolInfo,
} from '@/types/market'
import type { MainIndicatorRequestParams } from '@/utils/mainIndicators'
import {
  toCanonicalBarsRequest,
  toCanonicalIndicatorsRequest,
} from '@/utils/dataCoreV2Market'

const BACKTEST_KLINE_PADDING_DAYS = 5

interface BacktestKlineQueryOptions {
  limit?: number
  preferTradeWindow?: boolean
  paddingDays?: number
}

/** 获取合约列表 */
export function getSymbols(exchange?: string) {
  return request.get<any, SymbolInfo[]>('/api/symbols', { params: { exchange } })
}

/** 获取K线数据 */
export function getKlines(params: {
  symbol: string
  contract: string
  period: string
  start?: string
  end?: string
  limit?: number
}) {
  return request.get<any, BarData[]>('/api/klines', { params })
}

/** 获取主力/可报价合约列表 */
export function getMarketDominants(params?: {
  exchange?: string
  quote_ready?: boolean
  search?: string
}) {
  return request.get<any, DominantContractListResponse>('/market/dominants', { params })
}

export interface MarketWorkbenchCoverageParams {
  symbol?: string
  contract?: string
  period?: string
  profile_id?: string | null
  access_mode?: 'browser' | 'research'
  include_paths?: boolean
  summary?: boolean
}

/** 获取 K线工作台可展示 coverage */
export function getMarketWorkbenchCoverage(params?: MarketWorkbenchCoverageParams) {
  return request.get<any, MarketWorkbenchCoverage>('/market/workbench/coverage', { params })
}

/** 获取 Data Core V2 Catalog coverage，不读取 legacy Profile/Binding。 */
export function getCanonicalMarketCoverage(symbol = 'jm') {
  return request.get<any, MarketWorkbenchCoverage>('/market/coverage/canonical', {
    params: { symbol },
  })
}

/** 获取 K线工作台 bars 和质量摘要 */
export function getMarketBars(params: MarketBarsRequestParams) {
  if (params.dataset_kind) {
    return request.get<any, MarketBarsResponse>('/market/bars/canonical', {
      params: toCanonicalBarsRequest(params),
    })
  }
  return request.get<any, MarketBarsResponse>('/market/bars', { params })
}

/** 获取 K 线叠加指标序列 */
export function getMarketIndicators(params: MainIndicatorRequestParams) {
  if (params.dataset_kind) {
    return request.get<any, MarketIndicatorsResponse>('/market/indicators/canonical', {
      params: toCanonicalIndicatorsRequest(params),
    })
  }
  return request.get<any, MarketIndicatorsResponse>('/market/indicators', { params })
}

/** 获取 MACD 指标（Web 兼容策略 web_macd_legacy_v1） */
export function getMarketMacdIndicator(params: MarketBarsRequestParams & { policy?: 'web_macd_legacy_v1' }) {
  if (params.dataset_kind) {
    return request.get<any, MarketMacdIndicatorResponse>('/market/indicators/macd/canonical', {
      params: toCanonicalBarsRequest(params),
    })
  }
  return request.get<any, MarketMacdIndicatorResponse>('/market/indicators/macd', {
    params: { policy: 'web_macd_legacy_v1', ...params },
  })
}

/** 获取实时行情 coverage */
export function getLiveMarketCoverage(params?: MarketWorkbenchCoverageParams) {
  return request.get<any, MarketWorkbenchCoverage>('/market/live/coverage', { params })
}

/** 获取实时行情 K 线 bars */
export function getLiveMarketBars(params: {
  symbol: string
  contract: string
  period: string
  start?: string
  end?: string
  provider?: string | null
  source_mode?: string | null
  limit?: number
}) {
  return request.get<any, LiveMarketBarsResponse>('/market/live/bars', { params })
}

/** 获取实时订阅目标合约列表 */
export function getLiveTargets() {
  return request.get<any, import('@/types/market').LiveTargetContractsResponse>('/market/live/targets')
}

/** 获取数据 profile 摘要列表 */
export function getDataProfiles() {
  return request.get<any, DataProfileSummary[]>('/data/profiles')
}

/** 从回测报告与成交明细推导 K 线查询参数（含候选组合） */
export function normalizeMarketQueryFromReport(
  report: BacktestReport,
  trades: BacktestTrade[],
  options: BacktestKlineQueryOptions = {},
): BacktestMarketBarsQueryDebug {
  const metadata = objectRecord(report.summary?.report_metadata)
  const symbol = normalizeProductSymbol(
    stringValue(metadata?.symbol) || report.symbol || firstTradeValue(trades, 'symbol') || firstTradeValue(trades, 'instrument_symbol'),
  )
  const exchange = normalizeExchange(stringValue(metadata?.exchange) || exchangeFromVtSymbol(stringValue(metadata?.vt_symbol)))
  const interval = normalizeMarketInterval(
    stringValue(metadata?.interval) || report.period || firstTradeRawValue(trades, 'entry_interval') || firstTradeRawValue(trades, 'interval'),
  )
  const timeRange = resolveBacktestKlineTimeRange(report, trades, metadata, options)
  const contract = normalizeMarketContract(
    stringValue(metadata?.contract) || report.contract || stringValue(metadata?.vt_symbol) || firstTradeValue(trades, 'contract'),
    symbol,
    exchange,
  )
  const provider = report.data_source || stringValue(metadata?.data_source) || null
  const dataRole = report.data_role || stringValue(metadata?.data_role) || null

  return {
    symbol,
    vt_symbol: stringValue(metadata?.vt_symbol) || null,
    contract,
    exchange: exchange || null,
    interval,
    start: timeRange.start,
    end: timeRange.end,
    provider,
    data_role: dataRole,
    attempted: buildBacktestKlineCandidates({
      symbol,
      contract,
      period: interval,
      start: timeRange.start,
      end: timeRange.end,
      provider,
      data_role: dataRole,
      limit: options.limit || 10000,
    }, report, trades, exchange),
  }
}

/** 按回测报告自动尝试多组合约/provider 拉取 K 线，返回首个有数据的响应 */
export async function getMarketBarsForBacktestReport(
  report: BacktestReport,
  trades: BacktestTrade[],
  options: BacktestKlineQueryOptions = {},
): Promise<BacktestMarketBarsResult> {
  const query = normalizeMarketQueryFromReport(report, trades, options)
  let lastResponse: MarketBarsResponse | null = null

  // 依次尝试候选查询，命中非空 bars 即返回
  for (const candidate of query.attempted) {
    const response = await getMarketBars(candidate)
    lastResponse = response
    if (response.bars.length > 0) {
      return {
        response,
        query: {
          ...query,
          symbol: candidate.symbol,
          contract: candidate.contract,
          interval: candidate.period,
          start: candidate.start,
          end: candidate.end,
          provider: candidate.provider,
          data_role: candidate.data_role,
        },
      }
    }
  }

  return {
    response: lastResponse || (await getMarketBars(query.attempted[0])),
    query,
  }
}

/** @deprecated 后端暂无 /api/quote，请使用 dominants / bars API */
export function getQuote(_symbol: string) {
  return Promise.reject(new Error('quote API is not available; use getMarketDominants or getMarketBars'))
}

/** 构建回测 K 线请求的合约/provider 候选列表 */
function buildBacktestKlineCandidates(
  primary: MarketBarsRequestParams,
  report: BacktestReport,
  trades: BacktestTrade[],
  exchange: string,
) {
  const symbol = primary.symbol
  const metadata = objectRecord(report.summary?.report_metadata)
  const contractCandidates = [
    primary.contract,
    normalizeMarketContract(report.contract, symbol, exchange),
    normalizeMarketContract(stringValue(metadata?.contract), symbol, exchange),
    `${symbol}.MAIN`,
    ...trades.flatMap((trade) => [
      normalizeMarketContract(trade.contract, symbol, exchange),
      normalizeMarketContract(trade.entry_contract, symbol, exchange),
      normalizeMarketContract(trade.exit_contract, symbol, exchange),
      normalizeMarketContract(trade.contract_code, symbol, exchange),
    ]),
  ].filter(Boolean)
  const uniqueContracts = [...new Set(contractCandidates)]
  const candidates: MarketBarsRequestParams[] = []

  uniqueContracts.forEach((contract, index) => {
    const withProvider = {
      ...primary,
      contract,
    }
    // 首选保留 report provider；每组合约再追加不带 provider 的降级候选
    if (index === 0 && primary.provider) candidates.push(withProvider)
    candidates.push({ ...withProvider, provider: undefined })
  })

  return dedupeMarketBarCandidates(candidates)
}

/** 按查询键去重 market bars 候选 */
function dedupeMarketBarCandidates(candidates: MarketBarsRequestParams[]) {
  const seen = new Set<string>()
  return candidates.filter((candidate) => {
    const key = JSON.stringify({
      symbol: candidate.symbol,
      contract: candidate.contract,
      period: candidate.period,
      start: candidate.start,
      end: candidate.end,
      provider: candidate.provider || null,
      data_role: candidate.data_role || null,
    })
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

/** 解析回测 K 线时间范围（报告区间或成交窗口 ± padding） */
function resolveBacktestKlineTimeRange(
  report: BacktestReport,
  trades: BacktestTrade[],
  metadata: Record<string, unknown> | null,
  options: BacktestKlineQueryOptions,
) {
  const reportStart = stringValue(metadata?.start) || stringValue(report.summary?.start_date)
  const reportEnd = stringValue(metadata?.end) || stringValue(report.summary?.end_date)
  // 未要求成交窗口时，优先使用报告 metadata 区间
  if (!options.preferTradeWindow && (reportStart || reportEnd)) {
    return {
      start: reportStart || undefined,
      end: reportEnd || undefined,
    }
  }

  const tradeTimes = trades.flatMap((trade) => [trade.open_time, trade.close_time]).filter(Boolean)
  // 无成交时间则回退报告区间
  if (!tradeTimes.length && (reportStart || reportEnd)) {
    return {
      start: reportStart || undefined,
      end: reportEnd || undefined,
    }
  }
  if (!tradeTimes.length) return {}
  const paddingDays = options.paddingDays ?? BACKTEST_KLINE_PADDING_DAYS
  // 以首末笔成交时间向前后各扩展 padding 天
  return {
    start: shiftIsoDate(minString(tradeTimes), -paddingDays),
    end: shiftIsoDate(maxString(tradeTimes), paddingDays),
  }
}

/** 归一化品种代码（去 MAIN 后缀、取字母段并转小写） */
function normalizeProductSymbol(value: string) {
  const normalized = value.trim().replace(/_MAIN$/i, '').replace(/\.MAIN$/i, '')
  const match = normalized.match(/[A-Za-z]+/)
  return (match?.[0] || normalized).toLowerCase()
}

/** 归一化合约标识（MAIN 连续合约、具体合约、交易所前缀等格式） */
function normalizeMarketContract(value: string | null | undefined, symbol: string, exchange: string) {
  const raw = String(value || '').trim()
  if (!raw) return `${symbol}.MAIN`
  const parts = raw.split('.').filter(Boolean)

  // 交易所.品种.MAIN 或 品种.MAIN → 品种.main
  if (parts.length >= 3 && parts[1].toUpperCase() === 'MAIN') return `${parts[0].toLowerCase()}.MAIN`
  if (parts.length === 2 && parts[1].toUpperCase() === 'MAIN') return `${parts[0].toLowerCase()}.MAIN`
  // 合约.交易所 或 交易所.合约 → EXCHANGE.contract
  if (parts.length === 2 && isExchangeCode(parts[1])) return normalizeActualContract(parts[0], parts[1])
  if (parts.length === 2 && isExchangeCode(parts[0])) return normalizeActualContract(parts[1], parts[0])
  if (/_MAIN$/i.test(raw)) return `${normalizeProductSymbol(raw)}.MAIN`
  if (/\.MAIN$/i.test(raw)) return `${normalizeProductSymbol(raw)}.MAIN`
  if (/^[A-Za-z]+\d+$/i.test(raw)) return exchange ? normalizeActualContract(raw, exchange) : raw.toLowerCase()
  return raw
}

/** 将具体合约格式化为 EXCHANGE.contract（小写、去下划线） */
function normalizeActualContract(contract: string, exchange: string) {
  const normalizedContract = contract.replace(/_/g, '').toLowerCase()
  return `${exchange.toUpperCase()}.${normalizedContract}`
}

/** 归一化 K 线周期（日/分钟别名 → 1d、Nm） */
function normalizeMarketInterval(value: string) {
  const normalized = value.trim().toLowerCase()
  if (['d', 'day', 'daily', '1day'].includes(normalized)) return '1d'
  const minuteMatch = normalized.match(/^(\d+)\s*(m|min|minute|minutes)$/)
  if (minuteMatch) return `${minuteMatch[1]}m`
  return normalized
}

/** 归一化交易所代码为大写 */
function normalizeExchange(value: string) {
  return value ? value.trim().toUpperCase() : ''
}

/** 从 vt_symbol 末段提取交易所代码 */
function exchangeFromVtSymbol(value: string) {
  const parts = value.split('.').filter(Boolean)
  const last = parts.at(-1)
  return last && isExchangeCode(last) ? last : ''
}

/** 判断字符串是否为交易所代码（非 MAIN） */
function isExchangeCode(value: string) {
  return /^[A-Z]{2,8}$/i.test(value) && value.toUpperCase() !== 'MAIN'
}

/** 取成交明细中首个非空字段值 */
function firstTradeValue(trades: BacktestTrade[], key: keyof BacktestTrade) {
  for (const trade of trades) {
    const value = trade[key]
    if (value !== undefined && value !== null && value !== '') return String(value)
  }
  return ''
}

/** 取成交明细 raw_payload 中首个非空字段值 */
function firstTradeRawValue(trades: BacktestTrade[], key: string) {
  for (const trade of trades) {
    const value = trade.raw_payload?.[key]
    if (value !== undefined && value !== null && value !== '') return String(value)
  }
  return ''
}

/** 将未知值转为字符串，null/undefined 返回空串 */
function stringValue(value: unknown) {
  return value === undefined || value === null ? '' : String(value)
}

/** 将未知值安全转为 Record，非对象返回 null */
function objectRecord(value: unknown) {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null
}

/** 取字符串数组字典序最小值 */
function minString(values: string[]) {
  return values.reduce((min, value) => (value < min ? value : min), values[0])
}

/** 取字符串数组字典序最大值 */
function maxString(values: string[]) {
  return values.reduce((max, value) => (value > max ? value : max), values[0])
}

/** 将 ISO 日期字符串偏移指定天数 */
function shiftIsoDate(value: string, days: number) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  date.setDate(date.getDate() + days)
  return date.toISOString()
}
