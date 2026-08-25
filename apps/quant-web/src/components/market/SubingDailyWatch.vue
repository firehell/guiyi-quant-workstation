<script setup lang="ts">
import { computed, ref } from 'vue'
import type {
  SubingDailyWatchCurrentResponse,
  SubingDailyWatchItem,
  SubingDailyWatchTrend,
} from '@/types/market'
import {
  subingDailyWatchReasonLabel,
  visibleDailyWatchItems,
} from '@/utils/subingDailyWatch'

const props = withDefaults(defineProps<{
  response: SubingDailyWatchCurrentResponse | null
  loading?: boolean
  requestFailed?: boolean
}>(), {
  loading: false,
  requestFailed: false,
})

const emit = defineEmits<{
  open: [item: SubingDailyWatchItem]
}>()

const longExpanded = ref(false)
const shortExpanded = ref(false)
const unavailableExpanded = ref(false)
const snapshot = computed(() => (
  props.response?.status === 'ready' ? props.response.snapshot : null
))

function priceSideLabel(trend: SubingDailyWatchTrend) {
  if (trend.price_side === 'above') return '价格在 EMA21 上方'
  if (trend.price_side === 'below') return '价格在 EMA21 下方'
  if (trend.price_side === 'equal') return '价格位于 EMA21'
  return '价格位置不可用'
}

function slopeLabel(trend: SubingDailyWatchTrend) {
  if (trend.slope_5_bps_per_bar > 0 && trend.slope_10_bps_per_bar > 0) return '5/10 斜率向上'
  if (trend.slope_5_bps_per_bar < 0 && trend.slope_10_bps_per_bar < 0) return '5/10 斜率向下'
  return '5/10 斜率方向不一致'
}

function remaining(items: readonly SubingDailyWatchItem[]) {
  return Math.max(0, items.length - 6)
}

function unavailableTimeframe(reasonCode: string) {
  if (reasonCode.startsWith('D1_')) return '日线'
  if (reasonCode.startsWith('H1_')) return '60m'
  return '数据身份'
}

function itemTitle(item: SubingDailyWatchItem) {
  return [item.symbol.toUpperCase(), item.product_name].filter(Boolean).join(' ')
}
</script>

<template>
  <section class="daily-watch" aria-labelledby="subing-daily-watch-heading" data-testid="subing-daily-watch">
    <header class="daily-watch__heading">
      <div>
        <span>每日观察</span>
        <h2 id="subing-daily-watch-heading">苏冰今日观察</h2>
      </div>
      <small v-if="snapshot">
        目标交易日 {{ snapshot.target_trading_day }} · 来源交易日 {{ snapshot.source_trading_day }}
      </small>
    </header>

    <div v-if="!snapshot" class="daily-watch__unavailable">
      <strong>{{ loading && !requestFailed ? '苏冰今日观察读取中' : '苏冰今日观察暂不可用' }}</strong>
      <span>{{ loading && !requestFailed ? '正在读取已发布的当前观察。' : '当前没有可用候选；运行概况、正式信号与全市场研究仍可独立使用。' }}</span>
    </div>

    <template v-else>
      <div class="daily-watch__counts" aria-label="今日观察汇总">
        <span>多头观察 <strong>{{ snapshot.counts.long_watch }}</strong></span>
        <span>空头观察 <strong>{{ snapshot.counts.short_watch }}</strong></span>
        <span>趋势不明确 <strong>{{ snapshot.counts.excluded }}</strong></span>
        <span>数据不可用 <strong>{{ snapshot.counts.unavailable }}</strong></span>
      </div>

      <div class="daily-watch__groups">
        <section class="daily-watch__group" data-testid="subing-daily-watch-group-long">
          <h3>多头观察 {{ snapshot.counts.long_watch }}</h3>
          <div v-if="snapshot.long_watch.length === 0" class="daily-watch__empty">暂无</div>
          <div v-else class="daily-watch__cards">
            <article
              v-for="item in visibleDailyWatchItems(snapshot.long_watch, longExpanded)"
              :key="item.symbol"
              class="daily-watch__card"
              data-testid="subing-daily-watch-card"
            >
              <div class="daily-watch__card-heading">
                <strong>{{ itemTitle(item) }}</strong>
                <span class="daily-watch__decision daily-watch__decision--long">多头观察</span>
                <button type="button" :aria-label="`检查 ${item.symbol.toUpperCase()} 15m`" @click="emit('open', item)">检查 15m</button>
              </div>
              <div v-if="item.daily" class="daily-watch__fact"><span>日线</span>{{ priceSideLabel(item.daily) }} · {{ slopeLabel(item.daily) }}</div>
              <div v-if="item.hourly" class="daily-watch__fact"><span>60m</span>{{ priceSideLabel(item.hourly) }} · {{ slopeLabel(item.hourly) }}</div>
            </article>
          </div>
          <button
            v-if="remaining(snapshot.long_watch) > 0"
            type="button"
            class="daily-watch__expand"
            :aria-label="longExpanded ? '收起多头观察' : `展开剩余 ${remaining(snapshot.long_watch)} 个多头观察`"
            @click="longExpanded = !longExpanded"
          >
            {{ longExpanded ? '收起' : `展开剩余 ${remaining(snapshot.long_watch)}` }}
          </button>
        </section>

        <section class="daily-watch__group" data-testid="subing-daily-watch-group-short">
          <h3>空头观察 {{ snapshot.counts.short_watch }}</h3>
          <div v-if="snapshot.short_watch.length === 0" class="daily-watch__empty">暂无</div>
          <div v-else class="daily-watch__cards">
            <article
              v-for="item in visibleDailyWatchItems(snapshot.short_watch, shortExpanded)"
              :key="item.symbol"
              class="daily-watch__card"
              data-testid="subing-daily-watch-card"
            >
              <div class="daily-watch__card-heading">
                <strong>{{ itemTitle(item) }}</strong>
                <span class="daily-watch__decision daily-watch__decision--short">空头观察</span>
                <button type="button" :aria-label="`检查 ${item.symbol.toUpperCase()} 15m`" @click="emit('open', item)">检查 15m</button>
              </div>
              <div v-if="item.daily" class="daily-watch__fact"><span>日线</span>{{ priceSideLabel(item.daily) }} · {{ slopeLabel(item.daily) }}</div>
              <div v-if="item.hourly" class="daily-watch__fact"><span>60m</span>{{ priceSideLabel(item.hourly) }} · {{ slopeLabel(item.hourly) }}</div>
            </article>
          </div>
          <button
            v-if="remaining(snapshot.short_watch) > 0"
            type="button"
            class="daily-watch__expand"
            :aria-label="shortExpanded ? '收起空头观察' : `展开剩余 ${remaining(snapshot.short_watch)} 个空头观察`"
            @click="shortExpanded = !shortExpanded"
          >
            {{ shortExpanded ? '收起' : `展开剩余 ${remaining(snapshot.short_watch)}` }}
          </button>
        </section>
      </div>

      <section v-if="snapshot.counts.unavailable > 0" class="daily-watch__unavailable-section">
        <button
          type="button"
          class="daily-watch__unavailable-toggle"
          :aria-label="unavailableExpanded ? '收起数据不可用品种' : `展开 ${snapshot.counts.unavailable} 个数据不可用品种`"
          @click="unavailableExpanded = !unavailableExpanded"
        >
          数据不可用 {{ snapshot.counts.unavailable }} · {{ unavailableExpanded ? '收起' : '展开查看' }}
        </button>
        <div v-if="unavailableExpanded" class="daily-watch__unavailable-list" data-testid="subing-daily-watch-unavailable">
          <article v-for="item in snapshot.unavailable" :key="item.symbol" class="daily-watch__unavailable-item">
            <strong>{{ itemTitle(item) }}</strong>
            <div v-for="reason in item.unavailable_reasons" :key="reason">
              影响周期：{{ unavailableTimeframe(reason) }} · 原因：{{ subingDailyWatchReasonLabel(reason) }}
            </div>
          </article>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.daily-watch { display: flex; flex-direction: column; gap: 14px; padding: 16px; border: .5px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-bg-panel); box-shadow: var(--gy-shadow-panel); }
