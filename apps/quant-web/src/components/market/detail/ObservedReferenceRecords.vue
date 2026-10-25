<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import ReferenceTradePanel from './ReferenceTradePanel.vue'
import type { AlertEvent } from '@/types/market'
import { formatBeijingInstant } from '@/utils/marketDisplay'
const props = defineProps<{ strategy: string; product: string; frequency: string; events: readonly AlertEvent[]; unavailable?: boolean; through?: string; seriesKind?: string }>()
const emit = defineEmits<{ focus: [identity: { barEnd: string; physicalContract: string }] }>()
const visibleCount = ref(20)
watch(() => [props.product, props.frequency], () => { visibleCount.value = 20 })
const events = computed(() => [...props.events].sort((a, b) => Date.parse(b.bar_end)-Date.parse(a.bar_end)))
</script>
<template>
  <section class="observed-records" aria-label="实时首次事件审计" data-actual-reference-source="forward_observation">
    <ReferenceTradePanel :strategy="strategy" :product="product" :frequency="frequency" :through="through" :series-kind="seriesKind" @focus="emit('focus', $event)" />
    <details class="observed-records__audit"><summary>实际观察／预警审计（{{ events.length }}）</summary>
    <h3>实际观察／预警记录</h3>
    <p>当前图表范围读到 {{ events.length }} 条实际记录；首次事件仅在审计视图展示，不覆盖盘后 Canonical 历史；版本未记录时明确标注。</p>
    <p v-if="unavailable" role="status">实际预警读取未完成或失败，当前实际覆盖尚不能确认。</p>
    <div v-if="events.length" class="observed-records__table"><table><thead><tr><th>信号K线</th><th>物理合约</th><th>实际信号</th><th>首次观察时间</th><th>操作</th></tr></thead><tbody><tr v-for="event in events.slice(0, visibleCount)" :key="event.id"><td>{{ formatBeijingInstant(event.bar_end) }}</td><td>{{ event.contract }}</td><td>{{ event.result_codes.map(code => code === 'buy' ? '买入观察' : '卖出观察').join(' / ') }}</td><td>{{ formatBeijingInstant(event.detected_at) }}</td><td><button type="button" @click="emit('focus', { barEnd: event.bar_end, physicalContract: event.contract })">定位图表</button></td></tr></tbody></table></div>
    <p v-else-if="!unavailable">当前已加载图表范围未读到实际观察记录；不以历史重算补齐。</p>
    <button v-if="events.length > visibleCount" type="button" @click="visibleCount += 20">显示更多实际记录</button>
    </details>
  </section>
</template>
<style scoped>
.observed-records { border:1px solid var(--gy-border); border-radius:var(--gy-radius-lg); padding:0; min-width:0; background:var(--gy-bg-panel); }
.observed-records__audit { padding:12px 14px; } summary { cursor:pointer; color:var(--gy-text-muted); font-size:12px; }
h3 { font-size:15px; margin:8px 0; } p { color:var(--gy-text-muted); font-size:12px; line-height:1.7; }
.observed-records__table { overflow-x:auto; } table { width:100%; border-collapse:collapse; font-size:12px; white-space:nowrap; } th,td { text-align:left; padding:10px 8px; border-bottom:1px solid var(--gy-border); }
button { padding:7px 10px; border:1px solid var(--gy-border); border-radius:var(--gy-radius-sm); background:var(--gy-bg-panel); color:var(--gy-text-secondary); cursor:pointer; }
</style>
