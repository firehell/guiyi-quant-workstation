<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { AlertEvent, AlertRuleCode } from '@/types/market'
import type { ProductOption } from '@/utils/productSearch'
import { ALERT_RULE_CODES, alertEventHomeResultLabel, alertEventRuleShortLabel } from '@/utils/alertRules'
import { newowMessageStrategies, type NewowMessage } from '@/api/newowMessages'
import { messageQueryIdentity, type UnifiedMessage, type UnifiedMessageQuery } from '@/api/marketMessages'
import { useUnifiedMessages } from '@/composables/useUnifiedMessages'
import { recordingPointLabel } from '@/utils/newowRecording'
import MarketChevron from './MarketChevron.vue'

const props = defineProps<{ options: ProductOption[]; directoryStatus: 'ready' | 'loading' | 'error'; reloadSequence: number }>()
const emit = defineEmits<{ open: [event: AlertEvent]; openNewow: [event: NewowMessage] }>()
const today = localDay(new Date())
const rangeStart = new Date(); rangeStart.setDate(rangeStart.getDate() - 6)
const defaults: UnifiedMessageQuery = { startDay: localDay(rangeStart), endDay: today, symbol: '', source: 'all', ruleCode: null, strategy: '', frequency: '', search: '' }
const periodsForValidation = ['', '1m', '5m', '15m', '30m', '60m', '1d', '1w']
const query = ref<UnifiedMessageQuery>(loadQuery())
const filtersOpen = ref(false)
const messages = useUnifiedMessages(undefined, 'market-home-unified-v1')
const page = messages.page
const validRange = computed(() => query.value.startDay <= query.value.endDay && (Date.parse(query.value.endDay) - Date.parse(query.value.startDay)) / 86400000 <= (query.value.source === 'alert' ? 365 : 93))
const todayCount = computed(() => page.value?.items.filter(row => row.event.trading_day === today).length ?? 0)
const sourceIssues = computed(() => Object.entries(page.value?.sources ?? {}).filter(([, value]) => value.status !== 'ready' || value.truncated || (value.excluded_streams ?? 0) > 0))
const periods = [{ value: '', label: '全部周期' }, { value: '1m', label: '1分钟' }, { value: '5m', label: '5分钟' }, { value: '15m', label: '15分钟' }, { value: '30m', label: '30分钟' }, { value: '60m', label: '60分钟' }, { value: '1d', label: '日线' }, { value: '1w', label: '周线' }]
const periodLabel = (frequency: string) => periods.find(row => row.value === frequency)?.label ?? frequency
const strategyName = (value: string) => newowMessageStrategies.find(row => row.value === value)?.label ?? value
const productName = (event: AlertEvent | NewowMessage) => props.options.find(row => row.symbol === event.symbol)?.name ?? event.symbol.toUpperCase()
let mounted = false
function selectKind(source: UnifiedMessageQuery['source'], rule: AlertRuleCode | null = null, strategy = '') {
  query.value = { ...query.value, source, ruleCode: rule, strategy, frequency: source === 'newow' && !['', '1w', '1d', '60m'].includes(query.value.frequency) ? '' : query.value.frequency }
}
function reset() { query.value = { ...defaults }; filtersOpen.value = false }
function load(force = false) { if (validRange.value) void messages.load({ ...query.value }, force); else messages.dispose() }
function persist() { try { sessionStorage.setItem('guiyi.market-home.messages.v2', JSON.stringify(query.value)) } catch {} }
function scrollElement(): HTMLElement | null {
  const content = document.querySelector<HTMLElement>('.content--market-home')
  const nested = content?.querySelector<HTMLElement>('.n-layout-scroll-container') ?? null
  return [content, nested, document.scrollingElement as HTMLElement | null].find(el => Boolean(el && el.scrollHeight > el.clientHeight + 1)) ?? content ?? nested
}
function scrollKey() { return `guiyi.market-home.messages.scroll:${messageQueryIdentity(query.value)}` }
function rememberScroll() { try { sessionStorage.setItem(scrollKey(), String(scrollElement()?.scrollTop ?? 0)) } catch {} }
async function restoreScroll() { if (!mounted) return; await nextTick(); if (!mounted) return; try { const top = Number(sessionStorage.getItem(scrollKey()) ?? 0); if (top > 0) requestAnimationFrame(() => { if (mounted) scrollElement()?.scrollTo({ top }) }) } catch {} }
function open(row: UnifiedMessage) { rememberScroll(); persist(); if (row.source === 'alert') emit('open', row.event); else emit('openNewow', row.event) }
watch(query, () => { persist(); if (!mounted) return; load() }, { deep: true })
watch(() => props.reloadSequence, () => { if (mounted) load(true) })
onMounted(async () => { mounted = true; if (validRange.value) await messages.load({ ...query.value }); if (mounted) await restoreScroll() })
onBeforeUnmount(() => { mounted = false; rememberScroll(); messages.dispose() })
function localDay(value: Date) { return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(value) }
function time(value: string) { return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value)) }
function loadQuery(): UnifiedMessageQuery {
  try {
    const value = JSON.parse(sessionStorage.getItem('guiyi.market-home.messages.v2') ?? sessionStorage.getItem('guiyi.market-home.messages.v1') ?? 'null')
    if (!value || typeof value !== 'object' || !/^\d{4}-\d{2}-\d{2}$/.test(value.startDay) || !/^\d{4}-\d{2}-\d{2}$/.test(value.endDay) || typeof value.symbol !== 'string' || ![null, ALERT_RULE_CODES.HTDY, ALERT_RULE_CODES.SUBING_THS].includes(value.ruleCode)) return { ...defaults }
    const strategy = value.strategy ?? value.newowStrategy ?? ''
    if (!['', ...newowMessageStrategies.map(row => row.value)].includes(strategy) || !periodsForValidation.includes(value.frequency ?? '')) return { ...defaults }
    return { startDay: value.startDay, endDay: value.endDay, symbol: value.symbol, ruleCode: value.ruleCode, frequency: value.frequency ?? '', strategy, search: typeof value.search === 'string' ? value.search.slice(0, 80) : '', source: value.ruleCode ? 'alert' : strategy ? 'newow' : ['all', 'alert', 'newow'].includes(value.source) ? value.source : 'all' }
  } catch { return { ...defaults } }
}
</script>

