<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getMarketChartProgress, type MarketChartProgress, type MarketStateRequest } from '@/api/market'
import { formatBeijingInstant } from '@/utils/marketDisplay'

const props = defineProps<{ identity: MarketStateRequest; historical: boolean }>()
const root = ref<HTMLElement | null>(null)
const progress = ref<MarketChartProgress | null>(null)
const failed = ref(false)
const rendered = ref<{ end: string; contract: string } | null>(null)
const request = new AbortController()
let timer: ReturnType<typeof setTimeout> | undefined
let observer: MutationObserver | undefined

function readRenderedEnd() {
  const chart = root.value?.parentElement?.querySelector<HTMLElement>('[data-kline-end]')
  const { klineEnd, klineContract, klineFrequency } = chart?.dataset ?? {}
  const owner = klineContract?.toLowerCase()
  const symbol = props.identity.symbol.toLowerCase()
  const matches = props.identity.contract
    ? owner === props.identity.contract.toLowerCase()
    : owner?.startsWith(symbol) && /^\d/.test(owner.slice(symbol.length))
  rendered.value = klineEnd && klineContract && matches && klineFrequency === props.identity.frequency
    ? { end: klineEnd, contract: klineContract }
    : null
}

async function refresh() {
  try {
    progress.value = await getMarketChartProgress(props.identity, request.signal)
    failed.value = false
  } catch {
    progress.value = null
    failed.value = true
  } finally {
    if (!request.signal.aborted) timer = setTimeout(refresh, 10_000)
  }
}

onMounted(() => {
  const workspace = root.value?.parentElement
  if (workspace) {
    observer = new MutationObserver(readRenderedEnd)
    observer.observe(workspace, {
      attributes: true,
      attributeFilter: ['data-kline-end', 'data-kline-contract', 'data-kline-frequency'],
      childList: true,
      subtree: true,
    })
    readRenderedEnd()
  }
  void refresh()
})

onBeforeUnmount(() => {
  request.abort()
  clearTimeout(timer)
  observer?.disconnect()
})

const status = computed(() => {
  if (props.historical) return '历史查看'
  if (failed.value) return '行情诊断不可用'
  const state = progress.value
  if (!state) return '正在读取行情进度'
  switch (state.status) {
    case 'historical': return '历史行情'
    case 'waiting': return state.phase === 'BREAK' ? '交易暂停' : state.phase === 'CLOSED' ? '已休市' : '等待本周期收线'
    case 'source': return '行情采集未跟上'
    case 'confirmation': return '完成确认未跟上'
    case 'unknown': return '行情进度未知'
    case 'confirmed':
      return rendered.value?.contract.toLowerCase() === state.contract?.toLowerCase()
        && Date.parse(rendered.value?.end ?? '') >= Date.parse(state.completed_end ?? '')
        ? '已更新至最新完成线' : '图表显示未跟上'
  }
})

const phaseName = computed(() => ({
  TRADING: '交易中', BREAK: '暂停交易', CLOSED: '休市', UNKNOWN: '未知',
})[progress.value?.phase ?? 'UNKNOWN'])
</script>

<template>
  <details ref="root" class="chart-progress" data-testid="market-chart-progress">
    <summary>
      {{ status }} <span>· 图表 {{ rendered ? formatBeijingInstant(rendered.end) : '未知' }}</span>
    </summary>
    <dl>
      <dt>交易时段</dt><dd>{{ phaseName }}</dd>
      <dt>诊断合约</dt><dd>{{ progress?.contract ?? rendered?.contract ?? '未知' }}</dd>
      <dt>本周期应完成</dt><dd>{{ progress?.expected_end ? formatBeijingInstant(progress.expected_end) : '—' }}</dd>
      <dt>采集最近 1 分钟观察</dt><dd>{{ progress?.source_end ? formatBeijingInstant(progress.source_end) : '未知' }}</dd>
      <dt>采集接收时间</dt><dd>{{ progress?.source_received_at ? formatBeijingInstant(progress.source_received_at) : '未知' }}</dd>
      <dt>服务端最近完成</dt><dd>{{ progress?.completed_end ? formatBeijingInstant(progress.completed_end) : '未知' }}</dd>
      <dt>浏览器最后绘制</dt><dd>{{ rendered ? formatBeijingInstant(rendered.end) : '未知' }}</dd>
    </dl>
  </details>
</template>

<style scoped>
.chart-progress {
  margin: 0.4rem 0;
  font-size: 0.8rem;
  color: var(--gy-text-muted, inherit);
}
summary { width: fit-content; cursor: pointer; }
dl {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 0.25rem 1rem;
  margin: 0.5rem 0;
}
dd { margin: 0; }
</style>
