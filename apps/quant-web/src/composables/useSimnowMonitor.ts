import { ref } from 'vue'
import { monitorClient, monitorQueryKey, validateOverview, validatePage, validateDetail, type MonitorClient, type MonitorOverview, type MonitorQuery, type MonitorPage, type MonitorDetail } from '../api/simnowMonitor.ts'

export function useSimnowMonitor(initial: MonitorQuery, client: MonitorClient = monitorClient, timers = { set: (fn: () => void) => setTimeout(fn, 5000), clear: (id: ReturnType<typeof setTimeout>) => clearTimeout(id) }, validity = { now: () => Date.now(), set: (fn: () => void, delay: number) => setTimeout(fn, delay), clear: (id: ReturnType<typeof setTimeout>) => clearTimeout(id) }) {
  const data = ref<MonitorOverview | null>(null), page = ref<MonitorPage | null>(null), detail = ref<MonitorDetail | null>(null)
  const selectedId = ref<string | null>(null), loading = ref(false), recordsLoading = ref(false), loadingMore = ref(false), detailLoading = ref(false)
  const error = ref<string | null>(null), recordsError = ref<string | null>(null), detailError = ref<string | null>(null), newRecords = ref(false)
  let queryValid = true
  let query = { ...initial }, active = false, visible = true, disposed = false, paged = false
  let timer: ReturnType<typeof setTimeout> | null = null, generation = 0, recordsGeneration = 0, detailGeneration = 0
  let expiryTimer: ReturnType<typeof setTimeout> | null = null
  function stopExpiry() { if (expiryTimer !== null) validity.clear(expiryTimer); expiryTimer = null }
  function revokeObserveReady() {
    stopExpiry()
    if (data.value?.observe_reconciliation_ready) data.value = { ...data.value, observe_reconciliation_ready: false, observe_reconciliation_status: 'stale' }
  }
  function armObserveExpiry() {
    stopExpiry()
    const value = data.value
    if (!value?.observe_reconciliation_ready) return
    const checked = Date.parse(value.observe_reconciliation_checked_at ?? ''), until = Date.parse(value.observe_reconciliation_valid_until ?? '')
    const now = validity.now(), remaining = Math.min(until - now, until - Date.parse(value.generated_at))
    if (!Number.isFinite(remaining) || now < checked || remaining <= 0) { revokeObserveReady(); return }
    expiryTimer = validity.set(revokeObserveReady, remaining)
  }
  let overviewAbort: AbortController | null = null, recordsAbort: AbortController | null = null, detailAbort: AbortController | null = null
  function stopTimer() { if (timer !== null) timers.clear(timer); timer = null }
  function schedule() { stopTimer(); if (active && visible && !disposed) timer = timers.set(() => { void refresh() }) }
  async function reloadRecords() {
    if (!queryValid || disposed || !visible) return
    loadingMore.value = false
    const id = ++recordsGeneration, key = monitorQueryKey(query)
    recordsAbort?.abort(); const abort = new AbortController(); recordsAbort = abort
    recordsLoading.value = true; recordsError.value = null
    try {
      const result = validatePage(await client.records({ ...query }, abort.signal))
      if (disposed || abort.signal.aborted || id !== recordsGeneration || key !== monitorQueryKey(query)) return
      page.value = result; paged = false; newRecords.value = false
    } catch { if (!disposed && !abort.signal.aborted && id === recordsGeneration) recordsError.value = '记录读取失败，已保留上次读取结果。' }
    finally { if (id === recordsGeneration) recordsLoading.value = false }
  }
  async function refresh() {
    if (disposed || !active || !visible) return
    stopTimer(); const id = ++generation
    overviewAbort?.abort(); const abort = new AbortController(); overviewAbort = abort
    loading.value = true; error.value = null
    try {
      const result = validateOverview(await client.overview(abort.signal))
      if (disposed || abort.signal.aborted || id !== generation) return
      if (data.value?.account && !result.account) throw Error('MONITOR_SOURCE_UNAVAILABLE')
      if (data.value?.account && result.account?.key !== data.value.account.key) { recordsGeneration++; recordsAbort?.abort(); recordsLoading.value = false; loadingMore.value = false; newRecords.value = false; page.value = null; closeDetail(); paged = false }
      data.value = result
      armObserveExpiry()
      if (result.status === 'unavailable') error.value = '监控来源暂不可用，未取得可核验的账户数据。'
      if (result.account) {
        const changed = page.value?.snapshot !== result.snapshot
        if (selectedId.value || paged || loadingMore.value) { if (changed) newRecords.value = true }
        else await reloadRecords()
      }
    } catch { if (!disposed && !abort.signal.aborted && id === generation) { revokeObserveReady(); error.value = '监控刷新失败，已保留上次快照及核验时间。' } }
    finally { if (id === generation) { loading.value = false; schedule() } }
  }
  async function loadMore() {
    if (!queryValid || !page.value?.next_cursor || loadingMore.value) return
    const id = ++recordsGeneration, key = monitorQueryKey(query), current = page.value
    recordsAbort?.abort(); const abort = new AbortController(); recordsAbort = abort; loadingMore.value = true
    try {
      const result = validatePage(await client.records({ ...query }, abort.signal, current.next_cursor!))
      if (disposed || abort.signal.aborted || id !== recordsGeneration || key !== monitorQueryKey(query)) return
      if (result.snapshot !== current.snapshot || result.items.some(r => current.items.some(old => old.id === r.id))) throw Error('MONITOR_SNAPSHOT_CHANGED')
      page.value = { ...result, items: [...current.items, ...result.items] }; paged = true; recordsError.value = null
    } catch { if (!disposed && !abort.signal.aborted && id === recordsGeneration) { newRecords.value = true; recordsError.value = '记录快照已变化或读取失败，请刷新列表后继续。' } }
    finally { if (id === recordsGeneration) loadingMore.value = false }
  }
  async function openDetail(id: string) {
    const token = ++detailGeneration
    detailAbort?.abort(); const abort = new AbortController(); detailAbort = abort
    if (id !== selectedId.value) detail.value = null
    selectedId.value = id; detailLoading.value = true; detailError.value = null
    try {
      const result = validateDetail(await client.detail(id, abort.signal))
      if (!disposed && !abort.signal.aborted && token === detailGeneration && result.selected.id === selectedId.value) detail.value = result
    } catch { if (!disposed && !abort.signal.aborted && token === detailGeneration) detailError.value = '执行链读取失败，可保留当前选择后重试。' }
    finally { if (token === detailGeneration) detailLoading.value = false }
  }
  function closeDetail() { detailGeneration++; detailAbort?.abort(); detail.value = null; selectedId.value = null; detailError.value = null; detailLoading.value = false }
  function setQueryValid(value: boolean) { queryValid = value; if (!value) { recordsGeneration++; recordsAbort?.abort(); recordsLoading.value = false; loadingMore.value = false; page.value = null } }
  function setQuery(value: MonitorQuery) {
    if (monitorQueryKey(query) === monitorQueryKey(value)) return
    query = { ...value }; recordsGeneration++; recordsAbort?.abort(); page.value = null; paged = false; newRecords.value = false; loadingMore.value = false
    if (active && visible && data.value?.account) void reloadRecords()
  }
  function setVisible(value: boolean) { if (value === visible) return; visible = value; if (!value) revokeObserveReady(); if (value && active) void refresh(); else { stopTimer(); generation++; overviewAbort?.abort(); recordsGeneration++; recordsAbort?.abort(); loading.value = false; recordsLoading.value = false; loadingMore.value = false } }
  function start() { active = true; void refresh() }
  function dispose() { revokeObserveReady(); disposed = true; active = false; stopTimer(); generation++; recordsGeneration++; detailGeneration++; overviewAbort?.abort(); recordsAbort?.abort(); detailAbort?.abort() }
  return { data, page, detail, selectedId, loading, recordsLoading, loadingMore, detailLoading, error, recordsError, detailError, newRecords, start, refresh, reloadRecords, loadMore, openDetail, closeDetail, setQuery, setQueryValid, setVisible, dispose }
}
