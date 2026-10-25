import { ref, shallowRef } from 'vue'
import { getForwardReferencePanel, getReferenceStreams, getReferenceTrades } from '../api/referenceTrading.ts'
import type { ForwardReferencePanel, ReferenceIdentity, ReferenceTradeView, ReferenceWindow } from '../types/referenceTrading.ts'
import { createForwardPanelCache } from '../utils/forwardPanelCache.ts'
import { createReferencePageState } from './referencePageState.ts'

const cache = createForwardPanelCache<ForwardReferencePanel>()
const defaultClient = { streams: getReferenceStreams, panel: getForwardReferencePanel, trades: getReferenceTrades }
export function useForwardReferencePanel(client = defaultClient) {
  const data = shallowRef<ForwardReferencePanel | null>(null)
  const rows = shallowRef<readonly ReferenceTradeView[]>([])
  const loading = ref(false), moreLoading = ref(false), capped = ref(false)
  const error = ref<string | null>(null), moreError = ref<string | null>(null)
  let generation = 0, controller = new AbortController()
  let window: ReferenceWindow | null = null, cursor: string | null = null
  const pages = createReferencePageState<ReferenceTradeView>(row => row.reference_trade_id)
  function dispose() {
    generation++; controller.abort(); controller = new AbortController()
    data.value = null; rows.value = []; error.value = null; moreError.value = null
    loading.value = false; moreLoading.value = false; capped.value = false; cursor = null; pages.reset()
  }
  async function refresh(identity: ReferenceIdentity, selectedWindow: ReferenceWindow, force = false) {
    dispose(); window = selectedWindow
    const own = generation, signal = controller.signal
    loading.value = true
    try {
      const matches = await client.streams({ ...identity, mode: 'forward_observation' }, { signal })
      if (own !== generation) return
      if (matches.length > 1) throw Error('AMBIGUOUS')
      const stream = matches[0]
      if (!stream) throw Error('NOT_RECORDED')
      if (!stream.readable || stream.recording_mode !== 'forward_observation') throw Error('NOT_ENABLED')
      const key = JSON.stringify([identity, selectedWindow, stream.stream_id, stream.active_revision_id, stream.latest_seq, stream.activation_generation, stream.health])
      const result = await cache.load(key, async active => {
        const value = await client.panel(stream.stream_id, selectedWindow, { signal: active })
        if (value.version !== 'forward_reference_panel_v1' || value.page.stream.stream_id !== stream.stream_id
          || value.page.stream.recording_mode !== 'forward_observation' || value.page.snapshot !== value.summary.snapshot
          || value.page.window.since !== selectedWindow.since || value.page.window.through !== selectedWindow.through
          || !Array.isArray(value.curve) || new Set(value.page.items.map(row => row.reference_trade_id)).size !== value.page.items.length) throw Error('SNAPSHOT_CONFLICT')
        return value
      }, signal, force)
      if (own !== generation) return
      const page = result.page
      pages.first(`${stream.stream_id}:${page.snapshot}:${page.revision_id}:${page.seq}`, page.items, page.next_cursor)
      rows.value = pages.items; capped.value = pages.capped; cursor = pages.cursor; data.value = result
    } catch (reason) { if (own === generation && !signal.aborted) error.value = displayError(reason) }
    finally { if (own === generation) loading.value = false }
  }
  async function loadMore() {
    const current = data.value, selected = window, before = cursor
    if (!current || !selected || !before || capped.value || moreLoading.value) return
    const own = generation
    moreLoading.value = true; moreError.value = null
    try {
      const next = await client.trades(current.page.stream.stream_id, selected, { signal: controller.signal, cursor: before, snapshot: current.page.snapshot })
      if (own !== generation) return
      if (next.snapshot !== current.page.snapshot || next.revision_id !== current.page.revision_id || next.seq !== current.page.seq) throw Error('SNAPSHOT_CONFLICT')
      rows.value = pages.append(`${current.page.stream.stream_id}:${next.snapshot}:${next.revision_id}:${next.seq}`, before, next.items, next.next_cursor)
      capped.value = pages.capped; cursor = pages.cursor
    } catch { if (own === generation) moreError.value = '记录读取失败或快照已变化；已载记录保留，请重新读取。' }
    finally { if (own === generation) moreLoading.value = false }
  }
  return { data, rows, loading, error, moreLoading, moreError, capped, hasMore: () => !!cursor, refresh, loadMore, dispose }
}
function displayError(reason: unknown) {
  const code = (reason as { response?: { data?: { detail?: { code?: string } } }; message?: string })?.response?.data?.detail?.code
    ?? (reason instanceof Error ? reason.message : '')
  if (code === 'NOT_RECORDED') return '此品种／周期尚无实时留存参考交易流；不使用历史重算或重绘记录补齐。'
  if (code === 'NOT_ENABLED') return '实时留存参考交易流当前未启用或不可读。'
  if (code === 'AMBIGUOUS') return '实时参考来源不唯一，暂不统计。'
  if (code.includes('CONFLICT')) return '参考快照已变化，请重新读取。'
  if (code === 'QUERY_BUDGET_EXCEEDED') return '参考记录超过本次读取预算，请缩小日期范围。'
  return '实时参考暂不可用，请重试；不会回退到历史重算。'
}
