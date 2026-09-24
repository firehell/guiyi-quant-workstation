import { ref, readonly } from 'vue'
import {
  getReferencePoints, getReferenceStreams, getReferenceSummary, getReferenceTrades,
} from '../api/referenceTrading.ts'
import type { ReferenceRequestOptions } from '../api/referenceTrading.ts'
import type {
  ReferenceIdentity, ReferencePage, ReferencePoint, ReferenceStreamInfo, ReferenceSummary,
  ReferenceTradeView, ReferenceWindow,
} from '../types/referenceTrading.ts'
import { createReferencePageState } from './referencePageState.ts'

export interface ReferenceClient {
  streams: typeof getReferenceStreams
  trades: typeof getReferenceTrades
  summary: typeof getReferenceSummary
  points: typeof getReferencePoints
}

const defaultClient: ReferenceClient = {
  streams: getReferenceStreams, trades: getReferenceTrades,
  summary: getReferenceSummary, points: getReferencePoints,
}

export function useReferenceTrading(client: ReferenceClient = defaultClient) {
  const stream = ref<ReferenceStreamInfo | null>(null)
  const page = ref<ReferencePage<ReferenceTradeView> | null>(null)
  const summary = ref<ReferenceSummary | null>(null)
  const signals = ref<ReferencePoint[]>([])
  const indicators = ref<ReferencePoint[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  let generation = 0
  let controller: AbortController | null = null
  let window: ReferenceWindow | null = null
  const pages = createReferencePageState<ReferenceTradeView>(item => item.reference_trade_id)

  function invalidate() {
    generation += 1
    pages.reset()
    controller?.abort()
    controller = null
    stream.value = null; page.value = null; summary.value = null
    signals.value = []; indicators.value = []
    loading.value = false; error.value = null
  }

  async function refresh(identity: ReferenceIdentity, selectedWindow: ReferenceWindow) {
    invalidate()
    const current = generation
    const active = new AbortController()
    controller = active
    window = selectedWindow
    loading.value = true
    const options: ReferenceRequestOptions = { signal: active.signal }
    try {
      const matches = await client.streams(identity, options)
      if (current !== generation) return
      if (matches.length !== 1) throw new Error(matches.length ? 'STREAM_IDENTITY_AMBIGUOUS' : identity.mode === 'forward_observation' ? 'NOT_ENABLED' : 'NOT_BUILT')
      const chosen = matches[0]!
      stream.value = chosen
      if (!chosen.readable) throw new Error(identity.mode === 'forward_observation' ? 'NOT_ENABLED' : 'NOT_BUILT')
      const first = await client.trades(chosen.stream_id, selectedWindow, options)
      if (current !== generation) return
      const [stats, signalPoints, indicatorPoints] = await Promise.all([
        client.summary(chosen.stream_id, selectedWindow, first.snapshot, options),
        allPoints(chosen.stream_id, 'signals', selectedWindow, first.snapshot, options),
        allPoints(chosen.stream_id, 'indicators', selectedWindow, first.snapshot, options),
      ])
      if (current !== generation) return
      if (stats.snapshot !== first.snapshot) throw new Error('SNAPSHOT_CONFLICT')
      pages.first(`${chosen.stream_id}:${first.snapshot}:${first.revision_id}:${first.seq}`, first.items, first.next_cursor)
      stream.value = chosen
      page.value = first
      summary.value = stats
      signals.value = signalPoints
      indicators.value = indicatorPoints
    } catch (reason) {
      if (current === generation) error.value = referenceError(reason)
    } finally {
      if (current === generation) loading.value = false
    }
  }

  async function allPoints(
    streamId: string, kind: 'signals' | 'indicators', selectedWindow: ReferenceWindow,
    snapshot: string, options: ReferenceRequestOptions,
  ): Promise<ReferencePoint[]> {
    const points: ReferencePoint[] = []
    let cursor: string | undefined
    do {
      const result = await client.points(streamId, kind, selectedWindow, snapshot, {
        ...options, cursor, limit: 200,
      })
      if (result.snapshot !== snapshot) throw new Error('SNAPSHOT_CONFLICT')
      points.push(...result.items)
      if (points.length > 10_000) throw new Error('PRESENTATION_BUDGET_EXCEEDED')
      cursor = result.next_cursor ?? undefined
    } while (cursor)
    return points
  }

  async function loadMore() {
    const previous = page.value
    const chosen = stream.value
    const selectedWindow = window
    if (!previous?.next_cursor || !chosen || !selectedWindow || loading.value) return
    const current = generation
    loading.value = true; error.value = null
    try {
      const next = await client.trades(chosen.stream_id, selectedWindow, {
        snapshot: previous.snapshot, cursor: previous.next_cursor, signal: controller?.signal,
      })
      if (current !== generation) return
      if (next.snapshot !== previous.snapshot || next.revision_id !== previous.revision_id || next.seq !== previous.seq) {
        throw new Error('SNAPSHOT_CONFLICT')
      }
      const items = pages.append(`${chosen.stream_id}:${next.snapshot}:${next.revision_id}:${next.seq}`, previous.next_cursor, next.items, next.next_cursor)
      page.value = { ...next, items, next_cursor: pages.cursor }
    } catch (reason) {
      if (current === generation) {
        pages.reset(); page.value = null; summary.value = null; signals.value = []; indicators.value = []
        error.value = referenceError(reason)
      }
    } finally {
      if (current === generation) loading.value = false
    }
  }

  return {
    stream: readonly(stream), page: readonly(page), summary: readonly(summary),
    signals: readonly(signals), indicators: readonly(indicators),
    loading: readonly(loading), error: readonly(error), refresh, loadMore, dispose: invalidate,
  }
}

function referenceError(reason: unknown): string {
  const code = (reason as { response?: { data?: { detail?: { code?: string } } }; message?: string } | null)?.response?.data?.detail?.code
    ?? (reason instanceof Error ? reason.message : '')
  if (code === 'SNAPSHOT_CONFLICT' || code === 'CURSOR_CONFLICT') return '历史参考快照已变化，请刷新后重试。'
  if (code === 'NOT_BUILT') return '历史参考尚未构建。'
  if (code === 'NOT_ENABLED') return '盘中观察参考尚未启用。'
  if (code === 'PRESENTATION_NOT_MATERIALIZED') return '已保存的历史参考缺少展示数据，需要重新构建。'
  return '已保存的历史参考暂不可用，请稍后重试。'
}
