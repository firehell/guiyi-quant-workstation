<script setup lang="ts">
import { computed, h, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NDataTable,
  NDescriptions,
  NDescriptionsItem,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSelect,
  NSwitch,
  NTag,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import KlineChart from '@/components/kline/KlineChart.vue'
import { getMarketBars } from '@/api/market'
import {
  addReviewAttachment,
  createReviewFromBacktestTrade,
  getReview,
  getReviewBacktestTrades,
  getReviewStats,
  getReviewTags,
  getReviews,
  updateReview,
} from '@/api/review'
import type { BarData, KlineMarker } from '@/types/market'
import type { ReviewNote, ReviewSourceTrade, ReviewStats, ReviewTag } from '@/types/review'

interface KlineChartExpose {
  focusTime: (time: string) => void
}

const message = useMessage()
const route = useRoute()
const router = useRouter()
const chartRef = ref<KlineChartExpose | null>(null)
const loading = ref(false)
const loadingBars = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const trades = ref<ReviewSourceTrade[]>([])
const reviews = ref<ReviewNote[]>([])
const tags = ref<ReviewTag[]>([])
const stats = ref<ReviewStats | null>(null)
const selectedReview = ref<ReviewNote | null>(null)
const selectedTrade = ref<ReviewSourceTrade | null>(null)
const bars = ref<BarData[]>([])
const activeMarkerId = ref<string | null>(null)
const attachmentPath = ref('')

const reviewedFilter = ref<string>('all')

const tagOptions = computed(() => {
  const byType = (type: ReviewTag['tag_type']) => tags.value.filter((tag) => tag.tag_type === type).map((tag) => ({ label: tag.name, value: tag.name }))
  return {
    mistake: byType('mistake'),
    phase: byType('market_phase'),
    rule: [...byType('entry_rule'), ...byType('exit_rule')],
    emotion: byType('emotion'),
  }
})

const filteredTrades = computed(() => {
  if (reviewedFilter.value === 'reviewed') return trades.value.filter((trade) => trade.reviewed)
  if (reviewedFilter.value === 'unreviewed') return trades.value.filter((trade) => !trade.reviewed)
  return trades.value
})

const markerData = computed<KlineMarker[]>(() => {
  if (!selectedReview.value) return []
  const markers: KlineMarker[] = []
  if (selectedReview.value.open_time) {
    markers.push({
      id: 'open',
      time: selectedReview.value.open_time,
      label: `${selectedReview.value.direction === 'long' ? '开多' : '开空'} ${briefNote(selectedReview.value.entry_reason)}`,
      color: selectedReview.value.direction === 'long' ? '#ef4444' : '#22c55e',
      position: selectedReview.value.direction === 'long' ? 'belowBar' : 'aboveBar',
      shape: selectedReview.value.direction === 'long' ? 'arrowUp' : 'arrowDown',
    })
  }
  if (selectedReview.value.close_time) {
    markers.push({
      id: 'close',
      time: selectedReview.value.close_time,
      label: `${selectedReview.value.direction === 'long' ? '平多' : '平空'} ${briefNote(selectedReview.value.exit_reason)}`,
      color: '#94a3b8',
      position: selectedReview.value.direction === 'long' ? 'aboveBar' : 'belowBar',
      shape: selectedReview.value.direction === 'long' ? 'arrowDown' : 'arrowUp',
    })
  }
  return markers
})

const tradeColumns: DataTableColumns<ReviewSourceTrade> = [
  {
    title: '交易',
    key: 'id',
    width: 86,
    render: (row) => h('button', { class: 'link-button', onClick: () => openTrade(row) }, `#${row.id}`),
  },
  { title: '品种', key: 'symbol', width: 74 },
  { title: '周期', key: 'period', width: 70 },
  {
    title: '方向',
    key: 'direction',
    width: 70,
    render: (row) => h(NTag, { size: 'small', type: row.direction === 'long' ? 'error' : 'success' }, { default: () => (row.direction === 'long' ? '多' : '空') }),
  },
  {
    title: '盈亏',
    key: 'net_pnl',
    render: (row) => h('span', { class: row.net_pnl >= 0 ? 'text-up' : 'text-down' }, formatMoney(row.net_pnl)),
  },
  {
    title: '状态',
    key: 'reviewed',
    width: 78,
    render: (row) => h(NTag, { size: 'small', type: row.reviewed ? 'success' : 'warning' }, { default: () => (row.reviewed ? '已复盘' : '待复盘') }),
  },
]

onMounted(async () => {
  await loadAll()
  await applyInitialSelection()
})

async function loadAll() {
  loading.value = true
  error.value = null
  try {
    const [tradeRows, reviewRows, tagRows, statRows] = await Promise.all([
      getReviewBacktestTrades(),
      getReviews(),
      getReviewTags(),
      getReviewStats(),
    ])
    trades.value = tradeRows
    reviews.value = reviewRows
    tags.value = tagRows
    stats.value = statRows
  } catch (err) {
    error.value = apiError(err, '加载复盘数据失败')
  } finally {
    loading.value = false
  }
}

async function openTrade(trade: ReviewSourceTrade) {
  selectedTrade.value = trade
  const review = trade.review_id ? await getReview(trade.review_id) : await createReviewFromBacktestTrade(trade.id)
  selectedReview.value = normalizeReview(review)
  await loadBars(selectedReview.value)
  await loadAll()
}

async function applyInitialSelection() {
  const reviewId = numericQuery(route.query.review_id)
  if (reviewId) {
    await openReviewById(reviewId)
    return
  }
  const tradeId = numericQuery(route.query.trade_id)
  if (tradeId) await openTradeById(tradeId)
}

async function openReviewById(reviewId: number) {
  try {
    const review = normalizeReview(await getReview(reviewId))
    selectedReview.value = review
    selectedTrade.value = review.source || null
    await loadBars(review)
  } catch (err) {
    error.value = apiError(err, '打开复盘记录失败')
  }
}

async function openTradeById(tradeId: number) {
  try {
    const review = normalizeReview(await createReviewFromBacktestTrade(tradeId))
    selectedReview.value = review
    selectedTrade.value = review.source || null
    await loadBars(review)
    await loadAll()
  } catch (err) {
    error.value = apiError(err, '打开交易复盘失败')
  }
}

async function loadBars(review: ReviewNote) {
  const period = review.entry_interval || review.period
  if (!review.symbol || !review.contract || !period) return
  loadingBars.value = true
  try {
    const response = await getMarketBars({
      symbol: review.symbol,
      contract: review.contract,
      period,
      start: dateOnly(review.kline_window_start || review.open_time),
      end: dateOnly(review.kline_window_end || review.close_time),
      limit: 10000,
    })
    bars.value = response.bars || []
    await nextTick()
    focusMarker('open')
  } finally {
    loadingBars.value = false
  }
}

async function saveReview() {
  if (!selectedReview.value) return
  saving.value = true
  try {
    const updated = await updateReview(selectedReview.value.id, {
      entry_reason: selectedReview.value.entry_reason,
      exit_reason: selectedReview.value.exit_reason,
      market_phase: selectedReview.value.market_phase,
      is_system_compliant: selectedReview.value.is_system_compliant,
      mistake_tags: selectedReview.value.mistake_tags,
      setup_tags: selectedReview.value.setup_tags,
      emotion_tags: selectedReview.value.emotion_tags,
      execution_note: selectedReview.value.execution_note,
      improvement_note: selectedReview.value.improvement_note,
      screenshot_path: selectedReview.value.screenshot_path,
      review_score: selectedReview.value.review_score,
    })
    selectedReview.value = normalizeReview(updated)
    message.success('复盘已保存')
    await loadAll()
  } catch (err) {
    error.value = apiError(err, '保存复盘失败')
  } finally {
    saving.value = false
  }
}

function openKlineFromReview() {
  if (!selectedReview.value) return
  const review = selectedReview.value
  void router.push({
    name: 'market',
    query: {
      symbol: review.symbol || undefined,
      contract: review.contract || undefined,
      period: review.entry_interval || review.period || undefined,
      report_id: review.report_id ? String(review.report_id) : undefined,
      trade_id: review.trade_id ? String(review.trade_id) : undefined,
      trade_no: review.trade_no || review.source?.trade_no || undefined,
      time: review.entry_time || review.open_time || undefined,
      strategy: review.strategy_name || undefined,
    },
  })
}

function normalizeReview(review: ReviewNote) {
  review.setup_tags = review.setup_tags || review.rule_tags || []
  review.improvement_note = review.improvement_note || review.lesson || null
  review.screenshot_path = review.screenshot_path || review.screenshot_paths?.[0] || ''
  review.entry_interval = review.entry_interval || review.period
  review.entry_time = review.entry_time || review.open_time
  review.exit_time = review.exit_time || review.close_time
  review.hold_bars = review.hold_bars ?? numberFrom(review.extra?.hold_bars ?? review.extra?.holding_bars, null)
  return review
}

async function addAttachment() {
  if (!selectedReview.value || !attachmentPath.value) return
  await addReviewAttachment(selectedReview.value.id, { file_path: attachmentPath.value, file_type: 'image' })
  selectedReview.value = await getReview(selectedReview.value.id)
  attachmentPath.value = ''
}

function focusMarker(side: 'open' | 'close') {
  if (!selectedReview.value) return
  const time = side === 'open' ? selectedReview.value.open_time : selectedReview.value.close_time
  if (!time) return
  activeMarkerId.value = side
  chartRef.value?.focusTime(time)
}

function dateOnly(value: string | null | undefined) {
  return value ? value.slice(0, 10) : undefined
}

function numericQuery(value: unknown) {
  const numeric = Number(value)
  return Number.isFinite(numeric) && numeric > 0 ? numeric : null
}

function numberFrom(value: unknown, fallback: number | null = 0) {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : fallback
}

function formatDateTime(value: string | null | undefined) {
  return value ? value.replace('T', ' ').slice(0, 16) : '-'
}

function formatMoney(value: number | null | undefined) {
  return (value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2, minimumFractionDigits: 2 })
}

