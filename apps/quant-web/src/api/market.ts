import request from './request'
import type { BacktestReport, BacktestTrade } from '@/types/backtest'
import type {
  BacktestMarketBarsQueryDebug,
  BacktestMarketBarsResult,
  BarData,
  DominantContractListResponse,
  LiveMarketBarsResponse,
  MarketBarsRequestParams,
  MarketBarsResponse,
  MarketWorkbenchCoverage,
  SymbolInfo,
} from '@/types/market'

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

export function getMarketDominants(params?: {
  exchange?: string
  quote_ready?: boolean
  search?: string
}) {
  return request.get<any, DominantContractListResponse>('/api/v1/market/dominants', { params })
}

/** 获取 K线工作台可展示 coverage */
export function getMarketWorkbenchCoverage() {
  return request.get<any, MarketWorkbenchCoverage>('/api/v1/market/workbench/coverage')
}

/** 获取 K线工作台 bars 和质量摘要 */
export function getMarketBars(params: {
  symbol: string
  contract: string
  period: string
  start?: string
  end?: string
  provider?: string | null
  data_role?: string | null
  quote_mode?: boolean
  allow_continuous?: boolean
  tail?: boolean
  limit?: number
}) {
  return request.get<any, MarketBarsResponse>('/api/v1/market/bars', { params })
}

export function getLiveMarketCoverage() {
  return request.get<any, MarketWorkbenchCoverage>('/api/v1/market/live/coverage')
}

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
  return request.get<any, LiveMarketBarsResponse>('/api/v1/market/live/bars', { params })
}

export function getLiveTargets() {
  return request.get<any, import('@/types/market').LiveTargetContractsResponse>('/api/v1/market/live/targets')
}

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

export async function getMarketBarsForBacktestReport(
  report: BacktestReport,
  trades: BacktestTrade[],
  options: BacktestKlineQueryOptions = {},
): Promise<BacktestMarketBarsResult> {
  const query = normalizeMarketQueryFromReport(report, trades, options)
  let lastResponse: MarketBarsResponse | null = null

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
    if (index === 0 && primary.provider) candidates.push(withProvider)
    candidates.push({ ...withProvider, provider: undefined })
  })

  return dedupeMarketBarCandidates(candidates)
}

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

function resolveBacktestKlineTimeRange(
  report: BacktestReport,
  trades: BacktestTrade[],
  metadata: Record<string, unknown> | null,
  options: BacktestKlineQueryOptions,
) {
  const reportStart = stringValue(metadata?.start) || stringValue(report.summary?.start_date)
  const reportEnd = stringValue(metadata?.end) || stringValue(report.summary?.end_date)
  if (!options.preferTradeWindow && (reportStart || reportEnd)) {
    return {
      start: reportStart || undefined,
      end: reportEnd || undefined,
    }
  }

  const tradeTimes = trades.flatMap((trade) => [trade.open_time, trade.close_time]).filter(Boolean)
  if (!tradeTimes.length && (reportStart || reportEnd)) {
    return {
      start: reportStart || undefined,
      end: reportEnd || undefined,
    }
  }
  if (!tradeTimes.length) return {}
  const paddingDays = options.paddingDays ?? BACKTEST_KLINE_PADDING_DAYS
  return {
    start: shiftIsoDate(minString(tradeTimes), -paddingDays),
    end: shiftIsoDate(maxString(tradeTimes), paddingDays),
  }
}

function normalizeProductSymbol(value: string) {
  const normalized = value.trim().replace(/_MAIN$/i, '').replace(/\.MAIN$/i, '')
  const match = normalized.match(/[A-Za-z]+/)
  return (match?.[0] || normalized).toLowerCase()
}

function normalizeMarketContract(value: string | null | undefined, symbol: string, exchange: string) {
  const raw = String(value || '').trim()
  if (!raw) return `${symbol}.MAIN`
  const parts = raw.split('.').filter(Boolean)

  if (parts.length >= 3 && parts[1].toUpperCase() === 'MAIN') return `${parts[0].toLowerCase()}.MAIN`
  if (parts.length === 2 && parts[1].toUpperCase() === 'MAIN') return `${parts[0].toLowerCase()}.MAIN`
  if (parts.length === 2 && isExchangeCode(parts[1])) return normalizeActualContract(parts[0], parts[1])
  if (parts.length === 2 && isExchangeCode(parts[0])) return normalizeActualContract(parts[1], parts[0])
  if (/_MAIN$/i.test(raw)) return `${normalizeProductSymbol(raw)}.MAIN`
  if (/\.MAIN$/i.test(raw)) return `${normalizeProductSymbol(raw)}.MAIN`
  if (/^[A-Za-z]+\d+$/i.test(raw)) return exchange ? normalizeActualContract(raw, exchange) : raw.toLowerCase()
  return raw
}

function normalizeActualContract(contract: string, exchange: string) {
  const normalizedContract = contract.replace(/_/g, '').toLowerCase()
  return `${exchange.toUpperCase()}.${normalizedContract}`
}

function normalizeMarketInterval(value: string) {
  const normalized = value.trim().toLowerCase()
  if (['d', 'day', 'daily', '1day'].includes(normalized)) return '1d'
  const minuteMatch = normalized.match(/^(\d+)\s*(m|min|minute|minutes)$/)
  if (minuteMatch) return `${minuteMatch[1]}m`
  return normalized
}

function normalizeExchange(value: string) {
  return value ? value.trim().toUpperCase() : ''
}

function exchangeFromVtSymbol(value: string) {
  const parts = value.split('.').filter(Boolean)
  const last = parts.at(-1)
  return last && isExchangeCode(last) ? last : ''
}

function isExchangeCode(value: string) {
  return /^[A-Z]{2,8}$/i.test(value) && value.toUpperCase() !== 'MAIN'
}

function firstTradeValue(trades: BacktestTrade[], key: keyof BacktestTrade) {
  for (const trade of trades) {
    const value = trade[key]
    if (value !== undefined && value !== null && value !== '') return String(value)
  }
  return ''
}

function firstTradeRawValue(trades: BacktestTrade[], key: string) {
  for (const trade of trades) {
    const value = trade.raw_payload?.[key]
    if (value !== undefined && value !== null && value !== '') return String(value)
  }
  return ''
}

function stringValue(value: unknown) {
  return value === undefined || value === null ? '' : String(value)
}

function objectRecord(value: unknown) {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null
}

function minString(values: string[]) {
  return values.reduce((min, value) => (value < min ? value : min), values[0])
}

function maxString(values: string[]) {
  return values.reduce((max, value) => (value > max ? value : max), values[0])
}

function shiftIsoDate(value: string, days: number) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  date.setDate(date.getDate() + days)
  return date.toISOString()
}