.daily-watch__heading { display: flex; align-items: end; justify-content: space-between; gap: 16px; }
.daily-watch__heading span, .daily-watch__heading small { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.daily-watch__heading h2, .daily-watch__group h3 { margin: 0; }
.daily-watch__heading h2 { margin-top: 3px; font-size: var(--gy-font-size-lg); }
.daily-watch__heading small { text-align: right; }
.daily-watch__unavailable { display: flex; flex-direction: column; gap: 4px; padding: 12px; border-radius: var(--gy-radius-md); background: var(--gy-status-warning-soft); color: var(--gy-text-secondary); font-size: var(--gy-font-size-sm); }
.daily-watch__counts { display: flex; flex-wrap: wrap; gap: 8px; }
.daily-watch__counts span { padding: 5px 9px; border-radius: var(--gy-radius-pill); background: var(--gy-bg-app); color: var(--gy-text-secondary); font-size: var(--gy-font-size-sm); }
.daily-watch__groups { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.daily-watch__group { display: flex; min-width: 0; flex-direction: column; gap: 8px; padding: 11px; border-radius: var(--gy-radius-md); background: var(--gy-bg-app); }
.daily-watch__group h3 { font-size: var(--gy-font-size-md); }
.daily-watch__cards { display: flex; flex-direction: column; gap: 8px; }
.daily-watch__card { display: flex; min-width: 0; flex-direction: column; gap: 7px; padding: 10px; border: .5px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.daily-watch__card-heading { display: flex; align-items: center; gap: 8px; }
.daily-watch__card-heading strong { min-width: 0; margin-right: auto; }
.daily-watch__decision { font-size: var(--gy-font-size-xs); font-weight: 500; white-space: nowrap; }
.daily-watch__decision--long { color: var(--gy-up); }
.daily-watch__decision--short { color: var(--gy-down); }
.daily-watch__card button, .daily-watch__expand, .daily-watch__unavailable-toggle { border: 0; background: none; color: var(--gy-accent); cursor: pointer; }
.daily-watch__fact { color: var(--gy-text-secondary); font-size: var(--gy-font-size-sm); }
.daily-watch__fact span { display: inline-block; min-width: 38px; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.daily-watch__expand { align-self: flex-start; padding: 2px 0; }
.daily-watch__unavailable-section { border-top: .5px solid var(--gy-border); padding-top: 10px; }
.daily-watch__unavailable-toggle { padding: 0; }
.daily-watch__unavailable-list { display: grid; gap: 8px; margin-top: 9px; }
.daily-watch__unavailable-item { display: flex; flex-direction: column; gap: 3px; padding: 9px 10px; border-radius: var(--gy-radius-md); background: var(--gy-bg-app); color: var(--gy-text-secondary); font-size: var(--gy-font-size-sm); }
.daily-watch__unavailable-item strong { color: var(--gy-text-primary); }
.daily-watch__empty { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
@media (max-width: 900px) { .daily-watch__groups { grid-template-columns: 1fr; } }
@media (max-width: 720px) { .daily-watch__heading { align-items: flex-start; flex-direction: column; } .daily-watch__heading small { text-align: left; } .daily-watch__card-heading { align-items: flex-start; flex-wrap: wrap; } }
</style>