function formatPct(value: number | null | undefined) {
  return `${((value || 0) * 100).toFixed(1)}%`
}

function briefNote(value: string | null | undefined) {
  if (!value) return ''
  return value.length > 18 ? `${value.slice(0, 18)}...` : value
}

function apiError(err: unknown, fallback: string) {
  if (typeof err === 'object' && err !== null && 'response' in err) {
    const response = (err as { response?: { data?: { detail?: string } } }).response
    return response?.data?.detail || fallback
  }
  return err instanceof Error ? err.message : fallback
}
</script>

<template>
  <div class="review-page">
    <NAlert v-if="error" type="error" :bordered="false">{{ error }}</NAlert>

    <section class="stats-grid">
      <div class="metric">
        <span>复盘数</span>
        <strong>{{ stats?.total_reviews || 0 }}</strong>
      </div>
      <div class="metric">
        <span>最常见错误</span>
        <strong>{{ stats?.mistake_tags[0]?.name || '-' }}</strong>
      </div>
      <div class="metric">
        <span>最有效规则</span>
        <strong>{{ stats?.rule_effectiveness[0]?.name || '-' }}</strong>
      </div>
      <div class="metric">
        <span>主要行情阶段</span>
        <strong>{{ stats?.market_phase[0]?.name || '-' }}</strong>
      </div>
    </section>

    <section class="workspace-grid">
      <aside class="panel source-panel">
        <div class="panel__header">
          <div>
            <h2>交易来源</h2>
            <p>复盘对象可以是回测交易，后期可扩展为手工交易</p>
          </div>
          <NButton size="small" :loading="loading" @click="loadAll">刷新</NButton>
        </div>
        <NSelect
          v-model:value="reviewedFilter"
          class="filter"
          :options="[
            { label: '全部', value: 'all' },
            { label: '待复盘', value: 'unreviewed' },
            { label: '已复盘', value: 'reviewed' },
          ]"
        />
        <NDataTable
          :columns="tradeColumns"
          :data="filteredTrades"
          :loading="loading"
          :bordered="false"
          :single-line="false"
          size="small"
          :pagination="{ pageSize: 10 }"
        />
      </aside>

      <main class="panel kline-panel">
        <div class="panel__header">
          <div>
            <h2>K线定位</h2>
            <p>{{ selectedReview ? `${selectedReview.symbol} ${selectedReview.contract} ${selectedReview.period}` : '选择一笔交易开始复盘' }}</p>
          </div>
          <div class="actions">
            <NButton size="small" :disabled="!selectedReview" @click="focusMarker('open')">定位开仓</NButton>
            <NButton size="small" :disabled="!selectedReview" @click="focusMarker('close')">定位平仓</NButton>
            <NButton size="small" :disabled="!selectedReview" @click="openKlineFromReview">行情K线</NButton>
          </div>
        </div>
        <KlineChart
          ref="chartRef"
          :bars="bars"
          :markers="markerData"
          :active-marker-id="activeMarkerId"
          :loading="loadingBars"
          :error="error"
        />
        <div v-if="selectedReview" class="kline-note">
          <strong>交易点备注</strong>
          <span>报告：#{{ selectedReview.report_id || '-' }} / 交易：#{{ selectedReview.trade_id || selectedReview.source_id || '-' }}</span>
          <span>周期：{{ selectedReview.entry_interval || selectedReview.period || '-' }} / 持仓：{{ selectedReview.hold_bars ?? '-' }}K</span>
          <span>开仓：{{ selectedReview.entry_reason || '-' }}</span>
          <span>平仓：{{ selectedReview.exit_reason || '-' }}</span>
          <span>执行：{{ selectedReview.execution_note || '-' }}</span>
        </div>
      </main>

      <aside class="panel review-form-panel">
        <div class="panel__header">
          <div>
            <h2>复盘卡</h2>
            <p>记录原因、标签和下一次改进</p>
          </div>
          <NButton type="primary" size="small" :disabled="!selectedReview" :loading="saving" @click="saveReview">保存</NButton>
        </div>

        <div v-if="!selectedReview" class="empty-block">请选择左侧一笔交易</div>
        <template v-else>
          <NDescriptions :column="2" bordered size="small">
            <NDescriptionsItem label="Report ID">#{{ selectedReview.report_id || '-' }}</NDescriptionsItem>
            <NDescriptionsItem label="Trade ID">#{{ selectedReview.trade_id || selectedReview.source_id || '-' }}</NDescriptionsItem>
            <NDescriptionsItem label="品种">{{ selectedReview.symbol || '-' }}</NDescriptionsItem>
            <NDescriptionsItem label="入场周期">{{ selectedReview.entry_interval || selectedReview.period || '-' }}</NDescriptionsItem>
            <NDescriptionsItem label="方向">{{ selectedReview.direction === 'long' ? '多' : '空' }}</NDescriptionsItem>
            <NDescriptionsItem label="持仓K数">{{ selectedReview.hold_bars ?? '-' }}</NDescriptionsItem>
            <NDescriptionsItem label="盈亏" :class="(selectedReview.net_pnl || 0) >= 0 ? 'text-up' : 'text-down'">
              {{ formatMoney(selectedReview.net_pnl) }}
            </NDescriptionsItem>
            <NDescriptionsItem label="开仓">{{ formatDateTime(selectedReview.entry_time || selectedReview.open_time) }}</NDescriptionsItem>
            <NDescriptionsItem label="平仓">{{ formatDateTime(selectedReview.exit_time || selectedReview.close_time) }}</NDescriptionsItem>
          </NDescriptions>

          <NForm class="review-form" label-placement="top">
            <NFormItem label="是否符合苏冰系统">
              <NSwitch
                :value="selectedReview.is_system_compliant ?? false"
                @update:value="(value: boolean) => selectedReview && (selectedReview.is_system_compliant = value)"
              >
                <template #checked>符合</template>
                <template #unchecked>不符合/未确认</template>
              </NSwitch>
            </NFormItem>
            <NFormItem label="行情阶段">
              <NSelect v-model:value="selectedReview.market_phase" clearable :options="tagOptions.phase" />
            </NFormItem>
            <NFormItem label="错误标签">
              <NSelect v-model:value="selectedReview.mistake_tags" multiple filterable :options="tagOptions.mistake" />
            </NFormItem>
            <NFormItem label="形态/场景标签">
              <NSelect v-model:value="selectedReview.setup_tags" multiple filterable :options="tagOptions.rule" />
            </NFormItem>
            <NFormItem label="情绪标签">
              <NSelect v-model:value="selectedReview.emotion_tags" multiple filterable :options="tagOptions.emotion" />
            </NFormItem>
            <NFormItem label="开仓依据">
              <NInput v-model:value="selectedReview.entry_reason" type="textarea" :autosize="{ minRows: 3, maxRows: 5 }" />
            </NFormItem>
            <NFormItem label="平仓依据">
              <NInput v-model:value="selectedReview.exit_reason" type="textarea" :autosize="{ minRows: 3, maxRows: 5 }" />
            </NFormItem>
            <NFormItem label="执行备注">
              <NInput v-model:value="selectedReview.execution_note" type="textarea" :autosize="{ minRows: 3, maxRows: 5 }" />
            </NFormItem>
            <NFormItem label="改进计划">
              <NInput v-model:value="selectedReview.improvement_note" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" />
            </NFormItem>
            <NFormItem label="复盘评分">
              <NInputNumber v-model:value="selectedReview.review_score" :min="0" :max="100" />
            </NFormItem>
            <NFormItem label="截图路径">
              <div class="attachment-row">
                <NInput v-model:value="selectedReview.screenshot_path" placeholder="后置字段，可为空" />
                <NInput v-model:value="attachmentPath" placeholder="额外截图登记路径" />
                <NButton @click="addAttachment">登记</NButton>
              </div>
            </NFormItem>
            <NFormItem label="AI 总结预留">
              <NInput :value="selectedReview.ai_summary || '暂未接入 AI 总结；后续会基于交易、标签和K线窗口生成复盘建议。'" type="textarea" readonly />
            </NFormItem>
          </NForm>
        </template>
      </aside>
    </section>

    <section class="stats-grid stats-grid--bottom">
      <div class="panel">
        <h3>常见错误</h3>
        <p v-for="item in stats?.mistake_tags.slice(0, 6) || []" :key="item.name">{{ item.name }}：{{ item.count }}</p>
      </div>
      <div class="panel">
        <h3>规则有效性</h3>
        <p v-for="item in stats?.rule_effectiveness.slice(0, 6) || []" :key="item.name">
          {{ item.name }}：{{ formatMoney(item.net_pnl) }} / 胜率 {{ formatPct(item.win_rate) }}
        </p>
      </div>
      <div class="panel">
        <h3>行情阶段</h3>
        <p v-for="item in stats?.market_phase.slice(0, 6) || []" :key="item.name">
          {{ item.name }}：{{ item.count }} 笔 / {{ formatMoney(item.net_pnl) }}
        </p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.review-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

