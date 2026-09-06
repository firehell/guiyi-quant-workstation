<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type {
  NewowProductSectionResponse,
  NewowReferenceTrade,
  NewowResourceLifecycle,
} from '@/types/newowProduct'
import {
  buildNewowReferencePanelViewModel,
  filterNewowReferenceRows,
  resolveNewowPanelRenderState,
  type NewowReferenceCategory,
} from '@/utils/newowProductViewModel'

const props = defineProps<{
  response: NewowProductSectionResponse<'reference'> | null
  chartResponse: NewowProductSectionResponse<'chart'> | null
  crossSectionCompatible: boolean
  lifecycle: NewowResourceLifecycle
  error: string | null
  selectedSignalId: string | null
  locateMessage: string | null
  loadingPage: boolean
}>()
const emit = defineEmits<{
  reload: [window: { performanceSince: string; performanceThrough: string }]
  'load-more': []
  locate: [trade: NewowReferenceTrade]
}>()

const filter = ref<'all' | NewowReferenceCategory | 'initial'>('all')
const expanded = ref<readonly string[]>([])
const performanceSince = ref('')
const performanceThrough = ref('')
const presentation = computed(() => resolveNewowPanelRenderState(props.lifecycle, props.response, props.error))
const model = computed(() => (
  presentation.value.showValue && props.response?.value
    ? buildNewowReferencePanelViewModel(props.response, props.chartResponse, props.crossSectionCompatible)
    : null
))
const visibleModel = computed(() => model.value === null ? null : filterNewowReferenceRows(model.value, filter.value))

watch(() => props.response?.value, (value) => {
  if (value === null || value === undefined) {
    performanceSince.value = ''
    performanceThrough.value = ''
    return
  }
  performanceSince.value = value.performance_since
  performanceThrough.value = value.performance_through
}, { immediate: true })

function toggle(id: string): void {
  expanded.value = expanded.value.includes(id)
    ? expanded.value.filter((item) => item !== id)
    : [...expanded.value, id]
}

function reload(): void {
  if (!performanceSince.value || !performanceThrough.value || performanceSince.value > performanceThrough.value) return
  emit('reload', { performanceSince: performanceSince.value, performanceThrough: performanceThrough.value })
}

function updateSince(event: Event): void { performanceSince.value = (event.target as HTMLInputElement).value }
function updateThrough(event: Event): void { performanceThrough.value = (event.target as HTMLInputElement).value }
function updateFilter(event: Event): void { filter.value = (event.target as HTMLSelectElement).value as typeof filter.value }
</script>

