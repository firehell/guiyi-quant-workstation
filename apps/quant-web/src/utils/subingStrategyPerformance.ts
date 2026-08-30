import { subingStrategyExitReasonLabel } from './subingStrategyRecords.ts'

const EPISODE_PAGE_SIZE = 20
const SHANGHAI_OFFSET = '+08:00'
const EMPTY_KPIS = {
  cumulativeLabel: '—',
  winRateLabel: '—',
  bestWorstLabel: '—',
  completedLabel: '—',
} as const

export const SUBING_PERFORMANCE_RANGE_OPTIONS = [
  { id: '1m', label: '近1月' },
  { id: '3m', label: '近3月' },
  { id: '6m', label: '近6月' },
  { id: 'ytd', label: '今年' },
  { id: '1y', label: '1年' },
  { id: 'all', label: '全部' },
] as const

export type SubingPerformanceRangeId = typeof SUBING_PERFORMANCE_RANGE_OPTIONS[number]['id']

export interface SubingTrendEpisodeInput {
  reference_change_percent: string | null
  exit_action: { effective_bar_end: string } | null
}

export interface SubingCumulativePoint {
  time: number
  value: number
}

export interface SubingTrendKpis {
  cumulativeLabel: string
  winRateLabel: string
  bestWorstLabel: string
  completedLabel: string
}

export interface SubingPerformanceTrend {
  points: SubingCumulativePoint[]
  kpis: SubingTrendKpis
}

function padDatePart(value: number): string {
  return String(value).padStart(2, '0')
}

function shanghaiYmd(iso: string): { year: number; month: number; day: number } | null {
  const instant = new Date(iso)
  if (!Number.isFinite(instant.getTime())) return null
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(instant)
  const mapped = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  const year = Number(mapped.year)
  const month = Number(mapped.month)
  const day = Number(mapped.day)
  if (![year, month, day].every(Number.isFinite)) return null
  return { year, month, day }
}

function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate()
}

function addCalendarMonths(
  year: number,
  month: number,
  day: number,
  deltaMonths: number,
): { year: number; month: number; day: number } {
  const monthIndex = month - 1 + deltaMonths
  const nextYear = year + Math.floor(monthIndex / 12)
  const nextMonthIndex = ((monthIndex % 12) + 12) % 12
  const nextMonth = nextMonthIndex + 1
  return {
    year: nextYear,
    month: nextMonth,
    day: Math.min(day, daysInMonth(nextYear, nextMonth)),
  }
}

function shanghaiMidnightMs(year: number, month: number, day: number): number {
  return Date.parse(
    `${year}-${padDatePart(month)}-${padDatePart(day)}T00:00:00${SHANGHAI_OFFSET}`,
  )
}

function rangeStartMs(
  range: SubingPerformanceRangeId,
  cutoffYmd: { year: number; month: number; day: number },
): number | null {
  if (range === 'all') return null
  if (range === 'ytd') return shanghaiMidnightMs(cutoffYmd.year, 1, 1)
  const months = range === '1m' ? 1 : range === '3m' ? 3 : range === '6m' ? 6 : 12
  const start = addCalendarMonths(cutoffYmd.year, cutoffYmd.month, cutoffYmd.day, -months)
  return shanghaiMidnightMs(start.year, start.month, start.day)
}

function parseChange(value: string | null): number | null {
  if (value === null) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function formatSignedPercent(value: number, digits: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`
}

function collectClosedRows(episodes: readonly SubingTrendEpisodeInput[]): Array<{ ms: number; change: number }> {
  const rows: Array<{ ms: number; change: number }> = []
  for (const episode of episodes) {
    const change = parseChange(episode.reference_change_percent)
    const ms = episode.exit_action
      ? Date.parse(episode.exit_action.effective_bar_end)
      : Number.NaN
    if (change === null || !Number.isFinite(ms)) continue
    rows.push({ ms, change })
  }
  rows.sort((left, right) => left.ms - right.ms)
  return rows
}

export function buildSubingPerformanceTrend(
  episodes: readonly SubingTrendEpisodeInput[],
  range: SubingPerformanceRangeId,
  resolvedCutoffIso: string,
): SubingPerformanceTrend {
  const cutoffMs = Date.parse(resolvedCutoffIso)
  const cutoffYmd = shanghaiYmd(resolvedCutoffIso)
  if (!Number.isFinite(cutoffMs) || cutoffYmd === null) {
    return { points: [], kpis: { ...EMPTY_KPIS } }
  }
  const startMs = rangeStartMs(range, cutoffYmd)
  const rows = collectClosedRows(episodes).filter((row) => (
    row.ms <= cutoffMs && (startMs === null || row.ms >= startMs)
  ))
  if (rows.length === 0) return { points: [], kpis: { ...EMPTY_KPIS } }

  const points: SubingCumulativePoint[] = []
  let cumulative = 0
  let positive = 0
  let best = rows[0].change
  let worst = rows[0].change
  for (const row of rows) {
    cumulative += row.change
    if (row.change > 0) positive += 1
    if (row.change > best) best = row.change
    if (row.change < worst) worst = row.change
    const time = Math.floor(row.ms / 1000)
    const last = points[points.length - 1]
    if (last && last.time === time) last.value = cumulative
    else points.push({ time, value: cumulative })
  }
  return {
    points,
    kpis: {
      cumulativeLabel: formatSignedPercent(cumulative, 2),
      winRateLabel: `+${Math.round(positive / rows.length * 100)}%`,
      bestWorstLabel: `${formatSignedPercent(best, 2)} / ${formatSignedPercent(worst, 2)}`,
      completedLabel: String(rows.length),
    },
  }
}

export function formatSubingMeanHoldingBars(value: string | null): string {
  if (value === null) return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? String(Math.round(parsed)) : '—'
}

export function nextSubingPerformanceEpisodeLimit(
  current: number,
  total: number,
): number {
  return Math.min(total, current + EPISODE_PAGE_SIZE)
}

export function subingPerformanceExitReasonRows(
  counts: ReadonlyArray<{ reason_code: string; count: number }>,
): Array<{ code: string; label: string; count: number }> {
  return counts.map(({ reason_code, count }) => ({
    code: reason_code,
    label: subingStrategyExitReasonLabel(reason_code),
    count,
  }))
}