.panel {
  min-width: 0;
  padding: 14px;
  background: #0f172a;
  border: 1px solid #1e293b;
  border-radius: 6px;
}

.panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.panel__header h2 {
  margin: 0;
  font-size: 18px;
}

.panel__header p,
.empty-block {
  margin: 4px 0 0;
  color: #94a3b8;
}

.actions,
.attachment-row {
  display: flex;
  gap: 8px;
}

.attachment-row {
  flex-direction: column;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(130px, 1fr));
  gap: 10px;
}

.stats-grid--bottom {
  grid-template-columns: repeat(3, 1fr);
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 64px;
  padding: 10px;
  background: #111827;
  border: 1px solid #1f2937;
  border-radius: 6px;
}

.metric span {
  color: #94a3b8;
  font-size: 12px;
}

.metric strong {
  color: #e2e8f0;
  font-size: 18px;
}

.workspace-grid {
  display: grid;
  grid-template-columns: minmax(320px, 0.9fr) minmax(520px, 1.6fr) minmax(360px, 1fr);
  gap: 14px;
  align-items: start;
}

.filter {
  margin-bottom: 10px;
}

.review-form {
  margin-top: 12px;
}

.kline-note {
  display: grid;
  gap: 6px;
  margin-top: 10px;
  padding: 10px;
  color: #cbd5e1;
  background: #111827;
  border: 1px solid #1e293b;
  border-radius: 6px;
}

.kline-note strong {
  color: #e2e8f0;
}

.text-up {
  color: #ef4444;
}

.text-down {
  color: #22c55e;
}

.panel h3 {
  margin: 0 0 10px;
  font-size: 15px;
}

.panel p {
  margin: 6px 0;
  color: #cbd5e1;
}

@media (max-width: 1300px) {
  .workspace-grid,
  .stats-grid,
  .stats-grid--bottom {
    grid-template-columns: 1fr;
  }
}
</style>
