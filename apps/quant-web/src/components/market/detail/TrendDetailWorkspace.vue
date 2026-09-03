<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import MarketDetailFactStrip from '@/components/market/detail/MarketDetailFactStrip.vue'
import MarketDetailInsightDeck from '@/components/market/detail/MarketDetailInsightDeck.vue'
import MarketDetailSectionTabs from '@/components/market/detail/MarketDetailSectionTabs.vue'
import NewowTrendChartStage from '@/components/market/detail/NewowTrendChartStage.vue'
import { useNewowTrendDetail } from '@/composables/useNewowTrendDetail'
import type { BarData } from '@/types/market'
import type { DetailViewModel, MarketDetailDisclosureSection, MarketDetailHeaderModel, MarketDetailIdentity } from '@/types/marketDetail'
import type { NewowTrendDetailResponse, NewowWarning } from '@/types/newow'
import { buildNewowDetailViewModel } from '@/utils/newowViewModel'

const props = defineProps<{
  identity: MarketDetailIdentity
  header: MarketDetailHeaderModel
  bars: readonly BarData[]
}>()

const emit = defineEmits<{
  'history-availability': [available: boolean]
}>()

const tabs = ref<InstanceType<typeof MarketDetailSectionTabs> | null>(null)
const activeTab = ref<string | null>(null)
const identity = computed(() => props.identity)
const bars = computed(() => props.bars)
const loader = useNewowTrendDetail({ identity, bars })
const model = computed(() => buildNewowDetailViewModel({
  identity: props.identity,
  header: props.header,
  data: loader.data.value as unknown as NewowTrendDetailResponse | null,
}))
const disclosureIdentity = computed(() => [
  props.identity.view,
  props.identity.symbol,
  props.identity.seriesKind,
  props.identity.frequency,
  loader.data.value?.meta.request_identity ?? 'newow-unavailable',
].join(':'))
const disclosureSections = computed<readonly MarketDetailDisclosureSection[]>(() => (
  buildDisclosureSections(
    model.value,
    loader.data.value as unknown as NewowTrendDetailResponse | null,
    loader.loading.value,
  )
))
const notices = computed(() => buildNotices(
  loader.data.value as unknown as NewowTrendDetailResponse | null,
  loader.loading.value,
))

function openHistory() {
  tabs.value?.openHistory()
}

defineExpose({ openHistory })

watch(() => model.value.history.length, (value) => {
  emit('history-availability', value > 0)
}, { immediate: true })
watch(() => props.identity, () => { activeTab.value = null }, { deep: true })
onBeforeUnmount(loader.dispose)

function buildDisclosureSections(
  viewModel: DetailViewModel,
  data: NewowTrendDetailResponse | null,
  loading: boolean,
): readonly MarketDetailDisclosureSection[] {
  if (data === null) {
    return [
      loading
        ? { ...viewModel.disclosureSections[0]!, summary: '正在读取 Newow 趋势数据', tone: 'default' }
        : viewModel.disclosureSections[0]!,
      {
        id: 'newow-calculation-unavailable',
        title: '计算身份',
        summary: loading ? '正在读取 Newow API 身份' : 'Newow API 身份不可用',
        updatedAt: null,
        tone: loading ? 'default' : 'unavailable',
        rows: [
          { label: '策略状态', value: loading ? '正在读取' : '不可用', source: 'newow' },
          { label: '计算身份', value: loading ? '正在读取' : '不可用', source: 'newow' },
          { label: '公式版本', value: loading ? '正在读取' : '不可用', source: 'newow' },
        ],
      },
      {
        id: 'newow-data-unavailable',
        title: '主力与数据',
        summary: loading ? '基础 completed D1 K 线（等候 Newow）' : '仅基础 completed D1 K 线',
        updatedAt: props.header.asOf,
        tone: loading ? 'default' : 'unavailable',
        rows: [
          { label: 'Newow API', value: loading ? '正在读取' : '不可用', source: 'newow' },
          { label: '序列', value: '真实主力', source: 'market' },
          { label: '回退范围', value: '仅基础 completed D1 K 线', source: 'market' },
        ],
      },
    ]
  }

  const [trend, riskShape, marketData] = viewModel.disclosureSections
  const latestBar = data.bars.at(-1)
  return [
    {
      ...trend!,
      rows: [
        ...trend!.rows,
        { label: '策略身份', value: data.meta.strategy_code, source: 'newow' },
        { label: '配置身份', value: data.meta.profile_id, source: 'newow' },
        { label: '计算身份', value: data.meta.calculation_identity, source: 'newow' },
      ],
    },
    riskShape!,
    {
      ...marketData!,
      rows: [
        ...marketData!.rows,
        { label: 'Bar 政策', value: data.bar_policy === 'completed_only' ? '仅已完成 D1' : '不可用', source: 'newow' },
        { label: '最新 Bar 来源身份', value: latestBar?.source_identity ?? '不可用', source: 'newow' },
        { label: '数据修订身份', value: data.meta.data_revision_identity ?? '未提供', source: 'newow' },
        { label: '请求身份', value: data.meta.request_identity, source: 'newow' },
      ],
    },
  ]
}

