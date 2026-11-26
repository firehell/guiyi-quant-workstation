<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { getMarketAfterCloseReference, getMarketAfterCloseSection, getReferenceSummary, getReferenceTrades } from '@/api/referenceTrading'
import { formatBeijingInstant, formatDecimalText } from '@/utils/marketDisplay'
import { NEWOW_PRODUCT_FREQUENCIES, NEWOW_PRODUCT_STRATEGIES, type NewowAuxiliaryComponent, type NewowProductIdentity } from '@/types/newowProduct'
import type { MarketAfterCloseReference, MarketAfterCloseSection, MarketAfterCloseSectionQuery, ReferenceSummary, ReferenceTradeView } from '@/types/referenceTrading'
import { projectNewowAuxiliaryReadiness } from '@/utils/newowDetailPresentation'
import NewowCupFactsPanel from './NewowCupFactsPanel.vue'
import NewowExplanationPanel from './NewowExplanationPanel.vue'
import NewowSharedAuxiliaryStage from './NewowSharedAuxiliaryStage.vue'
import { buildNewowAuxiliaryDisclosure } from './newowProductChartPrimitives'

const props = defineProps<{ product: string; strategy: string; frequency: string }>()
const emit = defineEmits<{ selected: [selection: { source: MarketAfterCloseReference; snapshot: string } | null] }>()
const busy = ref(false)
const error = ref(false)
const source = ref<MarketAfterCloseReference | null>(null)
const rows = ref<ReferenceTradeView[]>([])
const summary = ref<ReferenceSummary | null>(null)
const revision = ref(0)

const auxiliaryOptions = [
  { id: 'zhaoyao_mirror', label: '主力照妖镜' },
  { id: 'up_down_energy', label: '涨跌动能' },
  { id: 'main_force_control', label: '主力控盘' },
  { id: 'trend_reversal', label: '趋势转折' },
] as const
type SectionChoice = Exclude<NewowAuxiliaryComponent, 'macd'> | 'comparator'
const selectedSection = ref<SectionChoice>('zhaoyao_mirror')
const sectionRevision = ref(0)
const sectionLoading = ref(false)
const sectionError = ref(false)
const section = shallowRef<MarketAfterCloseSection | null>(null)
const sectionIdentity = computed<NewowProductIdentity | null>(() => {
  const strategy = NEWOW_PRODUCT_STRATEGIES.find(item => item === props.strategy)
  const frequency = NEWOW_PRODUCT_FREQUENCIES.find(item => item === props.frequency)
  return strategy && frequency ? { product: props.product, strategy, frequency, seriesKind: 'actual_dominant' } : null
})
const comparatorAvailable = computed(() => props.strategy === 'oscillation' && ['1w', '1d', '60m'].includes(props.frequency))
const cupAvailable = computed(() => props.strategy === 'trend' && props.frequency === '1d')
const auxiliary = computed(() => section.value?.result?.section === 'auxiliary' ? section.value.result : null)
const comparator = computed(() => section.value?.result?.section === 'comparator' ? section.value.result : null)
const readiness = computed(() => projectNewowAuxiliaryReadiness(
  auxiliary.value?.value, section.value?.chart?.value?.bars.at(-1),
))
const cup = computed(() => auxiliary.value?.value?.component === 'cup_handle' ? auxiliary.value.value : null)
const disclosure = computed(() => {
  const current = auxiliary.value
  return current?.value ? buildNewowAuxiliaryDisclosure(
    current.value.component, current.meta.identity.frequency, current.status.status,
  ).disclosure : null
})

watch(() => [props.product, props.strategy, props.frequency], () => {
  selectedSection.value = 'zhaoyao_mirror'
}, { flush: 'sync' })
watch(() => [source.value, sectionIdentity.value, selectedSection.value, sectionRevision.value] as const,
  async ([published, identity, selected], _, onCleanup) => {
    sectionLoading.value = false
    sectionError.value = false
    section.value = null
    if (!published || !identity) return
    const controller = new AbortController()
    onCleanup(() => controller.abort())
    const common = { identity, asOf: published.cutoff }
    const query: MarketAfterCloseSectionQuery = selected === 'comparator'
      ? { ...common, section: 'comparator' }
      : { ...common, section: 'auxiliary', component: selected }
    sectionLoading.value = true
    try {
      const saved = await getMarketAfterCloseSection(query, { signal: controller.signal })
      if (!controller.signal.aborted) section.value = saved
    } catch {
      if (!controller.signal.aborted) sectionError.value = true
    } finally {
      if (!controller.signal.aborted) sectionLoading.value = false
    }
  },
)
watch(() => [props.product, props.strategy, props.frequency, revision.value], async (_, __, onCleanup) => {
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  const options = { signal: controller.signal }
  busy.value = true
  emit('selected', null)
  error.value = false
  source.value = null
  rows.value = []
  summary.value = null
  try {
    const result = await getMarketAfterCloseReference({
      product: props.product, strategy: props.strategy, frequency: props.frequency,
    }, options)
    if (!result || controller.signal.aborted) return
    const window = { since: result.since, through: result.through, cutoff: result.cutoff }
    const page = await getReferenceTrades(result.stream_id, window, options)
    if (page.seq !== result.seq || page.revision_id !== result.revision_id) throw new Error('REFERENCE_SNAPSHOT_CHANGED')
    if (controller.signal.aborted) return
    emit('selected', { source: result, snapshot: page.snapshot })
    const totals = await getReferenceSummary(result.stream_id, window, page.snapshot, options)
    if (controller.signal.aborted) return
    source.value = result
    rows.value = page.items
    summary.value = totals
  } catch {
    if (!controller.signal.aborted) error.value = true
  } finally {
    if (!controller.signal.aborted) busy.value = false
  }
}, { immediate: true })
</script>

