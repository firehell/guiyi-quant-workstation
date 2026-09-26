<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { getNewowFusion, type FusionComparison } from '@/api/newowFusion'
import type { NewowProductSectionResponse } from '@/types/newowProduct'
import { formatMarketDecimal, formatBeijingInstant } from '@/utils/marketDisplay'
const props = defineProps<{ response: NewowProductSectionResponse<'reference'> }>()
const result = ref<FusionComparison | null>(null)
const loading = ref(false)
const error = ref('')
let controller: AbortController | null = null
let generation = 0
watch(() => [props.response.meta.identity.product, props.response.meta.identity.frequency, props.response.meta.as_of, props.response.value?.reference_input_sha256, props.response.value?.performance_since, props.response.value?.performance_through], () => {
  generation++; controller?.abort(); result.value = null; loading.value = false; error.value = ''
})
onBeforeUnmount(() => { generation++; controller?.abort() })
async function load() {
  const value = props.response.value
  if (!value) return
  const token = ++generation
  controller?.abort(); controller = new AbortController()
  loading.value = true; error.value = ''
  const identity = props.response.meta.identity
  try {
    const next = await getNewowFusion({ identity: { product: identity.product, strategy: 'trend', frequency: identity.frequency, seriesKind: 'actual_dominant' }, section: 'reference', asOf: props.response.meta.as_of, performanceSince: value.performance_since, performanceThrough: value.performance_through }, { signal: controller.signal })
    if (token === generation) result.value = next
  } catch { if (token === generation) error.value = '融合参考读取失败，请重试。' }
  finally { if (token === generation) loading.value = false }
}
const names = { trend: '趋势', oscillation: '震荡', fusion: '融合' }
const states = { OPEN: '未清仓', CLOSED: '已完成', ROLLOVER_INTERRUPTED: '换月中断', DATA_INTERRUPTED: '数据中断' }
const display = (value: string | null) => value === null ? '—' : formatMarketDecimal(value)
</script>
<template>
  <section class="fusion-panel" aria-label="双策略融合参考模型">
    <header><div><strong>双策略融合参考</strong><p>趋势 / 震荡 / 融合独立统计 · 单仓 long/flat · 零成本页面参考</p></div><button :disabled="loading" @click="load">{{ loading ? '计算中…' : result ? '重新计算' : '查看三组结果' }}</button></header>
    <p v-if="response.value?.history_coverage === 'PARTIAL'">数据覆盖不完整，结果仅限已验证片段；中断不计入已完成收益。</p>
    <details><summary>融合配对规则</summary><p>同根先清仓，再建仓；同方向多信号优先震荡价，其次趋势价。允许跨策略建仓、清仓配对，持有期间不重复建仓。没有融合入场的清仓不计收益。换月、数据段切换中断，不跨合约配对；末根未清仓保持开放。</p></details>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="result">
      <p>{{ result.performance_since }} — {{ result.performance_through }} · 截至 {{ formatBeijingInstant(result.reference_cutoff) }}<small>{{ result.reference_model_version }}</small></p>
      <div class="fusion-panel__scroll"><table><thead><tr><th>模型</th><th>已完成</th><th>累计收益百分点</th><th>未清仓</th><th>中断</th></tr></thead><tbody><tr v-for="g in result.groups" :key="g.model"><th>{{ names[g.model] }}</th><td>{{ g.closed_count }}</td><td :class="Number(g.sum_return_percentage_points) >= 0 ? 'gain' : 'loss'">{{ display(g.sum_return_percentage_points) }}</td><td>{{ g.open_count }}</td><td>{{ g.interrupted_count }}</td></tr></tbody></table></div>
      <p>累计只简单相加窗口内建仓且已完成的参考收益；未清仓浮动、中断、期初已有单独展示。</p>
      <details><summary>融合交易记录（{{ result.items.length }} 条{{ result.records_truncated ? '，仅显示最近 200 条，统计为完整窗口' : '' }}）</summary><div class="fusion-panel__scroll"><table><thead><tr><th>合约 / 状态</th><th>建仓来源 / 时间 / 价格</th><th>清仓来源 / 时间 / 价格</th><th>已完成收益</th><th>未清仓浮动 / 中断前变化</th></tr></thead><tbody><tr v-for="r in result.items" :key="r.reference_trade_id"><td>{{ r.physical_contract }} · {{ states[r.status] }}<small v-if="r.statistics_membership === 'initial_before_window'">期初已有，不计入统计</small></td><td>{{ names[r.entry_source] }}<small>{{ formatBeijingInstant(r.entry_bar_end) }}</small>{{ display(r.entry_reference_price) }}</td><td>{{ r.exit_source ? names[r.exit_source] : '—' }}<small>{{ r.exit_bar_end ? formatBeijingInstant(r.exit_bar_end) : '—' }}</small>{{ display(r.exit_reference_price) }}</td><td :class="Number(r.reference_return_pct) >= 0 ? 'gain' : 'loss'">{{ display(r.reference_return_pct) }}{{ r.reference_return_pct !== null ? '%' : '' }}</td><td>{{ r.status === 'CLOSED' ? '—' : display(r.mark_change_pct) + (r.mark_change_pct !== null ? '%' : '') }}</td></tr></tbody></table></div></details>
    </template>
  </section>
</template>
<style scoped>
.fusion-panel { border:1px solid #e8ebf0; border-radius:8px; padding:16px; margin:16px 0; color:#30343b; }
header { display:flex; align-items:center; justify-content:space-between; gap:12px; } p,small { color:#8891a5; font-size:12px; } small { display:block; } button { background:#fff; border:1px solid #ff6b35; color:#ff6b35; border-radius:8px; padding:8px 12px; } .fusion-panel__scroll { overflow:auto; } table { width:100%; border-collapse:collapse; font-size:13px; white-space:nowrap; } th,td { text-align:left; padding:10px; border-bottom:1px solid #eef0f4; } .gain { color:#ff4248; } .loss { color:#22b957; } summary { cursor:pointer; font-size:13px; margin:10px 0; }
</style>