function buildNotices(data: NewowTrendDetailResponse | null, loading: boolean): readonly string[] {
  const values = [
    '仅展示已完成 D1；未完成 Bar 不进入 Newow 事实。',
    '蓝色仅表示 Newow 的空仓或风险阶段，不表示建立期货空单。',
  ]
  if (data === null) {
    if (loading) {
      return [
        ...values,
        '正在读取 Newow 趋势数据；读取完成前仅显示基础 completed D1 K 线。',
      ]
    }
    return [
      ...values,
      'Newow 趋势策略数据不可用，以下仅显示基础 completed D1 K 线；不显示趋势带、Marker 或杯柄。',
      'Newow 不可用时不推断主力换月或跨合约状态。',
    ]
  }
  values.push(data.rollover_seams.length > 0
    ? `当前窗口包含 ${data.rollover_seams.length} 处主力换月；分界仅表示物理合约切换，不表示交易机会。`
    : '当前窗口未报告主力换月；状态仍按物理合约段独立计算。')
  values.push(...data.warnings.map(warningLabel))
  return values
}

function warningLabel(warning: NewowWarning): string {
  if (warning === 'NEWOW_TREND_WARMUP_INSUFFICIENT') return '趋势带 warm-up 不足，当前趋势不可用'
  if (warning === 'NEWOW_D123_WARMUP_INSUFFICIENT') return 'D1/D2/D3 warm-up 不足，当前风险不可用'
  return '杯柄 warm-up 不足，当前形态不可用'
}
</script>

<template>
  <section
    class="trend-workspace"
    data-detail-workspace="trend"
    :data-newow-state="loader.data.value !== null ? 'ready' : loader.loading.value ? 'loading' : 'unavailable'"
  >
    <p class="trend-workspace__semantic" role="status">
      {{ model.semanticBanner.text }}
    </p>
    <MarketDetailFactStrip :facts="model.facts" />
    <ul class="trend-workspace__notices" aria-label="趋势数据边界">
      <li v-for="notice in notices" :key="notice">{{ notice }}</li>
    </ul>
    <p
      v-if="loader.error.value"
      class="trend-workspace__unavailable"
      data-newow-state="unavailable"
      role="status"
    >
      趋势策略数据不可用；当前页面不会从基础 K 线推断 Newow 状态。
    </p>
    <MarketDetailInsightDeck
      :identity-key="disclosureIdentity"
      :sections="disclosureSections"
      :default-open="true"
      default-open-all
    />
    <NewowTrendChartStage
      :data="loader.data.value"
      :generic-bars="bars"
      :loading="loader.loading.value"
    />
    <MarketDetailSectionTabs
      ref="tabs"
      :tabs="[]"
      :active-id="activeTab"
      :history="model.history"
      @select="activeTab = $event"
    />
  </section>
</template>

<style scoped>
.trend-workspace { display: grid; gap: var(--gy-space-4); }
.trend-workspace__semantic,
.trend-workspace__notices,
.trend-workspace__unavailable {
  margin: 0;
  padding: var(--gy-space-3);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-md);
  background: var(--gy-bg-panel);
}
.trend-workspace__semantic {
  color: var(--gy-status-warning);
  background: color-mix(in srgb, var(--gy-status-warning) 10%, transparent);
}
.trend-workspace__notices {
  display: grid;
  gap: var(--gy-space-1);
  padding-left: calc(var(--gy-space-3) + 1.2rem);
  color: var(--gy-text-secondary);
  font-size: var(--gy-font-size-sm);
  line-height: 1.5;
}
.trend-workspace__unavailable {
  border-color: var(--gy-detail-warning-border);
  color: var(--gy-status-warning);
  background: var(--gy-surface-warning);
}
</style>
