<script setup lang="ts">
import { computed, useId } from 'vue'

import type { NewowProductSectionResponse, NewowResourceLifecycle } from '@/types/newowProduct'
import {
  buildNewowComparatorPanelViewModel,
  buildNewowExplanationPanelViewModel,
  resolveNewowPanelRenderState,
} from '@/utils/newowProductViewModel'

const props = defineProps<{
  mode?: 'explanation' | 'comparator'
  response: NewowProductSectionResponse<'explanation'> | null
  lifecycle: NewowResourceLifecycle
  error: string | null
  comparatorResponse: NewowProductSectionResponse<'comparator'> | null
  comparatorLifecycle: NewowResourceLifecycle
  comparatorError: string | null
}>()

const titleId = useId()
const presentation = computed(() => resolveNewowPanelRenderState(props.lifecycle, props.response, props.error))
const model = computed(() => presentation.value.showValue && props.response?.value
  ? buildNewowExplanationPanelViewModel(props.response)
  : null)
const comparatorPresentation = computed(() => resolveNewowPanelRenderState(props.comparatorLifecycle, props.comparatorResponse, props.comparatorError))
const comparator = computed(() => comparatorPresentation.value.showValue && props.comparatorResponse?.value
  ? buildNewowComparatorPanelViewModel(props.comparatorResponse)
  : null)
</script>

<template>
  <div class="newow-explanation-layout">
    <article v-if="mode !== 'comparator'" class="newow-explanation" data-testid="newow-explanation-panel" :aria-labelledby="`newow-explanation-${titleId}`">
      <header>
        <h3 :id="`newow-explanation-${titleId}`">当前综合解释</h3>
        <p>只解释当前服务端快照；不得冒充历史开仓当时的依据。</p>
      </header>
      <p v-if="presentation.message" class="newow-explanation__state" role="status">
        {{ presentation.message }} <span v-if="presentation.staleAt">stale 读取时间 {{ presentation.staleAt }}</span>
      </p>
      <template v-if="model">
        <p>快照 as_of {{ model.contextAsOf }} · completed / strict-before</p>
        <details><summary>多周期来源上下文</summary>
        <table>
          <caption>多周期来源上下文</caption>
          <thead><tr><th>周期</th><th>Bar 时间</th><th>状态</th><th>缺口原因</th></tr></thead>
          <tbody><tr v-for="row in model.contextRows" :key="row.frequency"><td>{{ row.frequency }}</td><td>{{ row.barEnd }}</td><td>{{ row.state }}</td><td>{{ row.reason }}</td></tr></tbody>
        </table></details>
        <dl class="newow-explanation__facts">
          <div><dt>参考仓位区间</dt><dd>{{ model.composite.positionRange }}</dd></div>
          <div><dt>方向 / 方向分</dt><dd>{{ model.composite.direction }} / {{ model.composite.directionPoints }}</dd></div>
          <div><dt>确定性分</dt><dd>{{ model.composite.certainty }}</dd></div>
          <div><dt>ATR / 波动率</dt><dd>{{ model.composite.volatility }}</dd></div>
          <div><dt>第一行动 token</dt><dd><code>{{ model.composite.firstActionToken }}</code> · {{ model.composite.firstActionDetail }}</dd></div>
          <div><dt>综合解释 evidence</dt><dd>{{ model.composite.evidenceReason }}</dd></div>
          <div><dt>趋势目标 / 吸筹 evidence</dt><dd>{{ model.targetReason }}</dd></div>
        </dl>
        <section v-if="model.evidenceGaps.length" aria-label="解释证据缺口">
          <h4>Evidence gaps</h4>
          <ul>
            <li v-for="gap in model.evidenceGaps" :key="`${gap.area}:${gap.name}`">
              {{ gap.area }} · {{ gap.name }} · {{ gap.reason }}
            </li>
          </ul>
        </section>
        <details><summary>规则与来源事实</summary>
        <table>
          <caption>规则与来源事实</caption>
          <thead><tr><th>Role</th><th>周期 / Bar</th><th>规则</th><th>证据</th><th>原因</th></tr></thead>
          <tbody><tr v-for="row in model.sourceRows" :key="`${row.role}:${row.frequency}`"><td>{{ row.role }}</td><td>{{ row.frequency }} / {{ row.barEnd }}</td><td>{{ row.formulas }}</td><td>{{ row.evidence }}</td><td>{{ row.reason }}</td></tr></tbody>
        </table></details>
      </template>
    </article>

    <article v-if="mode !== 'explanation'" class="newow-comparator" data-testid="newow-comparator-panel" :aria-labelledby="`newow-comparator-${titleId}`">
      <header><h3 :id="`newow-comparator-${titleId}`">{{ comparator?.label ?? '五窗口页面比较器（独立理论结果）' }}</h3></header>
      <p v-if="comparatorPresentation.message" class="newow-explanation__state" role="status">
        {{ comparatorPresentation.message }} <span v-if="comparatorPresentation.staleAt">stale 读取时间 {{ comparatorPresentation.staleAt }}</span>
      </p>
      <template v-if="comparator">
        <p>当前 Segment：{{ comparator.physicalContract }} / {{ comparator.segmentId }}</p>
        <p>{{ comparator.disclosure }}</p>
        <p v-if="comparator.reason !== '—'">Evidence {{ comparator.reason }}</p>
        <table>
          <caption>样本内五窗口理论结果</caption>
          <thead><tr><th>窗口</th><th>累计</th><th>最大回撤</th><th>胜率</th><th>样本末</th></tr></thead>
          <tbody><tr v-for="row in comparator.windows" :key="row.window"><td>{{ row.window }}</td><td>{{ row.returnText }}</td><td>{{ row.drawdownText }}</td><td>{{ row.winRateText }}</td><td>{{ row.syntheticTerminal ? '理论平仓' : '无理论平仓' }}</td></tr></tbody>
        </table>
      </template>
    </article>
  </div>
</template>

<style scoped>
.newow-explanation-layout { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--gy-space-3); }
.newow-explanation, .newow-comparator { display: grid; gap: var(--gy-space-3); padding: var(--gy-space-3); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.newow-explanation h3, .newow-explanation p, .newow-comparator h3, .newow-comparator p, .newow-explanation dl { margin: 0; }
.newow-explanation header p, .newow-explanation__state { color: var(--gy-status-warning); }
.newow-explanation table, .newow-comparator table { width: 100%; table-layout:fixed; border-collapse: collapse; }
.newow-explanation th, .newow-explanation td, .newow-comparator th, .newow-comparator td { padding: var(--gy-space-2); border: 1px solid var(--gy-border); text-align: left; vertical-align: top; overflow-wrap:anywhere; }
.newow-explanation caption, .newow-comparator caption { padding-block: var(--gy-space-2); text-align: left; font-weight: 600; }
.newow-explanation__facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: var(--gy-space-2); }
.newow-explanation__facts div { padding: var(--gy-space-2); background: var(--gy-bg-elevated); }
.newow-explanation__facts dt { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.newow-explanation__facts dd { margin: 4px 0 0; }
@media (max-width: 900px) { .newow-explanation-layout { grid-template-columns: 1fr; } }
</style>