<template>
  <section class="market-home-messages" aria-label="历史消息">
    <header class="market-message-header"><h1>消息</h1><div><button type="button" :aria-expanded="filtersOpen" @click="filtersOpen = !filtersOpen">筛选</button><button type="button" @click="reset">重置</button><button type="button" :disabled="messages.loading.value" @click="load(true)">{{ messages.loading.value ? '刷新中…' : '刷新消息' }}</button></div></header>
    <div class="market-message-kinds" aria-label="消息类型">
      <button type="button" :aria-pressed="query.source === 'all'" @click="selectKind('all')">全部</button>
      <button type="button" :aria-pressed="query.ruleCode === ALERT_RULE_CODES.HTDY" @click="selectKind('alert', ALERT_RULE_CODES.HTDY)">火天大有</button>
      <button type="button" :aria-pressed="query.ruleCode === ALERT_RULE_CODES.SUBING_THS" @click="selectKind('alert', ALERT_RULE_CODES.SUBING_THS)">苏冰预警</button>
      <button v-for="strategy in newowMessageStrategies" :key="strategy.value" type="button" :aria-pressed="query.source === 'newow' && query.strategy === strategy.value" @click="selectKind('newow', null, strategy.value)">{{ strategy.label }}</button>
    </div>
    <div class="market-message-kinds" aria-label="信号周期"><button v-for="period in periods" :key="period.value" type="button" :aria-pressed="query.frequency === period.value" :disabled="query.source === 'newow' && !['', '1w', '1d', '60m'].includes(period.value)" @click="query.frequency = period.value">{{ period.label }}</button></div>
    <div class="market-message-search"><input v-model="query.search" maxlength="80" type="search" aria-label="搜索消息" placeholder="搜索查询范围内的品种名称/代码/合约…" /></div>
    <div class="market-message-stats"><span>今日已加载 {{ todayCount }} 条</span><span>当前已加载 {{ page?.items.length ?? 0 }} 条<span v-if="page"> · 本次可读取 {{ page.available_count }} 条{{ page.coverage === 'partial' ? '（覆盖不完整）' : '' }}</span></span></div>
    <div v-if="filtersOpen" class="market-message-filters">
      <label>品种<span class="market-message-select"><select v-model="query.symbol"><option value="">全部品种</option><option v-for="row in options" :key="row.symbol" :value="row.symbol">{{ row.name }} {{ row.symbol.toUpperCase() }}</option></select><MarketChevron /></span></label>
      <label>开始交易日<input v-model="query.startDay" type="date" /></label><label>结束交易日<input v-model="query.endDay" type="date" /></label>
    </div>
    <p v-if="!validRange" class="market-dashboard-page__error" role="alert">日期范围无效：含牛哇消息最多相隔93天，预警消息最多366个自然日。</p>
    <p v-if="directoryStatus === 'loading'" class="market-message-status">正在读取品种目录…</p>
    <p v-else-if="directoryStatus === 'error'" class="market-dashboard-page__error" role="alert">品种目录刷新失败；保留可用品种名称。</p>
    <p v-if="messages.loading.value" class="market-message-status">{{ page ? '正在刷新；下方保留上次快照。' : '正在读取消息…' }}</p>
    <p v-if="messages.error.value" class="market-dashboard-page__error" role="alert">{{ messages.error.value === 'stale' ? '消息来源或查询快照已变化，请刷新后继续。' : '消息读取失败；如有旧快照则已保留，请刷新重试。' }}</p>
    <template v-if="validRange && page">
      <p class="market-message-note">快照截止 {{ time(page.snapshot.cutoff) }} · 按信号时间排序 · 搜索在服务端查询范围内执行</p>
      <p v-for="[source, state] in sourceIssues" :key="source" class="market-message-note" role="status">{{ source === 'newow' ? '牛哇参考' : '历史预警' }}：{{ state.status === 'unavailable' ? '来源读取失败，覆盖不完整' : state.truncated ? `仅扫描本范围最近${state.limit}条，请缩小查询范围` : `${state.excluded_streams}个匹配策略流尚未就绪，覆盖不完整` }}。空结果不代表完整历史无记录。</p>
      <div v-if="page.items.length" class="market-message-list" aria-label="统一消息列表">
        <button v-for="row in page.items" :key="`${row.source}:${row.id}`" type="button" @click="open(row)">
          <span class="market-message-row1"><strong>{{ productName(row.event) }}</strong><span class="market-message-code">({{ row.symbol.toUpperCase() }})</span><span class="market-message-rule">{{ row.source === 'alert' ? alertEventRuleShortLabel(row.event) : strategyName(row.event.strategy) }}</span><span class="market-message-period" :data-frequency="row.event.frequency">{{ periodLabel(row.event.frequency) }}</span><time :datetime="row.bar_end">{{ time(row.bar_end) }}</time></span>
          <span v-if="row.source === 'newow'" class="market-message-row2"><span class="market-message-action" :class="{ 'is-sell': ['CLEAR', 'CLOSE_LONG', 'CLOSE', 'REDUCE'].includes(String(row.event.point.value.kind)) }">{{ recordingPointLabel(row.event.point) }}{{ row.event.point.kind === 'action' ? '参考' : '' }}</span><span>{{ row.event.contract ?? '合约未记录' }}</span><span v-if="row.event.point.value.reference_price">参考价 {{ row.event.point.value.reference_price }}</span></span>
          <span v-else class="market-message-row2"><span class="market-message-action" :class="{ 'is-sell': row.event.result_codes.length === 1 && row.event.result_codes[0] === 'sell' }">{{ alertEventHomeResultLabel(row.event) }}</span><span>{{ row.event.contract }}</span></span>
          <small v-if="row.source === 'newow'">策略参考信号<span v-if="row.event.point.value.retrospective"> · 回看提示</span> · 记录于 {{ time(row.event.observed_at) }}</small>
          <small v-else>历史预警 · 记录于 {{ time(row.event.detected_at) }} · {{ row.event.notification_attempted_at ? `已尝试发送 ${time(row.event.notification_attempted_at)}` : '未记录发送尝试' }}</small>
        </button>
      </div>
      <div v-else-if="!messages.loading.value && !messages.error.value && !messages.retentionCapped.value" class="market-message-empty"><p>{{ page.coverage === 'complete' ? '当前查询范围暂无匹配消息' : '可读取范围内暂无匹配消息；部分来源失败或截断' }}</p></div>
      <p v-if="messages.retentionCapped.value" class="market-message-note" role="status">已达到本页记录显示上限，请缩小日期或筛选范围继续查看；这不代表完整历史已读取。</p>
      <button v-if="page.next_cursor && !messages.retentionCapped.value" class="market-message-more" type="button" :disabled="messages.loading.value || messages.loadingMore.value || messages.error.value === 'stale'" @click="messages.loadMore()">{{ messages.loadingMore.value ? '读取中…' : '加载更多' }}</button>
    </template>
    <p class="market-message-note">牛哇只读取已就绪的盘中观察策略流及其已保存参考记录；历史预警的发送尝试不代表已送达。消息不代表账户成交。</p>
  </section>
</template>