<template>
  <section class="newow-reference" aria-labelledby="newow-reference-title">
    <header class="newow-reference__header">
      <div>
        <h3 id="newow-reference-title">单品种乐观参考历史</h3>
        <p>固定乐观口径：只表达 long/flat；建仓与清仓采用同 Bar Close 或 API 参考价；零手续费、零滑点。不推断手数、不推断空单、不推断账户净值或真实收益；非因果回测、非模拟账户、非真实成交。</p>
      </div>
      <form class="newow-reference__window" @submit.prevent="reload">
        <label>统计起点 <input :value="performanceSince" type="date" @input="updateSince" /></label>
        <label>统计终点 <input :value="performanceThrough" type="date" @input="updateThrough" /></label>
        <button type="submit">读取统计窗口</button>
      </form>
    </header>

    <p v-if="presentation.message" class="newow-reference__state" role="status">
      {{ presentation.message }}
      <span v-if="presentation.staleAt">stale 读取时间 {{ presentation.staleAt }}</span>
    </p>

    <template v-if="model">
      <section class="newow-reference__summary" data-testid="newow-reference-summary" aria-label="参考交易统计摘要">
        <dl>
          <div><dt>已完成</dt><dd>{{ model.summary.closedCount }}</dd></div>
          <div><dt>胜率</dt><dd>{{ model.summary.winRateText }}</dd></div>
          <div><dt>平均单笔</dt><dd>{{ model.summary.meanText }}</dd></div>
          <div><dt>收益合计</dt><dd>{{ model.summary.sumText }} <small>{{ model.summary.sumUnit }}</small></dd></div>
          <div><dt>OPEN</dt><dd>{{ model.counts.open }}</dd></div>
          <div><dt>换月中断</dt><dd>{{ model.counts.interrupted }}</dd></div>
          <div><dt>期初已有</dt><dd>{{ model.counts.initial }}</dd></div>
        </dl>
        <p v-if="model.summary.closedCount === 0">暂无已完成参考交易；统计指标不是 0%。</p>
        <p>Performance window {{ model.performanceWindow.since }} → {{ model.performanceWindow.through }}</p>
        <p>实际可用至 {{ model.actualAvailableThrough }} · reference cutoff {{ model.performanceWindow.cutoff }}</p>
      </section>

      <div class="newow-reference__tools">
        <label>
          表格筛选
          <select :value="filter" aria-label="筛选参考历史" @change="updateFilter">
            <option value="all">全部记录</option>
            <option value="closed">CLOSED</option>
            <option value="open">OPEN</option>
            <option value="interrupted">ROLLOVER_INTERRUPTED</option>
            <option value="initial">期初已有</option>
          </select>
        </label>
        <span>筛选仅改变下表，不改变服务端统计或 Performance window。</span>
      </div>

      <div class="newow-reference__table-wrap">
        <table>
          <thead>
            <tr><th>记录</th><th>策略 / 周期</th><th>合约 / Segment</th><th>建仓</th><th>清仓</th><th>状态 / 持有</th><th>收益 / 估值</th><th>操作</th></tr>
          </thead>
          <tbody>
            <template v-for="row in visibleModel?.rows ?? []" :key="row.id">
              <tr :data-reference-category="row.category" :data-reference-initial="row.initial" :data-selected="selectedSignalId === row.trade.entry_signal_id">
                <td><code>{{ row.id }}</code></td>
                <td>{{ row.trade.strategy_code }} / {{ row.trade.frequency }}<br /><small>{{ row.trade.formula_versions.join(' / ') }}</small></td>
                <td>{{ row.trade.physical_contract }}<br /><small>{{ row.trade.segment_id }}</small></td>
                <td><code>{{ row.trade.entry_signal_id }}</code><br />{{ row.trade.entry_bar_end }}<br />参考价 {{ row.trade.entry_reference_price }}</td>
                <td><code>{{ row.trade.exit_signal_id ?? '—' }}</code><br />{{ row.trade.exit_bar_end ?? '—' }}<br />参考价 {{ row.trade.exit_reference_price ?? '—' }}</td>
                <td>{{ row.statusText }}<br />{{ row.trade.holding_bars }} Bars</td>
                <td>{{ row.returnText }}<br /><small>估值 {{ row.valuationText }}</small></td>
                <td>
                  <button type="button" :aria-label="`定位参考记录 ${row.id} 的建仓信号`" @click="emit('locate', row.trade)">定位</button>
                  <button type="button" :aria-label="`展开参考记录 ${row.id}`" :aria-expanded="expanded.includes(row.id)" @click="toggle(row.id)">Hint</button>
                </td>
              </tr>
              <tr v-if="expanded.includes(row.id)" class="newow-reference__details">
                <td colspan="8">
                  <p>身份 {{ row.trade.reference_model_version }} · {{ row.trade.futures_adaptation_version }}</p>
                  <p v-if="row.hints.length === 0">该记录没有服务端 Hint ID。</p>
                  <ul v-else>
                    <li v-for="hint in row.hints" :key="hint.id" :data-hint-availability="hint.availability">
                      <code>{{ hint.id }}</code> · {{ hint.text }}
                      <template v-if="hint.fact"> · known_at {{ hint.fact.known_at }} · anchor {{ hint.fact.anchor_price ?? '—' }} · {{ hint.fact.physical_contract }} / {{ hint.fact.segment_id }}</template>
                    </li>
                  </ul>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
      <p v-if="visibleModel?.rows.length === 0" class="newow-reference__state">当前筛选没有记录。</p>
      <p v-if="locateMessage" class="newow-reference__state" role="status">{{ locateMessage }}</p>
      <button v-if="model.nextBefore" type="button" :disabled="loadingPage" @click="emit('load-more')">加载更多参考历史</button>
    </template>
  </section>
</template>

<style scoped>
.newow-reference { display: grid; gap: var(--gy-space-3); }
.newow-reference__header, .newow-reference__summary, .newow-reference__state, .newow-reference__tools { padding: var(--gy-space-3); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.newow-reference__header { display: flex; justify-content: space-between; gap: var(--gy-space-3); }
.newow-reference h3, .newow-reference p, .newow-reference dl { margin: 0; }
.newow-reference__header p, .newow-reference__tools span, small { color: var(--gy-text-muted); }
.newow-reference__window, .newow-reference__tools { display: flex; flex-wrap: wrap; align-items: end; gap: var(--gy-space-2); }
.newow-reference__window label { display: grid; gap: 4px; }
.newow-reference button, .newow-reference input, .newow-reference select { min-height: 44px; padding: 0 var(--gy-space-2); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); color: var(--gy-text-primary); background: var(--gy-bg-panel); }
.newow-reference__summary dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: var(--gy-space-2); }
.newow-reference__summary dl div { padding: var(--gy-space-2); background: var(--gy-bg-elevated); }
.newow-reference__summary dt { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.newow-reference__summary dd { margin: 4px 0 0; font-variant-numeric: tabular-nums; }
.newow-reference__table-wrap { overflow-x: auto; }
.newow-reference table { width: 100%; min-width: 1120px; border-collapse: collapse; background: var(--gy-bg-panel); }
.newow-reference th, .newow-reference td { padding: var(--gy-space-2); border: 1px solid var(--gy-border); text-align: left; vertical-align: top; }
.newow-reference tr[data-selected="true"] { outline: 2px solid var(--gy-border-focus); outline-offset: -2px; }
.newow-reference__details td { background: var(--gy-bg-elevated); }
.newow-reference__state { color: var(--gy-status-warning); }
@media (max-width: 720px) { .newow-reference__header { flex-direction: column; } }
</style>