<template>
  <section aria-label="牛哇盘后参考交易" :aria-busy="busy" class="market-reference">
    <h3>牛哇盘后参考交易</h3>
    <p v-if="busy" role="status">正在读取盘后结果…</p>
    <p v-else-if="error" role="alert">盘后参考结果暂不可读。<button type="button" @click="revision++">重新读取</button></p>
    <p v-else-if="!source" role="status">该策略暂无已发布盘后结果。</p>
    <template v-else>
      <p>数据截至 {{ source.through }} · 计算完成 {{ formatBeijingInstant(source.computed_at) }}</p>
      <p v-if="summary">已完成 {{ summary.closed_count }} 笔 · 累计参考收益
        {{ formatDecimalText(summary.sum_return_percentage_points, { maximumFractionDigits: 2, signed: true }) }} 百分点</p>
      <table v-if="rows.length">
        <thead><tr><th>合约</th><th>状态</th><th>建仓时间</th><th>建仓参考价</th><th>清仓时间</th><th>清仓参考价</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.reference_trade_id">
          <td>{{ row.physical_contract }}</td><td>{{ row.status }}</td>
          <td>{{ formatBeijingInstant(row.entry_bar_end) }}</td><td>{{ row.entry_reference_price }}</td>
          <td>{{ row.exit_bar_end ? formatBeijingInstant(row.exit_bar_end) : '—' }}</td><td>{{ row.exit_reference_price ?? '—' }}</td>
        </tr></tbody>
      </table>
      <p v-else role="status">该窗口暂无参考交易记录。</p>
      <section v-if="sectionIdentity" class="market-reference__sections" aria-label="已保存的盘后指标与比较">
        <div class="market-reference__options" role="group" aria-label="盘后指标与比较">
          <button v-for="option in auxiliaryOptions" :key="option.id" type="button"
            :aria-pressed="selectedSection === option.id" @click="selectedSection = option.id">{{ option.label }}</button>
          <button v-if="cupAvailable" type="button" :aria-pressed="selectedSection === 'cup_handle'"
            @click="selectedSection = 'cup_handle'">杯柄</button>
          <button v-if="comparatorAvailable" type="button" :aria-pressed="selectedSection === 'comparator'"
            @click="selectedSection = 'comparator'">页面比较</button>
        </div>
        <p v-if="sectionLoading" role="status">正在读取已保存的盘后指标…</p>
        <p v-else-if="sectionError" role="alert">盘后快照暂不可读。<button type="button" @click="sectionRevision++">重新读取</button></p>
        <p v-else-if="section?.status === 'pending'" role="status">当前盘后结果尚待生成指标快照。<button type="button" @click="sectionRevision++">重新读取</button></p>
        <p v-else-if="section?.status === 'unavailable'" role="status">当前组合没有可用的已保存指标快照。</p>
        <template v-else-if="section?.status === 'ready'">
          <p>盘后指标截至 {{ formatBeijingInstant(section.result.meta.as_of) }}</p>
          <NewowExplanationPanel v-if="comparator" mode="comparator" :response="null" lifecycle="not_requested"
            :error="null" :comparator-response="comparator" :comparator-lifecycle="comparator.status.status" :comparator-error="null" />
          <template v-else-if="selectedSection === 'cup_handle'">
            <p v-if="readiness?.message" role="status">{{ readiness.message }}</p>
            <template v-for="segment in cup?.segments ?? []" :key="segment.segment_id">
              <NewowCupFactsPanel v-if="segment.status.status === 'ready'"
                :witnesses="Array.isArray(segment.data) ? segment.data : []" :physical-contract="segment.physical_contract"
                :segment-id="segment.segment_id" />
              <p v-else role="status">{{ segment.physical_contract }} · {{ segment.status.reason_code ?? '该区段杯柄事实暂不可用' }}</p>
            </template>
          </template>
          <template v-else>
            <NewowSharedAuxiliaryStage label="盘后辅助指标" :chart="section.chart" :auxiliary="auxiliary"
              :component="selectedSection === 'comparator' ? null : selectedSection" :lifecycle="auxiliary?.status.status" />
            <p v-if="readiness && readiness.message !== '当前可计算'" role="status">{{ readiness.message }}</p>
            <p v-if="disclosure">{{ disclosure }}</p>
          </template>
        </template>
      </section>
    </template>
  </section>
</template>

<style scoped>
.market-reference{min-width:0;overflow:auto}.market-reference table{width:100%;border-collapse:collapse;white-space:nowrap;text-align:left}
.market-reference td,.market-reference th{padding:6px 12px;border-bottom:1px solid var(--gy-border)}
.market-reference__sections{margin-block-start:12px}
.market-reference__options{display:flex;flex-wrap:wrap;gap:8px}
.market-reference__options button{padding:5px 10px;border:1px solid var(--gy-border);border-radius:5px;background:var(--gy-bg-panel);color:var(--gy-text-secondary)}
.market-reference__options button[aria-pressed="true"]{border-color:var(--gy-accent);color:var(--gy-accent)}
</style>
