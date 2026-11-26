import type { BarData, CanonicalBarDto, MarketBarsPageResponse } from '../types/market.ts'

export class MarketSeriesPhysicalIdentityError extends Error {
  readonly code = 'MARKET_SERIES_SEGMENT_CONFLICT'

  constructor() {
    super('MARKET_SERIES_SEGMENT_CONFLICT')
    this.name = 'MarketSeriesPhysicalIdentityError'
  }
}

export function normalizePhysicalContract(value: string | null | undefined): string | undefined {
  const normalized = value?.trim().toUpperCase()
  return normalized || undefined
}

export function resolveHistoricalPhysicalContract(
  page: MarketBarsPageResponse,
  bar: CanonicalBarDto,
): string | undefined {
  if (page.request.series_kind === 'contract') return normalizePhysicalContract(page.request.contract)
  if (page.request.series_kind === 'continuous') return undefined

  const matches = page.resolved_contract_segments.filter((segment) => (
    segment.start_trading_day <= bar.trading_day && bar.trading_day <= segment.end_trading_day
  ))
  if (matches.length !== 1) throw new MarketSeriesPhysicalIdentityError()
  const contract = normalizePhysicalContract(matches[0].contract)
  if (!contract) throw new MarketSeriesPhysicalIdentityError()
  return contract
}

/** Maps an already-normalized display DTO without repeating wire coercion. */
export function toBarData(item: CanonicalBarDto, physicalContract?: string): BarData {
  return {
    time: item.bar_end,
    trading_day: item.trading_day,
    ...(item.source_bar_sha256 ? { sourceBarSha256: item.source_bar_sha256 } : {}),
    physicalContract,
    open: item.open,
    high: item.high,
    low: item.low,
    close: item.close,
    volume: item.volume,
    turnover: item.turnover === null ? undefined : item.turnover,
    openInterest: item.open_interest === null ? undefined : item.open_interest,
  }
}

/** Display segments come from the resolver's mapping intervals and strict page
 * endpoint/quality validation, not a guessed contract or a strategy quality ID. */
export function historicalDisplayBar(page: MarketBarsPageResponse, bar: CanonicalBarDto): BarData {
  const physicalContract = resolveHistoricalPhysicalContract(page, bar)
  const segment = page.resolved_contract_segments.find(item => item.contract.toUpperCase() === physicalContract
    && item.start_trading_day <= bar.trading_day && bar.trading_day <= item.end_trading_day)
  const calculationSegmentId = segment ? `${physicalContract}:${segment.start_trading_day}`
    : page.request.series_kind === 'contract' && physicalContract ? `contract:${physicalContract}` : undefined
  return { ...toBarData(bar, physicalContract), calculationSegmentId }
}
