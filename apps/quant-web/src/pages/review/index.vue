<script setup lang="ts">
/** 复盘中心：回测交易来源、deep-link 打开复盘、冻结 lineage K 线与正式上下文面板。 */
import { computed, h, nextTick, onMounted, ref, watch } from 'vue'
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
import ReviewFoundationPanel from '@/components/review/ReviewFoundationPanel.vue'
import { getBacktestReport, getBacktestValidationContextObservation } from '@/api/backtestApi'
import {
  addReviewAttachment,
  createReviewFromBacktestTrade,
  getReview,
  getReviewBars,
  getReviewBacktestTrades,
  getReviewStats,
  getReviewTags,
  getReviews,
  updateReview,
} from '@/api/review'
import type { BacktestReport, BacktestTrade } from '@/types/backtest'
import type { BacktestValidationContext } from '@/types/backtestValidation'
import type { BarData, KlineMarker } from '@/types/market'
import type { ReviewFormalLineage, ReviewNote, ReviewSourceTrade, ReviewStats, ReviewTag } from '@/types/review'
import type { ReviewFoundationContext } from '@/types/reviewFoundation'
import { resolveChartTheme } from '@/styles/chartTheme'
import { buildReviewFoundationContext, parseReviewDeepLinkQuery } from '@/utils/reviewFoundation'
import { toSafeApiError } from '@/utils/errorRedaction'
import { formatTradeMarkerText } from '@/utils/tradeMarker'

interface KlineChartExpose {
  focusTime: (time: string) => void
}

const message = useMessage()
const route = useRoute()
const router = useRouter()
const chartTheme = resolveChartTheme()
const chartRef = ref<KlineChartExpose | null>(null)
const loading = ref(false)
const loadingBars = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const klineError = ref<string | null>(null)
const trades = ref<ReviewSourceTrade[]>([])
const reviews = ref<ReviewNote[]>([])
const tags = ref<ReviewTag[]>([])
const stats = ref<ReviewStats | null>(null)
const selectedReview = ref<ReviewNote | null>(null)
const selectedTrade = ref<ReviewSourceTrade | null>(null)
const foundationReport = ref<BacktestReport | null>(null)
const foundationValidation = ref<BacktestValidationContext | null>(null)
const foundationValidationError = ref<string | null>(null)
const foundationLineage = ref<ReviewFormalLineage | null>(null)
const foundationLineageError = ref<string | null>(null)
const bars = ref<BarData[]>([])
const klineQueryItems = ref<Array<{ label: string; value: string }>>([])
const activeMarkerId = ref<string | null>(null)
const attachmentPath = ref('')
const reportIdFilter = ref<number | null>(null)
const savedReviewSnapshot = ref('')
/** 并发选择请求序号，防止快速切换时旧响应覆盖新选中项 */
let reviewSelectionRequestId = 0

const foundationContext = computed<ReviewFoundationContext>(() =>
  buildReviewFoundationContext({
    report: foundationReport.value,
    trade: {
      entry_signal_time:
        (selectedTrade.value as { entry_signal_time?: string | null } | null)?.entry_signal_time ?? null,
      open_time:
        selectedReview.value?.entry_time ||
        selectedReview.value?.open_time ||
        selectedTrade.value?.entry_time ||
        selectedTrade.value?.open_time ||
        null,
    },
    lineage: foundationLineage.value,
    lineage_error: foundationLineageError.value,
    validation_context: foundationValidation.value,
    validation_error: foundationValidationError.value,
  }),
)

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
  let rows = trades.value
  if (reportIdFilter.value) rows = rows.filter((trade) => trade.report_id === reportIdFilter.value)
  if (reviewedFilter.value === 'reviewed') return rows.filter((trade) => trade.reviewed)
  if (reviewedFilter.value === 'unreviewed') return rows.filter((trade) => !trade.reviewed)
  return rows
})

const hasUnsavedChanges = computed(() => {
  if (!selectedReview.value) return false
  return reviewSnapshot(selectedReview.value) !== savedReviewSnapshot.value
})

const canFocusOpen = computed(() => Boolean(selectedReview.value?.open_time && bars.value.length > 0))
const canFocusClose = computed(() => Boolean(selectedReview.value?.close_time && bars.value.length > 0))
const canOpenMarket = computed(() => Boolean(selectedReview.value && klineQueryItems.value.length > 0))

