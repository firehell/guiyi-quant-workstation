<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import ReferenceTradePanel from './ReferenceTradePanel.vue'
import { getReferenceStreams } from '@/api/referenceTrading'
import type { AlertEvent } from '@/types/market'
import { formatBeijingInstant } from '@/utils/marketDisplay'
const props = defineProps<{ strategy: string; product: string; frequency: string; events: readonly AlertEvent[]; unavailable?: boolean }>()
const emit = defineEmits<{ focus: [identity: { barEnd: string; physicalContract: string }] }>()
const status = ref<'loading' | 'ready' | 'missing' | 'failed'>('loading')
let controller = new AbortController(), generation = 0
watch([() => props.strategy, () => props.product, () => props.frequency, () => props.events.reduce((latest, event) => Math.max(latest, event.id), 0)], async () => {
  controller.abort(); controller = new AbortController(); const current = ++generation
  status.value = 'loading'
  try {
    const streams = await getReferenceStreams({ strategy: props.strategy, product: props.product, frequency: props.frequency, mode: 'forward_observation' }, { signal: controller.signal })
    if (generation !== current) return
    if (streams.length > 1) throw new Error('ambiguous')
    status.value = streams.length === 1 && streams[0]?.readable ? 'ready' : 'missing'
  } catch { if (generation === current) status.value = 'failed' }
}, { immediate: true })
onBeforeUnmount(() => { controller.abort(); generation += 1 })
const visibleCount = ref(20)
watch(() => [props.product, props.frequency], () => { visibleCount.value = 20 })
const events = computed(() => [...props.events].sort((a, b) => Date.parse(b.bar_end)-Date.parse(a.bar_end)))
</script>
<template>
  <section class="observed-records" aria-label="实时首次事件审计" :data-actual-reference-status="status">
    <ReferenceTradePanel v-if="status === 'ready'" :strategy="strategy" :product="product" :frequency="frequency" />
    <p v-else-if="status === 'missing'" role="status">本周期暂无可读的实际参考交易流。以下为已保存的实际观察／预警，不代表账户成交；历史重算不会补写实际记录。</p>
    <p v-else-if="status === 'failed'" role="status">实际参考交易读取失败，不能用历史重算宣称实际运行结果。</p>
    <p v-else role="status">核对实际参考交易来源中…</p>
    <h3>实际观察／预警记录</h3>
    <p>当前图表范围读到 {{ events.length }} 条实际记录；首次事件仅在审计视图展示，不覆盖盘后 Canonical 历史；版本未记录时明确标注。</p>
    <p v-if="unavailable" role="status">实际预警读取未完成或失败，当前实际覆盖尚不能确认。</p>
    <div v-if="events.length" class="observed-records__table"><table><thead><tr><th>信号K线</th><th>物理合约</th><th>实际信号</th><th>首次观察时间</th><th>操作</th></tr></thead><tbody><tr v-for="event in events.slice(0, visibleCount)" :key="event.id"><td>{{ formatBeijingInstant(event.bar_end) }}</td><td>{{ event.contract }}</td><td>{{ event.result_codes.map(code => code === 'buy' ? '买入观察' : '卖出观察').join(' / ') }}</td><td>{{ formatBeijingInstant(event.detected_at) }}</td><td><button type="button" @click="emit('focus', { barEnd: event.bar_end, physicalContract: event.contract })">定位图表</button></td></tr></tbody></table></div>
    <p v-else-if="!unavailable">当前已加载范围未读到实际观察记录，图表保留有来源的历史重算参考。</p>
    <button v-if="events.length > visibleCount" type="button" @click="visibleCount += 20">显示更多实际记录</button>
  </section>
</template>
<style scoped>
.observed-records { border:1px solid var(--gy-border); border-radius:var(--gy-radius-lg); padding:var(--gy-panel-padding); min-width:0; background:var(--gy-bg-panel); }
h3 { font-size:15px; margin:8px 0; } p { color:var(--gy-text-muted); font-size:12px; line-height:1.7; }
.observed-records__table { overflow-x:auto; } table { width:100%; border-collapse:collapse; font-size:12px; white-space:nowrap; } th,td { text-align:left; padding:10px 8px; border-bottom:1px solid var(--gy-border); }
button { padding:7px 10px; border:1px solid var(--gy-border); border-radius:var(--gy-radius-sm); background:var(--gy-bg-panel); color:var(--gy-text-secondary); cursor:pointer; }
</style>
