import { BACKTEST_ARTIFACT_KINDS } from '../types/backtest.ts'
import type { ArtifactKind, BacktestRunDetail, RunStatus } from '../types/backtest.ts'


const STATUS_LABELS: Record<RunStatus, string> = {
  running: '运行中',
  succeeded: '已成功',
  failed: '失败',
  timed_out: '已超时',
  interrupted: '已中断',
}
const FAILURE_STATUSES = new Set<RunStatus>(['failed', 'timed_out', 'interrupted'])
const FIXED_FAILURE_ARTIFACTS: ArtifactKind[] = ['stdout_log', 'stderr_log']

export type BacktestRunStatusTagType = 'success' | 'info' | 'error'

export function backtestRunStatusLabel(status: RunStatus) {
  return STATUS_LABELS[status]
}

export function backtestRunStatusTagType(status: RunStatus): BacktestRunStatusTagType {
  if (status === 'succeeded') return 'success'
  if (status === 'running') return 'info'
  return 'error'
}

export function isBacktestFailureStatus(status: RunStatus) {
  return FAILURE_STATUSES.has(status)
}

export function formatBacktestDuration(run: Pick<BacktestRunDetail, 'status' | 'started_at' | 'finished_at'>) {
  if (run.status === 'running') return '进行中'
  if (!run.finished_at) return '—'
  const startedAt = Date.parse(run.started_at)
  const finishedAt = Date.parse(run.finished_at)
  if (!Number.isFinite(startedAt) || !Number.isFinite(finishedAt) || finishedAt < startedAt) return '—'

  const totalSeconds = Math.floor((finishedAt - startedAt) / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours) return `${hours} 小时 ${minutes} 分 ${seconds} 秒`
  if (minutes) return `${minutes} 分 ${seconds} 秒`
  return `${seconds} 秒`
}

export function visibleBacktestArtifacts(run: BacktestRunDetail): ArtifactKind[] {
  if (run.result) {
    return BACKTEST_ARTIFACT_KINDS.filter((kind) => run.result?.artifacts[kind])
  }
  return isBacktestFailureStatus(run.status) ? [...FIXED_FAILURE_ARTIFACTS] : []
}