const markerData = computed<KlineMarker[]>(() => {
  if (!selectedReview.value) return []
  const markers: KlineMarker[] = []
  if (selectedReview.value.open_time) {
    markers.push({
      id: 'open',
      time: selectedReview.value.open_time,
      label: formatTradeMarkerText(selectedReview.value, 'open'),
      tooltip: `trade_id:${selectedReview.value.trade_id || selectedReview.value.source_id || '-'} ${selectedReview.value.direction === 'long' ? '开多' : '开空'} 价:${formatMoney(selectedReview.value.open_price)} 净盈亏:${formatMoney(selectedReview.value.net_pnl)} ${briefNote(selectedReview.value.entry_reason)}`,
      color: selectedReview.value.direction === 'long' ? chartTheme.up : chartTheme.down,
      position: selectedReview.value.direction === 'long' ? 'belowBar' : 'aboveBar',
      shape: selectedReview.value.direction === 'long' ? 'arrowUp' : 'arrowDown',
    })
  }
  if (selectedReview.value.close_time) {
    markers.push({
      id: 'close',
      time: selectedReview.value.close_time,
      label: formatTradeMarkerText(selectedReview.value, 'close'),
      tooltip: `trade_id:${selectedReview.value.trade_id || selectedReview.value.source_id || '-'} ${selectedReview.value.direction === 'long' ? '平多' : '平空'} 价:${formatMoney(selectedReview.value.close_price)} 净盈亏:${formatMoney(selectedReview.value.net_pnl)} ${briefNote(selectedReview.value.exit_reason)}`,
      color: chartTheme.textMuted,
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
    render: (row) =>
      h(
        'button',
        {
          class: 'link-button',
          onClick: (event: MouseEvent) => {
            event.stopPropagation()
            void openTrade(row)
          },
        },
        `#${row.id}`,
      ),
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
  await applyRouteSelection()
})

watch(
  () => [route.query.review_id, route.query.trade_id, route.query.report_id],
  () => {
    void applyRouteSelection()
  },
)

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

/** 选中交易：若无复盘则创建，并行加载 K 线与报告正式上下文。 */
async function openTrade(trade: ReviewSourceTrade) {
  const requestId = ++reviewSelectionRequestId
  selectedTrade.value = trade
  const review = trade.review_id ? await getReview(trade.review_id) : await createReviewFromBacktestTrade(trade.id)
  if (!isCurrentReviewSelection(requestId)) return
  selectedReview.value = normalizeReview(review)
  markReviewSaved(selectedReview.value)
  await Promise.all([
    loadBars(selectedReview.value, requestId),
    loadFoundationReport(selectedReview.value.report_id, requestId),
  ])
  await loadAll()
}

/** 根据 URL query（review_id / trade_id）打开对应复盘。 */
async function applyRouteSelection() {
  const requestId = ++reviewSelectionRequestId
  const deepLink = parseReviewDeepLinkQuery(route.query as Record<string, unknown>)
  reportIdFilter.value = deepLink.report_id
  if (deepLink.review_id) {
    await openReviewById(deepLink.review_id, requestId)
    return
  }
  if (deepLink.trade_id) {
    await openTradeById(deepLink.trade_id, requestId)
    return
  }
  if (!deepLink.report_id) clearSelectedReviewState()
}

async function loadFoundationReport(reportId: number | null | undefined, requestId: number) {
  foundationReport.value = null
  foundationValidation.value = null
  foundationValidationError.value = null
  if (!reportId) return
  const [reportResult, validationResult] = await Promise.allSettled([
    getBacktestReport(reportId),
    getBacktestValidationContextObservation(reportId),
  ])
  if (!isCurrentReviewSelection(requestId)) return
  foundationReport.value = reportResult.status === 'fulfilled' ? reportResult.value : null
  if (validationResult.status === 'fulfilled') {
    foundationValidation.value = validationResult.value.available ? validationResult.value.context || null : null
    foundationValidationError.value = validationResult.value.available
      ? null
      : `${validationResult.value.error_type || 'VALIDATION_EVIDENCE_UNAVAILABLE'}: ${validationResult.value.error_message || 'validation evidence is unavailable'}`
  } else {
    foundationValidationError.value = apiError(validationResult.reason, '验证证据不可用')
  }
}

async function openReviewById(reviewId: number, requestId = ++reviewSelectionRequestId) {
  try {
    const review = normalizeReview(await getReview(reviewId))
    if (!isCurrentReviewSelection(requestId)) return
    selectedReview.value = review
    selectedTrade.value = review.source || null
    markReviewSaved(review)
    await Promise.all([loadBars(review, requestId), loadFoundationReport(review.report_id, requestId)])
  } catch (err) {
    if (!isCurrentReviewSelection(requestId)) return
    error.value = apiError(err, '打开复盘记录失败')
  }
}

async function openTradeById(tradeId: number, requestId = ++reviewSelectionRequestId) {
  try {
    const review = normalizeReview(await createReviewFromBacktestTrade(tradeId))
    if (!isCurrentReviewSelection(requestId)) return
    selectedReview.value = review
    selectedTrade.value = review.source || null
    markReviewSaved(review)
    await Promise.all([loadBars(review, requestId), loadFoundationReport(review.report_id, requestId)])
    await loadAll()
  } catch (err) {
    if (!isCurrentReviewSelection(requestId)) return
    error.value = apiError(err, '打开交易复盘失败')
  }
}

/** 按冻结 lineage 拉取复盘窗口 K 线；空数据或失败分别写入 klineError / lineageError。 */
async function loadBars(review: ReviewNote, requestId = reviewSelectionRequestId) {
  const trade = reviewToBacktestTrade(review)
  if (!trade) return
  loadingBars.value = true
  klineError.value = null
  foundationLineage.value = null
  foundationLineageError.value = null
  bars.value = []
  klineQueryItems.value = []
  try {
    const result = await getReviewBars(review.id)
    if (!isCurrentReviewSelection(requestId)) return
    foundationLineage.value = result.lineage
    klineQueryItems.value = lineageDebugItems(result.lineage)
    bars.value = result.bars || []
    if (bars.value.length === 0) klineError.value = '冻结 lineage 的精确交易窗口未返回K线数据'
    await nextTick()
    if (bars.value.length > 0) focusMarker('open')
  } catch (err) {
    if (!isCurrentReviewSelection(requestId)) return
    foundationLineageError.value = apiError(err, '加载交易K线失败')
    klineError.value = foundationLineageError.value
  } finally {
    if (isCurrentReviewSelection(requestId)) loadingBars.value = false
  }
}

function clearSelectedReviewState() {
  selectedReview.value = null
  selectedTrade.value = null
  foundationReport.value = null
  foundationValidation.value = null
  foundationValidationError.value = null
  foundationLineage.value = null
  foundationLineageError.value = null
  bars.value = []
  klineQueryItems.value = []
  activeMarkerId.value = null
  klineError.value = null
}

function isCurrentReviewSelection(requestId: number) {
  return requestId === reviewSelectionRequestId
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
    markReviewSaved(selectedReview.value)
    message.success('复盘已保存')
    await loadAll()
  } catch (err) {
    error.value = apiError(err, '保存复盘失败')
  } finally {
    saving.value = false
  }
}

/** 跳转行情页并携带 report/trade/time 等 deep-link 参数。 */
function openKlineFromReview() {
  if (!selectedReview.value) return
  const review = selectedReview.value
  const query = klineQueryObject()
  void router.push({
    name: 'market-chart',
    query: {
      symbol: query.symbol || review.symbol || undefined,
      contract: query.contract || review.contract || undefined,
      period: query.interval || review.entry_interval || review.period || undefined,
      interval: query.interval || review.entry_interval || review.period || undefined,
      report_id: review.report_id ? String(review.report_id) : undefined,
      trade_id: review.trade_id ? String(review.trade_id) : undefined,
      trade_no: review.trade_no || review.source?.trade_no || undefined,
      time: review.entry_time || review.open_time || undefined,
      datetime: review.entry_time || review.open_time || undefined,
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

function reviewToBacktestTrade(review: ReviewNote): BacktestTrade | null {
  const source = review.source || selectedTrade.value
  const openTime = review.entry_time || review.open_time || source?.open_time
  if (!openTime) return null
  const closeTime = review.exit_time || review.close_time || source?.close_time || openTime
  return {
    id: review.trade_id || review.source_id || source?.id,
    report_id: review.report_id || source?.report_id,
    trade_no: review.trade_no || source?.trade_no || String(review.trade_id || review.source_id || source?.id || 'trade'),
    instrument_symbol: review.symbol || source?.symbol,
    contract_code: review.contract || source?.contract,
    symbol: review.symbol || source?.symbol,
    contract: review.contract || source?.contract,
    direction: review.direction || source?.direction || 'long',
    open_time: openTime,
    open_price: numberFrom(review.open_price ?? source?.open_price, 0) || 0,
    close_time: closeTime,
    close_price: numberFrom(review.close_price ?? source?.close_price ?? review.open_price ?? source?.open_price, 0) || 0,
    volume: numberFrom(review.volume ?? source?.volume, 0) || 0,
    net_pnl: numberFrom(review.net_pnl ?? source?.net_pnl, 0) || 0,
    commission: numberFrom(source?.commission, 0) || 0,
    slippage: numberFrom(source?.slippage, 0) || 0,
    holding_bars: numberFrom(review.hold_bars ?? source?.hold_bars ?? source?.holding_bars, 0) || 0,
    entry_reason: review.entry_reason || source?.entry_reason || '',
    exit_reason: review.exit_reason || source?.exit_reason || '',
    raw_payload: {
      ...(review.extra || {}),
      entry_interval: review.entry_interval || review.period || source?.entry_interval || source?.period,
    },
  }
}

function lineageDebugItems(lineage: ReviewFormalLineage) {
  const primary = lineage.primary
  const bar = lineage.bar
  return [
    { label: 'symbol', value: primary.instrument_symbol || '-' },
    { label: 'contract', value: primary.contract_code || '-' },
    { label: 'interval', value: primary.period || '-' },
    { label: 'start', value: bar.bar_start || '-' },
    { label: 'end', value: bar.bar_end || '-' },
    { label: 'provider', value: primary.provider || '-' },
    { label: 'data_role', value: primary.data_role || '-' },
    { label: 'profile_id', value: primary.profile_id || '-' },
    { label: 'market_data_file_id', value: String(primary.market_data_file_id) },
  ]
}

function klineQueryObject() {
  return Object.fromEntries(klineQueryItems.value.map((item) => [item.label, item.value === '-' ? '' : item.value])) as {
    symbol?: string
    contract?: string
    interval?: string
  }
}

function tradeRowProps(row: ReviewSourceTrade) {
  return {
    class: selectedTrade.value?.id === row.id ? 'trade-row-active' : '',
    onClick: () => {
      void openTrade(row)
    },
  }
}

async function addAttachment() {
  if (!selectedReview.value || !attachmentPath.value.trim()) return
  await addReviewAttachment(selectedReview.value.id, { file_path: attachmentPath.value.trim(), file_type: 'image' })
  selectedReview.value = normalizeReview(await getReview(selectedReview.value.id))
  markReviewSaved(selectedReview.value)
  attachmentPath.value = ''
}

function reviewSnapshot(review: ReviewNote) {
  return JSON.stringify({
    entry_reason: review.entry_reason,
    exit_reason: review.exit_reason,
    market_phase: review.market_phase,
    is_system_compliant: review.is_system_compliant,
    mistake_tags: review.mistake_tags,
    setup_tags: review.setup_tags,
    emotion_tags: review.emotion_tags,
    execution_note: review.execution_note,
    improvement_note: review.improvement_note,
    screenshot_path: review.screenshot_path,
    review_score: review.review_score,
  })
}

function markReviewSaved(review: ReviewNote) {
  savedReviewSnapshot.value = reviewSnapshot(review)
}

function displayAttachmentLabel(path: string | null | undefined) {
  if (!path) return ''
  const normalized = path.trim()
  if (!normalized) return ''
  const parts = normalized.split(/[/\\]/)
  return parts[parts.length - 1] || 'attachment'
}

function focusMarker(side: 'open' | 'close') {
  if (!selectedReview.value) return
  const time = side === 'open' ? selectedReview.value.open_time : selectedReview.value.close_time
  if (!time || bars.value.length === 0) return
  activeMarkerId.value = side
  chartRef.value?.focusTime(time)
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
  return toSafeApiError(err, fallback)
}
</script>

<template>
  <div class="review-page">
    <NAlert v-if="error" type="error" :bordered="false">{{ error }}</NAlert>
    <NAlert v-if="reportIdFilter" type="info" :bordered="false">
      已按 report_id=#{{ reportIdFilter }} 过滤交易来源（deep-link）
    </NAlert>

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
          :row-props="tradeRowProps"
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
            <NButton size="small" :disabled="!canFocusOpen" @click="focusMarker('open')">定位开仓</NButton>
            <NButton size="small" :disabled="!canFocusClose" @click="focusMarker('close')">定位平仓</NButton>
            <NButton size="small" :disabled="!canOpenMarket" @click="openKlineFromReview">行情K线</NButton>
          </div>
        </div>
        <KlineChart
          ref="chartRef"
          :bars="bars"
          :markers="markerData"
          :active-marker-id="activeMarkerId"
          :loading="loadingBars"
          :error="klineError"
        />
        <div v-if="selectedReview && !loadingBars && bars.length === 0" class="kline-query-state">
          <strong>当前交易窗口未返回K线</strong>
          <span v-for="item in klineQueryItems" :key="item.label">{{ item.label }}={{ item.value }}</span>
        </div>
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
        <ReviewFoundationPanel :context="selectedReview ? foundationContext : null" />

        <div class="panel__header">
          <div>
            <h2>复盘卡</h2>
            <p>记录原因、标签和下一次改进</p>
          </div>
          <NButton type="primary" size="small" :disabled="!selectedReview" :loading="saving" @click="saveReview">
            保存{{ hasUnsavedChanges ? ' *' : '' }}
          </NButton>
        </div>
        <NAlert v-if="hasUnsavedChanges" type="warning" :bordered="false" class="unsaved-alert">
          复盘卡有未保存修改
        </NAlert>

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
            <NFormItem label="截图登记">
              <div class="attachment-row">
                <NInput
                  :value="displayAttachmentLabel(selectedReview.screenshot_path)"
                  placeholder="已登记截图（仅显示文件名）"
                  readonly
                />
                <NInput v-model:value="attachmentPath" placeholder="登记文件名或相对路径（不展示绝对路径）" />
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
  gap: var(--gy-space-4);
  min-width: 0;
}

.unsaved-alert {
  margin-bottom: 8px;
}

.panel {
  min-width: 0;
  padding: var(--gy-panel-padding);
  background: var(--gy-bg-panel);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-lg);
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
  color: var(--gy-text-muted);
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
  gap: var(--gy-space-3);
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
  background: var(--gy-bg-panel-strong);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-md);
}

.metric span {
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-sm);
}

.metric strong {
  color: var(--gy-text-primary);
  font-size: var(--gy-font-size-lg);
}

.workspace-grid {
  display: grid;
  grid-template-columns: minmax(320px, 0.9fr) minmax(520px, 1.6fr) minmax(360px, 1fr);
  gap: var(--gy-space-4);
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
  color: var(--gy-text-secondary);
  background: var(--gy-bg-panel-strong);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-md);
}

.kline-query-state {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  margin-top: 10px;
  padding: 8px 10px;
  color: var(--gy-text-secondary);
  background: var(--gy-bg-panel-strong);
  border: 1px solid var(--gy-border-strong);
  border-radius: var(--gy-radius-md);
  font-size: var(--gy-font-size-sm);
}

.kline-query-state strong {
  color: #fecaca;
}

.kline-query-state span {
  color: var(--gy-text-muted);
}

.kline-note strong {
  color: var(--gy-text-primary);
}

:deep(.trade-row-active td) {
  background: var(--gy-status-info-soft) !important;
}

.text-up {
  color: var(--gy-up);
}

.text-down {
  color: var(--gy-down);
}

.panel h3 {
  margin: 0 0 10px;
  font-size: 15px;
}

.panel p {
  margin: 6px 0;
  color: var(--gy-text-secondary);
}

@media (max-width: 1199px) {
  .workspace-grid {
    grid-template-columns: 1fr;
  }

  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .stats-grid--bottom {
    grid-template-columns: 1fr;
  }
}
</style>
