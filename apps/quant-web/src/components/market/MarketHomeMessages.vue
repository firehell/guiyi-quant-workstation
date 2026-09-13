<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { AlertEvent, AlertRuleCode } from '@/types/market'
import type { MarketHomeRow } from '@/utils/marketHomeViewModel'
import { ALERT_RULE_CODES, alertEventHomeResultLabel, alertEventRuleShortLabel } from '@/utils/alertRules'
import { useMarketMessages } from '@/composables/useMarketMessages'
import MarketChevron from './MarketChevron.vue'

const props = defineProps<{ rows: MarketHomeRow[]; reloadSequence: number }>()
const emit = defineEmits<{ open: [event: AlertEvent] }>()
const today = localDay(new Date())
const rangeStart = new Date()
rangeStart.setDate(rangeStart.getDate() - 6)
const saved = loadQuery()
const startDay = ref(saved?.startDay ?? localDay(rangeStart))
const endDay = ref(saved?.endDay ?? today)
const symbol = ref(saved?.symbol ?? '')
const ruleCode = ref<AlertRuleCode | null>(saved?.ruleCode ?? null)
const messages = useMarketMessages({ cacheKey: 'market-home-messages-v1' })
const validRange = computed(() => startDay.value <= endDay.value)
const query = () => ({ startDay: startDay.value, endDay: endDay.value, symbol: symbol.value, ruleCode: ruleCode.value })
let mounted = false

function load(force = false) { if (validRange.value) void messages.load(query(), { force }) }
function persistQuery() {
  try { sessionStorage.setItem('guiyi.market-home.messages.v1', JSON.stringify(query())) } catch {}
}
function messageScrollElement(): HTMLElement | null {
  if (typeof document === 'undefined') return null
  const content = document.querySelector<HTMLElement>('.content--market-home')
  const nested = content?.querySelector<HTMLElement>('.n-layout-scroll-container') ?? null
  return [content, nested, document.scrollingElement as HTMLElement | null]
    .find((element) => Boolean(element && element.scrollHeight > element.clientHeight + 1)) ?? content ?? nested
}
function rememberScroll() { messages.rememberScrollTop(messageScrollElement()?.scrollTop ?? 0) }
async function restoreScroll() {
  await nextTick()
  const top = messages.restoreScrollTop()
  if (top > 0) window.requestAnimationFrame(() => messageScrollElement()?.scrollTo({ top }))
}
function open(event: AlertEvent) { rememberScroll(); persistQuery(); emit('open', event) }
watch([startDay, endDay, symbol, ruleCode], () => { persistQuery(); if (mounted) load() })
watch(() => props.reloadSequence, () => { if (mounted) load(true) })
onMounted(() => { mounted = true; load(); void restoreScroll() })
onBeforeUnmount(() => { rememberScroll(); messages.dispose() })

function localDay(value: Date) { return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}` }
function time(value: string) { return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value)) }
function loadQuery(): { startDay: string; endDay: string; symbol: string; ruleCode: AlertRuleCode | null } | null {
  try {
    const value = JSON.parse(sessionStorage.getItem('guiyi.market-home.messages.v1') ?? 'null')
    const allowedRules = [null, ALERT_RULE_CODES.HTDY, ALERT_RULE_CODES.SUBING_THS]
    if (!value || typeof value !== 'object' || typeof value.startDay !== 'string' || typeof value.endDay !== 'string' || typeof value.symbol !== 'string' || !allowedRules.includes(value.ruleCode)) return null
    return value
  } catch { return null }
}
</script>

<template>
  <section class="market-home-messages" aria-label="历史消息">
    <header><div><h1>消息</h1><p>历史预警记录；发送尝试不代表已送达</p></div></header>
    <div class="market-message-filters">
      <div class="market-message-kinds" aria-label="消息类型">
        <button type="button" :aria-pressed="ruleCode === null" @click="ruleCode = null">全部</button>
        <button type="button" :aria-pressed="ruleCode === ALERT_RULE_CODES.HTDY" @click="ruleCode = ALERT_RULE_CODES.HTDY">火天大有</button>
        <button type="button" :aria-pressed="ruleCode === ALERT_RULE_CODES.SUBING_THS" @click="ruleCode = ALERT_RULE_CODES.SUBING_THS">苏冰</button>
      </div>
      <label>品种<span class="market-message-select"><select v-model="symbol"><option value="">全部品种</option><option v-for="row in rows" :key="row.symbol" :value="row.symbol">{{ row.product_name }} {{ row.symbol.toUpperCase() }}</option></select><MarketChevron /></span></label>
      <label>开始交易日<input v-model="startDay" type="date" /></label>
      <label>结束交易日<input v-model="endDay" type="date" /></label>
    </div>
    <p v-if="!validRange" class="market-dashboard-page__error" role="alert">开始日期不能晚于结束日期。</p>
    <p v-else-if="messages.error.value && !messages.items.value.length" class="market-dashboard-page__error" role="alert">消息暂不可用，请稍后重试。</p>
    <p v-else-if="messages.loading.value" class="market-message-status">正在读取消息…</p>
    <p v-else-if="!messages.items.value.length" class="market-message-status">所选日期与筛选下暂无正式 Event。</p>
    <div v-else class="market-message-list">
      <button v-for="event in messages.items.value" :key="event.id" type="button" @click="open(event)">
        <span class="market-message-rule">{{ alertEventRuleShortLabel(event) }}</span>
        <strong>{{ rows.find((row) => row.symbol === event.symbol)?.product_name ?? event.symbol.toUpperCase() }} · {{ alertEventHomeResultLabel(event) }}</strong>
        <span>{{ event.symbol.toUpperCase() }} · {{ event.contract }} · {{ event.frequency }} · {{ time(event.bar_end) }}</span>
        <small>{{ event.notification_attempted_at ? `已尝试发送 · ${time(event.notification_attempted_at)}` : '未记录发送尝试' }}</small>
      </button>
    </div>
    <button v-if="messages.nextBefore.value" class="market-message-more" type="button" :disabled="messages.refreshing.value || messages.loadingMore.value" @click="messages.loadMore()">{{ messages.refreshing.value ? '刷新中…' : messages.loadingMore.value ? '读取中…' : '加载更多' }}</button>
    <p v-if="messages.error.value && messages.items.value.length" class="market-dashboard-page__error" role="alert">下一页读取失败；已保留当前消息。</p>
  </section>
</template>
