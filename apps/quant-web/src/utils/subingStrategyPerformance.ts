import { subingStrategyExitReasonLabel } from './subingStrategyRecords.ts'

const EPISODE_PAGE_SIZE = 20

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
