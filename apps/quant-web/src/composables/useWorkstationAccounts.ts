import { computed, onMounted, onScopeDispose, shallowRef } from 'vue'
import { monitorClient, type MonitorPage } from '@/api/simulationMonitor'
import { readSubingPortfolioStatus } from '@/api/subingPortfolio'
import { projectSubingAccount, projectTqAccount } from '@/utils/workstationAccounts'

function useAccountRead<T>(read: (signal: AbortSignal) => Promise<T>) {
  const value = shallowRef<T | null>(null)
  const status = shallowRef<'loading' | 'ready' | 'error'>('loading')
  const controller = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  async function load() {
    try {
      const next = await read(controller.signal)
      if (controller.signal.aborted) return
      value.value = next
      status.value = 'ready'
    } catch {
      if (!controller.signal.aborted) status.value = 'error'
    } finally {
      if (!controller.signal.aborted) timer = setTimeout(load, 10_000)
    }
  }
  onMounted(load)
  onScopeDispose(() => {
    controller.abort()
    clearTimeout(timer)
  })
  return { value, status }
}

export function useWorkstationAccounts() {
  const tq = useAccountRead(monitorClient.overview)
  const recentTqRecords = useAccountRead<MonitorPage>(signal => monitorClient.records({
    kind: 'all', product: '', status: '', startDay: '', endDay: '',
  }, signal))
  const subing = useAccountRead(readSubingPortfolioStatus)
  const tqAccount = computed(() => projectTqAccount(tq.value.value,
    recentTqRecords.status.value === 'ready' ? recentTqRecords.value.value : null))
  const subingAccount = computed(() => projectSubingAccount(subing.value.value))
  const rows = computed(() => [...tqAccount.value.rows, ...subingAccount.value.rows])
  return { tq, subing, recentTqRecords, tqAccount, subingAccount, rows }
}
